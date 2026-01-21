"""
v2.9 Backtest Mode
Thin wrapper driving the Modular Architecture with Trade Engine v2.8.
- 09:20: Morning Call (LLM)
- 09:30-15:15 (Every 15 min): Tactical LLM call
- Every candle: Exit checks via TradeEngine
- 15:30: EOD close + Report
"""
import logging
import pandas as pd
from datetime import datetime, timedelta, time
import pytz

from engine.modes.base_mode import BaseMode
from engine.journal import Journal
from brain.llm_client import LLMClient
from brokers.simulator.broker import SimBroker

# v2.8 Modules
from adapters.data_adapter import data_adapter
from engine.research_engine import ResearchEngine
from config.config_loader import config

# v2.8 Trade Engine
from trade import (
    trade_ledger, exit_engine, eod_processor, trade_reporter,
    create_lifecycle, ExitReason
)

IST = pytz.timezone('Asia/Kolkata')
logger = logging.getLogger(__name__)

# --- SCHEDULE CONSTANTS ---
MORNING_BRIEF_TIME = time(9, 20)
TACTICAL_START_TIME = time(9, 30)
TACTICAL_END_TIME = time(15, 15)
EOD_TIME = time(15, 30)
TACTICAL_INTERVAL_MINUTES = 15


class BacktestMode(BaseMode):
    def __init__(self, start_date, end_date, symbol="NIFTY", resolution="5", initial_balance=30000, chat_id=None):
        self.chat_id = chat_id
        self.start_date = start_date
        self.end_date = end_date
        self.symbol = symbol
        self.resolution = resolution
        self.session_id = f"BACKTEST_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # 1. Infrastructure
        self.broker = SimBroker(initial_balance=initial_balance)
        self.journal = Journal(session_id=self.session_id)
        self.brain = LLMClient()
        
        # Override trace_logger session_id for this session
        from audit.trace_logger import trace_logger
        trace_logger.session_id = self.session_id
        
        # 2. Research Engine
        self.research_engine = ResearchEngine(llm_client=self.brain)
        
        # 3. Trade Engine (v2.8)
        self.lifecycle = create_lifecycle(self.session_id)
        
        # 4. Daily State
        self.running = False
        self.today_bars = []
        self.current_plan = None
        self.last_tactical_time = None
        self.daily_summaries = []
        self.daily_context = {}  # Added to persist historical data for the day

    def start(self):
        """Run the Historical Backtest"""
        logger.info(f"📊 Starting Backtest: {self.start_date.date()} to {self.end_date.date()} (Session: {self.session_id})")
        
        self.journal.register_session(
            symbol=self.symbol,
            start_date=self.start_date.strftime('%Y-%m-%d'),
            end_date=self.end_date.strftime('%Y-%m-%d')
        )
        
        self.running = True
        try:
            self._run_simulation()
        finally:
            # Generate final report (Reporting v2.8 Canonical)
            trade_reporter.generate_session_report(self.session_id, self.daily_summaries)

    def stop(self):
        self.running = False
        logger.info("🛑 Backtest Stopped")

    def on_tick(self, message, is_tactical_call: bool = False):
        """
        Handles a single tick (5-min candle).
        - ALWAYS: Check for exits via Trade Engine
        - If `is_tactical_call`: triggers full LLM pipeline
        """
        ts = message['timestamp']
        # Use full ISO format for enrichment modules that expect timestamp at [11:16]
        ts_iso = ts.strftime('%Y-%m-%d %H:%M:%S') if hasattr(ts, 'strftime') else "1970-01-01 00:00:00"
        ts_str = ts.strftime('%H:%M:%S') if hasattr(ts, 'strftime') else "00:00:00"

        # Accumulate Bar
        bar = {
            'ts': ts_iso,
            'o': message['open'], 'h': message['high'], 'l': message['low'], 'c': message['close'], 'v': message['volume']
        }
        self.today_bars.append(bar)
        
        # Construct Tick with historical context for enrichment
        hist_15min = self.daily_context.get('last_15min', [])
        
        tick = {
            'timestamp': ts,
            'open': message['open'],
            'high': message['high'],
            'low': message['low'],
            'close': message['close'],
            'volume': message['volume'],
            'symbol': self.symbol,
            'time_str': ts_str,
            'today_5min': self.today_bars, 
            'last_15min': hist_15min + self.today_bars, # Combine for ATR warmup
            'daily_3': self.daily_context.get('daily_3', []),
            'vix': self.daily_context.get('vix_spot', 15.0)
        }
        
        # 1. ALWAYS: Trade Engine Exit Checks
        exit_events = exit_engine.check_exits(tick)
        for exit_event in exit_events:
            self.lifecycle.close_trade(exit_event.trade_id, exit_event)
        
        # 2. TACTICAL CALL: Full LLM pipeline for new decision
        if is_tactical_call:
            # Differentiate log for Morning vs Tactical
            if ts_str == "09:20:00" or self.last_tactical_time == ts: # Simple heuristic for MB
                 logger.info(f"[SCHED] 🧠 Morning Tactical Sync @ {ts_str}")
            else:
                 logger.info(f"[SCHED] 🧠 Tactical Call @ {ts_str}")
            
            decision_packet = self.research_engine.process_tick(tick, self.current_plan, allow_llm=True)
            decision = decision_packet.get('decision', {})
            enrichment = decision_packet.get('enrichment', {})
            
            # 3. Entry via Trade Engine
            if decision.get('action') in ["BUY_CALL", "BUY_PUT"]:
                # Check if we already have an open position
                if not trade_ledger.has_open_position():
                    # Propose and open trade
                    trade = self.lifecycle.propose_trade(decision, enrichment, ts)
                    # Add SL/TGT from decision if not set
                    if trade.sl_price is None:
                        trade.sl_price = decision.get('sl') or (trade.entry_price - 50 if trade.direction == "CALL" else trade.entry_price + 50)
                    if trade.target_price is None:
                        trade.target_price = decision.get('target') or (trade.entry_price + 90 if trade.direction == "CALL" else trade.entry_price - 90)
                    
                    self.lifecycle.open_trade(trade)
                else:
                    logger.debug("[SCHED] Position already open, skipping entry")

    def _run_simulation(self):
        current_date = self.start_date
        
        while current_date <= self.end_date and self.running:
            day_str = current_date.strftime('%Y-%m-%d')
            logger.info(f"🌞 Simulating Day: {day_str}")
            
            # 1. Fetch Data (5-min candles)
            ticks = data_adapter.fetch_data_for_day(current_date, self.symbol, self.resolution)
            if ticks.empty:
                logger.info("   ⚠️ No data. Skipping.")
                current_date += timedelta(days=1)
                continue
            
            # 2. State Reset for the Day
            prev_close = data_adapter.fetch_prev_close(current_date, self.symbol) or 0.0
            
            # 2a. Real Morning Brief (Phase 2)
            first_tick = ticks.iloc[0].to_dict() if not ticks.empty else None
            self.current_plan = self._generate_morning_plan(current_date, prev_close, first_tick)
            if not self.current_plan:
                 logger.warning("   ❌ Morning Plan Failed. Using Fallback.")
                 self.current_plan = {"primary_bias": "NEUTRAL", "reference_levels": {"pivot": prev_close, "support": prev_close-100, "resistance": prev_close+100}}
            
            self.today_bars = []
            self.last_tactical_time = None
            trade_ledger.reset()
            exit_engine.reset()
            
            last_close = prev_close
            
            # 3. Tick Loop with Schedule
            eod_done = False
            for i, row in ticks.iterrows():
                if not self.running: break
                
                ts = row['timestamp']
                tick_time = ts.time()
                last_close = row['close']
                
                msg = {
                    'timestamp': ts,
                    'open': row['open'],
                    'high': row['high'],
                    'low': row['low'],
                    'close': row['close'],
                    'volume': row['volume']
                }
                
                # --- SCHEDULE LOGIC (Clock-Aligned v2.9) ---
                is_tactical = False
                
                # 1. Morning Brief @ 09:20 (Always trigger once)
                if tick_time >= MORNING_BRIEF_TIME and tick_time < TACTICAL_START_TIME:
                    if self.last_tactical_time is None or self.last_tactical_time.time() < MORNING_BRIEF_TIME:
                        levels = self.current_plan.get('reference_levels', {})
                        logger.info(f"   [SCHED] 📝 Morning Brief @ {tick_time}")
                        logger.info(f"   [MORNING] 🌅 Bias: {self.current_plan.get('primary_bias')} | Pivot: {levels.get('pivot', 0):.0f} | CPR: {levels.get('bc', 0):.0f}/{levels.get('tc', 0):.0f} | S1/R1: {levels.get('s1', 0):.0f}/{levels.get('r1', 0):.0f}")
                        is_tactical = True
                        self.last_tactical_time = ts
                
                # 2. Tactical Interval @ 09:30, 09:45, 10:00, ... 15:15
                elif TACTICAL_START_TIME <= tick_time <= TACTICAL_END_TIME:
                    # Trigger on 15-min clock boundaries
                    if tick_time.minute % TACTICAL_INTERVAL_MINUTES == 0:
                        # Only trigger if we haven't triggered in this 15-min bucket yet
                        # We use 10-min buffer to avoid double triggers in same bucket
                        # But we allow it if the last trigger was the Morning Brief (09:20)
                        last_time_obj = self.last_tactical_time.time() if self.last_tactical_time else None
                        if self.last_tactical_time is None or \
                           last_time_obj == MORNING_BRIEF_TIME or \
                           (ts - self.last_tactical_time).total_seconds() >= (TACTICAL_INTERVAL_MINUTES - 1) * 60:
                            is_tactical = True
                            self.last_tactical_time = ts
                
                # 3. EOD @ 15:30
                elif tick_time >= EOD_TIME:
                    logger.info(f"   [SCHED] 🌙 EOD @ {tick_time}")
                    # EOD Processing via Trade Engine with LLM Audit
                    summary = eod_processor.end_of_day(
                        self.lifecycle, last_close, ts,
                        llm_client=self.brain,
                        morning_plan=self.current_plan,
                        symbol=self.symbol,
                        today_bars=self.today_bars
                    )
                    self.daily_summaries.append(summary)
                    eod_done = True
                    break
                
                self.on_tick(msg, is_tactical_call=is_tactical)
            
            # Ensure EOD processing if loop ended without hitting EOD time (or data shortfall)
            if not eod_done:
                logger.info(f"   [SCHED] 🌙 EOD (Cleanup) @ {ts}")
                summary = eod_processor.end_of_day(
                    self.lifecycle, last_close, ts,
                    llm_client=self.brain,
                    morning_plan=self.current_plan,
                    symbol=self.symbol,
                    today_bars=self.today_bars
                )
                self.daily_summaries.append(summary)
            
            current_date += timedelta(days=1)

    def _generate_morning_plan(self, date, prev_close, first_tick=None):
        """Fetch pre-market context and call LLM for Morning Briefing"""
        from data.database import fetch_context_data
        
        try:
            # 1. Fetch Context (Daily 3, VIX, etc.)
            context = fetch_context_data(date, self.symbol)
            self.daily_context = context  # Store for use in every tick
            
            # 2. Call LLM for Morning Brief
            logger.info(f"   [BRAIN] 🧠 Generating real Morning Brief for {date.date()}...")
            plan = self.brain.get_morning_brief(context, first_tick, symbol=self.symbol)
            
            if not plan:
                return None
                
            # Plan already contains reference_levels, bias, risk_regime
            return plan
        except Exception as e:
            logger.error(f"   ❌ Morning Plan Error: {e}")
            return None
