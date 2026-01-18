import pandas as pd
from datetime import datetime, timedelta, time
import pytz
from data.database import get_connection, fetch_context_data, get_fyers_symbol, save_experience
from brain.llm_client import LLMClient
from hot_path.executor import HotPathExecutor
from engine.journal import Journal
from engine.modes.base_mode import BaseMode
import logging

IST = pytz.timezone('Asia/Kolkata')
UTC = pytz.utc
logger = logging.getLogger(__name__)

# Constants for balance calculation
PTS_TO_RUPEES = 35.75  # 1 NIFTY pt = ₹35.75 (65 qty × 0.55 delta)
MARGIN_PER_LOT = 10000  # ₹10,000 required to hold 1 lot

class BalanceMonitor:
    """Track capital, balance changes, and wipeout events"""
    
    def __init__(self, initial_balance=30000):
        self.initial_balance = initial_balance
        self.total_deposited = initial_balance # Initial deposit
        self.current_balance = initial_balance
        self.wipeout_count = 0
        self.balance_history = []  # [(timestamp, balance)]
        self.trade_count = 0
        
    def update_balance(self, pnl_pts, timestamp=None):
        """Update balance after a trade. PnL in points (NIFTY)."""
        rupee_pnl = pnl_pts * PTS_TO_RUPEES
        
        # Determine actual PnL outcome
        self.current_balance += rupee_pnl
        self.trade_count += 1
        
        # Record history
        self.balance_history.append({
            'timestamp': timestamp,
            'balance': self.current_balance,
            'pnl_rupees': rupee_pnl
        })
        
        # Check for wipeout (balance < margin required)
        if self.current_balance < MARGIN_PER_LOT:
            self.wipeout_count += 1
            old_balance = self.current_balance
            
            # Injection logic: Restore to Initial Balance
            injection_amount = self.initial_balance - self.current_balance
            self.total_deposited += injection_amount
            
            self.current_balance = self.initial_balance
            logger.info(f"      💀 WIPEOUT #{self.wipeout_count}! Balance ₹{old_balance:.0f} < ₹{MARGIN_PER_LOT} -> INJECTED ₹{injection_amount:.0f} -> Reset to ₹{self.initial_balance}")
            
        return self.current_balance
    
    def get_summary(self):
        """Return summary stats"""
        return {
            'initial_balance': self.initial_balance,
            'total_deposited': self.total_deposited, # Track total money put in
            'current_balance': self.current_balance,
            'net_pnl_rupees': self.current_balance - self.total_deposited, # True PnL
            'wipeout_count': self.wipeout_count,
            'trade_count': self.trade_count,
            'balance_history': self.balance_history
        }

