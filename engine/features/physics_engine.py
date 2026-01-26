"""
v4.0 PhysicsEngine: Geometric Anchors
Calculates VWAP, Pivots, and Daily Open for higher-dimension features.
"""
import pandas as pd
import numpy as np

class PhysicsEngine:
    @staticmethod
    def add_context(df: pd.DataFrame) -> pd.DataFrame:
        """
        Enhances DataFrame with required geometric context.
        Matches generate_64d_dataset.py logic exactly.
        """
        if df.empty: return df
        df = df.copy()
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['date'] = df['timestamp'].dt.date
        
        # 1. Daily Open
        df['daily_open'] = df.groupby('date')['open'].transform('first')
        
        # 2. VWAP (Daily)
        vol_safe = df['volume'].replace(0, 1.0)
        df['pv'] = df['close'] * vol_safe
        g = df.groupby('date')
        df['vwap'] = g['pv'].cumsum() / vol_safe.groupby(df['date']).cumsum()
        df['vwap'] = df['vwap'].fillna(df['close'])
        
        # 3. Pivot (Daily) - Use Prev Day HL C
        daily_stats = df.groupby('date').agg({'high':'max', 'low':'min', 'close':'last'})
        daily_stats['pivot_val'] = (daily_stats['high'] + daily_stats['low'] + daily_stats['close']) / 3
        daily_stats['pivot_prev'] = daily_stats['pivot_val'].shift(1)
        
        df = df.merge(daily_stats[['pivot_prev']], left_on='date', right_index=True, how='left')
        df = df.rename(columns={'pivot_prev': 'pivot'})
        df['pivot'] = df['pivot'].fillna(df['close'])
        
        return df
