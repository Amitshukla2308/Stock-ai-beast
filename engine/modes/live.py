"""
v6.2 Live Mode (Unified)
Thin wrapper driving the Modular Architecture (ResearchEngine + Orchestrator) with Fyers Broker (or SimBroker for Mock).
Ensures matching logic with v6.2 Backtest (Lifecycle + Darwinian Registry).
"""
import logging
import os
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
# from brain.llm_client import LLMClient # DELETED
from brokers.fyers.broker import FyersBroker
from brokers.simulator.broker import SimBroker
from data.database import fetch_context_data

# v6.2 Modules
from engine.research_engine import ResearchEngine
from config.config_loader import config

# v6.2 Trade Lifecycle
from trade import create_lifecycle, trade_store, ExitReason, ExitEvent
from trade.ledger import trade_ledger

from data.prefill import run as run_prefill
from workers.stream_producer import StreamProducer

IST = pytz.timezone('Asia/Kolkata')
logger = logging.getLogger(__name__)

def safe_float(val):
    try:
        f = float(val)
        return 0.0 if (math.isnan(f) or math.isinf(f)) else f
    except:
        return 0.0

class LiveMode(BaseMode):
    def __init__(self, debug_schedule=False, symbol="NIFTY", chat_id=None, mock=False, replay=False):
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self.symbol = symbol
        self.debug_schedule = debug_schedule
        self.is_mock = mock
        self.is_replay = replay
        self.mode_tag = "MOCK" if mock else "LIVE"
        self.session_id = f"{self.mode_tag}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # 1. Infrastructure
        if mock:
             logger.info("🎭 Initializing MOCK Broker (SimBroker with Real Option Pricing)")
             # Initialize Fyers client for option pricing (but not for execution)
             fyers_client = None
             try:
                 from engine.auth_fyers import get_fyers_instance
                 fyers_client = get_fyers_instance()
                 print(f"   ✅ [Mock] Fyers client initialized for option pricing: {fyers_client is not None}")
                 self.broker = SimBroker(fyers_client=fyers_client)
             except Exception as e:
                 print(f"   ⚠️ [Mock] Could not init Fyers for option pricing: {e}")
                 logger.warning(f"⚠️ Could not init Fyers for option pricing: {e}. Using delta model.")
                 self.broker = SimBroker()
        else:
             logger.info("🔴 Initializing LIVE Broker (Fyers)")
             self.broker = FyersBroker()
             
        self.journal = Journal(session_id=self.session_id)
        # self.brain = LLMClient() # DELETED
        self.last_token_reload = time.time() # v6.3 Watchdog
        
        # 2. Research Engine (v6.2 Logic)
        self.research_engine = ResearchEngine()
        
        # 3. Trade Lifecycle (v6.2 Persistence)
        self.lifecycle = create_lifecycle(self.session_id, self.broker, is_simulation=False)
        
        # 4. State & Helpers
        self.scheduler = BackgroundScheduler(timezone=IST)
        self.running = False
        self.last_tick = None
        self.morning_brief = None
        self.last_morning_date = None
        self.last_llm_time = datetime.min.replace(tzinfo=IST)
        self.eod_sent = False # v6.3.4 Graceful Summary Guard
        
        self._setup_schedule()

    def _resample_to_15m(self, df_5m):
        """Standard 15m Resampler (Parent Context)"""
        if df_5m.empty: return pd.DataFrame()
        df = df_5m.copy()
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.set_index('timestamp')
        agg = {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}
        df_15 = df.resample('15min').agg(agg).dropna().reset_index()
        return df_15

    def _prepare_dataframes(self, context):
        """Convert DB Context to Engine DataFrames"""
        # Combine History + Today
        full_data = context.get('last_5min', []) + context.get('today_5min', [])
        if not full_data: return pd.DataFrame(), pd.DataFrame()
        
        # Normalize
        normalized = []
        for b in full_data:
            ts = b.get('timestamp') or b.get('ts')
            # If string, parse. If datetime, use.
            if isinstance(ts, str):
                ts = date_parser.parse(ts)
            if ts.tzinfo is None:
                ts = IST.localize(ts)
            
            normalized.append({
                'timestamp': ts,
                'open': safe_float(b['o'] if 'o' in b else b['open']),
                'high': safe_float(b['h'] if 'h' in b else b['high']),
                'low': safe_float(b['l'] if 'l' in b else b['low']),
                'close': safe_float(b['c'] if 'c' in b else b['close']),
                'volume': safe_float(b['v'] if 'v' in b else b['volume'])
            })
            
        df_5m = pd.DataFrame(normalized).drop_duplicates('timestamp').sort_values('timestamp')
        df_15m = self._resample_to_15m(df_5m)
        return df_5m, df_15m

    def start(self):
        logger.info(f"🚀 Starting {self.mode_tag} Mode (v6.2-SOVEREIGN)")
        # v6.3 Pre-Market Wait Layer
        now_conf = datetime.now(IST)
        market_open = now_conf.replace(hour=9, minute=15, second=0, microsecond=0)
        
        if now_conf < market_open and not self.debug_schedule:
             wait_sec = (market_open - now_conf).total_seconds()
             logger.info(f"🌙 Pre-Market Wait Mode. Sleeping until 09:15 IST ({wait_sec/60:.1f}m)...")
             time.sleep(wait_sec)
             logger.info("☀️ Market Open! Starting Engine.")

        self.running = True
        self.scheduler.start()
        
        # v6.2.4 Startup Sequence
        logger.info("   ⏳ Startup: Prefilling 7d Context...")
        run_prefill(days=7, symbol=self.symbol) # Default 5min
        
        # v6.3: Also prefill 1min for Mock Replay (Socket Emulation)
        if self.mode_tag == "MOCK":
             logger.info("   ⏳ Startup: Prefilling 1min Data for Replay...")
             run_prefill(days=7, symbol=self.symbol, resolution="1")
        
        logger.info("   ⏳ Startup: Restoring Lifecycle State...")
        self.lifecycle.restore_open_trades()

        # v6.3.1: Broker State Sync (Fix for restored trades not showing option pricing)
        if self.is_mock and hasattr(self.broker, 'open_position'):
            from trade.ledger import trade_ledger
            restored_positions = list(trade_ledger.open_positions.values())
            if restored_positions:
                trade = restored_positions[0] # Single trade mode
                logger.info(f"   [Sync] Synchronizing SimBroker state for {trade.trade_id}...")
                
                # Check for option metadata
                opt_sym = trade.metadata.get('option_symbol')
                strike = trade.metadata.get('strike')
                
                # Sync into broker
                self.broker.open_position = {
                    'symbol': trade.symbol,
                    'side': trade.direction,
                    'quantity': trade.quantity,
                    'entry_price': trade.entry_price,
                    'entry_time': trade.entry_time,
                    'option_symbol': opt_sym,
                    'strike': strike,
                    'reason': "Restored"
                }
                
                # Upgrade index trades to real option tracking if possible
                if not opt_sym:
                    logger.info(f"   [Sync] 🚀 Attempting to find live option for restored trade...")
                    try:
                        from brokers.simulator.option_utils import find_nearest_expiry_with_ltp
                        # Use entry_price as spot if > 5000, else use current_price if available
                        spot_guess = trade.entry_price if trade.entry_price > 5000 else 25000.0 # Default fallback
                        
                        sym, ltp, stk = find_nearest_expiry_with_ltp(self.broker.fyers_client, spot_guess, trade.direction)
                        if sym:
                            self.broker.open_position['option_symbol'] = sym
                            self.broker.open_position['strike'] = stk
                            logger.info(f"   [Sync] ✅ Auto-associated {sym} with restored trade.")
                    except Exception as e:
                        logger.warning(f"   [Sync] ⚠️ Upgrade failed: {e}")

        self._start_redis_consumer()
        
        # v6.3 Restored Auto-Start Data Feed
        self._start_data_producer()

        # v6.3: Immediate Warmup Cycle (Don't wait 5 mins for first logs)
        print("   🔥 [System] Waiting for Market Data (up to 15s)...")
        # Poll for first tick so engine cycle doesn't skip
        for _ in range(30):
            if self.last_tick: break
            time.sleep(0.5)
            
        if self.last_tick:
            print(f"   🔥 [System] Data Received. Triggering Startup Engine Cycle...")
            try:
                self._run_engine_cycle(reason="Startup")
            except Exception as e:
                logger.error(f"❌ Startup Cycle Failed: {e}")
        else:
            print("   ⚠️ [System] No Data Received yet. Engine will start on schedule.")

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
        
        # v6.3: Live Persistence (Real-Time)
        # We must aggregate ticks into candles so fetching context works.
        self._aggregate_candle(message)
        
        # 1. DETERMINISTIC SAFETY (SL/Target Check) - Priority v4.4 PARITY
        # For Mock Mode (SimBroker) which doesn't enforce SL/TGT in its own tick thread.
        open_trades = list(trade_ledger.get_open_positions(self.symbol).values())
        for trade in open_trades:
            exit_price = None
            exit_reason = None
            
            if trade.direction == "CALL":
                if tick['low'] <= trade.sl_price:
                    exit_price = trade.sl_price
                    exit_reason = ExitReason.SL
                elif tick['high'] >= trade.target_price:
                    exit_price = trade.target_price
                    exit_reason = ExitReason.TGT
            else: # PUT
                if tick['high'] >= trade.sl_price:
                    exit_price = trade.sl_price
                    exit_reason = ExitReason.SL
                elif tick['low'] <= trade.target_price:
                    exit_price = trade.target_price
                    exit_reason = ExitReason.TGT
            
            if exit_price:
                logger.info(f"   🛡️ DETERMINISTIC EXIT: {trade.trade_id} @ {exit_price} ({exit_reason.value})")
                # 1. Execute on Broker (Virtual or Real)
                # In Real Live, this might fail if order already hit at exchange.
                self.broker.execute_exit(trade.symbol, trade.direction, trade.quantity, exit_price, exit_reason.value)
                
                # 2. Close in Lifecycle
                pts = (exit_price - trade.entry_price) if trade.direction == "CALL" else (trade.entry_price - exit_price)
                lot_size = config.get('GLOBAL.NIFTY_LOT_SIZE', 65)
                delta = config.get('GLOBAL.OPTIONS_DELTA', 0.55)
                pnl_rupees = pts * trade.quantity * delta
                
                event = ExitEvent(trade.trade_id, ts, exit_price, exit_reason, pts, pnl_rupees)
                self.lifecycle.close_trade(trade.trade_id, event)
                self._emit_telegram_event("TRADE_CLOSE", trade.to_dict(), mode_tag=self.mode_tag)
                
        # 2. Heartbeat
        self._check_heartbeat(ts, tick)


    def _run_engine_cycle(self, context=None, reason="Scheduled"):
        """
        Periodically runs the full Research Stack to check for entries AND exits.
        Connected to Scheduler (every 5m).
        """
        if not self.last_tick:
            # v6.2.5 Warn if Data Feed is silent logic
            now = datetime.now(IST)
            if not hasattr(self, '_last_no_data_warn') or (now - self._last_no_data_warn).total_seconds() > 300:
                logger.warning(f"⚠️ [{now.strftime('%H:%M')}] Engine Cycle Skipped: No Market Data received yet. Check Redis/Feed.")
                self._last_no_data_warn = now
            return
        ts = self.last_tick['timestamp']
        
        if context is None:
            context = fetch_context_data(ts, symbol=self.symbol)
            context['time_str'] = ts.strftime('%H:%M:%S')
            context['symbol'] = self.symbol
            
        logger.info(f"   ⚙️ Running Engine Cycle ({reason})...")

        # 1. Prepare Data
        df_5m, df_15m = self._prepare_dataframes(context)
        if df_5m.empty: return

        # 2. Reasoning (Physics + Regime + Risk)
        # Note: process_tick returns dict with 'decision', 'regime_id', 'features_5m', etc.
        packet = self.research_engine.process_tick(df_5m, df_15m, silent=True) # Silence default log
        decision = packet.get('decision', {})
        regime_id = packet.get('regime_id', 'UNKNOWN')
        log_str = packet.get('log_str', '')
        
        # v6.3.5 Fix: Extract wr and alpha_state for downstream logic
        alpha_state = packet.get('alpha_state', {})
        wr = alpha_state.get('win_rate', 0.0)

        # 2.0 EOD Graceful Handling (v6.3.4)
        is_market_closed = (ts.hour == 15 and ts.minute >= 29) or (ts.hour >= 16)
        if is_market_closed:
             from trade.ledger import trade_ledger
             if trade_ledger.has_open_position(self.symbol):
                 logger.info("   🕒 [System] Market Closing soon. Triggering EOD Force Exit.")
                 # Leverage existing force exit logic below by injecting an EXIT action
                 decision['action'] = 'FORCE_EOD_EXIT'
                 packet['in_trade_action'] = 'EXIT'
                 packet['reason'] = 'Market Close'
             else:
                 logger.info("   🕒 [System] Market Closed. No positions to manage. Cycle Complete.")
                 self._send_eod_summary() # v6.3.4 Trigger Daily Report
                 return
        
        # 2.1 Append PnL (LiveMode Specific)
        # Check active trades
        from trade.ledger import trade_ledger
        open_pos_list = list(trade_ledger.open_positions.values())
        if open_pos_list:
            trade = open_pos_list[0] # Assuming single trade mode
            current_price = self.last_tick['close']
            
            # Index-level stats
            idx_pnl_pts = (current_price - trade.entry_price) if trade.direction == "CALL" else (trade.entry_price - current_price)
            
            # v6.3: Detect if entry_price is Premium (<1000) or Index (>1000)
            is_premium_entry = trade.entry_price < 5000 # NIFTY is ~25k
            
            # Mock Mode Enhancement: Use Real Option Price for UPnL
            option_ltp = None
            if self.is_mock and hasattr(self.broker, 'open_position') and self.broker.open_position:
                option_symbol = self.broker.open_position.get('option_symbol')
                if option_symbol and hasattr(self.broker, 'fyers_client') and self.broker.fyers_client:
                    try:
                        from brokers.simulator.option_utils import get_option_ltp
                        option_ltp = get_option_ltp(self.broker.fyers_client, option_symbol)
                    except:
                        pass
            
            # Calculate UPnL
            if option_ltp and is_premium_entry:
                # Case A: Pure Option Tracking
                pnl_rupees = (option_ltp - trade.entry_price) * trade.quantity
                label = f"Opt: ₹{option_ltp:.2f}"
            elif is_premium_entry:
                # Case B: Premium Entry but Quote failed (Fallback to Delta estimation)
                # We don't have index PnL here easily, so we use a roughly estimated delta pnl
                # But safer to just show the premium diff if we had one
                label = f"Opt_Entry (No Quote)"
                pnl_rupees = 0 # Cannot calculate without current premium
            else:
                # Case C: Index Entry (Delta Model)
                delta = config.get('GLOBAL.OPTIONS_DELTA', 0.55)
                pnl_rupees = idx_pnl_pts * trade.quantity * delta
                label = f"{idx_pnl_pts:+.1f}pts"
            
            color = "\033[92m" if pnl_rupees >= 0 else "\033[91m"
            log_str += f" | {color}UPnL: {label} (₹{pnl_rupees:+.0f})\033[0m"
            
            # Debug Math (Only if user is confused)
            # print(f"   [Debug PnL] Cur: {current_price} | Entry: {trade.entry_price} | Diff: {idx_pnl_pts:+.2f} | PnL: {pnl_rupees:+.0f}")

        logger.info(log_str)
        
        # v6.3.3: Periodic High-Fidelity UPnL Update for Telegram
        if trade_ledger.has_open_position(self.symbol):
            trade = trade_ledger.get_open_position(self.symbol)
            if trade:
                self._emit_telegram_event("UPNL_UPDATE", {
                    "trade_id": trade.trade_id,
                    "price": current_price,
                    "upnl_pts": idx_pnl_pts,
                    "upnl_rupees": pnl_rupees,
                    "label": label,
                    "regime": regime_id, # v6.3.4 Fix: Use in-scope variable
                    "wr": wr,
                    "bars_held": trade.bars_held
                }, mode_tag=self.mode_tag)
        
        # v6.3: Live Persistence
        # Ensure context is updated for next cycle
        if self.last_tick:
             dummy_tick = self.last_tick.copy()
             dummy_tick['ltp'] = dummy_tick['close']
             self._aggregate_candle(dummy_tick) # Updated from existing state
        
        # 3. Trade Management (In-Trade Monitor) - The Sovereign Guardrail
        # Iterating a copy of values to avoid modification issues
        open_trades = list(trade_ledger.open_positions.values())
        
        for trade in open_trades:
            # v6.3.4: Force Exit on Market Close (Priority Check)
            is_eod = (ts.hour == 15 and ts.minute >= 29)
            
            if is_eod:
                monitor = {"in_trade_action": "EXIT", "reason": "Market Close"}
            else:
                # Check for Traps / Decay
                monitor = self.research_engine.process_in_trade_tick(
                    df_5m, df_15m, trade, pre_computed_result=packet, current_price=self.last_tick['close']
                )
            
            if monitor.get('in_trade_action') == "EXIT":
                logger.info(f"   🚨 EXECUTING FORCE EXIT: {monitor.get('reason')}")
                # Execute on Broker
                fill = self.broker.execute_exit(
                    symbol=trade.symbol,
                    side=trade.direction,
                    quantity=trade.quantity,
                    price=self.last_tick['close'],
                    reason=monitor.get('reason')
                )
                
                # Close in Lifecycle using Broker's Fill Data
                pnl_pts = fill.get('pnl_pts', 0)
                pnl_rupees = fill.get('rupee_pnl', 0)
                exit_price = fill.get('price', self.last_tick['close'])
                
                # Exit Reason Mapping
                er = ExitReason.INVALIDATION
                if "Stale" in monitor.get('reason', ''): er = ExitReason.STALE
                elif "Jitter" in monitor.get('reason', ''): er = ExitReason.JITTER
                
                event = ExitEvent(
                    trade_id=trade.trade_id,
                    exit_time=datetime.now(IST),
                    exit_price=exit_price,
                    exit_reason=er,
                    pnl_points=pnl_pts,
                    pnl_rupees=pnl_rupees,
                    bars_held=trade.bars_held
                )
                
                # Persistence
                # v6.3.2 Fix: Pass trade_id string, not Trade object
                self.lifecycle.close_trade(trade.trade_id, event)
                
                # Enrich Payload for High-Fidelity Logs
                payload = trade.to_dict()
                payload.update({
                    "final_regime": monitor.get('regime_id'),
                    "final_wr": monitor.get('win_rate'),
                    "exit_pnl_pts": pnl_pts,
                    "exit_pnl_rupees": pnl_rupees,
                    "reason": monitor.get('reason')
                })
                self._emit_telegram_event("TRADE_CLOSE", payload, mode_tag=self.mode_tag)

        # 4. Entry Logic (Only if no open trades)
        action = decision.get('action', 'HOLD')
        if action in ["BUY_CALL", "BUY_PUT"]:
            # Single Trade Constraint
            if trade_ledger.has_open_position(self.symbol):
                return
            
            # v6.3.4 EOD Guard: No new trades after 15:15
            if ts.hour == 15 and ts.minute > 15:
                logger.info("   ⏳ EOD Guard: Skipping new trade due to proximity to market close.")
                return

            # A. Propose
            # Prepare context for Lifecycle
            # Unified Context Extraction (v4.6)
            ctx = self.research_engine.get_trade_context(packet, self.symbol, self.last_tick['close'], mode="LIVE")
            trade = self.lifecycle.propose_trade(decision, ctx, datetime.now(IST))
            
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
                if fill.get('price'): trade.entry_price = fill.get('price')
                trade.metadata['broker_order_id'] = fill.get('order_id')
                trade.metadata['option_symbol'] = fill.get('option_symbol')
                trade.metadata['strike'] = fill.get('strike')
                
                if self.lifecycle.open_trade(trade):
                    logger.info(f"✅ Trade {trade.trade_id} OPENED in Ledger.")
                    
                    # Enrich for Telegram
                    payload = trade.to_dict()
                    payload.update({
                        "alpha_state": packet.get('alpha_state'),
                        "physics_ctx": packet.get('physics_vector')
                    })
                    self._emit_telegram_event("TRADE_OPEN", payload, mode_tag=self.mode_tag)
                else:
                    logger.error(f"❌ Failed to Open Trade {trade.trade_id} in Lifecycle")
            else:
                 logger.error(f"❌ Broker Execution Failed: {fill.get('error')}")

        self._emit_trace(packet, reason)
        logger.info(f"   🏁 Engine Cycle Complete.")


    def _setup_schedule(self):
        if self.debug_schedule:
             self.scheduler.add_job(self._run_engine_cycle, 'interval', minutes=5)
             return
        
        self.scheduler.add_job(self._run_engine_cycle, 'cron', hour='9-15', minute='*/5', day_of_week='mon-fri', max_instances=3)
        
        # v6.3 Operational Watchdogs
        self.scheduler.add_job(self._check_token_health, 'cron', minute='0') # Hourly (:00)

    def _start_redis_consumer(self):
        import threading
        t = threading.Thread(target=self._redis_consumer_loop)
        t.daemon = True
        t.start()

    def _start_data_producer(self):
        """
        Starts the Fyers/Mock StreamProducer in a separate thread.
        This ensures LiveMode is self-contained (no external workers needed).
        """
        import threading
        def _run_producer():
            # In Mock, simulation days default to 1 or passed via args (if passed to LiveMode)
            # Use '1' as default for now or expose in __init__
            days = 1
            
            # v6.3: Explicit Replay Control
            # If default Mock (Paper Trading), use LIVE feed. If Replay requested, use MOCK feed (DB).
            producer_mode = "MOCK" if self.is_replay else "LIVE"
            
            producer = StreamProducer(
                mode=producer_mode, 
                days=days, 
                symbol=self.symbol
            )
            # This is blocking, so strictly thread it
            producer.start()

        logger.info(f"   🚀 Launching Embedded Data Producer ({self.mode_tag})...")
        t = threading.Thread(target=_run_producer)
        t.daemon = True
        t.start()

    def _redis_consumer_loop(self):
        import redis
        import os
        
        # Robust Connection Logic (mirrors stream_producer.py)
        # Robust Redis Discovery
        potential_hosts = [
            os.getenv("REDIS_HOST", "beast_redis"),
            "beast_redis",
            "redis",
            "172.19.0.3",
            "localhost"
        ]
        hosts = list(dict.fromkeys([h for h in potential_hosts if h]))
        
        r = None
        for host in hosts:
            try:
                # logger.info(f"   🔎 [Redis] Trying {host}...")
                client = redis.Redis(host=host, port=6379, decode_responses=False, socket_connect_timeout=1)
                client.ping()
                logger.info(f"   ✅ [Redis] LiveMode connected to {host}")
                r = client
                break
            except Exception:
                continue
                
        if r:
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


    
    def _check_token_health(self):
        """v6.3 Token Watchdog (Hot Reload)"""
        import os
        token_path = "fyers_token.json"
        if not os.path.exists(token_path):
             self._emit_telegram_event("CRITICAL", {"msg": "🚨 Fyers Token Missing! Re-login required."}, mode_tag=self.mode_tag)
             return

        # Check modification time
        mtime = os.path.getmtime(token_path)
        if mtime > self.last_token_reload:
             logger.info("♻️ Token File Updated. Requesting Broker Reload...")
             try:
                 # Re-init broker to pick up new token
                 if not self.is_mock:
                     from brokers.fyers.broker import FyersBroker
                     self.broker = FyersBroker()
                     self.lifecycle.broker = self.broker # Update lifecycle ref
                 self.last_token_reload = time.time()
                 logger.info("✅ Broker Connectivity Refreshed.")
                 self._emit_telegram_event("STATUS", {"msg": "♻️ Token Hot-Reloaded."}, mode_tag=self.mode_tag)
             except Exception as e:
                 logger.error(f"❌ Hot Reload Failed: {e}")

    def _check_heartbeat(self, ts, tick):
        if not hasattr(self, 'last_heartbeat_time'): self.last_heartbeat_time = ts
        time_since_hb = (ts - self.last_heartbeat_time).total_seconds() / 60
        if time_since_hb >= 5:
            # We can check open positions via TradeLedger now
            from trade.ledger import trade_ledger
            open_pos = len(trade_ledger.open_positions)
            status = f"Active Trades: {open_pos}"
            logger.info(f"   [{ts.strftime('%H:%M')}] 💓 [FEED] Price {tick['close']:.1f} | {status}")
            self.last_heartbeat_time = ts

    def _send_eod_summary(self):
        """Calculates and pushes a professional daily performance report to Telegram (DB-Backed)."""
        if self.eod_sent:
            return
            
        try:
            import os
            import pandas as pd
            from data.database import get_connection
            
            db_name = os.environ.get("BEAST_DB_NAME", "trading.db")
            conn = get_connection(db_name)
            
            # v6.3.6: Always query DB for today's trades to handle engine restarts
            today_str = datetime.now(IST).strftime('%Y-%m-%d')
            
            # Filter by mode (MOCK/LIVE) and exit_time from today
            query = f"""
                SELECT pnl_points, pnl_rupees 
                FROM trades 
                WHERE session_id LIKE '{self.mode_tag}%' 
                AND exit_time >= '{today_str}'
                AND status = 'CLOSED'
            """
            df = pd.read_sql(query, conn)
            
            # Supplement with Ledger just in case some are not yet committed
            from trade.ledger import trade_ledger
            ledger_trades = trade_ledger.get_all_closed()
            
            total_trades = len(df)
            if total_trades == 0 and not ledger_trades:
                logger.info("   🕒 [System] No trades found in DB or Ledger for today. Skipping Summary.")
                return

            if total_trades > 0:
                wins = sum(1 for p in df['pnl_points'] if p > 0)
                net_points = float(df['pnl_points'].sum())
                net_rupees = float(df['pnl_rupees'].sum())
            else:
                # Fallback to ledger only
                total_trades = len(ledger_trades)
                wins = sum(1 for t in ledger_trades if t.pnl_points > 0)
                net_points = sum(t.pnl_points for t in ledger_trades)
                net_rupees = sum(t.pnl_rupees for t in ledger_trades)
                
            losses = total_trades - wins
            win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
            balance = self.broker.get_balance() if self.broker else 0
            
            payload = {
                "date": datetime.now(IST).strftime('%d-%m-%Y'),
                "total_trades": total_trades,
                "wins": wins,
                "losses": losses,
                "win_rate": f"{win_rate:.1f}%",
                "net_pnl_pts": f"{net_points:+.1f}",
                "net_pnl_rupees": f"₹{net_rupees:+,.0f}",
                "final_balance": f"₹{balance:,.0f}"
            }
            
            self._emit_telegram_event("DAILY_SUMMARY", payload, mode_tag=self.mode_tag)
            logger.info(f"📊 DB-Backed EOD Summary Sent: {total_trades} trades, {net_points:+.1f} pts")
            self.eod_sent = True
            
        except Exception as e:
            logger.error(f"❌ Failed to send EOD Summary: {e}")

    def _emit_telegram_event(self, event_type, payload, mode_tag="LIVE"):
        """
        Routes internal events to the centralized Communication Module.
        This sends the data to n8n Webhook for Telegram Notification.
        """
        # Ensure Chat ID is attached
        if self.chat_id:
            payload['chatId'] = self.chat_id
            
        emit_telegram_signal(event_type, payload, mode_tag=mode_tag)

    def _aggregate_candle(self, tick):
        """
        Aggregates ticks into 1min candles and persists to DB.
        This provides the 'Context' for the next engine cycle.
        """
        try:
            from data.database import get_connection, get_fyers_symbol
            from dateutil import parser
            import os
            
            # Handle both string and datetime timestamps
            ts_raw = tick.get('timestamp')
            if isinstance(ts_raw, str):
                ts = parser.parse(str(ts_raw))
            elif isinstance(ts_raw, datetime):
                ts = ts_raw
            else:
                logger.warning(f"   [DB] ⚠️ Invalid timestamp type: {type(ts_raw)}")
                return
            
            # Ensure timezone aware
            if ts.tzinfo is None:
                ts = IST.localize(ts)
                
            price = float(tick.get('ltp', 0))
            if price == 0:
                logger.warning(f"   [DB] ⚠️ Zero price in tick, skipping aggregation")
                return
            
            # Ensure we write with the Canonical/Fyers symbol (e.g., NSE:NIFTY50-INDEX)
            # so that fetch_context_data can find it.
            db_symbol = get_fyers_symbol(self.symbol)
            
            # Normalize to 1-minute bucket
            candle_ts = ts.replace(second=0, microsecond=0)
            
            # Upsert 1m
            query = """
            INSERT INTO candles_1min (timestamp, symbol, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, 0)
            ON CONFLICT(timestamp, symbol) DO UPDATE SET
                high = MAX(high, excluded.high),
                low = MIN(low, excluded.low),
                close = excluded.close
            """
            
            # Normalize to 5-minute bucket for Engine Context
            minute = (candle_ts.minute // 5) * 5
            candle_5m_ts = candle_ts.replace(minute=minute)
            
            query_5m = """
            INSERT INTO candles_5min (timestamp, symbol, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, 0)
            ON CONFLICT(timestamp, symbol) DO UPDATE SET
                high = MAX(high, excluded.high),
                low = MIN(low, excluded.low),
                close = excluded.close
            """
            
            db_name = os.environ.get("BEAST_DB_NAME", "trading.db")
            conn = get_connection(db_name)
            try:
                # Convert to UTC string for storage (database expects UTC naive strings)
                candle_ts_utc_str = candle_ts.astimezone(pytz.UTC).strftime('%Y-%m-%d %H:%M:%S')
                candle_5m_ts_utc_str = candle_5m_ts.astimezone(pytz.UTC).strftime('%Y-%m-%d %H:%M:%S')
                
                conn.execute(query, (candle_ts_utc_str, db_symbol, price, price, price, price))
                conn.execute(query_5m, (candle_5m_ts_utc_str, db_symbol, price, price, price, price))
                conn.commit()  # Explicit commit
                
                # Debug log (uncomment if issues persist)
                logger.debug(f"   [DB] ✅ Written: {candle_5m_ts.strftime('%H:%M')} @ {price:.2f} to {db_name}")
            except Exception as write_err:
                logger.error(f"❌ DB Write Failed: {write_err}")
                conn.rollback()
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"❌ Candle Aggregation Failed: {e}")

    def _emit_trace(self, packet, reason):
        # Trace implementation (logging)
        pass