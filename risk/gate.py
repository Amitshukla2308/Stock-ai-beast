"""
v2.8 Risk: Hard Gates
Handles non-negotiable blocking rules (Trade counts, Time limits, Eco floors).
Migrated from hot_path/executor.py (Phase 2 Refactor).
"""
from typing import Tuple, Optional
from datetime import time
from config.config_loader import config

class RiskGate:
    def __init__(self):
        self.total_trades_today = 0
        self.force_exit_time = time(15, 15)
        self.entry_cutoff = time(14, 45)
        
    def check_global_gates(self, current_time: time) -> Tuple[bool, Optional[str]]:
        """
        Check global constraints (Time, Trade Counts).
        Returns: (Allowed, Reason)
        """
        # 1. Trade Limit
        if self.total_trades_today >= 4:
            return False, "Daily trade limit reached (4 trades)"
            
        # 2. Time Limit
        if current_time > self.force_exit_time:
            return False, "Past square-off time"
            
        return True, None

    def check_trade_gates(self, action: str, entry: float, sl: float, target: float) -> Tuple[bool, Optional[str]]:
        """
        Check per-trade constraints (R:R, Econ Floor).
        Returns: (Allowed, Reason)
        """
        if action not in ["BUY_CALL", "BUY_PUT"]:
            return True, None
            
        # 1. R:R Guard
        if sl and target and entry:
            sl_dist = abs(entry - sl)
            tgt_dist = abs(entry - target)
            if sl_dist < 5: sl_dist = 5
            
            rr = tgt_dist / sl_dist
            if rr < 1.8: # Hardcoded min R:R as per executor.py constants
                return False, f"Low R:R ({rr:.1f} < 1.8)"
                
            # 2. Econ Guard
            potential_profit = tgt_dist * 25.0 # Nifty Lot Size approx
            if potential_profit < 1200: # 1200 INR floor
                return False, f"Trivial Profit (₹{potential_profit:.0f})"
                
        return True, None

    def increment_trade_count(self):
        self.total_trades_today += 1

    def reset_daily(self):
        self.total_trades_today = 0

# Global instance
risk_gate = RiskGate()
