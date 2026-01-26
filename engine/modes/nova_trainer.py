"""
Super Nova Phase 1: Clean Training Engine (Observer Mode)
- Goal: Learn X (Latent State) -> Y (Oracle Outcome)
- Isolated: No trading, no policy, no ledger, no positions.
- Schema: 10-Dimensional Numeric Vector (No Semantics)
- Output: Parquet only (atlas_v2/market_oracle.parquet).
"""
import logging
import os
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from engine.modes.base_mode import BaseMode
from adapters.data_adapter import data_adapter
from brain.llm_client import LLMClient

# Physics Enrichment (Observables)
from enrichment.advanced_momentum import calculate_velocity, calculate_acceleration, calculate_slope
from enrichment.entropy import calculate_price_entropy
from enrichment.trend import calculate_trend_efficiency

logger = logging.getLogger(__name__)

class OracleMeasurement:
    """Tracks a point-in-time observation for a fixed future horizon."""
    def __init__(self, timestamp, entry_price, latent_vector, horizon=30):
        self.timestamp = timestamp
        self.entry_price = entry_price
        self.latent_vector = latent_vector # List of 10 floats
        self.horizon = horizon
        self.bars_seen = 0
        self.high = entry_price
        self.low = entry_price
        self.is_complete = False
        self.outcome = {}

    def update(self, h, l, c):
        self.high = max(self.high, h)
        self.low = min(self.low, l)
        self.bars_seen += 1
        
        if self.bars_seen >= self.horizon:
            # y = What actually happened over next K bars
            res = {
                'timestamp': self.timestamp.isoformat() if hasattr(self.timestamp, 'isoformat') else str(self.timestamp),
                'call_mfe': float(self.high - self.entry_price),
                'call_mae': float(self.entry_price - self.low),
                'put_mfe': float(self.entry_price - self.low),
                'put_mae': float(self.high - self.entry_price),
                'hold_pnl': float(c - self.entry_price)
            }
            # Add latent Dimensions
            for i, val in enumerate(self.latent_vector):
                res[f'latent_{i+1}'] = val
                
            self.outcome = res
            self.is_complete = True

