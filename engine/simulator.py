import pandas as pd
from datetime import datetime, timedelta, time
from data.database import get_connection, fetch_context_data, get_fyers_symbol
from brain.llm_client import LLMClient
from hot_path.executor import HotPathExecutor
from engine.journal import Journal

class MarketSimulator:
    def __init__(self, start_date, end_date, symbol="BANKNIFTY"):
        self.start_date = start_date
        self.end_date = end_date
        self.symbol = symbol
        self.conn = get_connection()
        
        # Components
        self.brain = LLMClient()
        self.hot_path = HotPathExecutor()
        self.journal = Journal()
        
        # State
        self.current_time = None
        self.daily_context = {}
        self.tactical_state = {}

    def fetch_data_for_day(self, date):
        """Fetch 5-min candles and VIX for the specific day"""
        date_str = date.strftime('%Y-%m-%d')
        full_symbol = get_fyers_symbol(self.symbol)
        query = f"""
            SELECT * FROM candles_5min 
            WHERE symbol = '{full_symbol}'
              AND timestamp >= '{date_str} 09:15:00' 
              AND timestamp <= '{date_str} 15:30:00'
            ORDER BY timestamp ASC
        """
        return self.conn.execute(query).fetchdf()

    def run(self):
        """
        Main Event Loop
        """
        # Register session for Dashboard visibility
        self.journal.register_session(self.symbol, self.start_date, self.end_date)
        
        current_date = self.start_date
        
        while current_date <= self.end_date:
            print(f"🌞 Simulating Day: {current_date.date()}")
            
            # 1. Fetch Day's Tick Data (using 5min candles as ticks for backtest)
            day_ticks = self.fetch_data_for_day(current_date)
            
            if day_ticks.empty:
                print("   ⚠️ No data for this day. Skipping.")
                current_date += timedelta(days=1)
                continue

            # 2. Morning Briefing (09:15 - technically 09:00 in real life, but we use data avail)
            # In live, we run this at 09:08 pre-open or 09:15.
            first_tick_dict = day_ticks.iloc[0].to_dict() if not day_ticks.empty else None
            if first_tick_dict:
                 # Convert timestamp to string if needed or ensure format matches
                 pass 
            self.trigger_morning_brief(current_date, first_tick=first_tick_dict)
            
            # 3. Intraday Loop
            last_tactical_update = None
            
            for _, tick in day_ticks.iterrows():
                self.current_time = tick['timestamp']
                
                # Check for 15-min Tactical Update
                # We want updates at 09:30, 09:45, etc.
                if self.should_trigger_tactical(self.current_time, last_tactical_update):
                    self.trigger_tactical_update(tick)
                    last_tactical_update = self.current_time
                
                # Hot Path Execution (Every Tick)
                self.run_hot_path(tick)
            
            # 4. EOD Journal
            self.trigger_eod_journal(current_date)
            
            current_date += timedelta(days=1)

    def should_trigger_tactical(self, current_time, last_update):
        """Trigger every 15 minutes starting 09:30"""
        if current_time.time() < time(9, 30):
            return False
            
        if last_update is None:
            return True
            
        diff = (current_time - last_update).total_seconds() / 60
        return diff >= 15

    def trigger_morning_brief(self, date, first_tick=None):
        """Call LLM for daily regime and plan"""
        print(f"   [09:15] 🧠 Morning Briefing...")
        # Ensure we use the tick timestamp for precise context
        ts = first_tick['timestamp'] if first_tick else date.replace(hour=9, minute=15)
        context = fetch_context_data(ts)
        
        # SLICING: Match Live Engine Logic
        mb_context = context.copy()
        mb_context['last_15min'] = context.get('last_15min', [])[-3:]
        mb_context['today_5min'] = context.get('today_5min', [])[-3:]

        brief = self.brain.get_morning_brief(mb_context, current_tick=first_tick)
        plan = brief.get('reasoning', "No Plan Generated")
        print(f"      📝 Plan: {plan}")
        self.morning_brief = brief # Store for tactical
        self.journal.log_event(date.replace(hour=9, minute=15), "MORNING", brief)

    def trigger_tactical_update(self, tick):
        """Call LLM for intraday adjustments"""
        current_time = tick['timestamp'] # Use tick time here
        
        # print(f"   [{current_time.time()}] 🧠 Tactical Update...")
        
        # Fetch Real Context
        context = fetch_context_data(current_time)
        
        # Calculate Day PnL from permanent ledger (filter by today's date)
        today_str = current_time.strftime('%Y-%m-%d') if hasattr(current_time, 'strftime') else str(current_time)[:10]
        day_pnl = 0.0
        for t in self.hot_path.trade_ledger:
            exit_time = t.get('exit_time')
            if exit_time and t.get('pnl') is not None:
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
            current_pnl=0, # TODO: Track Position PnL
            open_position=self.hot_path.open_position,
            day_pnl=day_pnl
        )
        if instructions:
            self.hot_path.update_instructions(instructions)
            self.journal.log_event(current_time, "TACTICAL", instructions)

    def run_hot_path(self, tick):
        """Deterministic Order Execution"""
        self.hot_path.process_tick(tick)
        if self.hot_path.trades:
             for trade in self.hot_path.trades:
                 if trade.get('type') == 'EXIT':
                     self.journal.log_trade(trade)
             self.hot_path.trades = [] # Clear buffer

    def trigger_eod_journal(self, date):
        """Analyze day performance"""
        print(f"   [15:30] 📔 EOD Journaling & Audit...")
        eod_data = {
            'date': date.strftime('%Y-%m-%d'), 
            'ticker': f'{self.symbol} (SIM)',
            'trades_count': len(self.hot_path.trade_ledger)
        }
        summary = self.brain.get_eod_journal(
            trades=self.hot_path.trade_ledger,
            morning_plan=self.morning_brief,
            session_id=date.strftime('%Y-%m-%d'),
            eod_data=eod_data
        )
        print(f"      📊 {summary}")
        self.journal.log_event(date.replace(hour=15, minute=30), "EOD_AUDIT", summary)

if __name__ == "__main__":
    import argparse
    import sys
    from engine.auth_fyers import authenticate_fyers
    
    # 1. Ensure Authentication
    try:
        authenticate_fyers()
    except Exception as e:
        print(f"❌ Auth Failed: {e}")
        sys.exit(1)
    
    parser = argparse.ArgumentParser(description="Run Stock AI Beast Simulation")
    parser.add_argument("--days", type=int, default=5, help="Number of recent days to simulate")
    args = parser.parse_args()

    # Determine date range based on DB Data or Current Time
    # Let's find the max timestamp in DB to be safe, or just assume "recent" means up to today
    conn = get_connection()
    try:
        max_date_row = conn.execute("SELECT MAX(timestamp) FROM candles_5min").fetchone()
        if max_date_row and max_date_row[0]:
            end_date = max_date_row[0]
        else:
            end_date = datetime.now()
    except:
        end_date = datetime.now()
    finally:
        conn.close()

    start_date = end_date - timedelta(days=args.days)
    
    print(f"🗓️ Configured Simulation: Last {args.days} days ({start_date.date()} to {end_date.date()})")

    sim = MarketSimulator(
        start_date=start_date,
        end_date=end_date
    )
    sim.run()
