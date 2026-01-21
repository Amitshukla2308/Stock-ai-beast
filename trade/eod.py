"""
Trade Engine v2.8: End of Day
Closes the day. This is what gives you: Daily PnL, Win rate, Style performance.
Now includes optional EOD LLM Audit call.
"""
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from trade.models import Trade, DailySummary, ExitReason
from trade.ledger import trade_ledger
from trade.lifecycle import TradeLifecycle

logger = logging.getLogger(__name__)


class EODProcessor:
    """End of day processing with optional LLM audit"""
    
    def end_of_day(
        self, 
        lifecycle: TradeLifecycle, 
        current_price: float, 
        timestamp: datetime,
        llm_client=None,
        morning_plan: Dict[str, Any] = None,
        symbol: str = "NIFTY",
        today_bars: List[Dict] = None
    ) -> DailySummary:
        """
        Close all open positions, compute daily stats, and optionally run LLM audit.
        """
        # Force close all open positions
        closed_count = lifecycle.force_close_all(current_price, timestamp, ExitReason.EOD)
        
        if closed_count > 0:
            logger.info(f"[EOD] 🌙 Closed {closed_count} positions at EOD @ {current_price}")
        
        # Get closed trades
        trades = trade_ledger.get_all_closed()
        
        # Compute daily stats
        summary = self.compute_daily_stats(
            date=timestamp.strftime('%Y-%m-%d'),
            session_id=lifecycle.session_id,
            trades=trades,
            today_bars=today_bars,
            morning_plan=morning_plan
        )
        
        # Log EOD summary
        self._log_summary(summary)
        
        # EOD LLM Audit (if client provided)
        if llm_client:
            self._run_eod_audit(llm_client, trades, morning_plan or {}, lifecycle.session_id, symbol, today_bars)
        
        return summary
    
    def _run_eod_audit(self, llm_client, trades: List[Trade], morning_plan: Dict, session_id: str, symbol: str, today_bars: List[Dict] = None):
        """Run LLM EOD Audit for learning"""
        try:
            # Convert Trade objects to dicts for LLM
            trades_data = []
            for t in trades:
                trades_data.append({
                    'side': t.direction,
                    'entry_price': t.entry_price,
                    'exit_price': t.exit_price,
                    'entry_time': t.entry_time,
                    'exit_time': t.exit_time,
                    'reason': t.exit_reason.value if t.exit_reason else 'UNKNOWN',
                    'pnl': t.pnl_points,
                    'style': t.style
                })
            
            # Format EOD Chart (OHLC)
            chart_summary = []
            if today_bars:
                # Samples for LLM (keep it compact)
                step = max(1, len(today_bars) // 15)
                for i in range(0, len(today_bars), step):
                    b = today_bars[i]
                    chart_summary.append(f"{b['ts']} Close: {b['c']:.1f}")
                
            eod_data = {
                'trend_efficiency': morning_plan.get('trend_efficiency', 0.0) if morning_plan else 0.0,
                'final_price': trades[-1].exit_price if trades else 0,
                'intraday_path': chart_summary
            }
            
            logger.info("[EOD] 🧠 Running LLM Audit...")
            audit = llm_client.get_eod_journal(trades_data, morning_plan, session_id, eod_data, symbol)
            
            if audit:
                logger.info(f"[EOD AUDIT] 📊 Bias Fitness: {audit.get('bias_fitness', 'N/A')} | Edge: {audit.get('primary_edge_source', 'N/A')}")
                if audit.get('nugget_good'):
                    logger.info(f"[EOD AUDIT] ✅ Good: {audit.get('nugget_good')}")
                if audit.get('nugget_bad'):
                    logger.info(f"[EOD AUDIT] ⚠️ Bad: {audit.get('nugget_bad')}")
        except Exception as e:
            logger.error(f"[EOD] Failed to run LLM audit: {e}")
    
    def compute_daily_stats(
        self, 
        date: str, 
        session_id: str, 
        trades: List[Trade], 
        today_bars: List[Dict] = None,
        morning_plan: Dict[str, Any] = None
    ) -> DailySummary:
        """Compute statistics from closed trades and daily market dynamics"""
        if not trades and not today_bars:
            return DailySummary(date=date, session_id=session_id)
        
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
        
        # --- RESEARCH METRICS (Phase 8) ---
        daily_ter = 0.0
        or_range = 0.0
        
        if today_bars:
            from enrichment.trend import calculate_trend_efficiency
            from enrichment.volatility import calculate_opening_range
            
            # Daily TER (Whole day efficiency)
            ter_val, _, _ = calculate_trend_efficiency(today_bars, window=len(today_bars))
            daily_ter = ter_val
            
            # OR Range
            or_data = calculate_opening_range(today_bars)
            or_range = or_data.get('or_range', 0.0) if or_data else 0.0
            
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
            trend_efficiency=daily_ter,
            or_range=or_range
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
""")


# Global instance
eod_processor = EODProcessor()
