import vectorbt as vbt
import pandas as pd
import numpy as np
import os

# Updated to pull from data directory (MARKET_DATA_DIR was defined in loader as 'market_data')
DATA_FILE = "market_data/NSE_NIFTYBANK_INDEX.parquet"

def run_strategy():
    if not os.path.exists(DATA_FILE):
        print(f"❌ Data file not found: {DATA_FILE}")
        print("Please run `python -m data.loader` first.")
        return

    print(f"Loading data from {DATA_FILE}...")
    df = pd.read_parquet(DATA_FILE)
    close = df['close']

    fast_ma = vbt.MA.run(close, 10, short_name='fast')
    slow_ma = vbt.MA.run(close, 50, short_name='slow')

    entries = fast_ma.ma_crossed_above(slow_ma)
    exits = fast_ma.ma_crossed_below(slow_ma)

    pf = vbt.Portfolio.from_signals(
        close, 
        entries, 
        exits, 
        fees=0.0005, 
        freq='1m'
    )

    print("\n--- Strategy Performance ---")
    print(pf.stats())

def optimize_params():
    if not os.path.exists(DATA_FILE):
        return

    df = pd.read_parquet(DATA_FILE)
    close = df['close']
    
    fast_windows = np.arange(5, 20)
    slow_windows = np.arange(30, 60)
    
    print("\nRunning Parameter Optimization...")
    fast_ma, slow_ma = vbt.MA.run_combs(
        close, [fast_windows, slow_windows], r=2, short_names=['fast', 'slow']
    )
    
    entries = fast_ma.ma_crossed_above(slow_ma)
    exits = fast_ma.ma_crossed_below(slow_ma)
    
    pf = vbt.Portfolio.from_signals(close, entries, exits, fees=0.0005, freq='1m')
    
    print("\nTop 5 Combinations by Total Return:")
    print(pf.total_return().sort_values(ascending=False).head())
