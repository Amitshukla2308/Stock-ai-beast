import os
import time
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from fyers_apiv3.FyersWebsocket import data_ws
from brokers.fyers.auth import load_token
from brain.llm_client import LLMClient
from hot_path.executor import HotPathExecutor
from engine.journal import Journal
from dotenv import load_dotenv
import pytz
IST = pytz.timezone('Asia/Kolkata')
from data.database import fetch_context_data
from dateutil import parser as date_parser

def safe_float(val):
    if val is None or val == "None":
        return 0.0
    try:
        return float(val)
    except:
        return 0.0

load_dotenv()

class LiveEngine:
    def __init__(self, debug_schedule=False, simulation=False, trade_mode='PAPER'):
        self.access_token = load_token()  # Only needed if using Fyers websocket directly
        self.client_id = os.getenv("FYERS_CLIENT_ID")
        self.debug_schedule = debug_schedule
        self.simulation = simulation
        self.trade_mode = trade_mode
        
        # Initialize Broker based on mode
        self.broker = None
        if trade_mode == 'LIVE':
            print("   🔴 Initializing LIVE Broker (Fyers)")
            from fyers_apiv3 import fyersModel
            self.broker = fyersModel.FyersModel(client_id=self.client_id, token=self.access_token, is_async=False, log_path="")
        elif trade_mode == 'PAPER':
            print("   📝 Initializing PAPER Broker")
            from brokers.paper.connector import PaperBroker
            self.broker = PaperBroker()
        else:
            print("   😶 MOCK Mode: No broker instance")
        
        # Components
        self.brain = LLMClient()
        self.hot_path = HotPathExecutor()
        self.journal = Journal()
        
        # Portfolio Manager
        from engine.portfolio_manager import PortfolioManager
        self.portfolio = PortfolioManager(initial_capital=100000)
        
        # Scheduler
        self.scheduler = BackgroundScheduler(timezone=IST)
        self._setup_schedule()

        # State
        self.last_tick = None
        self.morning_brief = None # Store the daily plan
        self.last_morning_date = None # Track last brief date for throttling
        self.running = False

    def _setup_schedule(self):
        """Define the critical event loop"""
        if self.debug_schedule:
            print("   ⚠️ DEBUG SCHEDULE ACTIVE: Tactical every 15min, Morning every 30s, EOD every 2min")
            self.scheduler.add_job(self.trigger_morning_brief, 'interval', seconds=30, misfire_grace_time=15)
            self.scheduler.add_job(self.trigger_tactical_update, 'interval', minutes=15, misfire_grace_time=15)
            self.scheduler.add_job(self.trigger_eod_journal, 'interval', minutes=2, misfire_grace_time=15)
            return

        # Morning Briefing (09:15)
        self.scheduler.add_job(self.trigger_morning_brief, 'cron', hour=9, minute=15, day_of_week='mon-fri', misfire_grace_time=60)
        
        # Tactical Update (Every 15 mins from 09:15 to 15:15)
        self.scheduler.add_job(self.trigger_tactical_update, 'cron', hour='9-15', minute='*/15', day_of_week='mon-fri', misfire_grace_time=60)
        
        # EOD Journal (15:30)
        self.scheduler.add_job(self.trigger_eod_journal, 'cron', hour=15, minute=30, day_of_week='mon-fri', misfire_grace_time=60)

    def start(self):
        """Start the Engine"""
        print("🚀 Starting Stock AI Beast Live Engine...")
        print(f"   🧠 Brain: {self.brain.model}")
        print(f"   🎭 SIMULATION MODE: {'ACTIVE (Strict Time)' if self.simulation else 'OFF (System Time)'}")
        
        # CRITICAL FIX: In simulation mode, wait for first tick before starting scheduler
        if self.simulation:
            print("   ⏳ Waiting for first tick to sync simulation time...")
            print("      (Ensure producer is running: docker logs beast-producer)")
            for i in range(300):  # Wait max 30 seconds (was 10s)
                if self.last_tick:
                    print(f"   ✅ First tick received: {self.last_tick['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}")
                    break
                if i % 10 == 0:
                    print(f"      ... waiting {i/10}s (last_tick is None) ...")
                time.sleep(0.1)
            
            if not self.last_tick:
                print("   ❌ FATAL: No market data received after 30s.")
                # print("      → Check if producer is running: docker logs beast-producer")
                # print("      → Check Redis stream: docker exec beast-redis redis-cli XLEN market_feed")
                return
        
        # 1. Start Scheduler (NOW with valid simulation time)
        self.scheduler.start()
        print("   ⏰ Scheduler Started (Morning, Tactical, EOD)")

        # 2. Start Websocket (Replaced by Redis Consumer)
        # self._connect_websocket()
        
        # 3. Main Keep-Alive Loop
        self.running = True
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        print("\n🛑 Stopping Engine...")
        self.running = False
        self.scheduler.shutdown()
        
        # Generate final performance report
        print("\n📈 Generating Final Performance Report...")
        self.portfolio.print_final_report()
        
        # Close websocket if needed

    def _start_redis_consumer(self):
        """Consume ticks from Redis Stream"""
        import threading
        print("   📡 Starting Redis Stream Consumer...")
        t = threading.Thread(target=self._redis_consumer_loop)
        t.daemon = True
        t.start()

    def _redis_consumer_loop(self):
        """Background thread to consume from Redis"""
        import redis
        import sys # Correct import for flushing logic
        
        def log_debug(msg):
             try:
                import sys
                sys.stderr.write(f"{datetime.now()}: {msg}\n")
                sys.stderr.flush()
                with open("/app/data/thread_debug.log", "a") as f:
                    f.write(f"{datetime.now()}: {msg}\n")
             except: pass

        try:
            # FORCE HARDCODED HOST for debugging
            # DNS Resolution hangs in thread (Deadlock). Use Direct IP.
            # IP obtained from `docker inspect beast_redis` -> 172.19.0.2
            # Note: In production this IP might change, but for this persistent session it is stable.
            redis_ip = '172.19.0.2' 
            log_debug(f"Connecting to Redis IP: {redis_ip} (Bypassing DNS)...")
            
            # CRITICAL: Use decode_responses=False to avoid library crashes on mixed data
            # We will decode manually/safely
            r = redis.Redis(host=redis_ip, port=6379, decode_responses=False)
            log_debug("Redis Connected! (Lazy, Binary Mode)")
        except Exception as e:
            print(f"   ❌ Redis Connection Failed: {e}")
            log_debug(f"Redis Connection Failed: {e}")
            return

        stream_key = b"market_feed" # Bytes key
        # For Mock Replay, force 0-0
        last_id = b'0-0'
        
        print(f"   🚀 Consumer Loop Started. Key: {stream_key}. LastID: {last_id}")
        sys.stdout.flush()
        
        # CRITICAL FIX: Ensure running flag is True (Handling potential startup race signals)
        if not self.running:
            self.running = True
        
        while self.running:
             # Non-blocking read (count=1 for immediate processing)
             # Binary mode: Messages are bytes
             try:
                 messages = r.xread({stream_key: last_id}, count=1)
                 
                 if messages:
                     for stream, msg_list in messages:
                         for msg_id, data in msg_list:
                             try:
                                # Decode manually to avoid library crashes
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
                             except Exception as e_tick:
                                 print(f"   ⚠️ Tick Error: {e_tick}")
                                 sys.stdout.flush()
                 else:
                     # No data, brief sleep to yield CPU
                     time.sleep(0.01)

             except Exception as e_loop:
                 print(f"   ❌ Redis Loop Error: {e_loop}")
                 sys.stdout.flush()
                 time.sleep(1)

    def on_tick(self, message):
        """Hot Path: Process every tick"""
        # Parse timestamp from string (sent by producer)
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
        
        # Execute Deterministic Logic
        self.hot_path.process_tick(tick)
        
        # If trade happened, log it
        if self.hot_path.trades:
             for trade in self.hot_path.trades:
                  # Use explicit type field from HotPathExecutor
                  is_entry = (trade.get('type') == 'ENTRY')
                  
                  if is_entry:
                      action = "BUY"
                      # Select option contract
                      from engine.contract_selector import select_option_contract
                      symbol = select_option_contract(trade['side'], self.last_tick['close'])
                      trade['symbol'] = symbol  # Store for exit
                      
                  else:  # Exit
                      action = "SELL"
                      symbol = trade.get('symbol', 'UNKNOWN')
                  
                  # Execute order via OMS
                  if self.trade_mode in ['LIVE', 'PAPER']:
                      from workers.oms import execute_order
                      result = execute_order(
                          broker_model=self.broker,
                          symbol=symbol,
                          action=action,
                          quantity=1,  # TODO: Calculate from capital allocation
                          reason=trade.get('reason', 'Strategy'),
                          market_price=self.last_tick['close']
                      )
                      trade['order_status'] = result.get('status')
                      
                      # Update portfolio ledger
                      if result.get('status') in ['FILLED', 'SUBMITTED']:
                          order_type = 'ENTRY' if is_entry else 'EXIT'
                          self.portfolio.process_fill(
                              order_type=order_type,
                              symbol=symbol,
                              quantity=1,
                              price=self.last_tick['close'],
                              side=trade['side']
                          )
                      
                      print(f"   {'⚠️' if self.trade_mode == 'LIVE' else '📝'} {self.trade_mode} ORDER: {action} {symbol} @ {self.last_tick['close']:.1f}")
                  else:
                      trade['order_status'] = 'MOCK'
                      print(f"   😶 MOCK ({action} {trade['side']})")
                  
                  # Log trade with order details
                  self.journal.log_trade(trade)
                      
             self.hot_path.trades = []

    def trigger_morning_brief(self):
        # Strict Simulation Mode: If no tick, we do NOT exist yet.
        if not self.last_tick:
            if self.simulation:
                return # Silence is golden during bootstrap
            # Live Mode fallback
            sim_time = datetime.now(IST)
        else:
            sim_time = self.last_tick['timestamp']
        
        # State Check: Prevent calling Morning Brief multiple times for the same day
        if self.last_morning_date == sim_time.date():
             print(f"   💤 Morning Briefing already done for {sim_time.date()}. Skipping.")
             return
             
        print(f"   [{sim_time.strftime('%H:%M')}] 🧠 Morning Briefing...")
        
        # Fetch Real Context from DB based on Simulated Time
        context = fetch_context_data(sim_time)
        print(f"      📊 Context: {len(context['daily_3'])} Daily, {len(context['last_15min'])} 15m, {len(context['today_5min'])} 5m")
        
        brief = self.brain.get_morning_brief(context)
        plan = brief.get('reasoning', "No Plan") # Using reasoning as summary now
        print(f"      📝 Plan: {plan}")
        self.morning_brief = brief
        self.last_morning_date = sim_time.date()
        self.journal.log_event(sim_time, "MORNING", brief)

    def trigger_tactical_update(self):
        if not self.last_tick:
            print("   ⚠️ No tick data yet for Tactical Update")
            return

        # Fetch Real Context
        sim_time = self.last_tick['timestamp']
        
        # --- GUARDRAIL 1: Stale Data Check (Live Mode Only) ---
        if not self.simulation:
            lag = (datetime.now(IST) - sim_time).total_seconds()
            if lag > 300: # 5 minutes
                print(f"   ⚠️ DATA LAG DETECTED ({lag:.0f}s). Skipping update.")
                return

        # --- GUARDRAIL 2: Hard Exit at 15:15 ---
        if sim_time.hour == 15 and sim_time.minute >= 15:
            if self.hot_path.open_position:
                 print(f"   🛑 HARD EXIT TIME (15:15). Squaring off...")
                 self.hot_path.square_off(self.last_tick['close'], sim_time, reason="EOD Auto-Squareoff")
            return # No more brain calls after 15:15
            
        # --- GUARDRAIL 3: Entry Cutoff at 14:30 ---
        # If we are FLAT and it's after 14:30, do not annoy the brain.
        if sim_time.hour > 14 or (sim_time.hour == 14 and sim_time.minute >= 30):
            if not self.hot_path.open_position:
                print(f"   🛑 ENTRY CUTOFF (14:30+). Market closing soon. Staying Flat.")
                return 

        context = fetch_context_data(sim_time)

        print(f"   [{sim_time.strftime('%H:%M:%S')}] 🧠 Tactical Update (Ctx: {len(context['last_15min'])} 15m, {len(context['today_5min'])} 5m)...")
        instructions = self.brain.get_tactical_update(
            self.last_tick, 
            context,
            self.morning_brief,
            current_pnl=0, 
            open_position=self.hot_path.open_position
        )
        if instructions:
            print(f"      ⚙️ Instructions: {instructions.get('action')}")
            self.hot_path.update_instructions(instructions)
            self.journal.log_event(datetime.now(IST), "TACTICAL", instructions)

    def trigger_eod_journal(self):
        print(f"   [15:30] 📔 EOD Journaling...")
        summary = self.brain.get_eod_journal(self.hot_path.trades) # Needs accumulation fix
        self.journal.log_event(datetime.now(IST), "EOD", summary)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-exec", action="store_true", help="ENABLE REAL MONEY TRADING")
    parser.add_argument("--debug-schedule", action="store_true", help="Run updates every minute (for testing)")
    parser.add_argument("--simulation", action="store_true", help="Run in strict simulation mode (trust data timestamp)")
    args = parser.parse_args()

    trade_mode = 'LIVE' if args.live_exec else 'PAPER'
    engine = LiveEngine(
        debug_schedule=args.debug_schedule, 
        simulation=args.simulation,
        trade_mode=trade_mode
    )
    
    print(f"🛡️ TRADING MODE: {trade_mode}")
    if args.live_exec:
        print("   ⚠️ WARNING: REAL MONEY WILL BE USED.")
        time.sleep(3)
    
    # Start Redis Consumer FIRST (before start())
    engine._start_redis_consumer()
    
    # Then start engine (will wait for first tick in simulation mode)
    engine.start()
