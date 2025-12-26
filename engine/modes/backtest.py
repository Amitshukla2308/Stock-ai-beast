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

class BacktestMode(BaseMode):
    def __init__(self, start_date, end_date, symbol="BANKNIFTY"):
        self.start_date = start_date
        self.end_date = end_date
        self.symbol = symbol
        self.conn = get_connection()
        self.session_id = f"BACKTEST_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Components
        self.brain = LLMClient()
        self.hot_path = HotPathExecutor()
        self.journal = Journal(session_id=self.session_id)
        
        # State
        self.current_time = None
        self.morning_brief = None
        self.running = False

    def start(self):
        """Run the Historical Backtest"""
        print(f"📊 Starting Backtest Mode: {self.start_date.date()} to {self.end_date.date()} (Session: {self.session_id})")
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
            trades_df = conn.execute(f"SELECT pnl, exit_time FROM simulation_trades WHERE session_id = '{self.session_id}' ORDER BY exit_time ASC").fetchdf()
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
                
                # Calculate metrics
                total_days = (self.end_date - self.start_date).days
                days_with_trades = len(daily_stats)
                days_with_no_trades = total_days - days_with_trades
                avg_trades_per_day = total_trades / days_with_trades if days_with_trades > 0 else 0
                
                # Highest trades day
                max_trade_day = daily_stats.loc[daily_stats['trades'].idxmax()]
                max_trade_pnl_str = f"+{max_trade_day['pnl']:.1f}" if max_trade_day['pnl'] >= 0 else f"{max_trade_day['pnl']:.1f}"
                
                # Avg profit/loss per trade
                winning_trades = trades_df[trades_df['pnl'] > 0]['pnl']
                losing_trades = trades_df[trades_df['pnl'] < 0]['pnl']
                avg_win = winning_trades.mean() if len(winning_trades) > 0 else 0
                avg_loss = losing_trades.mean() if len(losing_trades) > 0 else 0
                
                print("\n📊 AGGREGATED STATISTICS:")
                print("-"*60)
                print(f"   Highest Trades Day:    {max_trade_day['date']} ({int(max_trade_day['trades'])} trades → {max_trade_pnl_str} pts)")
                print(f"   Avg Trades/Day:        {avg_trades_per_day:.1f}")
                print(f"   Days with No Trades:   {days_with_no_trades}")
                print(f"   Avg Profit/Win:        +{avg_win:.1f} pts")
                print(f"   Avg Loss/Lose:         {avg_loss:.1f} pts")
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
            SELECT * FROM candles_5min 
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
            
            for _, tick in day_ticks.iterrows():
                # Convert pandas series to dict if needed
                if isinstance(tick, pd.Series): tick = tick.to_dict()
                
                current_time = tick['timestamp']
                
                # A. Morning Briefing @ 09:30
                if not morning_brief_done and current_time.time() >= time(9, 30):
                    self.trigger_morning_brief(current_date, first_tick=tick)
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

    def trigger_morning_brief(self, date, first_tick=None):
        print(f"   [09:30] 🧠 Morning Briefing (Gap Analysis)...")
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

        brief = self.brain.get_morning_brief(mb_context, current_tick=first_tick, symbol=self.symbol)
        logic = brief.get('market_logic', "No Logic Provided")
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
        day_pnl = sum([t.get('pnl', 0) for t in self.hot_path.trade_ledger 
                       if t.get('pnl') is not None and str(t.get('exit_time', ''))[:10] == today_str])
        
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
        summary = self.brain.get_eod_journal(
            trades=day_trades,
            morning_plan=self.morning_brief,
            session_id=date.strftime('%Y-%m-%d'),
            eod_data=eod_data,
            symbol=self.symbol
        )
        
        print(f"      📊 {summary}")
        # Log in IST
        self.journal.log_event(date.astimezone(IST).replace(hour=15, minute=30), "EOD_AUDIT", summary)
        
        # 4. Reset state for next day (prevents carryover)
        self.morning_brief = None
        self.hot_path.active_instructions = {}  # Clear pending instructions
        # Note: open_position should already be None from 15:15 square-off
