"""
v2.8 Live Mode (Unified)
Thin wrapper driving the Modular Architecture (ResearchEngine + Orchestrator) with Fyers Broker (or SimBroker for Mock).
Decoupled from legacy HotPathExecutor.
"""
import logging
import time
import pytz
import math
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from dateutil import parser as date_parser

from engine.modes.base_mode import BaseMode
from engine.journal import Journal
from brain.llm_client import LLMClient
from brokers.fyers.broker import FyersBroker
from brokers.simulator.broker import SimBroker
from data.database import fetch_context_data

# v2.8 Modules
from core.orchestrator import Orchestrator
from executor.execute import Executor
from engine.research_engine import ResearchEngine
from config.config_loader import config

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
        
        # 2. The Modular Graph
        self.executor = Executor(broker=self.broker)
        self.orchestrator = Orchestrator(executor=self.executor)
        self.research_engine = ResearchEngine(llm_client=self.brain)
        
        # 3. State & Helpers
        self.scheduler = BackgroundScheduler(timezone=IST)
        self.running = False
        self.last_tick = None
        self.morning_brief = None
        self.last_morning_date = None
        
        self.last_llm_time = datetime.min.replace(tzinfo=IST)
        
        self.last_ledger_len = 0
        
        self._setup_schedule()

    def start(self):
        logger.info(f"🚀 Starting {self.mode_tag} Mode")
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
        # ... logic
        try:
             ts = date_parser.parse(message.get('timestamp'))
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
        
        # 1. Orchestrate
        self.orchestrator.process_tick(tick)
        
        # 2. Research (Event Driven)
        if self.morning_brief:
            self._check_signals_and_trigger(tick, ts)
            
        # 3. Sync Trades
        self._sync_new_trades(ts)

        # Heartbeat
        self._check_heartbeat(ts, tick)

    def _check_signals_and_trigger(self, tick, ts):
        context = fetch_context_data(ts, symbol=self.symbol)
        context['time_str'] = ts.strftime('%H:%M:%S')
        context['symbol'] = self.symbol
        
        # Gated call (Fast)
        packet = self.research_engine.process_tick(context, self.morning_brief, allow_llm=False)
        signals = packet.get('signals', {})
        
        reason = ""
        trigger = False
        if signals.get('rejection'): trigger, reason = True, "Rejection"
        elif signals.get('impulse_detected'): trigger, reason = True, "Impulse"
        elif signals.get('structural_break'): trigger, reason = True, "Breakout"
        
        if trigger:
             if (datetime.now(IST) - self.last_llm_time).total_seconds() > 300:
                  self._run_tactical_update(context, reason)

    def _sync_new_trades(self, ts):
        current_len = len(self.executor.trade_ledger)
        if current_len > self.last_ledger_len:
             new_trades = self.executor.trade_ledger[self.last_ledger_len:]
             for trade in new_trades:
                  # Log Closed Trades
                  if trade.get('type') == 'EXIT':
                       self.journal.log_trade(trade)
                       self._emit_trade_alert(trade, ts)
             self.last_ledger_len = current_len

    def _emit_trade_alert(self, trade, ts):
        self._emit_telegram_event("TRADE", {
            "date": ts.strftime('%Y-%m-%d'),
            "side": trade.get('side'),
            "entry": trade.get('entry_price'),
            "exit": trade.get('exit_price'),
            "pnl": trade.get('pnl'),
            "reason": trade.get('reason')
        }, mode_tag=self.mode_tag)

    # ... (Rest methods same as previous step: _run_tactical_update, _emit_trace, _setup_schedule, triggers etc)
    # Re-pasting the methods for completeness in write_to_file
    
    def _run_tactical_update(self, context=None, reason="Scheduled"):
        if not self.morning_brief: return
        
        if context is None:
            if not self.last_tick: return
            ts = self.last_tick['timestamp']
            context = fetch_context_data(ts, symbol=self.symbol)
            context['time_str'] = ts.strftime('%H:%M:%S')
            context['symbol'] = self.symbol
            
        logger.info(f"   🧠 Running Tactical Update ({reason})...")
        packet = self.research_engine.process_tick(context, self.morning_brief, allow_llm=True)
        decision = packet.get('decision', {})
        
        self.last_llm_time = datetime.now(IST)
        self._emit_trace(packet, reason)
        
        if decision.get('action') in ["BUY_CALL", "BUY_PUT"]:
            self.executor.execute_entry(decision, datetime.now(IST))

    def _emit_trace(self, packet, reason):
        decision = packet.get('decision', {})
        enrichment = packet.get('enrichment', {})
        trace_payload = {
            "llm_type": "TACTICAL",
            "time": datetime.now(IST).strftime('%H:%M'),
            "trigger": reason,
            "action": decision.get('action', 'HOLD'),
            "selected_style": decision.get('selected_style', 'NONE'),
            "confidence": decision.get('confidence', 0.0),
            "reason": decision.get('reason'),
            "market_micro_context": {
                "trend": enrichment.get('trend_regime'),
                "ter": enrichment.get('trend_efficiency'),
                "location": enrichment.get('location_class')
            }
        }
        self._emit_telegram_event("LLM_TRACE", trace_payload, mode_tag=self.mode_tag)

    def _setup_schedule(self):
        if self.debug_schedule:
             self.scheduler.add_job(self.trigger_morning_brief, 'interval', seconds=30)
             self.scheduler.add_job(self._run_tactical_update, 'interval', minutes=15)
             return
        self.scheduler.add_job(self.trigger_morning_brief, 'cron', hour=9, minute=30, day_of_week='mon-fri')
        self.scheduler.add_job(self._run_tactical_update, 'cron', hour='9-15', minute='*/15', day_of_week='mon-fri')
        self.scheduler.add_job(self.trigger_eod_journal, 'cron', hour=15, minute=30, day_of_week='mon-fri')

    def trigger_morning_brief(self):
        if not self.last_tick: return
        ts = self.last_tick['timestamp']
        if self.last_morning_date == ts.date(): return
        
        logger.info(f"   [{ts.strftime('%H:%M')}] 🧠 Generatng Morning Brief...")
        context = fetch_context_data(ts, symbol=self.symbol)
        
        brief = self.brain.get_morning_brief(context, current_tick=self.last_tick, symbol=self.symbol)
        self.morning_brief = brief
        self.last_morning_date = ts.date()
        
        self._emit_telegram_event("MORNING_BRIEF", {
            "date": ts.strftime('%Y-%m-%d'),
            "plan": brief.get('morning_logic')
        }, mode_tag=self.mode_tag)

    def trigger_eod_journal(self):
        # Placeholder for EOD logic
        pass

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
            last_id = b'0-0'
            while self.running:
                 try:
                     messages = r.xread({stream_key: last_id}, count=1)
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
                     else:
                         time.sleep(0.01)
                 except Exception:
                     time.sleep(1)
        except Exception:
            pass

    def _check_heartbeat(self, ts, tick):
        if not hasattr(self, 'last_heartbeat_time'): self.last_heartbeat_time = ts
        time_since_hb = (ts - self.last_heartbeat_time).total_seconds() / 60
        if time_since_hb >= 5:
            pos = self.executor.open_position
            status = f"Pos: {pos['side']} @ {pos['entry_price']}" if pos else "WAIT"
            logger.info(f"   [{ts.strftime('%H:%M')}] 💓 Monitor: Price {tick['close']:.1f} | {status}")
            self.last_heartbeat_time = ts