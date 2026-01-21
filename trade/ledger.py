"""
Trade Engine v2.8: Ledger
In-memory state manager. The BRAIN of reality.
This is what executor queries, not the DB. DB is history. Ledger is truth.
"""
import logging
from typing import Dict, List, Optional
from trade.models import Trade, ExitEvent, TradeStatus

logger = logging.getLogger(__name__)


class TradeLedger:
    """
    In-memory truth of current trading state.
    Single source of truth for: What positions exist? What are we holding?
    """
    
    def __init__(self):
        self.open_positions: Dict[str, Trade] = {}  # symbol -> Trade
        self.closed_positions: List[Trade] = []
        self.daily_high_prices: Dict[str, float] = {}  # trade_id -> highest price seen
        self.daily_low_prices: Dict[str, float] = {}   # trade_id -> lowest price seen
    
    def has_open_position(self, symbol: str = None) -> bool:
        """Check if any (or specific) position is open"""
        if symbol:
            return symbol in self.open_positions
        return len(self.open_positions) > 0
    
    def get_open_position(self, symbol: str = None) -> Optional[Trade]:
        """Get open position for symbol (or first if none specified)"""
        if symbol:
            return self.open_positions.get(symbol)
        if self.open_positions:
            return list(self.open_positions.values())[0]
        return None
    
    def open_trade(self, trade: Trade) -> bool:
        """
        Add trade to open positions.
        Returns False if position already exists for symbol.
        """
        if trade.symbol in self.open_positions:
            logger.warning(f"[LEDGER] Cannot open: Position already exists for {trade.symbol}")
            return False
        
        trade.status = TradeStatus.OPEN
        self.open_positions[trade.symbol] = trade
        
        # Initialize MFE/MAE tracking
        self.daily_high_prices[trade.trade_id] = trade.entry_price
        self.daily_low_prices[trade.trade_id] = trade.entry_price
        
        logger.info(f"[LEDGER] 📗 Opened: {trade.trade_id} | {trade.direction} @ {trade.entry_price}")
        return True
    
    def update_price_extremes(self, trade_id: str, current_price: float):
        """Track MFE/MAE for a trade"""
        if trade_id in self.daily_high_prices:
            self.daily_high_prices[trade_id] = max(self.daily_high_prices[trade_id], current_price)
        if trade_id in self.daily_low_prices:
            self.daily_low_prices[trade_id] = min(self.daily_low_prices[trade_id], current_price)
    
    def close_trade(self, trade_id: str, exit_event: ExitEvent) -> Optional[Trade]:
        """
        Close a trade and move to closed positions.
        Returns the closed Trade or None if not found.
        """
        # Find the trade
        trade = None
        for symbol, t in self.open_positions.items():
            if t.trade_id == trade_id:
                trade = t
                break
        
        if not trade:
            logger.warning(f"[LEDGER] Cannot close: Trade {trade_id} not found in open positions")
            return None
        
        # Calculate MFE/MAE
        high = self.daily_high_prices.get(trade_id, trade.entry_price)
        low = self.daily_low_prices.get(trade_id, trade.entry_price)
        
        if trade.direction == "CALL":
            trade.mfe = high - trade.entry_price
            trade.mae = trade.entry_price - low
        else:
            trade.mfe = trade.entry_price - low
            trade.mae = high - trade.entry_price
        
        # Update trade with exit info
        trade.status = TradeStatus.CLOSED
        trade.exit_time = exit_event.exit_time
        trade.exit_price = exit_event.exit_price
        trade.exit_reason = exit_event.exit_reason
        trade.bars_held = exit_event.bars_held
        trade.pnl_points = exit_event.pnl_points
        trade.pnl_rupees = exit_event.pnl_rupees
        trade.mfe = exit_event.mfe if exit_event.mfe else trade.mfe
        trade.mae = exit_event.mae if exit_event.mae else trade.mae
        
        # Move to closed
        del self.open_positions[trade.symbol]
        self.closed_positions.append(trade)
        
        # Cleanup tracking
        self.daily_high_prices.pop(trade_id, None)
        self.daily_low_prices.pop(trade_id, None)
        
        logger.info(f"[LEDGER] 📕 Closed: {trade_id} | {exit_event.exit_reason.value} @ {exit_event.exit_price} | PnL: {exit_event.pnl_points:+.1f}pts")
        return trade
    
    def get_all_closed(self) -> List[Trade]:
        """Get all closed trades for this session"""
        return self.closed_positions.copy()
    
    def reset(self):
        """Reset ledger for new day/session"""
        self.open_positions.clear()
        self.closed_positions.clear()
        self.daily_high_prices.clear()
        self.daily_low_prices.clear()
        logger.debug("[LEDGER] Reset for new session")


# Global instance
trade_ledger = TradeLedger()
