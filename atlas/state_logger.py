"""
Project Atlas: State Logger
Purpose:
Persist the "Market State Vector" at every tick (or decision point).
This data becomes the 'X' (Features) for the Atlas Machine Learning system.
Target: atlas/data/states_YYYYMMDD.csv

Schema:
- Timestamp, Symbol, Price
- Trend Geometry (TER, Regime, Slope)
- Volatility (ATR, VIX, OR_Range, VolRatio)
- Entropy (Price, Volume)
- Momentum (Velocity, Acceleration, Skew)
- Location (Dist_OR_High, Dist_OR_Low, LocationClass)
- Trade (Action, Style) - if any
"""

import os
import pandas as pd
from datetime import datetime
from typing import Dict, Any, List

class AtlasStateLogger:
    def __init__(self, output_dir="atlas/data"):
        self.output_dir = output_dir
        self.buffer: List[Dict] = []
        self.buffer_limit = 200 # Flush every 200 ticks (approx 1 per day in Learn Mode)
        self.current_date = None
        
        # Ensure dir exists
        os.makedirs(self.output_dir, exist_ok=True)
        
    def log_probe_outcome(self, trade):
        """
        Event-Driven Log: Called when a Probe Trade CLOSES.
        Combines Entry State (Frozen) + Exit Outcome (Reality).
        """
        try:
            enrichment = trade.metadata.get('atlas_state', {})
            timestamp_str = trade.entry_time.strftime('%Y-%m-%d %H:%M:%S')
            
            # Extract Date for file partitioning
            try:
                dt = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                date_str = dt.strftime('%Y%m%d')
            except:
                date_str = datetime.now().strftime('%Y%m%d')

            # Build Row
            row = self._extract_features(enrichment, trade, timestamp_str)
            self.buffer.append(row)
            
            # Flush Check
            if len(self.buffer) >= self.buffer_limit or date_str != self.current_date:
                self.flush(date_str)
                self.current_date = date_str
            
        except Exception as e:
            print(f"ATLAS LOG ERROR: {e}")

    def flush(self, date_str=None):
        """
        Write buffer to Parquet.
        """
        if not self.buffer: return
        
        if not date_str:
            date_str = self.current_date if self.current_date else datetime.now().strftime('%Y%m%d')
            
        filename = os.path.join(self.output_dir, f"states_{date_str}.parquet")
        
        new_df = pd.DataFrame(self.buffer)
        
        try:
            if os.path.exists(filename):
                existing_df = pd.read_parquet(filename)
                combined_df = pd.concat([existing_df, new_df], ignore_index=True)
                combined_df.to_parquet(filename)
            else:
                new_df.to_parquet(filename)
                
            print(f"[Atlas] 💾 Flushed {len(self.buffer)} logs to {filename}")
            self.buffer = [] # Clear buffer
            
        except Exception as e:
            print(f"❌ Parquet Write Error: {e}")

    def _safe_float(self, val, round_digits=4):
        try:
            if val is None: return 0.0
            return round(float(val), round_digits)
        except:
            return 0.0

    def _extract_features(self, enrich, trade, ts):
        """Map enrichment + Trade Outcome to Flat Row"""
        return {
            "timestamp": ts,
            "symbol": trade.symbol,
            "price": self._safe_float(enrich.get('price')),
            
            # 1. Trend
            "ter": self._safe_float(enrich.get('trend_efficiency')),
            "regime": enrich.get('trend_regime', 'ROTATION'),
            "mom_slope": self._safe_float(enrich.get('momentum_slope')),
            
            # 2. Volatility
            "atr": self._safe_float(enrich.get('atr')),
            "vix": self._safe_float(enrich.get('vix')),
            "or_range": self._safe_float(enrich.get('or_range')),
            "vol_ratio": self._safe_float(enrich.get('vol_ratio')),
            
            # 3. Entropy
            "entropy_price": self._safe_float(enrich.get('entropy_price')),
            "entropy_vol": self._safe_float(enrich.get('entropy_volume')),
            
            # 4. Adv Momentum
            "velocity": self._safe_float(enrich.get('velocity')),
            "accel": self._safe_float(enrich.get('acceleration')),
            "skew": self._safe_float(enrich.get('skew')),
            
            # 5. Location
            "loc_class": enrich.get('location_class', 'MID'),
            "dist_or_h": self._safe_float(enrich.get('dist_or_high')),
            "dist_or_l": self._safe_float(enrich.get('dist_or_low')),
            
            # 6. Action & Outcome
            "action": f"BUY_{trade.direction}", # BUY_CALL / BUY_PUT
            "style": trade.style,
            
            "pnl_points": self._safe_float(trade.pnl_points),
            "mae": self._safe_float(trade.mae),
            "mfe": self._safe_float(trade.mfe),
            "bars_held": trade.bars_held
        }

# Global Instance
atlas_logger = AtlasStateLogger()
