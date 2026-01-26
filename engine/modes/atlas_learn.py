"""
Atlas Learn Mode
Pure data collection mode. No strategy, no LLM, no decision-making.
Just: Market State → 4 Basis Actions → Outcome Logging.
"""
import logging
import pandas as pd
from datetime import datetime, timedelta, time
import pytz

from engine.modes.base_mode import BaseMode
from engine.journal import Journal
from adapters.data_adapter import data_adapter
from engine.research_engine import ResearchEngine

# Trade Engine
from trade import (
    trade_ledger, exit_engine, create_lifecycle, ExitReason
)
from atlas.state_logger import atlas_logger

IST = pytz.timezone('Asia/Kolkata')
logger = logging.getLogger(__name__)

class AtlasLearnMode(BaseMode):
    """Simplified mode for Atlas data collection"""
    
    def __init__(self, start_date, end_date, symbol="NIFTY", resolution="5"):
        self.start_date = start_date
        self.end_date = end_date
        self.symbol = symbol
        self.resolution = resolution
        self.session_id = f"ATLAS_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Minimal infrastructure
        self.journal = Journal(session_id=self.session_id)
        self.research_engine = ResearchEngine(llm_client=None)  # No LLM
        self.research_engine.set_mode('learn')
        self.lifecycle = create_lifecycle(self.session_id)
        
        # State
        self.running = False
        self.today_bars = []
        self.daily_context = {}
        
        # Silence noisy infrastructure loggers in Learn Mode
        # We only want to see Atlas-specific logs and errors
        logging.getLogger("engine.research_engine").setLevel(logging.WARNING)
        logging.getLogger("trade.lifecycle").setLevel(logging.WARNING)
        logging.getLogger("trade.ledger").setLevel(logging.WARNING)
        logging.getLogger("trade.exit_engine").setLevel(logging.WARNING)
        logging.getLogger("atlas.state_logger").setLevel(logging.INFO) # Keep atlas info

        
    def start(self):
        """Run the Atlas data collection simulation"""
        logger.info(f"🧠 [ATLAS LEARN] {self.start_date.date()} to {self.end_date.date()}")
        
        self.journal.register_session(
            symbol=self.symbol,
            start_date=self.start_date.strftime('%Y-%m-%d'),
            end_date=self.end_date.strftime('%Y-%m-%d')
        )
        
        self.running = True
        try:
            self._run_simulation()
        finally:
            atlas_logger.flush()  # Final flush
            logger.info("✅ [ATLAS] Data collection complete")
    
    def stop(self):
        self.running = False
        atlas_logger.flush()
    
    def _run_simulation(self):
        current_date = self.start_date
        
        while current_date <= self.end_date and self.running:
            day_str = current_date.strftime('%Y-%m-%d')
            logger.info(f"📅 {day_str}")
            
            # Fetch data
            ticks = data_adapter.fetch_data_for_day(current_date, self.symbol, self.resolution)
            if ticks.empty:
                logger.info("   ⚠️  No data")
                current_date += timedelta(days=1)
                continue
            
            # Fetch context (historical data for indicators)
            from data.database import fetch_context_data
            try:
                self.daily_context = fetch_context_data(current_date, self.symbol, resolution=self.resolution)
            except:
                self.daily_context = {}
            
            # Calculate proper levels (same as real trading)
            from enrichment.morning import calculate_pivots, calculate_cpr
            daily_data = self.daily_context.get('daily_3', [])
            
            if daily_data:
                pivots = calculate_pivots(daily_data)
                cpr = calculate_cpr(daily_data)
                levels = {**pivots, **cpr, "support": pivots['s1'], "resistance": pivots['r1']}
                logger.info(f"   [ATLAS] Pivot: {levels['pivot']:.0f} | CPR: {levels['bc']:.0f}/{levels['tc']:.0f}")
            else:
                # Fallback
                first_close = ticks.iloc[0]['close'] if not ticks.empty else 25000
                levels = {
                    "pivot": first_close, "bc": first_close - 50, "tc": first_close + 50,
                    "s1": first_close - 100, "s2": first_close - 200,
                    "r1": first_close + 100, "r2": first_close + 200,
                    "support": first_close - 100, "resistance": first_close + 100
                }
                logger.warning(f"   [ATLAS] Using fallback levels")
            
            morning_plan = {
                "primary_bias": "NEUTRAL",
                "reference_levels": levels
            }
            
            # Reset for day
            self.today_bars = []
            trade_ledger.reset()
            exit_engine.reset()
            
            # Process each tick
            tick_count = 0
            last_ts = current_date # Fallback
            for i, row in ticks.iterrows():
                if not self.running: break
                tick_count += 1
                last_ts = row['timestamp']
                
                # Periodic Heartbeat (since other logs are silenced)
                if tick_count % 50 == 0:
                    logger.info(f"   💓 Heartbeat @ {row['timestamp'].strftime('%H:%M:%S')} | Collected: {len(trade_ledger.closed_positions)} probes")

                # Delegate to on_tick for BaseMode compliance
                is_last_tick = (i == len(ticks) - 1)
                message = {
                    'timestamp': row['timestamp'],
                    'open': row['open'], 'high': row['high'], 'low': row['low'], 
                    'close': row['close'], 'volume': row['volume'],
                    'is_last_tick': is_last_tick
                }
                self.on_tick(message, morning_plan)
            
            # EOD cleanup
            if trade_ledger.has_open_position():
                last_row = ticks.iloc[-1]
                for key, trade in list(trade_ledger.open_positions.items()):
                    from trade.models import ExitEvent, ExitReason
                    
                    # Calculate PnL for EOD
                    pnl_points = (last_row['close'] - trade.entry_price) if trade.direction == "CALL" else (trade.entry_price - last_row['close'])
                    pnl_rupees = pnl_points * trade.quantity
                    
                    # Round for clean logging/training
                    pnl_points = round(pnl_points, 2)
                    pnl_rupees = round(pnl_rupees, 2)
                    
                    exit_event = ExitEvent(
                        trade_id=trade.trade_id,
                        exit_time=last_ts,
                        exit_price=last_row['close'],
                        exit_reason=ExitReason.EOD,
                        bars_held=0,
                        pnl_points=pnl_points,
                        pnl_rupees=pnl_rupees
                    )
                    self.lifecycle.close_trade(trade.trade_id, exit_event)
            
            current_date += timedelta(days=1)

    def on_tick(self, message, morning_plan=None):
        """
        Satisfies BaseMode interface.
        In Learn Mode, this is called directly from the simulation loop.
        """
        ts = message['timestamp']
        ts_iso = ts.strftime('%Y-%m-%d %H:%M:%S') if hasattr(ts, 'strftime') else "1970-01-01 00:00:00"
        ts_str = ts.strftime('%H:%M:%S') if hasattr(ts, 'strftime') else "00:00:00"
        
        # Build bar
        bar = {
            'ts': ts_iso,
            'o': message['open'], 'h': message['high'], 'l': message['low'], 
            'c': message['close'], 'v': message['volume']
        }
        self.today_bars.append(bar)
        
        # Build tick context
        hist_5min = self.daily_context.get('last_5min', [])
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
            'last_15min': hist_15min + self.today_bars,
            'rolling_5min': hist_5min + self.today_bars,
            'daily_3': self.daily_context.get('daily_3', []),
            'vix': self.daily_context.get('vix_spot', 15.0),
            'vol_ratio': self.daily_context.get('vol_ratio', 100.0)
        }
        
        if len(tick['rolling_5min']) < 10:
             logger.warning(f"[ATLAS] ⚠️ Low history for {ts_str}: {len(tick['rolling_5min'])} bars")
        
        # 1. Exit checks
        exit_events = exit_engine.check_exits(tick)
        for exit_event in exit_events:
            self.lifecycle.close_trade(exit_event.trade_id, exit_event)
        
        # 2. Force Basis Probes (The Atlas Experiment)
        if message.get('is_last_tick', False):
            # logger.debug(f"[ATLAS] Skipping probes on last tick to avoid 0.0 PnL noise")
            return

        # We call process_tick purely to get the 'enrichment' features
        decision_packet = self.research_engine.process_tick(tick, morning_plan or {}, allow_llm=False)
        enrichment = decision_packet.get('enrichment', {})
        
        # Basis Definitions (ITC/REMR x CALL/PUT)
        atr_val = enrichment.get('atr', 50.0)
        sl_dist = max(30.0, atr_val * 1.0)
        tgt_dist = sl_dist * 1.85 # Pass risk guard
        
        basis_actions = [
            ('ITC', 'BUY_CALL'), ('ITC', 'BUY_PUT'),
            ('REMR', 'BUY_CALL'), ('REMR', 'BUY_PUT')
        ]
        
        for style, action in basis_actions:
            dir_mult = 1 if action == 'BUY_CALL' else -1
            decision = {
                'selected_style': style,
                'action': action,
                'confidence': 1.0,
                'reason': 'ATLAS_BASIS_PROBE',
                'entry_price': message['close'],
                'sl': message['close'] - (dir_mult * sl_dist),
                'target': message['close'] + (dir_mult * tgt_dist),
                'metadata': {
                    'is_atlas_probe': True,
                    'atlas_state': enrichment # <--- Required for Atlas logging
                }
            }
            
            trade = self.lifecycle.propose_trade(decision, enrichment, ts)
            self.lifecycle.open_trade(trade)
