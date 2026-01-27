"""
v6.2 Live Mode (Unified)
Thin wrapper driving the Modular Architecture (ResearchEngine + Orchestrator) with Fyers Broker (or SimBroker for Mock).
Ensures matching logic with v6.2 Backtest (Lifecycle + Darwinian Registry).
"""
import logging
import time
import pytz
import math
import pandas as pd
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from dateutil import parser as date_parser

from engine.modes.base_mode import BaseMode
from engine.comm import emit_telegram_signal # Integrated
from engine.journal import Journal
from brain.llm_client import LLMClient
from brokers.fyers.broker import FyersBroker
from brokers.simulator.broker import SimBroker
from data.database import fetch_context_data

# v6.2 Modules
from engine.research_engine import ResearchEngine
from config.config_loader import config

# v6.2 Trade Lifecycle
from trade import create_lifecycle, trade_store

IST = pytz.timezone('Asia/Kolkata')
logger = logging.getLogger(__name__)

def safe_float(val):
    try:
        f = float(val)
        return 0.0 if (math.isnan(f) or math.isinf(f)) else f
    except:
        return 0.0

class LiveMode(BaseMode):
    def __init__(self, debug_schedule=False, symbol="NIFTY", chat_id=None, mock=False):
        self.chat_id = chat_id
        self.symbol = symbol
        self.debug_schedule = debug_schedule
        self.is_mock = mock
        self.mode_tag = "MOCK" if mock else "LIVE"
        self.session_id = f"{self.mode_tag}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # 1. Infrastructure
        if mock:
             logger.info("🎭 Initializing MOCK Broker (SimBroker)")
             self.broker = SimBroker()
        else:
             logger.info("🔴 Initializing LIVE Broker (Fyers)")
             self.broker = FyersBroker()
             
        self.journal = Journal(session_id=self.session_id)
        self.brain = LLMClient()
        
        # 2. Research Engine (v6.2 Logic)
        self.research_engine = ResearchEngine(llm_client=self.brain)
        
        # 3. Trade Lifecycle (v6.2 Persistence)
        self.lifecycle = create_lifecycle(self.session_id, self.broker, is_simulation=False)
        
        # 4. State & Helpers
        self.scheduler = BackgroundScheduler(timezone=IST)
        self.running = False
        self.last_tick = None
        self.morning_brief = None
        self.last_morning_date = None
        self.last_llm_time = datetime.min.replace(tzinfo=IST)
        
        self._setup_schedule()

    def start(self):
        logger.info(f"🚀 Starting {self.mode_tag} Mode (v6.2-SOVEREIGN)")
        self.running = True
        self.scheduler.start()
        
        self._start_redis_consumer()
        
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        logger.info(f"🛑 Stopping {self.mode_tag} Mode...")
        self.running = False
        self.scheduler.shutdown()
        # Summary for Mock
        if self.is_mock and hasattr(self.broker, 'get_summary'):
             summary = self.broker.get_summary()
             logger.info(f"📊 Mock Portfolio: {summary}")

    def on_tick(self, message):
        """Handle Live Tick"""
        if not self.running: return

        try:
             # Flexible timestamp parsing
             ts_raw = message.get('timestamp')
             if isinstance(ts_raw, str):
                 ts = date_parser.parse(ts_raw)
             else:
                 ts = datetime.fromtimestamp(ts_raw if ts_raw else time.time())
                 
             if ts.tzinfo is None: ts = IST.localize(ts)
        except:
             ts = datetime.now(IST)
             
        tick = {
            'timestamp': ts,
            'close': safe_float(message.get('ltp')),
            'open': safe_float(message.get('open')),
            'high': safe_float(message.get('high')),
            'low': safe_float(message.get('low')),
            'volume': 0,
            'symbol': self.symbol
        }
        self.last_tick = tick
        
        # 1. Process Tick (Research Engine Update)
        # Note: In Live, we don't run the heavy loop every tick.
        # We rely on Morning Brief + Scheduled Tactical Updates + Alerts
        pass

        # Heartbeat
        self._check_heartbeat(ts, tick)


    def _run_engine_cycle(self, context=None, reason="Scheduled"):
        """
        Periodically runs the full Research Stack to check for entries.
        Connected to Scheduler (every 5m).
        """
        if context is None:
            if not self.last_tick: return
            ts = self.last_tick['timestamp']
            context = fetch_context_data(ts, symbol=self.symbol)
            context['time_str'] = ts.strftime('%H:%M:%S')
            context['symbol'] = self.symbol
            
        logger.info(f"   ⚙️ Running Engine Cycle ({reason})...")
        
        # 1. Reasoning
        packet = self.research_engine.process_tick(context, None, allow_llm=False) # LLM disabled
        decision = packet.get('decision', {})
        self.last_llm_time = datetime.now(IST)
        
        # 2. Logic: Signal -> Lifecycle -> Broker -> DB
        action = decision.get('action', 'HOLD')
        if action in ["BUY_CALL", "BUY_PUT"]:
            
            # A. Propose
            trade = self.lifecycle.propose_trade(decision, context, datetime.now(IST))
            
            # B. Execute (Broker)
            logger.info(f"⚡ Executing {trade.direction} {trade.quantity} Qty @ Market...")
            
            fill = self.broker.execute_entry(
                symbol=trade.symbol,
                side=trade.direction,
                quantity=trade.quantity,
                price=trade.entry_price,
                sl=trade.sl_price,
                target=trade.target_price,
                reason=trade.reason,
                timestamp=trade.entry_time
            )
            
            # C. Open (Persistence)
            if fill.get('status') == "FILLED" or fill.get('order_id'):
                # Patch Trade with actuals if available
                if fill.get('price'): trade.entry_price = fill.get('price')
                trade.metadata['broker_order_id'] = fill.get('order_id')
                
                if self.lifecycle.open_trade(trade):
                    logger.info(f"✅ Trade {trade.trade_id} OPENED in Ledger.")
                    self._emit_telegram_event("TRADE_OPEN", trade.to_dict(), mode_tag=self.mode_tag)
                else:
                    logger.error(f"❌ Failed to Open Trade {trade.trade_id} in Lifecycle (Ledger Conflict?)")
            else:
                 logger.error(f"❌ Broker Execution Failed: {fill.get('error')}")

        self._emit_trace(packet, reason)

    # --- Darwinian EOD Update ---
    def trigger_eod_journal(self):
        """
        v6.2 EOD Routine:
        1. Query today's trades from DB.
        2. Feed into Registry.update_walk_forward_map for Darwinian learning.
        3. Print Summary.
        """
        logger.info("🌙 Running EOD Darwinian Update...")
        
        # 1. Fetch Today's Trades
        today_str = datetime.now(IST).strftime('%Y-%m-%d')
        import sqlite3
        conn = sqlite3.connect('data/trading.db')
        
        # Assuming v6.2 schema
        query = f"SELECT * FROM trades WHERE date(entry_time) = '{today_str}'"
        df = pd.read_sql(query, conn)
        conn.close()
        
        if df.empty:
            logger.info("   ⚠️ No trades today. No learning updates.")
        else:
            # 2. Update Registry
            self.research_engine.registry.update_walk_forward_map(df)
            logger.info(f"   🦅 Registry Updated with {len(df)} live trades.")
            
        logger.info("✅ EOD Sequence Complete.")

    def _setup_schedule(self):
        if self.debug_schedule:
             self.scheduler.add_job(self._run_engine_cycle, 'interval', minutes=5)
             return
        
        # Standard Market Schedule (Every 5 mins to match Backtest Logic)
        self.scheduler.add_job(self._run_engine_cycle, 'cron', hour='9-15', minute='*/5', day_of_week='mon-fri')
        self.scheduler.add_job(self.trigger_eod_journal, 'cron', hour=15, minute=35, day_of_week='mon-fri')

    def _start_redis_consumer(self):
        import threading
        t = threading.Thread(target=self._redis_consumer_loop)
        t.daemon = True
        t.start()

    def _redis_consumer_loop(self):
        import redis
        try:
            r = redis.Redis(host='172.19.0.2', port=6379, decode_responses=False)
            stream_key = b"market_feed"
            last_id = b'$' # Start from new messages
            
            while self.running:
                 try:
                     messages = r.xread({stream_key: last_id}, count=1, block=1000)
                     if messages:
                         for stream, msg_list in messages:
                             for msg_id, data in msg_list:
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
                 except Exception:
                     time.sleep(1)
        except Exception:
            pass

    def _check_heartbeat(self, ts, tick):
        if not hasattr(self, 'last_heartbeat_time'): self.last_heartbeat_time = ts
        time_since_hb = (ts - self.last_heartbeat_time).total_seconds() / 60
        if time_since_hb >= 5:
            # We can check open positions via TradeLedger now
            from trade.ledger import trade_ledger
            open_pos = len(trade_ledger.open_positions)
            status = f"Active Trades: {open_pos}"
            logger.info(f"   [{ts.strftime('%H:%M')}] 💓 Monitor: Price {tick['close']:.1f} | {status}")
            self.last_heartbeat_time = ts

    def _emit_telegram_event(self, event_type, payload, mode_tag="LIVE"):
        """
        Routes internal events to the centralized Communication Module.
        This sends the data to n8n Webhook for Telegram Notification.
        """
        # Ensure Chat ID is attached
        if self.chat_id:
            payload['chatId'] = self.chat_id
            
        emit_telegram_signal(event_type, payload, mode_tag=mode_tag)

    def _emit_trace(self, packet, reason):
        # Trace implementation (logging)
        pass