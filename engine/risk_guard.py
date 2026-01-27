"""
v4.0 RiskGuard: The Decision Gate
Prevents low-alpha trades and enforces deterministic geometry.
"""
import logging
from typing import Dict, Any, Optional
from config.config_loader import config

logger = logging.getLogger(__name__)

class RiskGuard:
    def __init__(self, wr_floor: float = 0.55):
        self.wr_floor = wr_floor
        self._load_drivers()
        
    def _load_drivers(self):
        try:
            import json, os
            path = "atlas/models/cluster_drivers.json"
            if os.path.exists(path):
                with open(path, 'r') as f:
                    self.drivers = json.load(f)
            else:
                self.drivers = {}
        except Exception:
            self.drivers = {}

    def validate_alpha(self, alpha_state: Dict[str, Any], current_price: float, current_time: Any = None, daily_trade_count: int = 0, consecutive_losses: int = 0) -> Dict[str, Any]:
        """
        Validates the confluence bias and sets exit prices.
        Now supports Morning WR Floor overrides and Daily Loss Churn Brakes (v4.4).
        """
        bias = alpha_state.get("bias", "NONE")
        wr = alpha_state.get("win_rate", 0.0)
        conf_id = alpha_state.get("confluence_id", "UNKNOWN")
        is_fallback = alpha_state.get("is_fallback", False)
        
        decision = {
            "action": "HOLD",
            "confidence": wr,
            "selected_style": "ATLAS",
            "is_fallback": is_fallback,
            "size_factor": 1,
            "reason": f"Cluster {conf_id}",
            "sl": None,
            "target": None
        }

        if bias == "NONE":
            decision["reason"] = f"No Alpha for {conf_id}"
            return decision

        # 0. EARLY GEOMETRY (Before Limits)
        # Ensure SL/TGT are set for Counterfactuals regardless of Veto
        if bias in ["LONG", "SHORT"]:
            self._set_geometry(decision, bias, current_price, alpha_state.get("tier", 2))

        # 1. LOAD CONFIG
        blocks = config.get("FORENSIC_BLOCKS", {})
        sem_cfg = config.get("SEMANTIC_RISK_GUARD", {})
        risk_caps = config.get("RISK_CAPS", {})

        # 2. DAILY LIMITS & CHURN BRAKE (v4.4 Surgical Hardening)
        # Churn Brake: Stop if first N are losses
        loss_cfg = risk_caps.get("daily_loss_limit", {})
        max_losses = loss_cfg.get("max_consecutive_losses", 2)
        if consecutive_losses >= max_losses:
            decision["reason"] = f"Churn Brake: {max_losses} consecutive losses reached"
            return decision

        # Trade Count Limits
        max_hard = risk_caps.get("max_daily_trades", 3)
        soft_cap = risk_caps.get("soft_limit", 2)
        
        if daily_trade_count >= max_hard:
            decision["reason"] = f"Risk Cap: Hard Limit {max_hard} reached"
            return decision
            
        if daily_trade_count >= soft_cap:
            # Check for Morning Window Override
            morning = risk_caps.get("morning_window", {})
            in_morning = False
            
            if current_time:
                ts_str = current_time.strftime('%H:%M') if hasattr(current_time, 'strftime') else str(current_time)[11:16]
                if morning.get("start", "09:15") <= ts_str <= morning.get("end", "10:45"):
                    in_morning = True
            
            min_alpha = morning.get("wr_floor_override", 0.50) if in_morning else risk_caps.get("soft_limit_wr_floor", 0.65)
            
            if wr < min_alpha:
                reason_tag = "Morning Window" if in_morning else "Soft Limit"
                decision["reason"] = f"Risk Cap: {reason_tag} requires WR > {min_alpha}"
                return decision

        # 3. FORENSIC BLOCKS & STERILIZATION (v4.5)
        # Extract c15:c5 from conf_id (Handles "LONG_15_18", "STAT_15_18", etc.)
        regime_tag = "UNKNOWN"
        try:
            parts = conf_id.split("_")
            if len(parts) >= 3:
                regime_tag = f"{parts[-2]}:{parts[-1]}"
        except Exception: pass

        # Hard Regime Block (Existing Forensic Logic)
        if regime_tag in blocks.get("regimes", []):
            decision["reason"] = f"Forensic Block: Toxic Regime {regime_tag}"
            return decision
            
        # Surgical Sterilization (v4.5)
        steril_cfg = config.get("REGIME_STERILIZATION", {})
        
        # 1. Hard Block (New)
        if regime_tag in steril_cfg.get("block_list", []):
             decision["reason"] = f"Surgical Pruning: Hard Veto {regime_tag}"
             return decision

        # 2. Soft Toxic List
        if regime_tag in steril_cfg.get("toxic_regimes", []):
            veto_wr = steril_cfg.get("sterilization_wr_floor", 0.70)
            if wr < veto_wr:
                decision["reason"] = f"Regime Sterilization: {regime_tag} requires WR > {veto_wr}"
                return decision
        
        # 3. Darwinian Tier Policies (v6.1)
        tier = alpha_state.get("tier", 2)
        
        # Tier 4: Blocked (Hard Veto)
        if tier == 4:
            decision["reason"] = f"Darwinian Block: {regime_tag} failed survival"
            return decision

        # Tier 3: Probation (Penalized Sizing + Rehab Gate)
        if tier == 3:
            prob_wr_gate = 0.45 # Allow recovery attempts
            if wr < prob_wr_gate:
                decision["reason"] = f"Probation Gate: {regime_tag} failed Rehab WR {prob_wr_gate}"
                return decision
            decision["size_factor"] = 0.5
            decision["reason"] += " [PROBATION_PENALTY]"

        # Tier 1: Golden (Amplified)
        elif tier == 1:
            decision["size_factor"] = 2.0
            decision["reason"] += " [GOLDEN_BOOST]"

        # Tier 2: Standard (v5.3/v6.0 Fallback for non-live or non-categorized)
        elif regime_tag in config.get("ALPHA_AMPLIFICATION", {}).get("golden_regimes", []):
             decision["size_factor"] = config.get("ALPHA_AMPLIFICATION", {}).get("size_multiplier", 2)
             decision["reason"] += " [GOLDEN_AMPLIFIED]"
            
        # 4. TIME GATE
        if current_time:
            # Parse time if needed, assuming datetime object or string? 
            # Engine passes pandas timestamp or python datetime.
            # Convert to HH:MM string for comparison
            time_str = current_time.strftime('%H:%M') if hasattr(current_time, 'strftime') else str(current_time)[11:16]
                
            for window in blocks.get("time_windows", []):
                start = window.get("start", "00:00")
                end = window.get("end", "00:00")
                min_conf = window.get("min_confidence", 1.0)
                
                if start <= time_str < end:
                    # In restricted window. Check confidence exception.
                    if wr < min_conf:
                        decision["reason"] = f"Time Gate: Restricted window WR veto"
                        return decision

        # 5. SEMANTIC VETO (v4.3 Exhaustion Protection)
        # Check if cluster driver contains exhaustion features
        try:
            parts = conf_id.split("_")
            c5_id = parts[-1]
            drivers = self.drivers.get("5m", {}).get(c5_id, [])
            
            exh_cfg = sem_cfg.get("exhaustion_veto", {})
            if exh_cfg.get("enabled", True):
                exh_features = exh_cfg.get("features", [])
                wr_veto = exh_cfg.get("wr_floor_override", 0.65)
                
                for d in drivers:
                    if d['feature'] in exh_features and d['sign'] == 'HIGH':
                        if wr < wr_veto:
                            decision["reason"] = f"Semantic Veto: High Exhaustion requires WR > {wr_veto}"
                            return decision
        except Exception: pass

        # Absolute Code Floor (v5.0 Reset)
        if wr < 0.0:
            decision["reason"] = f"Veto: WR {wr:.2f} < 0.0"
            return decision

        # 6. Final Geometry & Action Attribution
        
        if bias == "LONG":
            decision["action"] = "BUY_CALL"
        elif bias == "SHORT":
            decision["action"] = "BUY_PUT"

        return decision

    def _set_geometry(self, decision, bias, current_price, tier: int = 2):
        """Standardized SL/TGT calculator for both real and ghost trades."""
        from config.config_loader import config # Defensive Import
        exit_cfg = config.get("EXIT_STRATEGY", {})
        target_offset = exit_cfg.get("fixed_target_points", 90.0) if exit_cfg.get("target_type") == "FIXED" else 10000.0
        
        # v6.1 Darwinian Rehab Exit (Smaller targets for Tier 3)
        if tier == 3:
            target_offset = target_offset * 0.5 # Catch small wins
            decision["reason"] += " [REHAB_TARGET]"
            
        # Semantic Target Modulation could be added here if needed for ghosts too
        if bias == "LONG":
            decision["sl"] = current_price - 50
            decision["target"] = current_price + target_offset
        elif bias == "SHORT":
            decision["sl"] = current_price + 50
            decision["target"] = current_price - target_offset
