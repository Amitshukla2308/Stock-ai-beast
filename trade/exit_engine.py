"""
Trade Engine v2.8: Exit Engine
This is where exits ACTUALLY happen. Runs every candle.
SL/TGT/Time/Invalidation logic lives here. Not in backtest.py. Not in executor.
"""
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from trade.models import Trade, ExitEvent, ExitReason
from trade.ledger import trade_ledger

logger = logging.getLogger(__name__)


class ExitEngine:
    """
    Checks for exit conditions on every candle.
    Returns exit events to be processed by lifecycle.
    """
    
    def __init__(self):
        self.bar_counters: Dict[str, int] = {}  # trade_id -> bars since entry
    
    def check_exits(self, tick: Dict[str, Any]) -> List[ExitEvent]:
        """
        Main entry point. Called every candle.
        Returns list of exit events (usually 0 or 1).
        """
        exit_events = []
        
        timestamp = tick.get('timestamp')
        current_price = tick.get('close', 0)
        candle_high = tick.get('high', current_price)
        candle_low = tick.get('low', current_price)
        candle_open = tick.get('open', current_price)
        
        # Iterate over open positions
        for symbol, trade in list(trade_ledger.open_positions.items()):
            # Skip same-candle checks
            if trade.entry_time == timestamp:
                continue
            
            # Increment bar counter
            self.bar_counters[trade.trade_id] = self.bar_counters.get(trade.trade_id, 0) + 1
            bars_held = self.bar_counters[trade.trade_id]
            
            # Update MFE/MAE tracking
            trade_ledger.update_price_extremes(trade.trade_id, candle_high)
            trade_ledger.update_price_extremes(trade.trade_id, candle_low)
            
            # Check exit conditions
            exit_event = self._check_trade_exit(
                trade, timestamp, current_price, candle_high, candle_low, candle_open, bars_held
            )
            
            if exit_event:
                exit_events.append(exit_event)
                # Clean up bar counter
                self.bar_counters.pop(trade.trade_id, None)
            else:
                # TRADE UPDATE: Log status while active
                unrealized = (current_price - trade.entry_price) if trade.direction == "CALL" else (trade.entry_price - current_price)
                unrealized_rupees = unrealized * trade.quantity
                high = trade_ledger.daily_high_prices.get(trade.trade_id, trade.entry_price)
                low = trade_ledger.daily_low_prices.get(trade.trade_id, trade.entry_price)
                mfe = (high - trade.entry_price) if trade.direction == "CALL" else (trade.entry_price - low)
                mae = (trade.entry_price - low) if trade.direction == "CALL" else (high - trade.entry_price)
                
                logger.debug(f"[TRADE UPDATE] ID={trade.trade_id} Bars={bars_held} Unrealized={unrealized:+.1f}pts (₹{unrealized_rupees:+.0f}) MFE={mfe:+.1f} MAE={mae:+.1f}")
        
        return exit_events
    
    def _check_trade_exit(
        self, 
        trade: Trade, 
        timestamp: datetime,
        current_price: float,
        candle_high: float,
        candle_low: float,
        candle_open: float,
        bars_held: int
    ) -> Optional[ExitEvent]:
        """
        Check if a specific trade should exit.
        Returns ExitEvent if exit triggered, None otherwise.
        """
        exit_price = None
        exit_reason = None
        
        sl = trade.sl_price
        target = trade.target_price
        
        if trade.direction == "CALL":
            # SL Hit (price dropped below SL)
            if sl is not None and candle_low <= sl:
                exit_price = sl if candle_open > sl else candle_open
                exit_reason = ExitReason.SL
            # Target Hit (price rose above target)
            elif target is not None and candle_high >= target:
                exit_price = target if candle_open < target else candle_open
                exit_reason = ExitReason.TGT
        else:  # PUT
            # SL Hit (price rose above SL)
            if sl is not None and candle_high >= sl:
                exit_price = sl if candle_open < sl else candle_open
                exit_reason = ExitReason.SL
            # Target Hit (price dropped below target)
            elif target is not None and candle_low <= target:
                exit_price = target if candle_open > target else candle_open
                exit_reason = ExitReason.TGT
        
        if exit_price is None:
            return None
        
        # Calculate PnL
        pnl_points = (exit_price - trade.entry_price) if trade.direction == "CALL" else (trade.entry_price - exit_price)
        pnl_rupees = pnl_points * trade.quantity
        
        # Calculate MFE/MAE
        high = trade_ledger.daily_high_prices.get(trade.trade_id, trade.entry_price)
        low = trade_ledger.daily_low_prices.get(trade.trade_id, trade.entry_price)
        
        if trade.direction == "CALL":
            mfe = high - trade.entry_price
            mae = trade.entry_price - low
        else:
            mfe = trade.entry_price - low
            mae = high - trade.entry_price
        
        return ExitEvent(
            trade_id=trade.trade_id,
            exit_time=timestamp,
            exit_price=exit_price,
            exit_reason=exit_reason,
            pnl_points=pnl_points,
            pnl_rupees=pnl_rupees,
            bars_held=bars_held,
            mfe=mfe,
            mae=mae
        )
    
    def reset(self):
        """Reset for new session"""
        self.bar_counters.clear()


# Global instance
exit_engine = ExitEngine()
