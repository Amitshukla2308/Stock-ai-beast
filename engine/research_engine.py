"""
v4.0 Research Engine: The Deterministic Brain
Coordinates the modular pipeline: Physics -> Regime -> Registry -> RiskGuard.
"""
import logging
import pandas as pd
from typing import Dict, Any, Optional
from datetime import datetime

from engine.features.physics_engine import PhysicsEngine
from engine.features.calculators import AtlasFeatures
from atlas.regime import Regime
from atlas.registry import Registry
from engine.risk_guard import RiskGuard

logger = logging.getLogger(__name__)

class ResearchEngine:
    def __init__(self, wr_floor: float = 0.55, use_gpu: bool = False):
        logger.info(f"🧠 Initializing v4.4 Research Engine (Sovereign Architecture | GPU={use_gpu})...")
        self.physics = PhysicsEngine()
        self.use_gpu = use_gpu
        
        if use_gpu:
            from atlas.regime_gpu import RegimeGPU
            from engine.features.calculators_gpu import AtlasFeaturesGPU
            self.regime = RegimeGPU()
            self.physics_gpu = AtlasFeaturesGPU
        else:
            self.regime = Regime()
            
        self.registry = Registry()
        self.risk_guard = RiskGuard(wr_floor=wr_floor)
        self.daily_count = 0
        self.daily_losses = 0
        self.current_date = None
        

    def update_daily_state(self, timestamp: datetime):
        """Resets counters on new day (Critical for multi-day sim)"""
        date_now = timestamp.date()
        if self.current_date != date_now:
            self.current_date = date_now
            self.daily_count = 0
            self.daily_losses = 0

    def process_tick(self, df_5m: pd.DataFrame, df_15m: pd.DataFrame, silent: bool = False) -> Dict[str, Any]:
        """
        Executes the v4.0 Pipeline:
        Physics -> Enrichment -> Regime -> Registry -> RiskGuard
        """
        if df_5m.empty or len(df_5m) < 200:
            current_price = df_5m['close'].iloc[-1] if not df_5m.empty else 0.0
            ts = df_5m['timestamp'].iloc[-1].strftime('%H:%M:%S') if not df_5m.empty else "00:00:00"
            log_str = f"[ATLAS] ⏳ {ts} | Warmup: {len(df_5m)}/200 bars | Price: {current_price:,.2f}"
            if not silent: logger.info(log_str)
            return {"decision": {"action": "HOLD", "reason": "Warmup Mode"}, "log_str": log_str}

        # Date Management (Reset daily count)
        ts_now = df_5m['timestamp'].iloc[-1]
        self.update_daily_state(ts_now)

        # 1. Physics & Enrichment
        if self.use_gpu:
            df_5m_64d = self.physics_gpu.calculate_all(self.physics.add_context(df_5m))
            df_15m_64d = self.physics_gpu.calculate_all(self.physics.add_context(df_15m))
        else:
            df_5m_64d = AtlasFeatures.calculate_all(self.physics.add_context(df_5m))
            df_15m_64d = AtlasFeatures.calculate_all(self.physics.add_context(df_15m))
        
        # 2. Regime Identification
        c15, c5, physics_vector = self.regime.identify_clusters(df_5m_64d, df_15m_64d)
        
        # 3. Registry Lookup 
        alpha_state = self.registry.get_alpha_state(c15, c5, cutoff_time=ts_now)
        
        # 4. Risk Guard Decision (Pass Daily Count & Losses)
        current_price = df_5m['close'].iloc[-1]
        decision = self.risk_guard.validate_alpha(
            alpha_state, current_price, current_time=ts_now, 
            daily_trade_count=self.daily_count, 
            consecutive_losses=self.daily_losses
        )
        
        # Tracking Increment (Executor will actually open it, but we predict it here for limits)
        if decision['action'] != "HOLD":
            # We don't increment here because process_tick can be called multiple times per bar 
            # or by the In-Trade monitor. The Mode (Backtest/Live) should increment it in reality.
            # However, for consistency, we pass the current known count.
            pass

        # Narrative Logging
        wr = alpha_state.get('win_rate', 0.0)
        ts = ts_now.strftime('%H:%M:%S')
        
        res_color = "\033[92m" if decision['action'] != "HOLD" else "\033[0m"
        log_str = f"[ATLAS] 🧠 {ts} | Price: {current_price:,.2f} | Regime: {c15}:{c5} | WR: {wr:.2f} | Action: {res_color}{decision['action']}\033[0m"
        
        if not silent:
            logger.info(log_str)
        
        # Pass features forward for in-trade monitoring (v4.3)
        return {
            "decision": decision,
            "regime_id": f"{c15}:{c5}",
            "alpha_state": alpha_state,
            "physics_vector": physics_vector,
            "features_5m": df_5m_64d.iloc[-1].to_dict(),
            "log_str": log_str
        }

    def process_in_trade_tick(self, df_5m: pd.DataFrame, df_15m: pd.DataFrame, trade: Any, pre_computed_result: Optional[Dict[str, Any]] = None, current_price: float = 0.0) -> Dict[str, Any]:
        """
        Transition Engine: In-Trade Monitor.
        Supports: Regime Decay, Stall Decay, Jitter Guard, and Stale Exit.
        """
        # Call process_tick silently to avoid double logs, or use pre-computed if available
        if pre_computed_result:
            result = pre_computed_result
        else:
            result = self.process_tick(df_5m, df_15m, silent=True)
        alpha_state = result.get('alpha_state', {})
        wr = alpha_state.get('win_rate', 0.0)
        regime_id = result.get('regime_id', 'UNKNOWN')
        features = result.get('features_5m', {})
        
        if not trade:
             return {"in_trade_action": "HOLD", "reason": "No Trade", "confidence": 0.0}

        # Transition Logic (The "Regime Decay" Guard)
        # Hysteresis Implementation (v4.2 Fix)
        # We require N consecutive bars of "Trap" conditions to trigger exit.
        
        from config.config_loader import config
        trans_cfg = config.get("TRANSITION_ENGINE", {})
        sem_cfg = config.get("SEMANTIC_RISK_GUARD", {})
        
        if not trans_cfg.get("enabled", True):
             return {"in_trade_action": "HOLD", "reason": "Transition Engine Disabled", "confidence": 0.0}

        # --- v4.3 EMERGENCY JITTER GUARD ---
        jitter_cfg = sem_cfg.get("jitter_guard", {})
        if jitter_cfg.get("enabled", True):
            fear_idx = features.get('X44_Ulcer_Idx', 0.0)
            if fear_idx > jitter_cfg.get("ulcer_child_jump", 2.0):
                logger.info(f"   [TRANSITION] ⚡ JITTER GUARD: Fear Spike Detected ({fear_idx:.1f}). Emergency Exit.")
                return {"in_trade_action": "EXIT", "reason": "Jitter Guard (Fear Spike)", "confidence": 1.0}

        # --- v4.3 STALE TRADE EXIT (Time Decay) ---
        stale_cfg = sem_cfg.get("stale_exit", {})
        if stale_cfg.get("enabled", True):
            # Check bars held (Assuming trade object has duration_bars or we calculate it)
            # trade.duration_bars should be updated by the Mode/Lifecycle.
            bars = getattr(trade, 'duration_bars', 0)
            mfe = getattr(trade, 'mfe', 0.0)
            
            if bars >= stale_cfg.get("max_bars", 6) and mfe < stale_cfg.get("min_mfe_points", 15.0):
                logger.info(f"   [TRANSITION] ⏳ STALE EXIT: No profit in {bars} bars. Exiting.")
                return {"in_trade_action": "EXIT", "reason": "Stale Trade (Time Decay)", "confidence": 1.0}

        # --- v4.2 STALL AND DECAY (Structural Protection) ---
        pnl_pts = 0.0
        # Blackwell Patch: Use passed price if df_5m is None
        if current_price == 0.0 and df_5m is not None:
             current_price = df_5m['close'].iloc[-1]
        
        pnl_pts = current_price - trade.entry_price if trade.direction == "CALL" else trade.entry_price - current_price

        stall_cfg = trans_cfg.get("stall_decay", {})
        if stall_cfg.get("enabled", True):
            # If trade is negative AND WR is weak (even if not a full trap)
            if pnl_pts < -5.0 and wr < stall_cfg.get("wr_threshold", 0.35):
                current_stall_strike = trade.metadata.get('stall_strike', 0) + 1
                trade.metadata['stall_strike'] = current_stall_strike
                # logger.info(f"   [TRANSITION] ⏳ Stall Warning (PNL {pnl_pts:.1f} | WR {wr:.2f}) | Strike {current_stall_strike}/{max_stall}")
                
                if current_stall_strike >= stall_cfg.get("max_bars_negative", 4):
                    logger.info(f"   [TRANSITION] 📉 Stall Confirmed. In-trade decay detected. Force Exit.")
                    return {"in_trade_action": "EXIT", "reason": f"Stall Decay (R{regime_id})", "confidence": 1.0}
            else:
                trade.metadata['stall_strike'] = 0 # Reset on recovery

        # --- REGIME TRAP (Existing Logic) ---
        # Check for Invalidation
        # If WR drops below threshold, it's a potential trap.
        is_trap = wr < trans_cfg.get("invalidation_threshold", 0.15)
        
        if is_trap:
             # Increment counter in Trade Metadata (Stateful)
             current_strike = trade.metadata.get('transition_strike', 0) + 1
             trade.metadata['transition_strike'] = current_strike
             
             # logger.info(f"   [TRANSITION] ⚠️ Trap Potential (R{regime_id} | WR {wr:.2f}) | Strike {current_strike}/{hysteresis}")
             
             if current_strike >= trans_cfg.get("hysteresis_period", 2):
                 logger.info(f"   [TRANSITION] 📉 Trap Confirmed (Strike Limit Reached). Issueing Force Exit.")
                 return {"in_trade_action": "EXIT", "reason": f"Regime Decay (R{regime_id})", "confidence": 1.0}
        else:
             # Reset counter if regime recovers (Flicker Protection)
             if trade.metadata.get('transition_strike', 0) > 0:
                 logger.info(f"   [TRANSITION] ✅ Regime Recovered (R{regime_id} | WR {wr:.2f}). Resetting Strikes.")
                 trade.metadata['transition_strike'] = 0
             
        return {"in_trade_action": "HOLD", "reason": f"R{regime_id} Valid", "confidence": 0.0}
