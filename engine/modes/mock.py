import os
import time
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from engine.modes.base_mode import BaseMode
from brain.llm_client import LLMClient
from hot_path.executor import HotPathExecutor
from engine.journal import Journal
from engine.portfolio_manager import PortfolioManager
from data.database import fetch_context_data
from dateutil import parser as date_parser
import pytz
from dotenv import load_dotenv

IST = pytz.timezone('Asia/Kolkata')
load_dotenv()

def safe_float(val):
    try: return float(val)
    except: return 0.0

class MockMode(BaseMode):
    def __init__(self, debug_schedule=False, symbol="BANKNIFTY"):
        self.debug_schedule = debug_schedule
        self.symbol = symbol
        
        # Components
        self.brain = LLMClient()
        self.hot_path = HotPathExecutor()
        self.journal = Journal()
        self.portfolio = PortfolioManager(initial_capital=100000)
        
        # Scheduler
        self.scheduler = BackgroundScheduler(timezone=IST)
        self._setup_schedule()
        
        # State
        self.last_tick = None
        self.morning_brief = None
        self.last_morning_date = None
        self.running = False

    def start(self):
        print("🎭 Starting MOCK Mode (Live Data + Paper Money)")
        self.running = True
        self.scheduler.start()
        
        # Start Redis Consumer (Live Feed)
        self._start_redis_consumer()
        
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        print("\n🛑 Stopping Mock Mode...")
        self.running = False
        self.scheduler.shutdown()
        self.portfolio.print_final_report()

    def on_tick(self, message):
        """Handle Live Tick"""
        # Parse logic identical to live_engine.py
        try:
             ts = date_parser.parse(message.get('timestamp'))
        except:
             ts = datetime.now(IST)
             
        tick = {
            'timestamp': ts,
            'close': safe_float(message.get('ltp')),
            'open': safe_float(message.get('open')),
            'high': safe_float(message.get('high')),
            'low': safe_float(message.get('low'))
        }
        self.last_tick = tick
        self.hot_path.process_tick(tick)
        
        # HEARTBEAT LOGGING
        if not hasattr(self, 'last_heartbeat_time'): self.last_heartbeat_time = ts
        time_since_hb = (ts - self.last_heartbeat_time).total_seconds() / 60
        if time_since_hb >= 5:
            instr = self.hot_path.active_instructions.get('action', 'WAIT')
            entry = self.hot_path.active_instructions.get('entry_price', 'N/A')
            print(f"   [{ts.strftime('%H:%M')}] 💓 Monitor: Price {tick['close']:.1f} | Instr: {instr} ({entry})")
            self.last_heartbeat_time = ts

        if self.hot_path.trades:
             for trade in self.hot_path.trades:
                  # MOCK EXECUTION
                  is_entry = (trade.get('type') == 'ENTRY')
                  action = "BUY" if is_entry else "SELL"
                  symbol = trade.get('symbol', 'MOCK_OPT')
                  
                  if is_entry:
                        from engine.contract_selector import select_option_contract
                        symbol = select_option_contract(trade['side'], tick['close'])
                        trade['symbol'] = symbol
                  else:
                        symbol = trade.get('symbol', 'UNKNOWN')

                  print(f"   😶 MOCK ORDER: {action} {symbol} @ {tick['close']:.1f}")
                  
                  # Update Internal Ledger
                  self.portfolio.process_fill(
                      order_type='ENTRY' if is_entry else 'EXIT',
                      symbol=symbol,
                      quantity=1,
                      price=tick['close'],
                      side=trade['side']
                  )
                  
                  trade['order_status'] = 'FILLED'
                  
                  # Log only full trades to Journal
                  if not is_entry:
                      self.journal.log_trade(trade)
                      
             self.hot_path.trades = []

    def _setup_schedule(self):
        if self.debug_schedule:
             self.scheduler.add_job(self.trigger_morning_brief, 'interval', seconds=30)
             self.scheduler.add_job(self.trigger_tactical_update, 'interval', minutes=15)
             self.scheduler.add_job(self.trigger_eod_journal, 'interval', minutes=2)
             return
             
        # CHANGED: 09:15 -> 09:30
        self.scheduler.add_job(self.trigger_morning_brief, 'cron', hour=9, minute=30, day_of_week='mon-fri')
        self.scheduler.add_job(self.trigger_tactical_update, 'cron', hour='9-15', minute='*/15', day_of_week='mon-fri')
        self.scheduler.add_job(self.trigger_eod_journal, 'cron', hour=15, minute=30, day_of_week='mon-fri')

    def trigger_morning_brief(self):
        if not self.last_tick: return
        sim_time = self.last_tick['timestamp']
        
        if self.last_morning_date == sim_time.date(): return
        
        print(f"   [{sim_time.strftime('%H:%M')}] 🧠 Morning Briefing...")
        context = fetch_context_data(sim_time, symbol=self.symbol)
        
        # Slicing Optimization
        mb_context = context.copy()
        mb_context['last_15min'] = context['last_15min'][-3:]
        mb_context['today_5min'] = context['today_5min'][-3:]
        
        brief = self.brain.get_morning_brief(mb_context, current_tick=self.last_tick, symbol=self.symbol)
        print(f"      📝 Plan: {brief.get('reasoning')}")
        self.morning_brief = brief
        self.last_morning_date = sim_time.date()
        self.journal.log_event(sim_time, "MORNING", brief)

    def trigger_tactical_update(self):
        if not self.last_tick: return
        sim_time = self.last_tick['timestamp']
        
        # Guardrails (same as live)
        lag = (datetime.now(IST) - sim_time).total_seconds()
        if lag > 300: return

        if sim_time.hour == 15 and sim_time.minute >= 15:
             if self.hot_path.open_position:
                  self.hot_path.square_off(self.last_tick['close'], sim_time, reason="EOD")
             return

        context = fetch_context_data(sim_time, symbol=self.symbol)
        
        # Calculate Day PnL from permanent ledger (filter by today's date)
        today_str = sim_time.strftime('%Y-%m-%d') if hasattr(sim_time, 'strftime') else str(sim_time)[:10]
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
            self.last_tick, context, self.morning_brief, 0, self.hot_path.open_position, day_pnl=day_pnl, symbol=self.symbol
        )
        if instructions:
             self.hot_path.update_instructions(instructions)
             self.journal.log_event(datetime.now(IST), "TACTICAL", instructions)

    def trigger_eod_journal(self):
        print(f"   [15:30] 📔 EOD Journaling & Audit...")
        sid = datetime.now(IST).strftime('%Y-%m-%d')
        eod_data = {
            'date': sid, 
            'ticker': f"{self.symbol} (MOCK)",
            'trades_count': len(self.hot_path.trade_ledger)
        }
        
        summary = self.brain.get_eod_journal(
            trades=self.hot_path.trade_ledger,
            morning_plan=self.morning_brief,
            session_id=sid,
            eod_data=eod_data,
            symbol=self.symbol
        )
        self.journal.log_event(datetime.now(IST), "EOD_AUDIT", summary)

    def _start_redis_consumer(self):
        import threading
        t = threading.Thread(target=self._redis_consumer_loop)
        t.daemon = True
        t.start()

    def _redis_consumer_loop(self):
        # ... (Identical to live_engine.py connection logic)
        import redis
        try:
            r = redis.Redis(host='172.19.0.2', port=6379, decode_responses=False)
            stream_key = b"market_feed"
            last_id = b'0-0'
            while self.running:
                 try:
                     messages = r.xread({stream_key: last_id}, count=1)
                     if messages:
                         for stream, msg_list in messages:
                             for msg_id, data in msg_list:
                                 # Decode and on_tick
                                 def decode(b): return b.decode('utf-8') if isinstance(b, bytes) else str(b)
                                 tick_data = {
                                    'symbol': decode(data.get(b'symbol')),
                                    'ltp': safe_float(decode(data.get(b'ltp'))),
                                    'open': safe_float(decode(data.get(b'open'))),
                                    'high': safe_float(decode(data.get(b'high'))),
                                    'low': safe_float(decode(data.get(b'low'))),
                                    'timestamp': decode(data.get(b'timestamp'))
                                 }
                                 self.on_tick(tick_data)
                                 last_id = msg_id
                     else:
                         time.sleep(0.01)
                 except Exception as e:
                     print(f"Redis Loop Error: {e}")
                     time.sleep(1)
        except Exception as e:
            print(f"Redis Init Failed: {e}")
