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
        today_bars: List[Dict] = None,
        branch_outcomes: Dict[str, Any] = None # New Spec-002 Oracle Data
    ) -> DailySummary:
        """
        Close all open positions, compute daily stats, and optionally run LLM audit.
        """
        # Force close all open positions
        closed_count = lifecycle.force_close_all(current_price, timestamp, ExitReason.EOD)
        
        if closed_count > 0:
            logger.info(f"[EOD] 🌙 Closed {closed_count} positions at EOD @ {current_price}")
        
        # Get closed trades
        all_trades = trade_ledger.get_all_closed()
        
        # Separately track Real vs Counterfactual
        real_trades = [t for t in all_trades if not t.is_counterfactual]
        ghost_trades = [t for t in all_trades if t.is_counterfactual]
        
        # Get Current Balance
        balance = lifecycle.broker.get_balance() if lifecycle.broker else 0.0
        
        # Compute daily stats (ONLY REAL TRADES for PnL/Stats)
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
        
        # Log Ghost Stats (Research)
        if ghost_trades:
            g_pnl = sum(t.pnl_points for t in ghost_trades)
            g_pnl_r = sum(t.pnl_rupees for t in ghost_trades)
            g_wins = sum(1 for t in ghost_trades if t.pnl_points > 0)
            print(f"[RESEARCH] 👻 Ghost Stats: Trades={len(ghost_trades)} | Wins={g_wins} | Missed PnL: {g_pnl:+.1f}pts ({g_pnl_r:+.0f}₹)")
        
        # EOD LLM Audit (if client provided)
        # Note: We send ALL trades (Real + Ghost) to the LLM for learning, 
        # but we should probably tag them so the LLM knows which were real.
        if llm_client:
            self._run_eod_audit(llm_client, all_trades, morning_plan or {}, lifecycle.session_id, symbol, timestamp, today_bars, branch_outcomes)
        
        return summary
    
    def _run_eod_audit(self, llm_client, trades: List[Trade], morning_plan: Dict, session_id: str, symbol: str, timestamp: datetime, today_bars: List[Dict] = None, branch_outcomes: Dict = None):
        """Run LLM EOD Audit for learning and persist experience"""
        try:
            # Convert Trade objects to dicts for LLM
            trades_data = []
            for t in trades:
                status_tag = "[GHOST]" if t.is_counterfactual else "[REAL]"
                trades_data.append({
                    'side': f"{status_tag} {t.direction}",
                    'entry_price': t.entry_price,
                    'exit_price': t.exit_price,
                    'entry_time': t.entry_time,
                    'exit_time': t.exit_time,
                    'reason': t.exit_reason.value if t.exit_reason else 'UNKNOWN',
                    'pnl': t.pnl_points,
                    'style': t.style,
                    'trade_id': t.trade_id,
                    'regime': t.regime
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
                'final_price': trades[-1].exit_price if trades else (today_bars[-1]['c'] if today_bars else 0),
                'intraday_path': chart_summary,
                'branch_wisdom': branch_outcomes # Oracle Data
            }
            
            logger.info("[EOD] 🧠 Running LLM Audit...")
            audit = llm_client.get_eod_journal(trades_data, morning_plan, session_id, eod_data, symbol)
            
            if audit:
                logger.info(f"[EOD AUDIT] 📊 Bias Fitness: {audit.get('bias_fitness', 'N/A')} | Edge: {audit.get('primary_edge_source', 'N/A')}")
                if audit.get('nugget_good'):
                    logger.info(f"[EOD AUDIT] ✅ Good: {audit.get('nugget_good')}")
                if audit.get('nugget_bad'):
                    logger.info(f"[EOD AUDIT] ⚠️ Bad: {audit.get('nugget_bad')}")
                    
                # PERSIST EXPERIENCE to RAG (Strict Causality)
                from data.database import save_experience
                
                # Separate stats for persistence?
                # Usually we want Real stats for "Performance" tracking.
                real_trades = [t for t in trades if not t.is_counterfactual]
                
                total_pnl = sum(t.pnl_points for t in real_trades)
                stats = {
                    'total_pnl': total_pnl,
                    'wins': sum(1 for t in real_trades if t.pnl_points > 0),
                    'losses': sum(1 for t in real_trades if t.pnl_points <= 0)
                }
                
                market_state = {
                    'bias': morning_plan.get('primary_bias'),
                    'regime': morning_plan.get('period_regime', 'UNKNOWN')
                }
                
                # Sage Context (Technical + Counterfactual)
                tech_context = {}
                if morning_plan:
                    tech_context = {
                        'vix': morning_plan.get('vix_at_open'),
                        'atr': morning_plan.get('atr_at_open'),
                        'regime_id': morning_plan.get('regime_id')
                    }
                
                # Simplified Counterfactual mapping for RAG
                # We'll probably want the EOD LLM to summarize these into the nugget text.
                
                save_experience(
                    session_id=session_id,
                    date=timestamp.strftime('%Y-%m-%d'),
                    symbol=symbol,
                    market_state=market_state,
                    plan=morning_plan or {},
                    trades=trades_data,
                    stats=stats,
                    audit=audit,
                    timestamp=timestamp,
                    tech_context=tech_context
                )
                logger.debug(f"[RAG] 💾 Experience saved for {timestamp}")

        except Exception as e:
            logger.error(f"[EOD] Failed to run LLM audit: {e}", exc_info=True)
    
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
            or_range=or_range,
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
