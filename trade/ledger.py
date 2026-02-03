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
        if not symbol:
            return len(self.open_positions) > 0
        # Search values because keys could be trade_ids or symbols
        for t in self.open_positions.values():
            if t.symbol == symbol:
                return True
        return False
    
    def get_open_position(self, symbol: str = None) -> Optional[Trade]:
        """Get open position for symbol (or first if none specified)"""
        if not symbol:
            if self.open_positions:
                return list(self.open_positions.values())[0]
            return None
        
        for t in self.open_positions.values():
            if t.symbol == symbol:
                return t
        return None
        
    def has_real_position(self, symbol: str = None) -> bool:
        """Check if any REAL (non-counterfactual) position is open"""
        if symbol:
            trade = self.open_positions.get(symbol)
            return trade is not None and not trade.is_counterfactual
        
        # Check if ANY trade is real
        for t in self.open_positions.values():
            if not t.is_counterfactual:
                return True
        return False
    
    def open_trade(self, trade: Trade) -> bool:
        """
        Add trade to open positions.
        Returns False if position already exists for symbol.
        """
        is_atlas = trade.metadata.get('is_atlas_probe', False)
        is_ghost = trade.is_counterfactual
        
        # We allow concurrent only if it's Atlas or Ghost vs Real.
        # But for safety, let's just use trade_id as key for everything and rely on high-level logic to block.
        # Or keep the current spirit: Real trades are single-per-symbol.
        if not is_atlas and not is_ghost:
            if self.has_real_position(trade.symbol):
                logger.warning(f"[LEDGER] Cannot open REAL: Position already exists for {trade.symbol}")
                return False
        
        # Use trade_id as key for everything in v2.9 to avoid collision and support concurrency logic
        key = trade.trade_id
        trade.status = TradeStatus.OPEN # v6.3 Fix: Ensure status is updated before persisting
        self.open_positions[key] = trade
        
        # Initialize MFE/MAE tracking
        self.daily_high_prices[trade.trade_id] = trade.entry_price
        self.daily_low_prices[trade.trade_id] = trade.entry_price
        
        C_RESET = "\033[0m"
        C_GREEN = "\033[92m"
        logger.info(f"[LEDGER] 📗 {C_GREEN}Opened{C_RESET}: {trade.trade_id} | {trade.direction} @ {trade.entry_price}")
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
        # Find the trade (key could be symbol or trade_id)
        trade = None
        key_to_delete = None
        for key, t in self.open_positions.items():
            if t.trade_id == trade_id:
                trade = t
                key_to_delete = key
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
        
        # Move to closed (use the correct key, not symbol)
        del self.open_positions[key_to_delete]
        self.closed_positions.append(trade)
        
        # Cleanup tracking
        self.daily_high_prices.pop(trade_id, None)
        self.daily_low_prices.pop(trade_id, None)
        
        C_RESET = "\033[0m"
        C_RED = "\033[91m"
        C_GREEN = "\033[92m"
        pnl_color = C_GREEN if exit_event.pnl_points >= 0 else C_RED
        
        logger.info(f"[LEDGER] 📕 Closed: {trade_id} | {exit_event.exit_reason.value} @ {exit_event.exit_price} | PnL: {pnl_color}{exit_event.pnl_points:+.1f}pts{C_RESET}")
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
