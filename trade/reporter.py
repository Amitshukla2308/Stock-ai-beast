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
    
    def generate_session_report(self, session_id: str, daily_summaries: List[DailySummary] = None, llm_client=None) -> Dict[str, Any]:
        """
        Generate comprehensive canonical session report.
        Phase 3-9 of Reporting v2.8.
        Optional Phase 10: LLM Research Report.
        """
        raw_trades = trade_store.get_session_trades(session_id)
        if not raw_trades:
            logger.warning(f"[REPORTER] No trades found for session {session_id}")
            return {}

        # Convert to Trade objects for consistent property access
        # Convert to Trade objects for consistent property access
        all_trades = []
        for rd in raw_trades:
            all_trades.append(rd)
            
        # Filter Logic (Real vs Ghost)
        # Note: 'is_counterfactual' stored as 1/0 in DB, so check truthiness
        trades = [t for t in all_trades if not t.get('is_counterfactual')]
        ghost_trades = [t for t in all_trades if t.get('is_counterfactual')]
        
        closed_ghosts = [t for t in ghost_trades if t.get('status') == 'CLOSED']

        closed_trades = [t for t in trades if t.get('status') == 'CLOSED']
        if not closed_trades:
            logger.info("[REPORTER] No CLOSED real trades. Generating report for Ghosts/Analysis...")


        # --- EXECUTION ENGINE (Phase 3) ---
        exec_metrics = self._compute_executive_metrics(closed_trades)
        
        # --- DISTRIBUTION (Phase 4) ---
        distributions = self._compute_distributions(closed_trades)
        
        # --- REGIME ATTRIBUTION (v4.0 Smart Phase) ---
        regime_stats = self._compute_regime_attribution(closed_trades)
        
        # --- ALPHA QUALITY (v4.0 Smart Phase) ---
        alpha_quality = self._compute_alpha_quality(closed_trades)
        
        # --- EXIT QUALITY (Phase 5) ---
        exit_quality = self._compute_exit_quality(closed_trades)
        
        # --- DAILY BREAKDOWN (Phase 7) ---
        daily_map = self._compute_daily_map(daily_summaries)
        
        # --- OPPORTUNITY COST (Phase 8) ---
        opp_cost = self._compute_opportunity_cost(daily_summaries, closed_trades)
        
        # --- COUNTERFACTUAL ANALYSIS (User Request) ---
        ghost_pnl = sum(t.get('pnl_points', 0) for t in closed_ghosts)
        ghost_wins = len([t for t in closed_ghosts if t.get('pnl_points', 0) > 0])
        ghost_wr = (ghost_wins / len(closed_ghosts) * 100) if closed_ghosts else 0.0
        
        # --- LOSS ATTRIBUTION (v4.2) ---
        top_losers = sorted([t for t in closed_trades if t.get('pnl_points', 0) < 0], key=lambda x: x.get('pnl_points', 0))[:5]
        
        # --- SYSTEM VERDICT (Phase 9) ---
        verdict = self._generate_verdict(exec_metrics, exit_quality, opp_cost)

        report = {
            "session_id": session_id,
            "executive_summary": exec_metrics,
            "distributions": distributions,
            "regime_attribution": regime_stats,
            "alpha_quality": alpha_quality,
            "exit_quality": exit_quality,
            "daily_breakdown": daily_map,
            "opportunity_cost": opp_cost,
            "counterfactuals": {
                "trades": len(closed_ghosts),
                "net_pnl": ghost_pnl,
                "win_rate": ghost_wr,
                "block_reasons": self._compute_block_reasons(ghost_trades)
            },
            "top_losers": top_losers,
            "verdict": verdict
        }

        self._print_analyst_report(report)
        
        # --- PHASE 10: RESEARCH STATE ENGINE (Spec-002) ---
        if llm_client:
            logger.info("\n🧠 [PHASE 10] GENERATING RESEARCH REPORT (Deterministic)...")
            try:
                # 1. Compute Research State (Deterministic Truth)
                from enrichment.diagnostics import compute_research_state
                from trade.models import Trade
                
                research_states = []
                valid_fields = set(Trade.__annotations__.keys())
                
                for t_dict in raw_trades:
                    # Filter DB columns that aren't in Model (e.g., created_at)
                    clean_dict = {k: v for k, v in t_dict.items() if k in valid_fields}
                    # Handle Enums conversions if needed? 
                    # TradeStatus/ExitReason are Enums in model but strings in DB.
                    # Dataclass might expect Enum?
                    # Python dataclasses don't enforce type check on init, but logic might fail later.
                    # Diagnostics uses .style (str) and .entry_time (datetime).
                    # DB returns ISO strings for time!
                    from datetime import datetime
                    if isinstance(clean_dict.get('entry_time'), str):
                        clean_dict['entry_time'] = datetime.fromisoformat(clean_dict['entry_time'])
                    if isinstance(clean_dict.get('exit_time'), str):
                        clean_dict['exit_time'] = datetime.fromisoformat(clean_dict['exit_time'])
                        
                    trade_obj = Trade(**clean_dict)
                    r_state = compute_research_state(trade_obj)
                    research_states.append(r_state)
                
                # 2. Build Payload
                research_payload = {
                    "session_summary": report['executive_summary'],
                    "trades": research_states,
                    "market_context": report.get('market_context', {})
                }
                
                # 3. Call LLM (Narrator Mode)
                research_md = llm_client.generate_research_report(research_payload)
                logger.info("\n" + "="*80 + "\n" + research_md + "\n" + "="*80)
                
            except Exception as e:
                logger.error(f"❌ Failed to generate Research Report: {e}", exc_info=True)
                
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

    def _compute_block_reasons(self, ghost_trades: List[Dict]) -> Dict[str, int]:
        reasons = {}
        for t in ghost_trades:
            br = t.get('block_reason', 'Unknown Risk')
            reasons[br] = reasons.get(br, 0) + 1
        return reasons

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
            return {"days_with_edge": 0, "days_traded": 0, "days_missed": 0, "participation_rate": 0, "missed_edge_cost": 0}
            
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

    def _compute_regime_attribution(self, trades: List[Dict]) -> List[Dict]:
        """v4.0 Smart Attribution: Breakdown by Cluster Pairs"""
        regimes = set(t.get('regime', 'UNK') for t in trades)
        attribution = []
        for reg in regimes:
            r_trades = [t for t in trades if t.get('regime') == reg]
            wins = [t for t in r_trades if t.get('pnl_points', 0) > 0]
            pnl = sum(t.get('pnl_points', 0) for t in r_trades)
            mfe = sum(t.get('mfe', 0) for t in r_trades) / len(r_trades)
            mae = abs(sum(t.get('mae', 0) for t in r_trades) / len(r_trades))
            
            attribution.append({
                "regime": reg,
                "trades": len(r_trades),
                "win_rate": len(wins)/len(r_trades) * 100,
                "pnl": pnl,
                "avg_mfe": mfe,
                "avg_mae": mae,
                "sharpness": (mfe / mae) if mae > 0 else mfe
            })
        return sorted(attribution, key=lambda x: x['pnl'], reverse=True)

    def _compute_alpha_quality(self, trades: List[Dict]) -> Dict[str, Any]:
        """v4.0 Alpha Quality: High-Alpha (Confluence) vs Fallback (Stat)"""
        high_alpha = [t for t in trades if not t.get('metadata', {}).get('is_fallback', False)]
        fallback = [t for t in trades if t.get('metadata', {}).get('is_fallback', False)]
        
        def summarize(subset):
            if not subset: return {"trades": 0, "pnl": 0.0, "pnl_per_trade": 0.0, "wr": 0.0}
            pnl = sum(t.get('pnl_points', 0) for t in subset)
            wins = len([t for t in subset if t.get('pnl_points', 0) > 0])
            return {
                "trades": len(subset),
                "pnl": pnl,
                "pnl_per_trade": pnl / len(subset),
                "wr": wins / len(subset) * 100
            }

        return {
            "high_alpha": summarize(high_alpha),
            "fallback": summarize(fallback)
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

    def _print_analyst_report(self, report: Dict):
        """v4.0 Smart Analyst Layout: Data-Dense & Physics-Aware"""
        e = report['executive_summary']
        d = report['distributions']
        q = report['exit_quality']
        v = report['verdict']
        a = report['alpha_quality']
        
        C_RESET = "\033[0m"
        C_CYAN = "\033[96m"
        C_YELLOW = "\033[93m"
        C_GREEN = "\033[92m"
        C_RED = "\033[91m"
        C_DIM = "\033[2m"

        print(f"\n{C_CYAN}" + "="*80)
        print(f"🔬 SOVEREIGN RESEARCH REPORT v4.0 | {report['session_id']}")
        print("="*80 + f"{C_RESET}")

        print(f"\n{C_YELLOW}1. ALPHA MATURITY & QUALITY{C_RESET}")
        print("-" * 40)
        ha = a['high_alpha']
        fs = a['fallback']
        print(f"High-Alpha (Confluence) : {ha['trades']} trades | WR: {ha['wr']:.1f}% | PnL: {C_GREEN}{ha['pnl']:+.1f}{C_RESET}")
        print(f"Stat-Fallback          : {fs['trades']} trades | WR: {fs['wr']:.1f}% | PnL: {C_GREEN if fs['pnl'] >= 0 else C_RED}{fs['pnl']:+.1f}{C_RESET}")
        print(f"Alpha Integrity        : {C_DIM}{'CONVERGENT' if ha['pnl'] > fs['pnl'] else 'DECENTRALIZED'}{C_RESET}")

        print(f"\n{C_YELLOW}2. REGIME ATTRIBUTION (Top 5 Cluster Pairs){C_RESET}")
        print("-" * 40)
        print(f"{'Regime':<12} | {'Trades':<6} | {'WR':<6} | {'PnL':<8} | {'Sharpness'}")
        for ra in report['regime_attribution'][:5]:
            p_color = C_GREEN if ra['pnl'] > 0 else C_RED
            print(f"{ra['regime']:<12} | {ra['trades']:<6} | {ra['win_rate']:>5.0f}% | {p_color}{ra['pnl']:>8.1f}{C_RESET} | {ra['sharpness']:.2f}")

        print(f"\n{C_RED}3. LOSS ATTRIBUTION (Top 5 Failures){C_RESET}")
        print("-" * 40)
        print(f"{'Trade ID':<20} | {'Regime':<10} | {'Reason':<12} | {'PnL'}")
        for lt in report['top_losers']:
            # Shorten trade ID for display
            short_id = lt['trade_id'].split('_')[-2:]
            short_id = "_".join(short_id)
            print(f"{short_id:<20} | {lt['regime']:<10} | {lt['exit_reason']:<12} | {C_RED}{lt['pnl_points']:>8.1f}{C_RESET}")

        print(f"\n{C_YELLOW}4. EXECUTIVE PHYSICS SUMMARY{C_RESET}")
        print("-" * 40)
        pnl_color = C_GREEN if e['total_pnl_points'] > 0 else C_RED
        rupee_color = C_GREEN if e['total_pnl_rupees'] > 0 else C_RED
        print(f"Net PnL (Points)      : {pnl_color}{e['total_pnl_points']:+.1f} pts{C_RESET}")
        print(f"Net PnL (Rupees)      : {rupee_color}₹{e['total_pnl_rupees']:+,.0f}{C_RESET}")
        print(f"Profit Factor         : {e['profit_factor']:.2f}")
        print(f"Win Rate              : {e['win_rate']:.1f}%")
        print(f"Max Drawdown          : {C_RED}{e['max_drawdown_pts']:.1f} pts{C_RESET}")

        print(f"\n{C_YELLOW}5. EXIT QUALITY & LEAKAGE{C_RESET}")
        print("-" * 40)
        giveback_color = C_RED if q['profit_giveback_ratio'] > 50 else C_GREEN
        print(f"Avg MFE (Potential)   : {q['avg_mfe']:.1f} pts")
        print(f"Avg Realized Win      : {q['avg_realized_win']:.1f} pts")
        print(f"Profit Giveback       : {giveback_color}{q['profit_giveback_ratio']:.1f}%{C_RESET}")
        print(f"Exit Efficacy         : {q['exit_efficiency_score']:.1f}%")

        # New Forensic Exit Breakdown (v4.4)
        print(f"\n{C_YELLOW}5.1 FORENSIC EXIT BREAKDOWN (v4.4){C_RESET}")
        print("-" * 40)
        ex_dist = d.get('exit_reason', {})
        for reason, count in ex_dist.items():
            # Check for Enum value or string name
            r_name = reason.name if hasattr(reason, 'name') else str(reason)
            if r_name in ["STALE", "JITTER"]:
                print(f"{r_name:<10} Exits : {C_CYAN}{count}{C_RESET}")

        o = report['opportunity_cost']
        c = report['counterfactuals']
        print(f"\n{C_YELLOW}6. SYSTEM VITALITY & VERDICT{C_RESET}")
        print("-" * 40)
        print(f"Participation Rate    : {o['participation_rate']:.1f}%")
        
        # New Block Reason Summary (v4.4)
        if c['trades'] > 0:
            print(f"Risk-Blocked Signals : {C_RED}{c['trades']}{C_RESET}")
            for br, bcount in c.get('block_reasons', {}).items():
                short_br = br.split(":")[0] if ":" in br else br
                color = C_YELLOW if "Sterilization" in short_br else ""
                print(f"  -> {color}{short_br:<20} : {bcount}{C_RESET}")

        print(f"System Health         : {C_CYAN}{v['status']}{C_RESET}")
        print(f"Diagnosis             : {v['primary']}")
        print(f"Prescription          : {C_YELLOW}{v['action']}{C_RESET}")

        print(f"\n{C_CYAN}" + "="*80 + f"{C_RESET}\n")

# Global instance
trade_reporter = TradeReporter()