class NovaTrainer(BaseMode):
    def __init__(self, start_date, end_date, symbol="NIFTY", resolution="5", horizon=30, initial_balance=30000, **kwargs):
        self.start_date = start_date
        self.end_date = end_date
        self.symbol = symbol
        self.resolution = resolution
        self.horizon = horizon
        self.initial_balance = initial_balance
        self.running = False
        
        self.brain = LLMClient()
        self.active_measurements = []
        self.dataset = []
        self.rolling_candles = []
        
        self.daily_stats = {} # o, h, l, prev_close
        
        self.output_dir = "atlas_v2"
        os.makedirs(self.output_dir, exist_ok=True)
        self.output_file = os.path.join(self.output_dir, "market_oracle.parquet")

    def start(self):
        logger.info(f"🎓 Starting SUPER NOVA TRAINER: {self.start_date.date()} to {self.end_date.date()}")
        self.running = True
        self._run_loop()

    def stop(self):
        self.running = False
        self._flush_data()

    def on_tick(self, tick):
        # Normalize tick keys
        norm_tick = {
            'timestamp': tick.get('timestamp'),
            'o': float(tick.get('open', tick.get('o', 0))),
            'h': float(tick.get('high', tick.get('h', 0))),
            'l': float(tick.get('low', tick.get('l', 0))),
            'c': float(tick.get('close', tick.get('c', 0))),
            'v': float(tick.get('volume', tick.get('v', 0)))
        }
        
        # Update Daily High/Low
        self.daily_stats['h'] = max(self.daily_stats.get('h', norm_tick['h']), norm_tick['h'])
        self.daily_stats['l'] = min(self.daily_stats.get('l', norm_tick['l']), norm_tick['l'])
        if 'o' not in self.daily_stats: self.daily_stats['o'] = norm_tick['o']
        
        # 1. Update rolling window
        self.rolling_candles.append(norm_tick)
        if len(self.rolling_candles) > 50:
            self.rolling_candles.pop(0)
            
        # 2. Update oracle measurements
        for m in self.active_measurements:
            m.update(norm_tick['h'], norm_tick['l'], norm_tick['c'])
            
        # 3. Collect completed
        completed = [m.outcome for m in self.active_measurements if m.is_complete]
        if completed:
            self.dataset.extend(completed)
            self.active_measurements = [m for m in self.active_measurements if not m.is_complete]

        # 4. Observe every 15 mins (or every tick if testing, but context says 15m is optimal)
        # For training efficiency, we observe on every 15-min boundary if possible, 
        # but since we are in a backtest loop of 5m/1m, we check the clock.
        ts = norm_tick['timestamp']
        if hasattr(ts, 'minute') and ts.minute % 15 == 0:
            if len(self.rolling_candles) >= 14:
                self._observe(norm_tick)

    def _observe(self, tick):
        try:
            # A. OHLC Window (Last 10 bars)
            window = []
            for c in self.rolling_candles[-10:]:
                window.append({
                    'o': c['o'], 'h': c['h'], 'l': c['l'], 'c': c['c'], 'v': c['v']
                })
            
            # B. Daily Context
            prev_close = self.daily_stats.get('prev_close', tick['o'])
            gap_pct = round(((tick['o'] - prev_close) / prev_close) * 100, 2) if prev_close else 0.0
            
            daily_ctx = {
                'day_open': self.daily_stats.get('o'),
                'day_high': self.daily_stats.get('h'),
                'day_low': self.daily_stats.get('l'),
                'prev_close': prev_close,
                'gap_percent': gap_pct
            }
            
            # C. Volatility
            vol_ctx = {
                'vix_spot': 15.0, # Approximate or fetch
                'atr_14': 50.0 # Approximate or fetch
            }
            
            # D. Physics (X)
            vel = calculate_velocity(self.rolling_candles, period=6)
            acc = calculate_acceleration(self.rolling_candles, period=6)
            ent = calculate_price_entropy(self.rolling_candles, period=12)
            ter_data = calculate_trend_efficiency(self.rolling_candles)
            ter = ter_data[0] if isinstance(ter_data, tuple) else 0.0
            slp = calculate_slope([c['c'] for c in self.rolling_candles[-10:]])
            
            phys_ctx = {
                'velocity': vel,
                'acceleration': acc,
                'entropy': ent,
                'trend_efficiency': ter,
                'slope': slp
            }
            
            # E. Assemble Input Camera (Radar)
            full_context = {
                'timestamp': tick['timestamp'].isoformat() if hasattr(tick['timestamp'], 'isoformat') else str(tick['timestamp']),
                'symbol': self.symbol,
                'timeframe': f"{self.resolution}m",
                'ohlc_window': window,
                'daily_context': daily_ctx,
                'volatility': vol_ctx,
                'physics': phys_ctx
            }

            # F. Call LLM Encoder
            response = self.brain.get_market_latent_state(full_context)
            
            if response and 'latent_vector' in response:
                latent_vector = response['latent_vector']
                if len(latent_vector) == 10:
                    # Start new Measurement
                    m = OracleMeasurement(tick['timestamp'], tick['c'], latent_vector, horizon=self.horizon)
                    self.active_measurements.append(m)
                    logger.info(f"🧬 [ENCODER] Latent Vector Recorded (10D) at {tick['timestamp']}")
                else:
                    logger.warning(f"⚠️ [ENCODER] Invalid vector length: {len(latent_vector)}")
            else:
                logger.warning(f"⚠️ [ENCODER] Failed to get latent vector")
                
        except Exception as e:
            logger.error(f"❌ Observation Error: {e}")

    def _run_loop(self):
        current_date = self.start_date
        while current_date <= self.end_date and self.running:
            day_str = current_date.strftime('%Y-%m-%d')
            logger.info(f"🌞 Simulating Day: {day_str} for Data Lake")
            
            # Fetch Prev Close for Gap
            self.daily_stats = {
                'prev_close': data_adapter.fetch_prev_close(current_date, self.symbol)
            }
            
            ticks = data_adapter.fetch_data_for_day(current_date, self.symbol, self.resolution)
            if ticks.empty:
                current_date += timedelta(days=1)
                continue
            
            for _, row in ticks.iterrows():
                if not self.running: break
                msg = row.to_dict()
                self.on_tick(msg)
            
            # EOD Flush
            self._flush_data()
            current_date += timedelta(days=1)

    def _flush_data(self):
        if not self.dataset: return
        
        df_new = pd.DataFrame(self.dataset)
        
        # Merge if exists
        if os.path.exists(self.output_file):
            try:
                df_old = pd.read_parquet(self.output_file)
                df_final = pd.concat([df_old, df_new]).drop_duplicates(subset=['timestamp'])
            except:
                df_final = df_new
        else:
            df_final = df_new
            
        df_final.to_parquet(self.output_file)
        logger.info(f"💾 [DATA LAKE] Flushed {len(df_new)} samples to {self.output_file}. Total Size: {len(df_final)}")
        self.dataset = []
