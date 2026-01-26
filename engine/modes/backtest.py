"""
v2.9 Backtest Mode (Dimensional Engine)
Thin wrapper driving the 64D Atlas Strategy.
- Standard 5m/15m Tick Loop.
- Uses `DimensionalEngine` for all signals.
- Implements Transition Engine (Adaptive Exit) directly in the loop.
"""
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time
import pytz

from engine.modes.base_mode import BaseMode
from engine.journal import Journal
from brokers.simulator.broker import SimBroker

# v4.0 Engine
from engine.research_engine import ResearchEngine

# v2.8 Modules
from adapters.data_adapter import data_adapter
from config.config_loader import config
from atlas.state_logger import atlas_logger

# v2.8 Trade Engine
from trade import (
    trade_ledger, exit_engine, eod_processor, trade_reporter,
    create_lifecycle, ExitReason, ExitEvent
)
from trade.models import Trade, TradeStatus 

IST = pytz.timezone('Asia/Kolkata')
logger = logging.getLogger(__name__)

# --- SCHEDULE CONSTANTS ---
TACTICAL_START_TIME = time(9, 15) # Start immediately
TACTICAL_END_TIME = time(15, 30)
EOD_TIME = time(15, 30)

class BacktestMode(BaseMode):
    def __init__(self, start_date, end_date, symbol="NIFTY", resolution="5", initial_balance=30000, chat_id=None):
        self.chat_id = chat_id
        self.start_date = start_date
        self.end_date = end_date
        self.symbol = symbol
        self.resolution = resolution
        self.session_id = f"BACKTEST_ATLAS_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # 1. Infrastructure
        self.broker = SimBroker(initial_balance=initial_balance)
        self.journal = Journal(session_id=self.session_id)
        
        # Override trace_logger session_id for this session
        from audit.trace_logger import trace_logger
        trace_logger.session_id = self.session_id
        
        # 2. Research Engine (v4.0 Brain)
        self.engine = ResearchEngine()
        
        # 3. Trade Engine (v2.8)
        self.lifecycle = create_lifecycle(self.session_id, self.broker, is_simulation=True)
        
        # 4. Daily State
        self.running = False
        self.today_bars = []
        self.daily_summaries = []
        self.daily_context = {} 

    def start(self):
        """Run the Historical Backtest"""
        logger.info(f"📊 Starting Atlas Backtest: {self.start_date.date()} to {self.end_date.date()} (Session: {self.session_id})")
        
        self.journal.register_session(
            symbol=self.symbol,
            start_date=self.start_date.strftime('%Y-%m-%d'),
            end_date=self.end_date.strftime('%Y-%m-%d')
        )
        
        self.running = True
        try:
            self._run_simulation()
        finally:
            atlas_logger.flush()
            from audit.trace_logger import trace_logger
            trace_logger.flush()
            # Generate Report
            trade_reporter.generate_session_report(self.session_id, self.daily_summaries, llm_client=None)

    def stop(self):
        self.running = False
        logger.info("🛑 Backtest Stopped")
        atlas_logger.flush()

    def _on_day_ended(self, ts, last_close):
        """Standard EOD Hook."""
        summary = eod_processor.end_of_day(
            self.lifecycle, last_close, ts,
            llm_client=None, # No LLM summary
            morning_plan={"primary_bias": "ATLAS", "reference_levels": {}},
            symbol=self.symbol,
            today_bars=self.today_bars
        )
        return summary

    def _resample_to_15m(self, df_5m):
        """Resample 5m DataFrame to 15m (Parent)"""
        if df_5m.empty: return pd.DataFrame()
        
        df = df_5m.copy()
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.set_index('timestamp')
        
        agg_dict = {
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }
        
        # Check if we have context info to preserve? 
        # For now just OHLCV is needed for calculators
        
        df_15 = df.resample('15min').agg(agg_dict).dropna()
        df_15 = df_15.reset_index()
        return df_15

    def on_tick(self, message):
        """
        Handles a single tick (5-min candle).
        1. Build DataFrames.
        2. Call DimensionalEngine.
        3. Execute Trades.
        """
        ts = message['timestamp']
        ts_str = ts.strftime('%H:%M:%S')
        
        # Accumulate Bar
        bar = {
            'ts': ts.strftime('%Y-%m-%d %H:%M:%S'),
            'o': message['open'], 'h': message['high'], 'l': message['low'], 'c': message['close'], 'v': message['volume']
        }
        self.today_bars.append(bar)
        
        # 1. Prepare DataFrames for Engine
        # Retrieve historical context (list of dicts)
        hist_5min = self.daily_context.get('last_5min', [])
        
        # Today's bars (Normalize keys to match hist_5min)
        from data.database import IST
        today_bars_std = []
        for b in self.today_bars:
            dt = pd.to_datetime(b['ts'])
            if dt.tzinfo is None:
                dt = dt.tz_localize('Asia/Kolkata') # Assume IST for backtest local strings
            today_bars_std.append({
                'timestamp': dt,
                'open': b['o'], 'high': b['h'], 'low': b['l'], 'close': b['c'], 'volume': b['v']
            })

        # Combine: History + Today (Full Series)
        full_data = hist_5min + today_bars_std
        
        df_5m = pd.DataFrame(full_data)
        df_5m = df_5m.drop_duplicates('timestamp').sort_values('timestamp')
        
        # Resample for Parent (15m Hierarchy)
        df_15m = self._resample_to_15m(df_5m)
        
        # 2. RUN ENGINE
        # Check if in trade for UPnL logging
        current_trade = trade_ledger.get_open_position()
        
        try:
            # Call engine silently if we plan to manually print a unified log
            analysis = self.engine.process_tick(df_5m, df_15m, silent=True)
        except Exception as e:
            logger.error(f"   [ATLAS] ❌ Inference Error: {e}")
            return
            
        decision = analysis.get('decision', {})
        signal = decision.get('action', 'HOLD')
        regime_id = analysis.get('regime_id', 'UNKNOWN')
        log_str = analysis.get('log_str', '')

        # 3. UNIFIED LOGGING (Continuous Time Series)
        if current_trade:
             # Calculate UPnL
             price = message['close']
             upnl = (price - current_trade.entry_price) if current_trade.direction == "CALL" else (current_trade.entry_price - price)
             color = "\033[92m" if upnl >= 0 else "\033[91m"
             # Append UPnL to the engine's log_str
             log_str += f" | {color}UPnL: {upnl:+.1f}\033[0m"
        
        logger.info(log_str)
        
        # 4. TRADE MANAGEMENT (Transition Engine)
        if current_trade:
            trade = current_trade
            
            # MFE/MAE Tracking (v4.0 Performance Fix)
            trade_ledger.update_price_extremes(trade.trade_id, message['close'])
            trade_ledger.update_price_extremes(trade.trade_id, message['high'])
            trade_ledger.update_price_extremes(trade.trade_id, message['low'])

            # Multiplier Constants
            delta = config.get('GLOBAL.OPTIONS_DELTA', 0.55)
            multiplier = trade.quantity * delta

            # Transition Monitor (Adaptive Exit: Regime Decay / Trap)
            monitor = self.engine.process_in_trade_tick(df_5m, df_15m, trade)
            if monitor.get('in_trade_action') == "EXIT":
                pts = (message['close'] - trade.entry_price) if trade.direction == "CALL" else (trade.entry_price - message['close'])
                pnl_rupees = pts * multiplier
                exit_event = ExitEvent(
                    trade_id=trade.trade_id, exit_time=ts, exit_price=message['close'],
                    exit_reason=ExitReason.INVALIDATION, # Unified with current exit logics
                    pnl_points=pts, pnl_rupees=pnl_rupees, bars_held=0, mfe=0, mae=0
                )
                self.lifecycle.close_trade(trade.trade_id, exit_event)
                return

            # SL/Target Check (Deterministic)
            pts = 0.0
            exit_price = None
            exit_reason = None

            if trade.direction == "CALL":
                 if message['low'] <= trade.sl_price:
                     exit_price = trade.sl_price
                     exit_reason = ExitReason.SL
                 elif message['high'] >= trade.target_price:
                     exit_price = trade.target_price
                     exit_reason = ExitReason.TGT
            else: # PUT
                 if message['high'] >= trade.sl_price:
                     exit_price = trade.sl_price
                     exit_reason = ExitReason.SL
                 elif message['low'] <= trade.target_price:
                     exit_price = trade.target_price
                     exit_reason = ExitReason.TGT

            if exit_price:
                pts = (exit_price - trade.entry_price) if trade.direction == "CALL" else (trade.entry_price - exit_price)
                pnl_rupees = pts * multiplier
                event = ExitEvent(trade.trade_id, ts, exit_price, exit_reason, pts, pnl_rupees)
                self.lifecycle.close_trade(trade.trade_id, event)
        
        else:
            # 4. ENTRY LOGIC
            if signal in ["BUY_CALL", "BUY_PUT"]:
                # Single Trade Constraint (Authoritative Gate)
                if trade_ledger.has_open_position(self.symbol):
                    return

                # Prepare standard context for Propose
                ctx = {
                    'symbol': self.symbol,
                    'close': message['close'],
                    'regime_id': regime_id,
                    'is_fallback': decision.get('is_fallback', False),
                    'atr': 0.0, # Placeholder
                }
                
                # Propose + Open sequence (State Machine)
                trade = self.lifecycle.propose_trade(decision, ctx, ts)
                trade.metadata['is_fallback'] = decision.get('is_fallback', False)
                self.lifecycle.open_trade(trade)

    def _run_simulation(self):
        current_date = self.start_date
        
        # Reset entire ledger only once at session start
        trade_ledger.reset()
        
        while current_date <= self.end_date and self.running:
            day_str = current_date.strftime('%Y-%m-%d')
            logger.info(f"🌞 Simulating Day: {day_str} | Current Balance: ₹{self.broker.get_balance():,.0f}")
            
            # 1. Fetch Data
            ticks = data_adapter.fetch_data_for_day(current_date, self.symbol, self.resolution)
            if ticks.empty:
                logger.info("   ⚠️ No data. Skipping.")
                current_date += timedelta(days=1)
                continue
                
            # 2. Daily Context (Warmup History - strictly pre-market)
            from data.database import fetch_context_data
            # Force midnight normalization to prevent lookahead if current_date has time
            warmup_cutoff = current_date.replace(hour=0, minute=0, second=0, microsecond=0)
            self.daily_context = fetch_context_data(warmup_cutoff, self.symbol, resolution=self.resolution)
            
            self.today_bars = []
            # trade_ledger.reset() -- REMOVED: Preserve trades across days for session report
            
            last_close = 0
            eod_done = False
            
            for i, row in ticks.iterrows():
                if not self.running: break
                
                ts = row['timestamp']
                last_close = row['close']
                
                tick_msg = {
                    'timestamp': ts,
                    'open': row['open'], 'high': row['high'], 'low': row['low'], 'close': row['close'], 'volume': row['volume']
                }
                
                if ts.time() >= EOD_TIME:
                     summary = self._on_day_ended(ts, last_close)
                     if summary: self.daily_summaries.append(summary)
                     eod_done = True
                     break
                     
                self.on_tick(tick_msg)
                
            if not eod_done and not ticks.empty:
                 summary = self._on_day_ended(ticks.iloc[-1]['timestamp'], last_close)
                 if summary: self.daily_summaries.append(summary)
            
            current_date += timedelta(days=1)