class BacktestMode(BaseMode):
    def __init__(self, start_date, end_date, symbol="NIFTY", resolution="1", initial_balance=30000, chat_id=None):
        self.chat_id = chat_id
        self.start_date = start_date
        self.end_date = end_date
        self.symbol = symbol
        self.resolution = resolution
        self.conn_rw = False # Connection will be opened on-demand
        self.session_id = f"BACKTEST_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Components
        self.brain = LLMClient()
        self.hot_path = HotPathExecutor()
        self.journal = Journal(session_id=self.session_id)
        
        # Balance Monitor
        self.balance_monitor = BalanceMonitor(initial_balance)
        self.hot_path.balance_monitor = self.balance_monitor  # Pass to executor
        
        # State
        self.current_time = None
        self.morning_brief = None
        self.running = False



    def start(self):
        """Run the Historical Backtest"""
        # Ensure Brain is Awake
        if not self.brain.wait_for_model_ready():
            logger.error("🛑 CRITICAL: Brain failed to load. Aborting Backtest.")
            return

        logger.info(f"📊 Starting Backtest Mode: {self.start_date.date()} to {self.end_date.date()} (Session: {self.session_id})")
        
        # Register session metadata
        self.journal.register_session(
            symbol=self.symbol,
            start_date=self.start_date.strftime('%Y-%m-%d'),
            end_date=self.end_date.strftime('%Y-%m-%d')
        )
        
        self.running = True
        try:
            self._run_simulation()
        finally:
            self.print_final_summary()

    def stop(self):
        self.running = False
        logger.info("🛑 Backtest Stopped")
        self.print_final_summary()

    def print_final_summary(self):
        """Aggregate results from Journal for this backtest session"""
        logger.info("\n\n" + "="*80)
        logger.info(f"🏁 FINAL BACKTEST REPORT | Session: {self.session_id}")
        logger.info("="*80)
        
        try:
            from data.database import get_connection
            import json
            conn = get_connection()
            
            # 1. Trade Metrics for THIS session
            trades_df = conn.execute(f"SELECT pnl, exit_time, max_pnl, mean_open_pnl FROM simulation_trades WHERE session_id = '{self.session_id}' ORDER BY exit_time ASC").fetchdf()
            total_trades = len(trades_df)
            total_pnl = trades_df['pnl'].sum() if total_trades > 0 else 0
            win_rate = (len(trades_df[trades_df['pnl'] > 0]) / total_trades * 100) if total_trades > 0 else 0
            
            # === AGGREGATED STATISTICS ===
            if total_trades > 0:
                trades_df['date'] = trades_df['exit_time'].dt.date
                daily_stats = trades_df.groupby('date').agg(
                    trades=('pnl', 'count'),
                    pnl=('pnl', 'sum')
                ).reset_index()
                
                # --- METRICS CALCULATION ---
                # Sharpe Ratio (Daily PnL)
                import numpy as np
                daily_pnl = daily_stats['pnl'].values
                mean_daily_pnl = np.mean(daily_pnl)
                std_daily_pnl = np.std(daily_pnl)
                
                # Annualized Sharpe (assuming 252 trading days)
                # Risk Free Rate roughly 0 for this short timeframe or included in expectation
                sharpe_ratio = (mean_daily_pnl / std_daily_pnl * np.sqrt(252)) if std_daily_pnl != 0 else 0
                
                # Sortino (Downside Deviation)
                downside_returns = daily_pnl[daily_pnl < 0]
                std_downside = np.std(downside_returns) if len(downside_returns) > 0 else 1e-9
                sortino_ratio = (mean_daily_pnl / std_downside * np.sqrt(252)) if len(downside_returns) > 0 else 0
                
                # Calculate metrics using business days to ignore weekends
                b_days = pd.bdate_range(start=self.start_date.date(), end=self.end_date.date())
                total_trading_days = len(b_days)
                days_with_trades = len(daily_stats)
                days_with_no_trades = max(0, total_trading_days - days_with_trades)
                avg_trades_per_day = total_trades / days_with_trades if days_with_trades > 0 else 0
                
                # Highest trades day
                max_trade_day = daily_stats.loc[daily_stats['trades'].idxmax()]
                max_trade_pnl_str = f"+{max_trade_day['pnl']:.1f}" if max_trade_day['pnl'] >= 0 else f"{max_trade_day['pnl']:.1f}"
                
                # Avg profit/loss per trade
                winning_trades = trades_df[trades_df['pnl'] > 0]['pnl']
                losing_trades = trades_df[trades_df['pnl'] < 0]['pnl']
                avg_win = winning_trades.mean() if len(winning_trades) > 0 else 0
                avg_loss = losing_trades.mean() if len(losing_trades) > 0 else 0
                profit_factor = abs(winning_trades.sum() / losing_trades.sum()) if losing_trades.sum() != 0 else 99.9
                
                # Fidelity metrics
                avg_max_pnl = trades_df['max_pnl'].mean() if total_trades > 0 else 0
                avg_mean_open_pnl = trades_df['mean_open_pnl'].mean() if total_trades > 0 else 0
                
                logger.info("\n📊 AGGREGATED STATISTICS:")
                logger.info("-"*60)
                logger.info(f"   Sharpe Ratio:          {sharpe_ratio:.2f}")
                logger.info(f"   Sortino Ratio:         {sortino_ratio:.2f}")
                logger.info(f"   Profit Factor:         {profit_factor:.2f}")
                logger.info(f"   Avg Trades/Day:        {avg_trades_per_day:.1f}")
                logger.info(f"   Avg Profit/Win:        +{avg_win:.1f} pts")
                logger.info(f"   Avg Loss/Lose:         {avg_loss:.1f} pts")
                logger.info(f"   Avg Peak Profit (MFE): +{avg_max_pnl:.1f} pts")

                # Advanced Metrics: Best, Worst, Streak
                try:
                    best_trade_pnl = 0
                    worst_trade_pnl = 0
                    longest_win_streak = 0
                    current_streak = 0
                    
                    if total_trades > 0:
                        best_trade_pnl = trades_df['pnl'].max()
                        worst_trade_pnl = trades_df['pnl'].min()
                        
                        # Calculate Streaks
                        for pnl in trades_df['pnl']:
                            if pnl > 0:
                                current_streak += 1
                            else:
                                longest_win_streak = max(longest_win_streak, current_streak)
                                current_streak = 0
                        longest_win_streak = max(longest_win_streak, current_streak)

                    logger.info(f"   Best Trade:            {best_trade_pnl:+.1f} pts")
                    logger.info(f"   Worst Trade:           {worst_trade_pnl:+.1f} pts")
                    logger.info(f"   Longest Win Streak:    {longest_win_streak} trades")
                except Exception as m_err:
                    logger.error(f"   ⚠️ Failed to calc advanced metrics: {m_err}")
                    best_trade_pnl = 0
                    worst_trade_pnl = 0
                    longest_win_streak = 0
                logger.info("-"*60)
            else:
                sharpe_ratio = 0
                sortino_ratio = 0
                profit_factor = 0
                best_trade_pnl = 0
                worst_trade_pnl = 0
                longest_win_streak = 0
            
            # Overall Max Drawdown (Equity Curve)
            max_dd = 0
            try:
                peak = 0
                cumulative_pnl = 0
                for pnl in trades_df['pnl']:
                    cumulative_pnl += pnl
                    if cumulative_pnl > peak:
                        peak = cumulative_pnl
                    dd = cumulative_pnl - peak
                    if dd < max_dd:
                        max_dd = dd
            except: pass

            # 2. Extract Nuggets from Logs for THIS session
            logs = conn.execute(f"SELECT content FROM simulation_logs WHERE event_type = 'EOD_AUDIT' AND session_id = '{self.session_id}'").fetchdf()
            nuggets = []
            for _, row in logs.iterrows():
                try:
                    content = row['content']
                    # Try parsing as JSON first for clean extraction
                    try:
                        data = json.loads(content)
                        # Extract from audit_summary which has the nugget appended
                        summary = data.get('audit_summary', '')
                        if "Nugget:" in summary:
                            nuggets.append(summary.split("Nugget:")[-1].strip())
                        else:
                            # Fallback to direct nugget keys
                            n = data.get('nugget_good', data.get('dataset_nugget'))
                            if n and n != 'N/A':
                                nuggets.append(n)
                    except:
                        # Fallback for old/corrupt logs
                        if "Nugget:" in content:
                            nuggets.append(content.split("Nugget:")[-1].strip().rstrip('"}'))
                except: continue

            logger.info(f"\n📈 OVERALL PERFORMANCE:")
            logger.info(f"   - Total PnL:     {total_pnl:+.2f} points (₹{total_pnl * PTS_TO_RUPEES:+,.2f} @ ₹{PTS_TO_RUPEES}/pt)")
            logger.info(f"   - Max Drawdown:  {abs(max_dd):.2f} points")
            logger.info(f"   - Win Rate:      {win_rate:.1f}% ({total_trades} trades)")
            
            # Balance Monitor Summary
            bal_summary = {}
            if self.balance_monitor:
                bal = self.balance_monitor.get_summary()
                rupee_pnl = bal['net_pnl_rupees']
                pnl_color = "+" if rupee_pnl >= 0 else ""
                bal_summary = bal
                logger.info(f"\n💰 CAPITAL TRACKING:")
                logger.info(f"   - Initial:           ₹{bal['initial_balance']:,}")
                logger.info(f"   - Total Deposited:   ₹{bal['total_deposited']:,.0f}")
                logger.info(f"   - Final Balance:     ₹{bal['current_balance']:,.0f}")
                logger.info(f"   - Net P&L (₹):       {pnl_color}₹{rupee_pnl:,.0f}")
                logger.info(f"   - Wipeouts:          {bal['wipeout_count']}")

            
            logger.info("\n💎 COLLECTED KNOWLEDGE (Fine-Tuning Nuggets):")
            if not nuggets:
                logger.info("   - No nuggets collected this session.")
            else:
                for idx, n in enumerate(nuggets, 1):
                    # Dedup nuggets if they repeat
                    logger.info(f"   [{idx}] {n}")
            
            logger.info("="*80 + "\n")
            
            # --- CONSTRUCT MARKDOWN REPORT ---
            status_emoji = "🟢" if total_pnl > 0 else "🔴"
            # Clean Report for Telegram (Busing fallback tags)
            report_text = f"🏁 *Backtest Complete: {self.symbol}*\n\n"
            report_text += f"{status_emoji} *Total PnL:* {total_pnl:+.1f} pts\n"
            report_text += f"📊 *Win Rate:* {win_rate:.1f}% ({total_trades} trades)\n"
            report_text += f"📉 *Max Drawdown:* {abs(max_dd):.1f} pts\n\n"
            report_text += f"*Performance Metrics:*\n"
            report_text += f"• Sharpe Ratio: {sharpe_ratio:.2f}\n"
            report_text += f"• Profit Factor: {profit_factor:.2f}\n"
            if 'avg_trades_per_day' not in locals(): avg_trades_per_day = 0 # Safety init
            report_text += f"• Avg Trade: {avg_trades_per_day:.1f}/day\n"
            report_text += f"• Best Trade: {best_trade_pnl:+.1f} pts\n"
            report_text += f"• Worst Trade: {worst_trade_pnl:+.1f} pts\n"
            report_text += f"• Longest Streak: {longest_win_streak} wins\n"
            
            if bal_summary:
                pnl_color = "🟢" if bal_summary['net_pnl_rupees'] >= 0 else "🔴"
                report_text += f"\n*💰 Capital Account:*\n"
                report_text += f"• Final Balance: ₹{bal_summary['current_balance']:,.0f}\n"
                report_text += f"• Net PnL: {pnl_color} ₹{bal_summary['net_pnl_rupees']:,.0f}\n"
                if bal_summary['wipeout_count'] > 0:
                     report_text += f"• 💀 Wipeouts: {bal_summary['wipeout_count']}\n"

            # --- NEW REGIME ANALYTICS (User Request) ---
            try:
                ledger = self.hot_path.trade_ledger
                report_text += f"\n*🔬 Regime Analytics:*\n"
                
                regime_stats = {} # {regime: [pnl]}
                hold_times = []
                sides = {'CALL': 0, 'PUT': 0}
                dir_aligned_wins = 0
                profitable_trades = 0
                
                for t in ledger:
                    # Filter for this session only (if hot_path is reused, though currently distinct per mode)
                    # Assuming ledger matches session.
                    pnl = t.get('pnl', 0)
                    if pnl is None: continue
                    
                    # Regime Extraction
                    uc = t.get('micro_context', {})
                    reg = uc.get('trend_regime', 'ROTATION')
                    if uc.get('is_grind'): reg = 'TREND_GRIND'
                    
                    if reg not in regime_stats: regime_stats[reg] = []
                    regime_stats[reg].append(pnl)
                    
                    # Side
                    s = t.get('side', 'UNKNOWN')
                    if 'CALL' in s: sides['CALL'] += 1
                    elif 'PUT' in s: sides['PUT'] += 1
                    
                    # Hold Time
                    et = t.get('entry_time')
                    xt = t.get('exit_time')
                    if et and xt:
                        # Handle string/datetime mix
                        try:
                            if isinstance(et, str): et = datetime.fromisoformat(str(et))
                            if isinstance(xt, str): xt = datetime.fromisoformat(str(xt))
                            dt = (xt - et).total_seconds() / 60
                            hold_times.append(dt)
                        except: pass
                    
                    # Directional Accuracy (NetProgress matches Winner)
                    np = uc.get('net_progress_3', 0)
                    is_profit = pnl > 0
                    if is_profit: profitable_trades += 1
                    
                    aligned = False
                    if np > 0 and 'CALL' in s: aligned = True
                    if np < 0 and 'PUT' in s: aligned = True
                    
                    if is_profit and aligned: dir_aligned_wins += 1
                
                # Stats Output
                for r, pnls in regime_stats.items():
                    c = len(pnls)
                    avg = sum(pnls)/c if c else 0
                    w = len([x for x in pnls if x > 0])
                    wr = (w/c*100) if c else 0
                    report_text += f"• {r}: {c} tx | Exp: {avg:+.1f} pts | WR: {wr:.0f}%\n"
                
                avg_hold = sum(hold_times)/len(hold_times) if hold_times else 0
                dir_acc = (dir_aligned_wins/profitable_trades*100) if profitable_trades else 0
                
                report_text += f"• Avg Hold Time: {avg_hold:.1f} min\n"
                report_text += f"• CALL/PUT Ratio: {sides['CALL']}:{sides['PUT']}\n"
                report_text += f"• Dir. Accuracy: {dir_acc:.1f}% (NetProg on Winners)\n"
                
                # Log for debug
                logger.info(f"   🔬 Regime Stats: {json.dumps({k:len(v) for k,v in regime_stats.items()})}")
                
            except Exception as reg_err:
                logger.error(f"   ⚠️ Regime metrics failed: {reg_err}")

            # TELEGRAM NOTIFICATION (Final Summary)
            summary_payload = {
                "total_pnl": total_pnl,
                "max_dd": abs(max_dd),
                "win_rate": win_rate,
                "total_trades": total_trades,
                "sharpe": f"{sharpe_ratio:.2f}",
                "profit_factor": f"{profit_factor:.2f}",
                "nuggets": nuggets if nuggets else [],
                "report_text": report_text,
                "message": report_text # Backwards compatibility/n8n direct text
            }
            
            if self.balance_monitor:
                bal = self.balance_monitor.get_summary()
                summary_payload['balance'] = {
                    "initial": bal['initial_balance'],
                    "total_deposited": bal['total_deposited'],
                    "final": bal['current_balance'],
                    "net_pnl": bal['net_pnl_rupees'],
                    "wipeouts": bal['wipeout_count']
                }
            
            self._emit_telegram_event("SUMMARY", summary_payload, mode_tag="BACKTEST")
            
            # --- BYPASS: Send via LLM_TRACE (Guaranteed Visibility) ---
            trace_payload = {
                "llm_type": "🏁 FINAL REPORT",
                "time": "END",
                "mode": "BACKTEST",
                "action": "COMPLETE",
                "confidence": 100.0,
                "sl_points": None,
                "target_points": None,
                "reason": report_text, # Inject Markdown Report here
                "engine_decision": "COMPLETED",
                "engine_reason": "Backtest Finished"
            }
            self._emit_telegram_event("LLM_TRACE", trace_payload, mode_tag="BACKTEST")
            
            # --- COUNTERFACTUAL ANALYSIS (Auto-run) ---
            from counterfactual_truth import CounterfactualAnalyzer
            
            logger.info("\n🔬 COUNTERFACTUAL ANALYSIS")
            logger.info("=" * 80)
            try:
                analyzer = CounterfactualAnalyzer(session_id=self.session_id)
                report = analyzer.run_full_analysis()
                if report:
                    logger.info(report)
                    # Send to Telegram - Wrap in dict for compatibility if needed, or send as text
                    self._emit_telegram_event("COUNTERFACTUAL", {"report": report}, mode_tag="BACKTEST")
                    logger.info("✅ Counterfactual analysis complete and sent to Telegram")
                else:
                    logger.info("⚠️  No counterfactual data available (or data load failed)")
            except Exception as cf_err:
                logger.error(f"❌ Counterfactual analysis failed: {cf_err}")
                import traceback
                traceback.print_exc()
            logger.info("=" * 80 + "\n")
            
            conn.close()
        except Exception as e:
            logger.error(f"   ❌ Final Reporting Error: {e}")

    def fetch_data_for_day(self, date):
        """Fetch candles for the specific day (Database is in UTC)"""
        date_str = date.strftime('%Y-%m-%d')
        # 09:15 IST = 03:45 UTC
        # 15:30 IST = 10:00 UTC
        full_symbol = get_fyers_symbol(self.symbol)
        
        table_name = "candles_5min" if getattr(self, 'resolution', '1') == '5' else "candles_1min"
        
        query = f"""
            SELECT * FROM {table_name}
            WHERE symbol = '{full_symbol}'
              AND timestamp >= '{date_str} 03:45:00' 
              AND timestamp <= '{date_str} 10:00:00'
            ORDER BY timestamp ASC
        """
        conn = get_connection()
        df = conn.execute(query).fetchdf()
        conn.close()
        
        # Ensure timestamp is timezone-aware UTC then convert to IST for the loop
        if not df.empty:
            if df['timestamp'].dt.tz is None:
                df['timestamp'] = df['timestamp'].dt.tz_localize('UTC')
            df['timestamp'] = df['timestamp'].dt.tz_convert(IST)
            
        return df

    def _run_simulation(self):
        current_date = self.start_date
        
        while current_date <= self.end_date and self.running:
            logger.info(f"🌞 Simulating Day: {current_date.date()}")
            
            # 1. Fetch Day's Tick Data
            day_ticks = self.fetch_data_for_day(current_date)
            
            if day_ticks.empty:
                logger.info("   ⚠️ No data for this day. Skipping.")
                current_date += timedelta(days=1)
                continue

            # 2. Daily State Reset
            self.morning_brief = None # Reset for the day
            morning_brief_done = False
            last_tactical_update = None
            last_heartbeat_time = None
            gap_analyzed = False
            gap_info = None  # Will store gap detection results
            prev_close = None  # Track previous day close
            
            # Get previous day's close for gap detection
            if current_date > self.start_date:
                prev_day = current_date - timedelta(days=1)
                prev_day_str = prev_day.strftime('%Y-%m-%d')
                full_symbol = get_fyers_symbol(self.symbol)
                prev_close_query = f"""
                    SELECT close FROM candles_1min 
                    WHERE symbol = '{full_symbol}'
                      AND timestamp >= '{prev_day_str} 09:45:00' 
                      AND timestamp <= '{prev_day_str} 10:00:00'
                    ORDER BY timestamp DESC LIMIT 1
                """
                conn = get_connection()
                result = conn.execute(prev_close_query).fetchone()
                conn.close()
                if result:
                    prev_close = result[0]
            
            for _, tick in day_ticks.iterrows():
                # Convert pandas series to dict if needed
                if isinstance(tick, pd.Series): tick = tick.to_dict()
                
                current_time = tick['timestamp']
                
                # A1. GAP DETECTION @ 09:20 (before morning brief)
                if not gap_analyzed and current_time.time() >= time(9, 20) and prev_close:
                    today_open = tick.get('open', tick['close'])
                    gap_pts = today_open - prev_close
                    gap_pct = (gap_pts / prev_close) * 100
                    
                    # Classify gap
                    if abs(gap_pct) >= 3.0:
                        gap_type = 'EXTREME'
                    elif abs(gap_pct) >= 1.5:
                        gap_type = 'SIGNIFICANT'
                    else:
                        gap_type = 'NORMAL'
                    
                    gap_direction = 'UP' if gap_pts > 0 else 'DOWN'
                    gap_info = {
                        'type': gap_type,
                        'direction': gap_direction,
                        'pts': gap_pts,
                        'pct': gap_pct
                    }
                    
                    if gap_type != 'NORMAL':
                        logger.info(f"   ⚡ GAP DETECTED: {gap_direction} {abs(gap_pts):.0f}pts ({abs(gap_pct):.1f}%) - {gap_type}")
                    gap_analyzed = True
                
                # A2. Morning Briefing @ 09:20 (always)
                if not morning_brief_done and current_time.time() >= time(9, 20):
                    self.trigger_morning_brief(current_date, first_tick=tick, gap_info=gap_info)
                    morning_brief_done = True
                    # Set tactical baseline to 09:30 so first tactical fires at 09:30
                    last_tactical_update = current_time.replace(hour=9, minute=15, second=0)
                    # Skip tactical on this same tick to decouple morning brief from tactical
                    skip_tactical_this_tick = True
                else:
                    skip_tactical_this_tick = False
                
                # B. Process Tick (Hot Path)
                self.on_tick(tick)
                
                # C. Check for 15-min Tactical Update (Only after Morning Brief, skip if same tick)
                if morning_brief_done and not skip_tactical_this_tick and self.should_trigger_tactical(current_time, last_tactical_update):
                    try:
                        self.trigger_tactical_update(tick)
                        last_tactical_update = current_time
                        last_heartbeat_time = current_time # Reset heartbeat on tactical update
                    except Exception as e:
                        logger.error(f"   ❌ Tactical Update Error at {current_time}: {e}")
                    
                # D. Heartbeat Log (Restored for Visibility)
                if last_heartbeat_time is None: last_heartbeat_time = current_time
                time_since_hb = (current_time - last_heartbeat_time).total_seconds() / 60
                # Log heartbeat every 60 mins OR if it's 15:00 (Near close)
                if time_since_hb >= 60 or (current_time.minute == 0 and current_time.hour == 15):
                    # Check current PnL if any
                    open_pnl_str = ""
                    if self.hot_path.open_position:
                         # Calculate mock pnl
                         pos = self.hot_path.open_position
                         live_pnl = (tick['close'] - pos['entry_price']) if pos['side'] == 'CALL' else (pos['entry_price'] - tick['close'])
                         open_pnl_str = f" | Open PnL: {live_pnl:.1f}"
                    
                    instr = self.hot_path.active_instructions.get('action', 'WAIT')
                    logger.info(f"   [{current_time.strftime('%H:%M')}] 💓 Heartbeat: {tick['close']:.1f} | Action: {instr}{open_pnl_str}")
                    
                    # Force TELEGRAM Status update (Visible to User)
                    # Force TELEGRAM Status update (Visible to User)
                    atr_val = getattr(self, 'last_atr', 'N/A')
                    vix_val = getattr(self, 'last_vix', 'N/A')
                    hb_msg = f"💓 *Heartbeat* [{current_time.strftime('%H:%M')} {current_time.strftime('%d-%m-%Y')}]\nPrice: {tick['close']:.1f}\nAction: {instr}"
                    if atr_val != 'N/A': hb_msg += f"\nVol: ATR {atr_val:.1f} | VIX {vix_val}"
                    if open_pnl_str: hb_msg += f"\n{open_pnl_str.strip()}"
                    
                    # Add Balance (Smart Log Request)
                    current_bal = self.balance_monitor.current_balance
                    hb_msg += f"\n💰 Balance: ₹{current_bal:,.0f}"

                    self._emit_telegram_event("STATUS", {
                        "date": current_time.strftime('%Y-%m-%d'),
                        "time": current_time.strftime('%H:%M'),
                        "price": tick['close'],
                        "action": instr,
                        "open_pnl": open_pnl_str.replace(" | Open PnL: ", "") if open_pnl_str else "0.0",
                        "balance": self.balance_monitor.current_balance,
                        "message": hb_msg,
                        "economics": {
                            "atr": atr_val,
                            "vix": vix_val
                        }
                    }, mode_tag="BACKTEST")
                    
                    last_heartbeat_time = current_time

            
            # 4. EOD Journal
            self.trigger_eod_journal(current_date)
            
            current_date += timedelta(days=1)

    def on_tick(self, tick):
        """Hot Path: Process every tick"""
        # Convert pandas series to dict if needed, or use as is if HotPath accepts it
        # Simulator passed Series or Dict. let's standardize on Dict for safety
        if isinstance(tick, pd.Series):
             tick = tick.to_dict()
             
        self.hot_path.process_tick(tick)
        
        # Log trades (Only log full closed trades to Journal)
        if self.hot_path.trades:
             for trade in self.hot_path.trades:
                 if trade.get('type') == 'EXIT':
                     self.journal.log_trade(trade)
                     
                     # --- CLEAN UI LOG (EXIT) ---
                     time_str = tick['timestamp'].strftime('%H:%M')
                     price = tick['close']
                     pnl = trade.get('pnl', 0)
                     pnl_str = f"+{pnl:.1f}" if pnl >= 0 else f"{pnl:.1f}"
                     bal = int(self.balance_monitor.current_balance)
                     
                     logger.info(f"[{time_str}] {price} | 💰 EXIT: PnL {pnl_str} (Balance: {bal})")

                     # TELEGRAM NOTIFICATION (EXIT)
                     self._emit_telegram_event("TRADE", {
                         "date": tick['timestamp'].strftime('%Y-%m-%d'),
                         "side": trade.get('side'),
                         "entry": trade.get('entry_price'),
                         "exit": trade.get('exit_price'),
                         "pnl": trade.get('pnl'),
                         "reason": trade.get('reason'),
                         "balance": self.balance_monitor.current_balance
                     }, mode_tag="BACKTEST")
                 
                 elif trade.get('type') == 'ENTRY':
                     # --- CLEAN UI LOG (ENTRY) ---
                     time_str = tick['timestamp'].strftime('%H:%M')
                     price = tick['close']
                     side = trade.get('side')
                     entry = trade.get('entry_price')
                     sl = trade.get('sl')
                     tgt = trade.get('target')
                     
                     logger.info(f"[{time_str}] {price} | 🚀 ENTRY: {side} @ {entry} (SL:{sl}, TGT:{tgt})")

                     # TELEGRAM NOTIFICATION (ENTRY)
                     self._emit_telegram_event("ENTRY", {
                         "date": tick['timestamp'].strftime('%Y-%m-%d'),
                         "side": trade.get('side'),
                         "entry": trade.get('entry_price'),
                         "sl": trade.get('sl'),
                         "target": trade.get('target'),
                         "balance": self.balance_monitor.current_balance
                     }, mode_tag="BACKTEST")
             self.hot_path.trades = [] # Clear buffer

    def should_trigger_tactical(self, current_time, last_update):
        """Trigger every 15 minutes starting 09:30"""
        if current_time.time() < time(9, 30):
            return False
            
        if last_update is None:
            return True
            
        diff = (current_time - last_update).total_seconds() / 60
        # Use a small epsilon for float precision
        return diff >= 14.9

    def trigger_morning_brief(self, date, first_tick=None, gap_info=None):
        if gap_info and gap_info['type'] != 'NORMAL':
            logger.info(f"   [09:20] 🧠 Morning Briefing ({gap_info['type']} Gap)...")
        else:
            logger.info(f"   [09:20] 🧠 Morning Briefing...")
        
        # Ensure we use the tick timestamp for precise context
        ts = first_tick['timestamp'] if first_tick else date.astimezone(IST).replace(hour=9, minute=20)
        context = fetch_context_data(ts, symbol=self.symbol, resolution=self.resolution)
        
        # SLICING: Optimization for Morning Brief
        mb_context = context.copy()
        
        # Add Prev Close for Gap Analysis
        if context.get('daily_3'):
            daily_3 = context['daily_3']
            # FILTER: Find first candle strictly BEFORE today
            current_date_str = date.strftime('%Y-%m-%d')
            prev_day_candle = next((d for d in daily_3 if d.get('date', '9999') < current_date_str), None)
            
            if prev_day_candle:
                # logger.debug(f"      [DEBUG] Fixed Prev Close Source: {prev_day_candle['date']} (Today: {current_date_str})")
                prev_close = prev_day_candle['c']
                # Inject into the tick data for the prompt
                if first_tick:
                    first_tick['prev_close'] = prev_close
        
        # Add gap info to context for LLM
        if gap_info:
            mb_context['gap_info'] = gap_info

        brief = self.brain.get_morning_brief(mb_context, current_tick=first_tick, symbol=self.symbol)
        
        if not brief:
             logger.info("      ⚠️ Brain Malfunction (Morning). Using Default Passive Plan.")
             brief = {
                 'market_personality': 'UNKNOWN',
                 'vix_regime': 'NORMAL',
                 'primary_bias': 'NEUTRAL',
                 'morning_logic': 'Fallback: Defensive Mode due to Brain Failure'
             }

        # ADAPT TO NEW POLICY SCHEMA (STATE MACHINE)
        # Old: morning_logic, market_personality, primary_bias
        # New: notes, risk_regime.vix_state, tactical_permissions.gap_protocol
        
        logic = brief.get('notes', brief.get('morning_logic', brief.get('market_logic', "No Logic Provided")))
        
        # Risk Regime as Personality proxy
        personality = brief.get('risk_regime', {}).get('vix_state', brief.get('market_personality', 'NORMAL'))
        
        # Gap Protocol or Bias as Bias proxy
        bias = brief.get('tactical_permissions', {}).get('gap_protocol', brief.get('primary_bias', 'POLICY_MODE'))

        logger.info(f"      [BRAIN] 📝 Plan: {logic}")
        self.morning_brief = brief 
        
        # Log calculated pivot levels (stored in reference_levels by llm_client)
        levels = brief.get('reference_levels', {})
        support = levels.get('support', 'N/A')
        pivot = levels.get('pivot', 'N/A')
        resistance = levels.get('resistance', 'N/A')
        logger.info(f"      [BRAIN] 📊 Levels: S={support} | P={pivot} | R={resistance}")
        
        self.journal.log_event(ts, "MORNING", brief)
        
        gap_str = "N/A"
        if gap_info:
            gap_str = f"{gap_info.get('direction')} {gap_info.get('pts'):.1f}pts ({gap_info.get('pct'):.1f}%) [{gap_info.get('type')}]"

        self._emit_telegram_event("MORNING_BRIEF", {
            "date": ts.strftime('%Y-%m-%d'),
            "personality": personality,
            "bias": bias,
            "plan": logic,
            "economics": {
                "vix_regime": brief.get('risk_regime', {}).get('vix_state', 'NORMAL'),
                "gap": gap_str,
                "prev_close": mb_context.get('daily_3', [{}])[0].get('c', 'N/A') if mb_context.get('daily_3') else 'N/A'
            },
            "balance": self.balance_monitor.current_balance
        }, mode_tag="BACKTEST")

    def trigger_tactical_update(self, tick):
        if isinstance(tick, pd.Series): tick = tick.to_dict()
        
        try:
            # Fetch Real Context
            context = fetch_context_data(tick['timestamp'], symbol=self.symbol, resolution=self.resolution)
            
            # Calculate Real PnL (Position)
            current_pnl = 0
            if self.hot_path.open_position:
                pos = self.hot_path.open_position
                if pos['side'] == 'CALL':
                    current_pnl = tick['close'] - pos['entry_price']
                else:
                    current_pnl = pos['entry_price'] - tick['close']
            
            # Calculate Day PnL (Sum of closed trades for TODAY from permanent ledger)
            today_str = tick['timestamp'].strftime('%Y-%m-%d')
            day_pnl = 0.0
            for t in self.hot_path.trade_ledger:
                exit_time = t.get('exit_time')
                if exit_time and t.get('pnl') is not None:
                    # Handle both datetime objects and strings
                    if hasattr(exit_time, 'strftime'):
                        exit_date = exit_time.strftime('%Y-%m-%d')
                    else:
                        exit_date = str(exit_time)[:10]
                    if exit_date == today_str:
                        day_pnl += t.get('pnl', 0)
            
            try:
                instructions = self.brain.get_tactical_update(
                    tick, 
                    context=context,
                    plan=self.morning_brief,
                    current_pnl=current_pnl, 
                    open_position=self.hot_path.open_position,
                    day_pnl=day_pnl,
                    symbol=self.symbol
                )
            except Exception as llm_err:
                logger.error(f"   ❌ LLM TACTICAL CALL FAILED: {llm_err}")
                import traceback
                traceback.print_exc()
                instructions = None
            
            if instructions is None:
                logger.warning(f"   ⚠️ TACTICAL returned None at {tick['timestamp'].strftime('%H:%M')}")
            
            if instructions:
                # Inject pre-computed logic for Hot Path
                instructions['atr'] = context.get('atr_14')
                instructions['vix'] = context.get('vix')
                instructions['morning_bias'] = self.morning_brief.get('primary_bias') if self.morning_brief else 'NEUTRAL'
                # Add S/P/R levels for proximity filter (stored in reference_levels)
                if self.morning_brief and 'reference_levels' in self.morning_brief:
                    levels = self.morning_brief['reference_levels']
                    instructions['support'] = levels.get('support', 0)
                    instructions['pivot'] = levels.get('pivot', 0)
                    instructions['resistance'] = levels.get('resistance', 0)
                
                # FIX: Inject tick_time for Exceptional Gate
                # Note: tick['timestamp'] is ALREADY in IST (converted at line 277)
                tick_ts = tick['timestamp']
                # Extract time directly - it's already IST-aware
                raw_tick_time = tick_ts.time() if hasattr(tick_ts, 'time') else tick_ts
                # Store raw time for gate comparison, string for JSON logging
                instructions['tick_time'] = raw_tick_time
                instructions['tick_time_str'] = str(raw_tick_time) if raw_tick_time else 'N/A'
                instructions['close'] = tick['close']
                
                self.hot_path.update_instructions(instructions)
                self.journal.log_event(tick['timestamp'], "TACTICAL", instructions)

                # DEBUG: Confirm we reached this point
                # print(f"      🔍 TRACE_DEBUG: Emitting TACTICAL LLM_TRACE at {tick['timestamp'].strftime('%H:%M')}")
                
                # --- CLEAN UI LOG ---
                time_str = tick['timestamp'].strftime('%H:%M')
                price = tick['close']
                act = instructions.get('action', 'HOLD')
                style = instructions.get('selected_style', 'NONE')
                reason = instructions.get('technical_reason', instructions.get('reason', 'N/A'))[:50] # Truncate reason
                
                # Icons for readability
                brain_icon = "🧠"
                if act == "BUY_CALL": brain_icon = "🟢 CALL"
                elif act == "BUY_PUT": brain_icon = "🔴 PUT"
                elif act == "EXIT": brain_icon = "👋 EXIT"
                
                # Only show style if it's not NONE
                style_str = f"| {style}" if style != "NONE" else ""
                
                logger.info(f"[{time_str}] {price} | {brain_icon} {act} {style_str} | \"{reason}...\"")

                # Save state for Heartbeat
                self.last_atr = instructions.get('atr')
                self.last_vix = instructions.get('vix')

                # --- EMIT LLM_TRACE (UPGRADE) ---
                # Only send if action is NOT HOLD, OR if it has been a long time since last trace (e.g. 60 mins)
                # We need to track last_trace_time on 'self' to do this properly.
                # Assuming 'last_tactical_update' roughly tracks it, but let's be permissive for HOLD.
                action_for_trace = instructions.get('action', 'HOLD')
                
                # Check for significant state changes
                is_trade_action = action_for_trace in ['BUY_CALL', 'BUY_PUT']
                is_rejected = instructions.get('gate_rejected')
                
                # Throttled TRACE for HOLD (Pass if minute is 00 or 30, i.e., twice an hour)
                # Since tactical runs every 15 mins (00, 15, 30, 45), fetching at 00 and 30 gives 2 traces/hr.
                is_periodic_hold = False
                if action_for_trace == 'HOLD':
                    minute = tick['timestamp'].minute
                    if minute == 0 or minute == 30: 
                        is_periodic_hold = True

                should_emit_trace = is_trade_action or is_rejected or is_periodic_hold
                
                if should_emit_trace:
                    try:
                        # Extract last 3 5-min candles for visibility
                        today_5min = context.get('today_5min', [])
                        last_3_candles = []
                        if today_5min:
                            for c in today_5min[-3:]:
                                last_3_candles.append({
                                    't': c.get('ts', 'N/A')[-5:] if c.get('ts') else 'N/A',  # Just HH:MM
                                    'o': round(c.get('o', 0), 1),
                                    'h': round(c.get('h', 0), 1),
                                    'l': round(c.get('l', 0), 1),
                                    'c': round(c.get('c', 0), 1)
                                })
                        
                        trace_title = "TACTICAL"
                        if action_for_trace == "HOLD":
                            trace_title = "TACTICAL (MONITORING)"
                        
                        trace_payload = {
                            "llm_type": trace_title,
                            "time": tick['timestamp'].strftime('%H:%M %d-%m-%Y'),
                            "tick_time": str(instructions.get('tick_time', 'N/A')),
                            "mode": instructions.get('mode', 'UNKNOWN'),
                            "selected_style": instructions.get('selected_style', 'NONE'),
                            "action": action_for_trace,
                            "confidence": instructions.get('confidence', 0.0),
                            "sl_points": instructions.get('sl_points'),
                            "target_points": instructions.get('target_points'),
                            "reason": f"{instructions.get('technical_reason', instructions.get('reason', 'N/A'))}\n\n💰 Balance: ₹{self.balance_monitor.current_balance:,.0f}",
                            "engine_decision": instructions.get('engine_decision', 'EXECUTED'),
                            "engine_reason": instructions.get('engine_reason'),
                            "last_3_candles": last_3_candles,
                            "market_data": {
                                "atr": instructions.get('atr', 'N/A'),
                                "vix": instructions.get('vix', 'N/A'),
                                "support": instructions.get('support', 'N/A'),
                                "resistance": instructions.get('resistance', 'N/A')
                            }
                        }
                        self._emit_telegram_event("LLM_TRACE", trace_payload, mode_tag="BACKTEST")
                    except Exception as trace_err:
                        print(f"      ❌ TACTICAL TRACE EMIT ERROR: {trace_err}")
                
                # --- EMIT EXCEPTIONAL GATE REJECTION (if applicable) ---
                if instructions.get('gate_rejected'):
                    self._emit_telegram_event("TRADE_REJECTED_EXCEPTIONAL_GATE", {
                        "time": tick['timestamp'].strftime('%H:%M'),
                        "action": instructions.get('action'),
                        "confidence": instructions.get('confidence', 0.0),
                        "rejection_reason": instructions.get('engine_reason')
                    }, mode_tag="BACKTEST")

        except KeyError as e:
            logger.error(f"   ❌ TACTICAL KEY ERROR: {e}")
            logger.error(f"      Tick Keys: {list(tick.keys())}")
            import traceback
            traceback.print_exc()
        except Exception as e:
            logger.error(f"   ❌ TACTICAL ERROR: {e}")
            import traceback
            traceback.print_exc()

    def trigger_eod_journal(self, date):
        logger.info(f"   [15:30] 📔 EOD Journaling & Audit...")
        
        # 1. Filter trades for THIS day only
        day_trades = [t for t in self.hot_path.trade_ledger 
                      if str(t.get('exit_time', ''))[:10] == date.strftime('%Y-%m-%d')]
        
        # 2. Prepare Market Reality (EOD Snapshot)
        eod_data = {
            'date': date.strftime('%Y-%m-%d'),
            'ticker': self.symbol,
            'trades_count': len(day_trades)
        }
        
        # 3. Call Auditor (Use filtered day trades)
        audit_res = self.brain.get_eod_journal(
            trades=day_trades,
            morning_plan=self.morning_brief,
            session_id=date.strftime('%Y-%m-%d'),
            eod_data=eod_data,
            symbol=self.symbol
        )
        
        if isinstance(audit_res, dict):
            summary = audit_res.get('audit_summary', "Audit Failed")
        else:
            summary = "Audit Failed (Invalid Response)"
        logger.info(f"      📊 {summary}")
        # Log in IST
        self.journal.log_event(date.astimezone(IST).replace(hour=15, minute=30), "EOD_AUDIT", audit_res)
        
        # TELEGRAM NOTIFICATION
        stats = {
            'total_pnl': sum(t.get('pnl', 0) for t in day_trades if t.get('pnl') is not None),
            'trade_count': len(day_trades),
            'win_rate': (len([t for t in day_trades if t.get('pnl', 0) > 0]) / len(day_trades) * 100) if day_trades else 0
        }
        self._emit_telegram_event("EOD", {
            "date": date.strftime('%Y-%m-%d'),
            "summary": summary,
            "total_pnl": stats.get('total_pnl'),
            "trades": stats.get('trade_count'),
            "win_rate": stats.get('win_rate'),
            "nugget": audit_res.get('dataset_nugget', audit_res.get('nugget_good', 'N/A')),
            "balance": self.balance_monitor.current_balance
        }, mode_tag="BACKTEST")

        # --- EMIT LLM_TRACE (UPGRADE) ---
        trace_payload = {
            "llm_type": "EOD",
            "time": "15:30",
            "mode": "N/A",
            "action": "N/A",
            "confidence": 0.0,
            "sl_points": None,
            "target_points": None,
            "reason": summary,
            "engine_decision": "EXECUTED",
            "engine_reason": None
        }
        self._emit_telegram_event("LLM_TRACE", trace_payload, mode_tag="BACKTEST")
        
        # Save Experience for RAG/RL
        stats = {
            'total_pnl': sum(t.get('pnl', 0) for t in day_trades if t.get('pnl') is not None),
            'trade_count': len(day_trades),
            'win_rate': (len([t for t in day_trades if t.get('pnl', 0) > 0]) / len(day_trades) * 100) if day_trades else 0
        }
        
        save_experience(
            session_id=f"{self.session_id}_{date.strftime('%Y%m%d')}",
            date=date,
            symbol=self.symbol,
            market_state=eod_data, 
            plan=self.morning_brief,
            trades=day_trades,
            stats=stats,
            audit=audit_res
        )
        
        # 4. Reset state for next day (prevents carryover)
        self.morning_brief = None
        self.hot_path.active_instructions = {}  # Clear pending instructions
        # Note: open_position should already be None from 15:15 square-off

    def _run_counterfactual_analysis(self):
        """
        Run counterfactual analysis to measure impact of each decision type.
        Returns formatted results for Telegram notification.
        """
        from counterfactual_truth import CounterfactualAnalyzer
        
        try:
            analyzer = CounterfactualAnalyzer('data/trading.db', self.session_id)
            
            # Run all analyses
            time_exits = analyzer.analyze_time_based_exits()
            blocked = analyzer.analyze_blocked_trades()
            modifications = analyzer.analyze_engine_modifications()
            smart_exits = analyzer.analyze_ai_smart_exits()
            opening_range = analyzer.analyze_opening_range()
            exceptional_gate = analyzer.analyze_exceptional_gate()
            
            # Calculate metrics
            time_saved = sum(-r['diff'] for r in time_exits if r['diff'] < 0)
            time_lost = sum(r['diff'] for r in time_exits if r['diff'] > 0)
            time_net = sum(-r['diff'] for r in time_exits)
            
            blocked_pnl = sum(r['pnl'] for r in blocked)
            blocked_wr = (sum(1 for r in blocked if r['pnl'] > 0) / len(blocked) * 100) if blocked else 0
            
            mod_benefit = sum(r['benefit'] for r in modifications)
            smart_benefit = sum(r['diff'] for r in smart_exits)
            or_pnl = opening_range['removed_pnl']
            late_pnl = sum(r['pnl'] for r in exceptional_gate)
            
            # Format result for Telegram
            result = {
                "time_exits": {
                    "saved": round(time_saved, 1),
                    "lost": round(time_lost, 1),
                    "net": round(time_net, 1),
                    "count": len(time_exits)
                },
                "blocked_trades": {
                    "hypothetical_pnl": round(blocked_pnl, 1),
                    "win_rate": round(blocked_wr, 1),
                    "count": len(blocked)
                },
                "engine_mods": {
                    "benefit": round(mod_benefit, 1),
                    "count": len(modifications)
                },
                "smart_exits": {
                    "benefit": round(smart_benefit, 1),
                    "count": len(smart_exits)
                },
                "opening_range": {
                    "net_pnl": round(or_pnl, 1),
                    "count": opening_range['removed_count']
                },
                "late_session_gate": {
                    "hypothetical_pnl": round(late_pnl, 1),
                    "count": len(exceptional_gate)
                }
            }
            
            # Log to console
            logger.info(f"  Time-Based Exits: Saved {time_saved:.1f}, Lost {time_lost:.1f}, Net {time_net:+.1f}pts ({len(time_exits)} trades)")
            logger.info(f"  Blocked Trades: Would have made {blocked_pnl:+.1f}pts @ {blocked_wr:.0f}% WR ({len(blocked)} signals)")
            logger.info(f"  Engine Modifications: Benefit {mod_benefit:+.1f}pts ({len(modifications)} trades)")
            logger.info(f"  AI Smart Exits: Benefit {smart_benefit:+.1f}pts ({len(smart_exits)} trades)")
            logger.info(f"  Opening Range: Net {or_pnl:+.1f}pts ({opening_range['removed_count']} trades)")
            logger.info(f"  Late Session Gate: Would have made {late_pnl:+.1f}pts ({len(exceptional_gate)} signals)")
            
            return result
            
        except Exception as e:
            logger.error(f"Counterfactual analysis error: {e}")
            import traceback
            traceback.print_exc()
            return None
