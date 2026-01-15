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
PTS_TO_RUPEES = 27.5  # 1 NIFTY pt = ₹27.5 (50 qty × 0.55 delta)
MARGIN_PER_LOT = 10000  # ₹10,000 required to hold 1 lot

class BalanceMonitor:
    """Track capital, balance changes, and wipeout events"""
    
    def __init__(self, initial_balance=30000):
        self.initial_balance = initial_balance
        self.current_balance = initial_balance
        self.wipeout_count = 0
        self.balance_history = []  # [(timestamp, balance)]
        self.trade_count = 0
        
    def update_balance(self, pnl_pts, timestamp=None):
        """Update balance after a trade. PnL in points (NIFTY)."""
        rupee_pnl = pnl_pts * PTS_TO_RUPEES
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
            self.current_balance = self.initial_balance
            logger.info(f"      💀 WIPEOUT #{self.wipeout_count}! Balance ₹{old_balance:.0f} < ₹{MARGIN_PER_LOT} → Reset to ₹{self.initial_balance}")
            
        return self.current_balance
    
    def get_summary(self):
        """Return summary stats"""
        return {
            'initial_balance': self.initial_balance,
            'current_balance': self.current_balance,
            'net_pnl_rupees': self.current_balance - self.initial_balance,
            'wipeout_count': self.wipeout_count,
            'trade_count': self.trade_count,
            'balance_history': self.balance_history
        }

