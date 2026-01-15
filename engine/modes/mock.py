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
import logging
logger = logging.getLogger(__name__)

import math

def safe_float(val):
    try:
        f = float(val)
        return 0.0 if (math.isnan(f) or math.isinf(f)) else f
    except:
        return 0.0

class MockMode(BaseMode):
    def __init__(self, debug_schedule=False, symbol="BANKNIFTY", chat_id=None):
        self.chat_id = chat_id
        self.debug_schedule = debug_schedule
        self.symbol = symbol
        self.mode_tag = "MOCK"
        
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
        logger.info("🎭 Starting MOCK Mode (Live Data + Paper Money)")
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
            instr = self.hot_path.active_instructions.get('action', 'WAIT')
            entry = self.hot_path.active_instructions.get('entry_price', 'N/A')
            logger.info(f"   [{ts.strftime('%H:%M')}] 💓 Monitor: Price {tick['close']:.1f} | Instr: {instr} ({entry})")
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

                  logger.info(f"   😶 MOCK ORDER: {action} {symbol} @ {tick['close']:.1f}")
                  
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

                      # TELEGRAM NOTIFICATION (Trade Closed)
                      self._emit_telegram_event("TRADE", {
                          "date": tick['timestamp'].strftime('%Y-%m-%d'),
                          "side": trade.get('side'),
                          "entry": trade.get('entry_price'),
                          "exit": trade.get('exit_price'),
                          "pnl": trade.get('pnl'),
                          "reason": trade.get('reason'),
                          "balance": 0 # Mock doesn't track balance in same way or needs portfolio update
                      }, mode_tag=self.mode_tag)
                      
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
        
        logger.info(f"   [{sim_time.strftime('%H:%M')}] 🧠 Morning Briefing...")
        context = fetch_context_data(sim_time, symbol=self.symbol)
        
        # Slicing Optimization
        mb_context = context.copy()
        mb_context['last_15min'] = context['last_15min'][-3:]
        mb_context['today_5min'] = context['today_5min'][-3:]
        
        
        brief = self.brain.get_morning_brief(mb_context, current_tick=self.last_tick, symbol=self.symbol)
        logger.info(f"      📝 Plan: {brief.get('reasoning')}")
        self.morning_brief = brief
        self.last_morning_date = sim_time.date()
        self.journal.log_event(sim_time, "MORNING", brief)
        
        self._emit_telegram_event("MORNING_BRIEF", {
            "date": sim_time.strftime('%Y-%m-%d'),
            "personality": brief.get('market_personality'),
            "bias": brief.get('primary_bias'),
            "plan": brief.get('morning_logic', brief.get('reasoning'))
        }, mode_tag=self.mode_tag)

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
             # FIX: Inject tick_time for Exceptional Gate (use sim_time)
             instructions['tick_time'] = sim_time.time() if hasattr(sim_time, 'time') else sim_time
             instructions['close'] = self.last_tick.get('close', 0) if self.last_tick else 0
             
             # Extract micro/economic context for logging (they were injected into the client internally)
             # But wait, the client doesn't return them. 
             # Actually, they are purely for the LLM prompt. 
             # I should probably return them from get_tactical_update or calculate them here.
             # Given the "NO CHANGE" rules, I'll calculate them here to avoid changing LLMClient signature.
             from engine.enrichment import calculate_micro_context, calculate_economic_context, calculate_opening_range
             or_data = calculate_opening_range(context.get('today_5min', []))
             or_range = or_data['or_range'] if or_data else 0

             micro_context = calculate_micro_context(
                 bars_15min=context.get('last_15min', []),
                 current_price=self.last_tick['close'],
                 support=self.morning_brief.get('boundary_levels', {}).get('support_zone', 0),
                 resistance=self.morning_brief.get('boundary_levels', {}).get('resistance_zone', 0),
                 pivot=self.morning_brief.get('boundary_levels', {}).get('pivot_point', 0),
                 atr_14=context.get('atr_14'),
                 or_range=or_range
             )
             economic_context = calculate_economic_context(
                 current_price=self.last_tick['close'],
                 target_pts=self.morning_brief.get('max_expected_move', 60)
             )

             self.hot_path.update_instructions(instructions)
             self.journal.log_event(datetime.now(IST), "TACTICAL", instructions, 
                                    micro_context=micro_context, 
                                    economic_context=economic_context)

             # --- EMIT LLM_TRACE (UPGRADE) ---
             trace_payload = {
                 "llm_type": "TACTICAL",
                 "time": sim_time.strftime('%H:%M'),
                 "tick_time": str(instructions.get('tick_time', 'N/A')),
                 "mode": instructions.get('mode', 'UNKNOWN'),
                 "selected_style": instructions.get('selected_style', 'NONE'),
                 "action": instructions.get('action', 'HOLD'),
                 "confidence": instructions.get('confidence', 0.0),
                 "sl_points": instructions.get('sl_points'),
                 "target_points": instructions.get('target_points'),
                 "reason": instructions.get('technical_reason', instructions.get('reason', 'N/A')),
                 "engine_decision": instructions.get('engine_decision', 'EXECUTED'),
                 "engine_reason": instructions.get('engine_reason'),
                 "market_micro_context": micro_context,
                 "economic_context": economic_context
             }
             self._emit_telegram_event("LLM_TRACE", trace_payload, mode_tag=self.mode_tag)
             
             # --- EMIT EXCEPTIONAL GATE REJECTION (if applicable) ---
             if instructions.get('gate_rejected'):
                 self._emit_telegram_event("TRADE_REJECTED_EXCEPTIONAL_GATE", {
                     "time": sim_time.strftime('%H:%M'),
                     "action": instructions.get('action'),
                     "confidence": instructions.get('confidence', 0.0),
                     "rejection_reason": instructions.get('engine_reason')
                 }, mode_tag=self.mode_tag)


    def trigger_eod_journal(self):
        print(f"   [15:30] 📔 EOD Journaling & Audit...")
        sid = datetime.now(IST).strftime('%Y-%m-%d')
        
        # Filter trades for TODAY only to avoid passing entire history to LLM
        today_str = sid
        day_trades = [t for t in self.hot_path.trade_ledger 
                      if str(t.get('exit_time', ''))[:10] == today_str]
        
        eod_data = {
            'date': sid, 
            'ticker': f"{self.symbol} (MOCK)",
            'trades_count': len(day_trades)
        }
        
        audit_res = self.brain.get_eod_journal(
            trades=day_trades,
            morning_plan=self.morning_brief,
            session_id=sid,
            eod_data=eod_data,
            symbol=self.symbol
        )
        
        # Defensive check
        if isinstance(audit_res, dict):
            summary = audit_res.get('audit_summary', "Audit Failed")
        else:
            summary = "Audit Failed (Invalid Response)"
            
        print(f"      📊 {summary}")
        self.journal.log_event(datetime.now(IST), "EOD_AUDIT", audit_res)

        # TELEGRAM NOTIFICATION
        self._emit_telegram_event("EOD", {
            "date": sid,
            "summary": summary,
            "total_pnl": sum(t.get('pnl', 0) for t in day_trades if t.get('pnl') is not None),
            "trades": len(day_trades),
            "win_rate": (len([t for t in day_trades if t.get('pnl', 0) > 0]) / len(day_trades) * 100) if day_trades else 0,
            "nugget": audit_res.get('dataset_nugget', audit_res.get('nugget_good', 'N/A'))
        }, mode_tag=self.mode_tag)

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
        self._emit_telegram_event("LLM_TRACE", trace_payload, mode_tag=self.mode_tag)

        # OPTIONAL: Save Experience for RAG/RL (Mirroring backtest)
        from data.database import save_experience
        stats = {
            'total_pnl': sum(t.get('pnl', 0) for t in day_trades if t.get('pnl') is not None),
            'trade_count': len(day_trades),
            'win_rate': (len([t for t in day_trades if t.get('pnl', 0) > 0]) / len(day_trades) * 100) if day_trades else 0
        }
        
        try:
            save_experience(
                session_id=f"MOCK_{sid}",
                date=datetime.now(IST),
                symbol=self.symbol,
                market_state=eod_data, 
                plan=self.morning_brief,
                trades=day_trades,
                stats=stats,
                audit=audit_res
            )
        except Exception as e:
            print(f"      ⚠️ Experience Save Error: {e}")

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