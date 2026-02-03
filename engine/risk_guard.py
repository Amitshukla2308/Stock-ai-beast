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
        v4.2 Sovereign: The Decision Gate.
        Enforces 0.55 WR Floor and Golden Morning Access.
        """
        bias = alpha_state.get("bias", "NONE")
        wr = alpha_state.get("win_rate", 0.0)
        conf_id = alpha_state.get("confluence_id", "UNKNOWN")
        is_fallback = alpha_state.get("is_fallback", False)
        
        decision = {
            "action": "HOLD", "confidence": wr, "selected_style": "ATLAS",
            "is_fallback": is_fallback, "size_factor": 1,
            "reason": f"Cluster {conf_id}", "sl": None, "target": None
        }

        if bias == "NONE":
            decision["reason"] = f"No Alpha for {conf_id}"
            return decision

        # 0. GEOMETRY (Ghosts & Trades)
        self._set_geometry(decision, bias, current_price, alpha_state)

        # 1. LOAD CONFIG
        # v4.5 Unified Block Logic
        blocked_cfg = config.get("BLOCKED_REGIMES", {})
        risk_caps = config.get("RISK_CAPS", {})
        amp_cfg = config.get("ALPHA_AMPLIFICATION", {})
        golden_set = set(amp_cfg.get("golden_regimes", []))

        # regime_tag Extraction (Handles LONG_15_18, STAT_15_18, etc.)
        regime_tag = "UNKNOWN"
        try:
            parts = conf_id.split("_")
            if len(parts) >= 3: regime_tag = f"{parts[-2]}:{parts[-1]}"
        except Exception: pass

        # 2. HARD BLOCKS (Unified)
        if regime_tag in blocked_cfg.get("regimes", []):
            decision["reason"] = f"Forensic Block: Toxic Regime {regime_tag}"
            return decision
        
        # 3. TIME-BASED BLOCKS (Future Optionality)
        current_ts_str = alpha_state.get('timestamp_str', '') # Or handle datetime
        # if current_ts_str in blocked_cfg.get("time_windows", []): ...

        # 3. WIN RATE FLOOR (Sovereign Core)
        # v4.2 Strictly enforce Research Floor (0.55)
        if wr < self.wr_floor:
            decision["reason"] = f"Veto: WR {wr:.2f} < Floor {self.wr_floor}"
            return decision

        # 4. OPERATIONAL FILTERS (Daily Limits / Windows)
        # Churn Brake
        max_losses = risk_caps.get("daily_loss_limit", {}).get("max_consecutive_losses", 2)
        if consecutive_losses >= max_losses:
            decision["reason"] = f"Churn Brake: {max_losses} losses reached"
            return decision

        # Daily Trade Limit
        max_hard = risk_caps.get("max_daily_trades", 10)
        if daily_trade_count >= max_hard:
            decision["reason"] = f"Risk Cap: Hard Limit {max_hard} reached"
            return decision

        # Time Windows
        if current_time:
            ts_str = current_time.strftime('%H:%M') if hasattr(current_time, 'strftime') else str(current_time)[11:16]
            
            # Morning Window (Gaps/Reversals) - GOLDEN ONLY
            morning = risk_caps.get("morning_window", {})
            if morning.get("start") <= ts_str <= morning.get("end"):
                # Golden Regimes have priority morning access
                if regime_tag not in golden_set:
                    decision["reason"] = f"Execution Veto: Morning Window requires Golden Regime. Current: {regime_tag}"
                    return decision
                
                min_alpha = morning.get("wr_floor_override", 0.60)
                if wr < min_alpha:
                    decision["reason"] = f"Execution Veto: Morning Golden requires WR > {min_alpha}"
                    return decision

            # Lunch Break (Low Liquidity)
            lunch = risk_caps.get("lunch_break", {})
            if lunch and lunch.get("start") <= ts_str <= lunch.get("end"):
                if regime_tag not in golden_set:
                    decision["reason"] = f"Execution Veto: Lunch Break requires Golden Regime."
                    return decision

            # EOD Filter
            late_filt = risk_caps.get("late_closing_filter", {})
            if late_filt and late_filt.get("start") <= ts_str <= late_filt.get("end"):
                decision["reason"] = f"Execution Veto: EOD Filter ({ts_str})"
                return decision

        # 5. AMPLIFICATION
        if regime_tag in golden_set:
             decision["size_factor"] = amp_cfg.get("size_multiplier", 2)
             decision["reason"] += " [GOLDEN_AMPLIFIED]"

        # 6. ACTION ATTRIBUTION
        if bias == "LONG": decision["action"] = "BUY_CALL"
        elif bias == "SHORT": decision["action"] = "BUY_PUT"

        return decision

    def _set_geometry(self, decision, bias, current_price, alpha_state: Dict[str, Any]):
        """
        v4.5 Sovereign Geometry:
        - Standard: 50 SL / 90 TGT
        - Probation: Dynamic (Avg MAE / Avg MFE) from Alpha State (Tightened)
        - Alpha Expansion: 50 SL / 125 TGT (High MFE)
        """
        # Default Standard
        sl_offset = 50.0
        target_offset = 90.0
        
        # Identify Regime
        conf_id = alpha_state.get("confluence_id", "UNKNOWN")
        regime_tag = "UNKNOWN"
        try:
            parts = conf_id.split("_")
            if len(parts) >= 3: regime_tag = f"{parts[-2]}:{parts[-1]}"
        except Exception: pass
        
        # Load Configs
        from config.config_loader import config
        probation_cfg = config.get("PROBATION_REGIMES", {})
        
        # 1. Check Probation (Dynamic Tightening)
        if regime_tag in probation_cfg.get("regimes", []):
            # Fetch Dynamic Physics
            dyn_sl = alpha_state.get('avg_mae', 0.0)
            dyn_tgt = alpha_state.get('avg_mfe', 0.0)
            
            # Fallback to Config if missing
            if dyn_sl <= 5.0: dyn_sl = probation_cfg.get("sl_points", 35.0)
            if dyn_tgt <= 5.0: dyn_tgt = probation_cfg.get("target_points", 60.0)
            
            # Safety Clamps (Don't let stops be too tight or too loose)
            # SL: Min 25 (Noise), Max 55 (Risk)
            # TGT: Min 40 (B/E), Max 100 (Unlikely in probation)
            sl_offset = max(25.0, min(55.0, dyn_sl))
            target_offset = max(40.0, min(100.0, dyn_tgt))
            
            decision["reason"] += f" [PROBATION_DYN:{target_offset:.0f}/{sl_offset:.0f}]"
            
        # 2. Check Alpha Expansion (Loosen) - Only if NOT in probation
        else:
             avg_mfe = alpha_state.get('avg_mfe', 0)
             if avg_mfe > 95: 
                 target_offset = 125.0
                 decision["reason"] += " [ALPHA_EXPAND]"
        
        if bias == "LONG":
            decision["sl"] = current_price - sl_offset
            decision["target"] = current_price + target_offset
        elif bias == "SHORT":
            decision["sl"] = current_price + sl_offset
            decision["target"] = current_price - target_offset
