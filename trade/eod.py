
"""
Trade Engine v2.8: End of Day
Closes the day. This is what gives you: Daily PnL, Win rate, Style performance.
"""
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from trade.models import Trade, DailySummary, ExitReason
from trade.ledger import trade_ledger
from trade.lifecycle import TradeLifecycle

logger = logging.getLogger(__name__)


class EODProcessor:
    """End of day processing (Pure Logic)"""
    
    def end_of_day(
        self, 
        lifecycle: TradeLifecycle, 
        current_price: float, 
        timestamp: datetime,
        llm_client=None, # Deprecated
        morning_plan: Dict[str, Any] = None,
        symbol: str = "NIFTY",
        today_bars: List[Dict] = None,
        branch_outcomes: Dict[str, Any] = None 
    ) -> DailySummary:
        """
        Close all open positions, compute daily stats.
        """
        # Force close all open positions
        closed_count = lifecycle.force_close_all(current_price, timestamp, ExitReason.EOD)
        
        if closed_count > 0:
            logger.info(f"[EOD] 🌙 Closed {closed_count} positions at EOD @ {current_price}")
        
        # Get closed trades
        all_trades = trade_ledger.get_all_closed()
        
        # Separately track Real vs Counterfactual
        real_trades = [t for t in all_trades if not t.is_counterfactual]
        
        # Get Current Balance
        balance = lifecycle.broker.get_balance() if lifecycle.broker else 0.0
        
        # Compute daily stats
        summary = self.compute_daily_stats(
            date=timestamp.strftime('%Y-%m-%d'),
            session_id=lifecycle.session_id,
            trades=real_trades,
            today_bars=today_bars,
            morning_plan=morning_plan,
            balance=balance
        )
        
        # Log EOD summary (Standard)
        self._log_summary(summary)
        
        return summary
    
    def compute_daily_stats(
        self, 
        date: str, 
        session_id: str, 
        trades: List[Trade], 
        today_bars: List[Dict] = None,
        morning_plan: Dict[str, Any] = None,
        balance: float = 0.0
    ) -> DailySummary:
        """Compute statistics from closed trades and daily market dynamics"""
        if not trades and not today_bars:
            return DailySummary(date=date, session_id=session_id, final_balance=balance)
        
        total_pnl_points = sum(t.pnl_points for t in trades)
        total_pnl_rupees = sum(t.pnl_rupees for t in trades)
        wins = sum(1 for t in trades if t.pnl_points > 0)
        losses = sum(1 for t in trades if t.pnl_points <= 0)
        
        # Best and worst style
        style_pnl = {}
        for t in trades:
            style_pnl[t.style] = style_pnl.get(t.style, 0) + t.pnl_points
        
        best_style = max(style_pnl, key=style_pnl.get) if style_pnl else ""
        worst_style = min(style_pnl, key=style_pnl.get) if style_pnl else ""
        
        # Max drawdown
        cumulative = 0
        peak = 0
        max_dd = 0
        for t in trades:
            cumulative += t.pnl_rupees
            peak = max(peak, cumulative)
            max_dd = max(max_dd, peak - cumulative)
            
        summary = DailySummary(
            date=date,
            session_id=session_id,
            total_trades=len(trades),
            wins=wins,
            losses=losses,
            total_pnl_points=total_pnl_points,
            total_pnl_rupees=total_pnl_rupees,
            best_style=best_style,
            worst_style=worst_style,
            max_drawdown=max_dd,
            trend_efficiency=0.0, # Deprecated
            or_range=0.0, # Deprecated
            final_balance=balance
        )
        
        return summary
    
    def _log_summary(self, summary: DailySummary):
        """Log EOD summary in standard format"""
        logger.info(f"""
[EOD SUMMARY]
Date={summary.date}
Trades={summary.total_trades}
Wins={summary.wins} Losses={summary.losses}
PnL={summary.total_pnl_points:+.1f}pts ({summary.total_pnl_rupees:+.0f}₹)
BestStyle={summary.best_style}
WorstStyle={summary.worst_style}
MaxDD={summary.max_drawdown:.0f}₹
Balance={summary.final_balance:,.0f}₹
""")


# Global instance
eod_processor = EODProcessor()
