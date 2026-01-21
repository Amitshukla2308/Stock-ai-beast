"""
Trade Engine v2.8: Lifecycle
State machine enforcement. Prevents illegal transitions.
No implicit close. No forgot to log. No silent corruption.
"""
import logging
from datetime import datetime
from typing import Dict, Any, Optional
from trade.models import Trade, ExitEvent, TradeStatus, ExitReason
from trade.ledger import trade_ledger
from trade.store import trade_store

logger = logging.getLogger(__name__)


class TradeLifecycle:
    """
    State machine for trade lifecycle.
    CANDIDATE → PROPOSED → OPEN → ACTIVE → EXITED → CLOSED → ARCHIVED
    """
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.trade_counter = 0
    
    def _generate_trade_id(self, timestamp: datetime) -> str:
        """Generate unique trade ID"""
        self.trade_counter += 1
        return f"{self.session_id}_{timestamp.strftime('%H%M%S')}_{self.trade_counter}"
    
    def propose_trade(self, decision: Dict[str, Any], context: Dict[str, Any], timestamp: datetime) -> Trade:
        """
        Create a proposed trade from decision and context.
        Does NOT open it yet.
        """
        trade = Trade(
            trade_id=self._generate_trade_id(timestamp),
            session_id=self.session_id,
            symbol=context.get('symbol', 'NSE:NIFTY50-INDEX'),
            style=decision.get('selected_style', 'UNKNOWN'),
            direction="CALL" if decision.get('action') == "BUY_CALL" else "PUT",
            entry_time=timestamp,
            entry_price=decision.get('entry_price', context.get('close', 0)),
            sl_price=decision.get('sl'),
            target_price=decision.get('target'),
            quantity=50 * decision.get('size_factor', 1),
            confidence=decision.get('confidence', 0),
            regime=context.get('trend_regime', 'UNKNOWN'),
            session_phase=context.get('session_phase', 'UNKNOWN'),
            trend_efficiency=context.get('trend_efficiency', 0),
            atr=context.get('atr', 0),
            or_range=context.get('or_range', 0),
            location=context.get('location_class', 'UNKNOWN'),
            reason=decision.get('reason', ''),
            status=TradeStatus.PROPOSED
        )
        
        logger.info(f"[LIFECYCLE] ✨ Proposed: {trade.trade_id} | {trade.style} {trade.direction}")
        return trade
    
    def open_trade(self, trade: Trade) -> bool:
        """
        Open a proposed trade. Updates ledger and store.
        Returns False if trade cannot be opened (e.g., position exists).
        """
        if trade.status != TradeStatus.PROPOSED:
            logger.error(f"[LIFECYCLE] Cannot open: Trade {trade.trade_id} is not in PROPOSED state")
            return False
        
        # Check no existing position
        if trade_ledger.has_open_position(trade.symbol):
            logger.warning(f"[LIFECYCLE] Cannot open: Position already exists for {trade.symbol}")
            return False
        
        # Open in ledger
        if not trade_ledger.open_trade(trade):
            return False
        
        # Persist to store
        trade_store.insert_trade(trade)
        
        # Log trade open
        logger.info(f"""
[TRADE OPEN]
ID={trade.trade_id}
Style={trade.style}
Dir={trade.direction}
Entry={trade.entry_price}
SL={trade.sl_price}
TGT={trade.target_price}
Conf={trade.confidence}
Regime={trade.regime}
Reason="{trade.reason}"
""")
        return True
    
    def close_trade(self, trade_id: str, exit_event: ExitEvent) -> Optional[Trade]:
        """
        Close an open trade. Updates ledger and store.
        Returns the closed Trade or None if failed.
        """
        # Close in ledger
        trade = trade_ledger.close_trade(trade_id, exit_event)
        if not trade:
            return None
        
        # Persist to store
        trade_store.close_trade(trade)
        
        # Log trade close
        logger.info(f"""
[TRADE CLOSE]
ID={trade.trade_id}
Exit={trade.exit_price}
Reason={trade.exit_reason.value if trade.exit_reason else 'UNKNOWN'}
BarsHeld={trade.bars_held}
PnL={trade.pnl_points:+.1f}pts ({trade.pnl_rupees:+.0f}₹)
MFE={trade.mfe:+.1f}
MAE={trade.mae:+.1f}
""")
        return trade
    
    def force_close_all(self, current_price: float, timestamp: datetime, reason: ExitReason = ExitReason.EOD) -> int:
        """
        Force close all open positions (e.g., at EOD).
        Returns count of closed trades.
        """
        closed_count = 0
        
        # Get list of open trades (copy to avoid modification during iteration)
        open_trades = list(trade_ledger.open_positions.values())
        
        for trade in open_trades:
            pnl_points = (current_price - trade.entry_price) if trade.direction == "CALL" else (trade.entry_price - current_price)
            pnl_rupees = pnl_points * trade.quantity
            
            exit_event = ExitEvent(
                trade_id=trade.trade_id,
                exit_time=timestamp,
                exit_price=current_price,
                exit_reason=reason,
                pnl_points=pnl_points,
                pnl_rupees=pnl_rupees,
                bars_held=0  # Would need bar counter
            )
            
            if self.close_trade(trade.trade_id, exit_event):
                closed_count += 1
        
        return closed_count


# Factory function for new sessions
def create_lifecycle(session_id: str) -> TradeLifecycle:
    return TradeLifecycle(session_id)