class BacktestMode(BaseMode):
    def __init__(self, start_date, end_date, symbol="NIFTY", initial_balance=30000, chat_id=None):
        self.chat_id = chat_id
        self.start_date = start_date
        self.end_date = end_date
        self.symbol = symbol
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
                
                # Fidelity metrics
                avg_max_pnl = trades_df['max_pnl'].mean() if total_trades > 0 else 0
                avg_mean_open_pnl = trades_df['mean_open_pnl'].mean() if total_trades > 0 else 0
                
                logger.info("\n📊 AGGREGATED STATISTICS:")
                logger.info("-"*60)
                logger.info(f"   Highest Trades Day:    {max_trade_day['date']} ({int(max_trade_day['trades'])} trades → {max_trade_pnl_str} pts)")
                logger.info(f"   Avg Trades/Day:        {avg_trades_per_day:.1f}")
                logger.info(f"   Days with No Trades:   {days_with_no_trades}")
                logger.info(f"   Avg Profit/Win:        +{avg_win:.1f} pts")
                logger.info(f"   Avg Loss/Lose:         {avg_loss:.1f} pts")
                logger.info(f"   Avg Peak Profit (MFE): +{avg_max_pnl:.1f} pts")
                logger.info(f"   Overall Mean Open PnL: +{avg_mean_open_pnl:.1f} pts")
                logger.info("-"*60)
            
            # Overall Max Drawdown (Equity Curve)
            max_dd = 0
            peak = 0
            cumulative_pnl = 0
            for pnl in trades_df['pnl']:
                cumulative_pnl += pnl
                if cumulative_pnl > peak:
                    peak = cumulative_pnl
                dd = cumulative_pnl - peak
                if dd < max_dd:
                    max_dd = dd

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
            logger.info(f"   - Total PnL:     {total_pnl:+.2f} points")
            logger.info(f"   - Max Drawdown:  {abs(max_dd):.2f} points")
            logger.info(f"   - Win Rate:      {win_rate:.1f}% ({total_trades} trades)")
            
            # Balance Monitor Summary
            if self.balance_monitor:
                bal = self.balance_monitor.get_summary()
                rupee_pnl = bal['net_pnl_rupees']
                pnl_color = "+" if rupee_pnl >= 0 else ""
                logger.info(f"\n💰 CAPITAL TRACKING:")
                logger.info(f"   - Initial Balance:   ₹{bal['initial_balance']:,}")
                logger.info(f"   - Final Balance:     ₹{bal['current_balance']:,.0f}")
                logger.info(f"   - Net P&L (₹):       {pnl_color}₹{rupee_pnl:,.0f}")
                logger.info(f"   - Wipeouts:          {bal['wipeout_count']} (resets when < ₹10,000)")

            
            logger.info("\n💎 COLLECTED KNOWLEDGE (Fine-Tuning Nuggets):")
            if not nuggets:
                logger.info("   - No nuggets collected this session.")
            else:
                for idx, n in enumerate(nuggets, 1):
                    # Dedup nuggets if they repeat
                    logger.info(f"   [{idx}] {n}")
            
            logger.info("="*80 + "\n")
            # TELEGRAM NOTIFICATION (Final Summary)
            summary_payload = {
                "total_pnl": total_pnl,
                "max_dd": abs(max_dd),
                "win_rate": win_rate,
                "total_trades": total_trades,
                "nuggets": nuggets if nuggets else []
            }
            
            if self.balance_monitor:
                bal = self.balance_monitor.get_summary()
                summary_payload['balance'] = {
                    "initial": bal['initial_balance'],
                    "final": bal['current_balance'],
                    "net_pnl": bal['net_pnl_rupees'],
                    "wipeouts": bal['wipeout_count']
                }
                
            self._emit_telegram_event("SUMMARY", summary_payload, mode_tag="BACKTEST")
            conn.close()
        except Exception as e:
            logger.error(f"   ❌ Final Reporting Error: {e}")

    def fetch_data_for_day(self, date):
        """Fetch 5-min candles for the specific day (Database is in UTC)"""
        date_str = date.strftime('%Y-%m-%d')
        # 09:15 IST = 03:45 UTC
        # 15:30 IST = 10:00 UTC
        full_symbol = get_fyers_symbol(self.symbol)
        query = f"""
            SELECT * FROM candles_1min 
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
                
                # A2. EARLY Morning Briefing @ 09:20 for SIGNIFICANT/EXTREME gaps
                if not morning_brief_done and gap_analyzed and gap_info and gap_info['type'] in ['SIGNIFICANT', 'EXTREME'] and current_time.time() >= time(9, 20):
                    logger.info(f"   ⚡ EARLY BRIEF triggered due to {gap_info['type']} gap")
                    self.trigger_morning_brief(current_date, first_tick=tick, gap_info=gap_info)
                    morning_brief_done = True
                    # For EXTREME gaps, trigger immediate tactical
                    if gap_info['type'] == 'EXTREME':
                        logger.info(f"   ⚡ IMMEDIATE TACTICAL for {gap_info['type']} gap")
                        self.trigger_tactical_update(tick)
                    last_tactical_update = current_time
                
                # A3. Standard Morning Briefing @ 09:30 (if no early brief)
                elif not morning_brief_done and current_time.time() >= time(9, 30):
                    self.trigger_morning_brief(current_date, first_tick=tick, gap_info=gap_info)
                    morning_brief_done = True
                    # Set tactical update baseline to now so we don't trigger immediately
                    last_tactical_update = current_time 
                
                # B. Process Tick (Hot Path)
                self.on_tick(tick)
                
                # C. Check for 15-min Tactical Update (Only after Morning Brief)
                if morning_brief_done and self.should_trigger_tactical(current_time, last_tactical_update):
                    try:
                        self.trigger_tactical_update(tick)
                        last_tactical_update = current_time
                        last_heartbeat_time = current_time # Reset heartbeat on tactical update
                    except Exception as e:
                        logger.error(f"   ❌ Tactical Update Error at {current_time}: {e}")
                    
                # D. Heartbeat Log removed for compact output - trade executions provide sufficient visibility
            
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
            logger.info(f"   [09:20] 🧠 EARLY Morning Briefing ({gap_info['type']} Gap)...")
        else:
            logger.info(f"   [09:30] 🧠 Morning Briefing...")
        
        # Ensure we use the tick timestamp for precise context
        ts = first_tick['timestamp'] if first_tick else date.astimezone(IST).replace(hour=9, minute=30)
        context = fetch_context_data(ts, symbol=self.symbol)
        
        # SLICING: Optimization for Morning Brief
        mb_context = context.copy()
        
        # Add Prev Close for Gap Analysis
        if context.get('daily_3'):
            prev_close = context['daily_3'][-1]['c']
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

        logic = brief.get('morning_logic', brief.get('market_logic', "No Logic Provided"))
        logger.info(f"      📝 Plan: {logic}")
        self.morning_brief = brief 
        self.journal.log_event(ts, "MORNING", brief)
        
        # TELEGRAM NOTIFICATION
        self._emit_telegram_event("MORNING_BRIEF", {
            "date": ts.strftime('%Y-%m-%d'),
            "personality": brief.get('market_personality'),
            "bias": brief.get('primary_bias'),
            "plan": logic
        }, mode_tag="BACKTEST")

        # --- EMIT LLM_TRACE (UPGRADE) ---
        trace_payload = {
            "llm_type": "MORNING",
            "time": ts.strftime('%H:%M'),
            "mode": "N/A",
            "action": "N/A",
            "confidence": 0.0,
            "sl_points": None,
            "target_points": None,
            "reason": logic,
            "engine_decision": "EXECUTED",
            "engine_reason": None
        }
        self._emit_telegram_event("LLM_TRACE", trace_payload, mode_tag="BACKTEST")

    def trigger_tactical_update(self, tick):
        if isinstance(tick, pd.Series): tick = tick.to_dict()
        
        try:
            # Fetch Real Context
            context = fetch_context_data(tick['timestamp'], symbol=self.symbol)
            
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
            
            instructions = self.brain.get_tactical_update(
                tick, 
                context=context,
                plan=self.morning_brief,
                current_pnl=current_pnl, 
                open_position=self.hot_path.open_position,
                day_pnl=day_pnl,
                symbol=self.symbol
            )
            if instructions:
                # Inject pre-computed logic for Hot Path
                instructions['atr'] = context.get('atr_14')
                instructions['vix'] = context.get('vix')
                instructions['morning_bias'] = self.morning_brief.get('primary_bias') if self.morning_brief else 'NEUTRAL'
                # Add S/P/R levels for proximity filter
                if self.morning_brief and 'boundary_levels' in self.morning_brief:
                    levels = self.morning_brief['boundary_levels']
                    instructions['support'] = levels.get('support_zone', 0)
                    instructions['pivot'] = levels.get('pivot_point', 0)
                    instructions['resistance'] = levels.get('resistance_zone', 0)
                
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
                print(f"      🔍 TRACE_DEBUG: Emitting TACTICAL LLM_TRACE at {tick['timestamp'].strftime('%H:%M')}")
                
                # --- EMIT LLM_TRACE (UPGRADE) ---
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
                    
                    trace_payload = {
                        "llm_type": "TACTICAL",
                        "time": tick['timestamp'].strftime('%H:%M'),
                        "tick_time": str(instructions.get('tick_time', 'N/A')),
                        "mode": instructions.get('mode', 'UNKNOWN'),
                        "action": instructions.get('action', 'HOLD'),
                        "confidence": instructions.get('confidence', 0.0),
                        "sl_points": instructions.get('sl_points'),
                        "target_points": instructions.get('target_points'),
                        "reason": instructions.get('technical_reason', instructions.get('reason', 'N/A')),
                        "engine_decision": instructions.get('engine_decision', 'EXECUTED'),
                        "engine_reason": instructions.get('engine_reason'),
                        "last_3_candles": last_3_candles
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
            "nugget": audit_res.get('dataset_nugget', audit_res.get('nugget_good', 'N/A'))
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
