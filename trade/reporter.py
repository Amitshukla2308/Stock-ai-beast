"""
Trade Engine v2.8: Reporter
ALL analytics + reporting live here. 
Objective: Diagnostic instrument for research-grade system health check.
No LLM involvement in metric computation. 
"""
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
import math
from trade.models import Trade, DailySummary, ExitReason
from trade.store import trade_store

logger = logging.getLogger(__name__)

class TradeReporter:
    """Diagnostic Instrument for System Health (Research-Grade)"""
    
    def generate_session_report(self, session_id: str, daily_summaries: List[DailySummary] = None) -> Dict[str, Any]:
        """
        Generate comprehensive canonical session report.
        Phase 3-9 of Reporting v2.8.
        """
        raw_trades = trade_store.get_session_trades(session_id)
        if not raw_trades:
            logger.warning(f"[REPORTER] No trades found for session {session_id}")
            return {}

        # Convert to Trade objects for consistent property access
        trades = []
        for rd in raw_trades:
            # Simple conversion back to Trade-like access if needed, 
            # but we can use dict access for performance since store returns dicts
            trades.append(rd)

        closed_trades = [t for t in trades if t.get('status') == 'CLOSED']
        if not closed_trades:
            return {"session_id": session_id, "total_trades": len(trades), "status": "NO_CLOSED_TRADES"}

        # --- EXECUTION ENGINE (Phase 3) ---
        exec_metrics = self._compute_executive_metrics(closed_trades)
        
        # --- DISTRIBUTION (Phase 4) ---
        distributions = self._compute_distributions(closed_trades)
        
        # --- EXIT QUALITY (Phase 5) ---
        exit_quality = self._compute_exit_quality(closed_trades)
        
        # --- STYLE DIAGNOSTICS (Phase 6) ---
        style_diagnostics = self._compute_style_diagnostics(closed_trades)
        
        # --- DAILY BREAKDOWN (Phase 7) ---
        daily_map = self._compute_daily_map(daily_summaries)
        
        # --- OPPORTUNITY COST (Phase 8) ---
        opp_cost = self._compute_opportunity_cost(daily_summaries, closed_trades)
        
        # --- SYSTEM VERDICT (Phase 9) ---
        verdict = self._generate_verdict(exec_metrics, exit_quality, opp_cost)

        report = {
            "session_id": session_id,
            "executive_summary": exec_metrics,
            "distributions": distributions,
            "exit_quality": exit_quality,
            "style_diagnostics": style_diagnostics,
            "daily_breakdown": daily_map,
            "opportunity_cost": opp_cost,
            "verdict": verdict
        }

        self._print_canonical_report(report)
        return report

    def _compute_executive_metrics(self, trades: List[Dict]) -> Dict[str, Any]:
        wins = [t for t in trades if t.get('pnl_points', 0) > 0]
        losses = [t for t in trades if t.get('pnl_points', 0) <= 0]
        
        total_pnl = sum(t.get('pnl_points', 0) for t in trades)
        gross_profit = sum(t.get('pnl_points', 0) for t in wins)
        gross_loss = abs(sum(t.get('pnl_points', 0) for t in losses))
        
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (gross_profit if gross_profit > 0 else 1.0)
        win_rate = len(wins) / len(trades) if trades else 0
        avg_pnl = total_pnl / len(trades) if trades else 0
        
        # Drawdown calculation
        equity = 0
        peak = 0
        max_dd = 0
        for t in trades:
            equity += t.get('pnl_points', 0)
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)
            
        return {
            "total_trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": win_rate * 100,
            "total_pnl_points": total_pnl,
            "total_pnl_rupees": sum(t.get('pnl_rupees', 0) for t in trades),
            "profit_factor": profit_factor,
            "expectancy": avg_pnl,
            "max_drawdown_pts": max_dd,
            "equity_efficiency": (total_pnl / peak * 100) if peak > 0 else 0
        }

    def _compute_distributions(self, trades: List[Dict]) -> Dict[str, Any]:
        dist = {"style": {}, "direction": {}, "exit_reason": {}}
        for t in trades:
            s, d, r = t.get('style', 'UNK'), t.get('direction', 'UNK'), t.get('exit_reason', 'UNK')
            dist["style"][s] = dist["style"].get(s, 0) + 1
            dist["direction"][d] = dist["direction"].get(d, 0) + 1
            dist["exit_reason"][r] = dist["exit_reason"].get(r, 0) + 1
        return dist

    def _compute_exit_quality(self, trades: List[Dict]) -> Dict[str, Any]:
        wins = [t for t in trades if t.get('pnl_points', 0) > 0]
        
        avg_mfe = sum(t.get('mfe', 0) for t in trades) / len(trades) if trades else 0
        avg_mae = sum(t.get('mae', 0) for t in trades) / len(trades) if trades else 0
        
        avg_real_win = sum(t.get('pnl_points', 0) for t in wins) / len(wins) if wins else 0
        
        # Profit Giveback: How much of MFE was realized?
        # ratio 1 means we exited at high. 0 means we exited at entry.
        exit_efficiency = avg_real_win / avg_mfe if avg_mfe > 0 else 0
        profit_giveback = 1 - exit_efficiency
        
        return {
            "avg_mfe": avg_mfe,
            "avg_mae": avg_mae,
            "avg_realized_win": avg_real_win,
            "profit_giveback_ratio": profit_giveback * 100,
            "exit_efficiency_score": exit_efficiency * 100
        }

    def _compute_style_diagnostics(self, trades: List[Dict]) -> List[Dict]:
        styles = set(t.get('style', 'UNK') for t in trades)
        diagnostics = []
        for style in styles:
            s_trades = [t for t in trades if t.get('style') == style]
            wins = [t for t in s_trades if t.get('pnl_points', 0) > 0]
            pnl = sum(t.get('pnl_points', 0) for t in s_trades)
            mfe = sum(t.get('mfe', 0) for t in s_trades) / len(s_trades)
            mae = sum(t.get('mae', 0) for t in s_trades) / len(s_trades)
            
            # Target/Stop Hit Rates
            targets = [t for t in s_trades if t.get('exit_reason') == 'TGT']
            stops = [t for t in s_trades if t.get('exit_reason') == 'SL']
            
            # Conclusion (Phase 6 Deterministic Logic)
            conclusion = "Neutral behavior."
            if mfe > abs(mae) and pnl < 0:
                conclusion = "ENTRY EDGE DETECTED: Lost in exit logic or slippage (high giveback)."
            elif mfe < abs(mae) and pnl < 0:
                conclusion = "NEGATIVE EDGE: Entry timing is fundamentally flawed for this style."
            elif pnl > 0 and (sum(t.get('mfe', 0) for t in wins) / len(wins) if wins else 0) > pnl/len(s_trades) * 2:
                conclusion = "POSITIVE EDGE: Entries are sharp, but significant profit left on table."
            
            diagnostics.append({
                "style": style,
                "trades": len(s_trades),
                "win_rate": len(wins)/len(s_trades) * 100,
                "target_hit_rate": len(targets)/len(s_trades) * 100,
                "stop_hit_rate": len(stops)/len(s_trades) * 100,
                "net_pnl": pnl,
                "avg_mfe": mfe,
                "avg_mae": mae,
                "avg_hold_time": sum(t.get('bars_held', 0) for t in s_trades) / len(s_trades),
                "conclusion": conclusion
            })
        return diagnostics

    def _compute_daily_map(self, summaries: List[DailySummary]) -> List[Dict]:
        if not summaries: return []
        return [
            {
                "date": s.date,
                "trades": s.total_trades,
                "pnl": s.total_pnl_points,
                "max_dd": s.max_drawdown
            } for s in summaries
        ]

    def _compute_opportunity_cost(self, summaries: List[DailySummary], trades: List[Dict]) -> Dict[str, Any]:
        if not summaries: 
            return {"days_traded": 0, "participation_rate": 0, "missed_edge_cost": 0}
            
        # Refined Edge Proxy (Phase 8): Days with high trend efficiency or significant OR range
        # OR Days where the system actually made money
        days_with_edge = sum(1 for s in summaries if s.trend_efficiency > 0.4 or s.or_range > 100 or s.total_pnl_points > 50)
        days_traded = len([s for s in summaries if s.total_trades > 0])
        
        # Missed Edge Cost (Simple calculation: avg pnl of winning days * missed days)
        winning_days = [s for s in summaries if s.total_pnl_points > 0]
        avg_day_win = sum(s.total_pnl_points for s in winning_days) / len(winning_days) if winning_days else 0
        days_missed = max(0, days_with_edge - days_traded)
        missed_edge_cost = days_missed * avg_day_win

        return {
            "days_with_edge": days_with_edge,
            "days_traded": days_traded,
            "days_missed": days_missed,
            "missed_edge_cost": missed_edge_cost,
            "participation_rate": (days_traded / max(days_with_edge, 1) * 100)
        }

    def _generate_verdict(self, exec: Dict, exit_q: Dict, opp: Dict) -> Dict[str, str]:
        pnl = exec['total_pnl_points']
        wr = exec['win_rate']
        pf = exec['profit_factor']
        eff = exit_q['exit_efficiency_score']
        
        status = "INCONCLUSIVE"
        primary = "Insufficient data."
        action = "Run more backtests."
        
        if pnl > 0 and pf > 1.5:
            status = "POSITIVE_EDGE"
            primary = "System has sustainable alpha."
            action = "Scale size slowly."
        elif pnl < 0:
            status = "NEGATIVE_EDGE"
            primary = "Mathematical drain detected."
            if eff < 40:
                primary += " Primarily due to high giveback (Exit leakage)."
                action = "Re-tighten Trailing Stop logic."
            else:
                primary += " Primarily due to poor Entry Sharpness (Avg MAE > Avg MFE)."
                action = "Audit Style Eligibility rules."
                
        return {
            "status": status,
            "primary": primary,
            "action": action
        }

    def _print_canonical_report(self, report: Dict):
        """Standard v2.8 printout"""
        e = report['executive_summary']
        d = report['distributions']
        q = report['exit_quality']
        v = report['verdict']

        logger.info(f"""
================================================================================
🔬 RESEARCH SESSION REPORT | {report['session_id']}
================================================================================

1. EXECUTIVE SUMMARY
--------------------------------------------------------------------------------
Total Trades          : {e['total_trades']}
Win Rate              : {e['win_rate']:.1f}%
Total PnL             : {e['total_pnl_points']:+.1f} pts (₹{e['total_pnl_rupees']:+.0f})
Profit Factor         : {e['profit_factor']:.2f}
Expectancy            : {e['expectancy']:+.2f} pts/trade
Max Drawdown          : {e['max_drawdown_pts']:.1f} pts
Equity Efficiency     : {e['equity_efficiency']:.1f}%

2. TRADE DISTRIBUTION
--------------------------------------------------------------------------------
By Style              : {d['style']}
By Direction          : {d['direction']}
By Exit Reason        : {d['exit_reason']}

3. EXIT QUALITY (The Leak Detector)
--------------------------------------------------------------------------------
Avg MFE (Potential)   : {q['avg_mfe']:.1f} pts
Avg Realized Win      : {q['avg_realized_win']:.1f} pts
Profit Giveback       : {q['profit_giveback_ratio']:.1f}%  {'⚠️ HIGH' if q['profit_giveback_ratio'] > 50 else '✅ CLEAN'}
Exit Efficiency       : {q['exit_efficiency_score']:.1f}%

4. STYLE DIAGNOSTICS
--------------------------------------------------------------------------------
""")
        for sd in report['style_diagnostics']:
            logger.info(f"[{sd['style']}] {sd['trades']} trades | {sd['win_rate']:.0f}% WR | PnL: {sd['net_pnl']:+.1f}")
            logger.info(f"   TGT Hit: {sd['target_hit_rate']:.0f}% | SL Hit: {sd['stop_hit_rate']:.0f}% | Hold: {sd['avg_hold_time']:.1f} bars")
            logger.info(f"   MFE: {sd['avg_mfe']:.1f} | MAE: {sd['avg_mae']:.1f}")
            logger.info(f"   Conclusion: {sd['conclusion']}")

        logger.info(f"""
5. DAILY BREAKDOWN
--------------------------------------------------------------------------------
""")
        for s in report['daily_breakdown']:
            logger.info(f"  {s['date']} | {s['trades']} trades | PnL: {s['pnl']:+.1f} | MaxDD: {s['max_dd']:.1f}")

        o = report['opportunity_cost']
        logger.info(f"""
6. OPPORTUNITY COST
--------------------------------------------------------------------------------
Days with Edge        : {o['days_with_edge']}
Days Traded           : {o['days_traded']}
Days Missed           : {o['days_missed']}
Missed Edge Cost      : {o['missed_edge_cost']:+.1f} pts
Participation Rate    : {o['participation_rate']:.1f}%

7. SYSTEM VERDICT
--------------------------------------------------------------------------------
STATUS                : {v['status']}
Primary Issue         : {v['primary']}
Action Plan           : {v['action']}

================================================================================
""")

# Global instance
trade_reporter = TradeReporter()
