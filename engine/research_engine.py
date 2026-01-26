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
    def __init__(self, wr_floor: float = 0.55):
        logger.info("🧠 Initializing v4.0 Research Engine (Sovereign Architecture)...")
        self.physics = PhysicsEngine()
        self.regime = Regime()
        self.registry = Registry()
        self.risk_guard = RiskGuard(wr_floor=wr_floor)
        
    def process_tick(self, df_5m: pd.DataFrame, df_15m: pd.DataFrame, silent: bool = False) -> Dict[str, Any]:
        """
        Executes the v4.0 Pipeline:
        Physics -> Enrichment -> Regime -> Registry -> RiskGuard
        """
        if df_5m.empty or len(df_5m) < 200:
            return {"decision": {"action": "HOLD", "reason": "Warmup Mode"}}

        # 1. Physics & Enrichment
        # Ensure latest candle is enriched
        df_5m_enriched = self.physics.add_context(df_5m)
        df_5m_64d = AtlasFeatures.calculate_all(df_5m_enriched)
        
        df_15m_enriched = self.physics.add_context(df_15m)
        df_15m_64d = AtlasFeatures.calculate_all(df_15m_enriched)
        
        # 2. Regime Identification
        c15, c5, physics_vector = self.regime.identify_clusters(df_5m_64d, df_15m_64d)
        
        # 3. Registry Lookup (Temporal Guard: Use cutoff_time to prevent lookahead)
        ts_now = df_5m['timestamp'].iloc[-1]
        alpha_state = self.registry.get_alpha_state(c15, c5, cutoff_time=ts_now)
        
        # 4. Risk Guard Decision
        current_price = df_5m['close'].iloc[-1]
        decision = self.risk_guard.validate_alpha(alpha_state, current_price)
        
        # Narrative Logging
        wr = alpha_state.get('win_rate', 0.0)
        ts = df_5m['timestamp'].iloc[-1].strftime('%H:%M:%S')
        
        res_color = "\033[92m" if decision['action'] != "HOLD" else "\033[0m"
        log_str = f"[ATLAS] 🧠 {ts} | Price: {current_price:,.2f} | Regime: {c15}:{c5} | WR: {wr:.2f} | Action: {res_color}{decision['action']}\033[0m"
        
        if not silent:
            logger.info(log_str)
        
        return {
            "decision": decision,
            "regime_id": f"{c15}:{c5}",
            "alpha_state": alpha_state,
            "physics_vector": physics_vector,
            "log_str": log_str
        }

    def process_in_trade_tick(self, df_5m: pd.DataFrame, df_15m: pd.DataFrame, trade: Any) -> Dict[str, Any]:
        """
        Transition Engine: In-Trade Monitor.
        Triggers Force Exit if the regime transitions to a non-alpha/trap state.
        """
        # Call process_tick silently to avoid double logs
        result = self.process_tick(df_5m, df_15m, silent=True)
        alpha_state = result.get('alpha_state', {})
        wr = alpha_state.get('win_rate', 0.0)
        regime_id = result.get('regime_id', 'UNKNOWN')
        
        # Transition Logic (The "Regime Decay" Guard)
        # If WinRate < 0.25, it's a Trap regime. Exit immediately.
        # This constant will move to config in next pass.
        if wr < 0.25:
             logger.info(f"   [TRANSITION] 📉 Trap Detected (R{regime_id} | WR {wr:.2f}). Issueing Force Exit.")
             return {"in_trade_action": "EXIT", "reason": f"Regime Decay (R{regime_id})", "confidence": 1.0}
             
        return {"in_trade_action": "HOLD", "reason": f"R{regime_id} Valid", "confidence": 0.0}
