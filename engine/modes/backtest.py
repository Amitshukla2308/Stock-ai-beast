import pandas as pd
from datetime import datetime, timedelta, time
import pytz
from data.database import get_connection, fetch_context_data, get_fyers_symbol
from brain.llm_client import LLMClient
from hot_path.executor import HotPathExecutor
from engine.journal import Journal
from engine.modes.base_mode import BaseMode

IST = pytz.timezone('Asia/Kolkata')
UTC = pytz.utc

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
            print(f"      💀 WIPEOUT #{self.wipeout_count}! Balance ₹{old_balance:.0f} < ₹{MARGIN_PER_LOT} → Reset to ₹{self.initial_balance}")
            
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
    def __init__(self, start_date, end_date, symbol="BANKNIFTY", initial_balance=30000):
        self.start_date = start_date
        self.end_date = end_date
        self.symbol = symbol
        self.conn = get_connection()
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
        print(f"📊 Starting Backtest Mode: {self.start_date.date()} to {self.end_date.date()} (Session: {self.session_id})")
        
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
        print("🛑 Backtest Stopped")
        self.print_final_summary()

    def print_final_summary(self):
        """Aggregate results from Journal for this backtest session"""
        print("\n\n" + "="*80)
        print(f"🏁 FINAL BACKTEST REPORT | Session: {self.session_id}")
        print("="*80)
        
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
                
                print("\n📊 AGGREGATED STATISTICS:")
                print("-"*60)
                print(f"   Highest Trades Day:    {max_trade_day['date']} ({int(max_trade_day['trades'])} trades → {max_trade_pnl_str} pts)")
                print(f"   Avg Trades/Day:        {avg_trades_per_day:.1f}")
                print(f"   Days with No Trades:   {days_with_no_trades}")
                print(f"   Avg Profit/Win:        +{avg_win:.1f} pts")
                print(f"   Avg Loss/Lose:         {avg_loss:.1f} pts")
                print(f"   Avg Peak Profit (MFE): +{avg_max_pnl:.1f} pts")
                print(f"   Overall Mean Open PnL: +{avg_mean_open_pnl:.1f} pts")
                print("-"*60)
            
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
                    if "Nugget:" in content:
                        nuggets.append(content.split("Nugget:")[-1].strip())
                except: continue

            print(f"\n📈 OVERALL PERFORMANCE:")
            print(f"   - Total PnL:     {total_pnl:+.2f} points")
            print(f"   - Max Drawdown:  {abs(max_dd):.2f} points")
            print(f"   - Win Rate:      {win_rate:.1f}% ({total_trades} trades)")
            
            # Balance Monitor Summary
            if self.balance_monitor:
                bal = self.balance_monitor.get_summary()
                rupee_pnl = bal['net_pnl_rupees']
                pnl_color = "+" if rupee_pnl >= 0 else ""
                print(f"\n💰 CAPITAL TRACKING:")
                print(f"   - Initial Balance:   ₹{bal['initial_balance']:,}")
                print(f"   - Final Balance:     ₹{bal['current_balance']:,.0f}")
                print(f"   - Net P&L (₹):       {pnl_color}₹{rupee_pnl:,.0f}")
                print(f"   - Wipeouts:          {bal['wipeout_count']} (resets when < ₹10,000)")

            
            print("\n💎 COLLECTED KNOWLEDGE (Fine-Tuning Nuggets):")
            if not nuggets:
                print("   - No nuggets collected this session.")
            else:
                for idx, n in enumerate(nuggets, 1):
                    # Dedup nuggets if they repeat
                    print(f"   [{idx}] {n}")
            
            print("="*80 + "\n")
            conn.close()
        except Exception as e:
            print(f"   ❌ Final Reporting Error: {e}")

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
        df = self.conn.execute(query).fetchdf()
        
        # Ensure timestamp is timezone-aware UTC then convert to IST for the loop
        if not df.empty:
            if df['timestamp'].dt.tz is None:
                df['timestamp'] = df['timestamp'].dt.tz_localize('UTC')
            df['timestamp'] = df['timestamp'].dt.tz_convert(IST)
            
        return df

    def _run_simulation(self):
        current_date = self.start_date
        
        while current_date <= self.end_date and self.running:
            print(f"🌞 Simulating Day: {current_date.date()}")
            
            # 1. Fetch Day's Tick Data
            day_ticks = self.fetch_data_for_day(current_date)
            
            if day_ticks.empty:
                print("   ⚠️ No data for this day. Skipping.")
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
                result = self.conn.execute(prev_close_query).fetchone()
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
                        print(f"   ⚡ GAP DETECTED: {gap_direction} {abs(gap_pts):.0f}pts ({abs(gap_pct):.1f}%) - {gap_type}")
                    gap_analyzed = True
                
                # A2. EARLY Morning Briefing @ 09:20 for SIGNIFICANT/EXTREME gaps
                if not morning_brief_done and gap_analyzed and gap_info and gap_info['type'] in ['SIGNIFICANT', 'EXTREME'] and current_time.time() >= time(9, 20):
                    print(f"   ⚡ EARLY BRIEF triggered due to {gap_info['type']} gap")
                    self.trigger_morning_brief(current_date, first_tick=tick, gap_info=gap_info)
                    morning_brief_done = True
                    # For EXTREME gaps, trigger immediate tactical
                    if gap_info['type'] == 'EXTREME':
                        print(f"   ⚡ IMMEDIATE TACTICAL for {gap_info['type']} gap")
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
                        print(f"   ❌ Tactical Update Error at {current_time}: {e}")
                    
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
            print(f"   [09:20] 🧠 EARLY Morning Briefing ({gap_info['type']} Gap)...")
        else:
            print(f"   [09:30] 🧠 Morning Briefing...")
        
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
        logic = brief.get('morning_logic', brief.get('market_logic', "No Logic Provided"))
        print(f"      📝 Plan: {logic}")
        self.morning_brief = brief 
        self.journal.log_event(ts, "MORNING", brief)

    def trigger_tactical_update(self, tick):
        if isinstance(tick, pd.Series): tick = tick.to_dict()
        
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
            
            self.hot_path.update_instructions(instructions)
            self.journal.log_event(tick['timestamp'], "TACTICAL", instructions)

    def trigger_eod_journal(self, date):
        print(f"   [15:30] 📔 EOD Journaling & Audit...")
        
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
        
        summary = audit_res.get('audit_summary', "Audit Failed")
        print(f"      📊 {summary}")
        # Log in IST
        self.journal.log_event(date.astimezone(IST).replace(hour=15, minute=30), "EOD_AUDIT", audit_res)
        
        # 4. Reset state for next day (prevents carryover)
        self.morning_brief = None
        self.hot_path.active_instructions = {}  # Clear pending instructions
        # Note: open_position should already be None from 15:15 square-off
