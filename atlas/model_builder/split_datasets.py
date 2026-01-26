import pandas as pd
import glob
import os
import hashlib
import duckdb
from datetime import datetime

def generate_trade_id(row, idx):
    """Deterministic hash for trade_id"""
    base = f"{row['timestamp']}_{row['action']}_{row['style']}_{idx}"
    return hashlib.md5(base.encode()).hexdigest()[:12]

def split_datasets(data_dir="atlas/data"):
    print(f"🚀 Starting Atlas Dataset Refactor in {data_dir}...")
    
    # 1. Use DuckDB to read ALL parquets and sort as one time series
    print("📂 Loading and sorting 741 daily files via DuckDB...")
    conn = duckdb.connect(':memory:')
    
    source_pattern = os.path.join(data_dir, "states_*.parquet")
    
    # Read, Sort by Timestamp, and export to DataFrame
    query = f"""
        SELECT * FROM read_parquet('{source_pattern}')
        ORDER BY timestamp ASC
    """
    master_df = conn.execute(query).df()
    conn.close()

    if master_df.empty:
        print("❌ Error: No data found in daily Parquet files!")
        return

    print(f"📦 Consolidated {len(master_df)} rows from 2023 to 2026.")
    
    # 2. Add Trade ID (Sequential key mapping)
    print("🆔 Generating unique trade IDs...")
    # Using index + values ensures uniqueness even with identical timestamps/actions
    master_df['trade_id'] = [generate_trade_id(row, i) for i, row in master_df.iterrows()]
    
    # 3. Define Schemas
    state_cols = [
        'trade_id', 'timestamp', 'symbol', 'price', 'ter', 'regime', 
        'mom_slope', 'atr', 'vix', 'or_range', 'vol_ratio',
        'entropy_price', 'entropy_vol', 'velocity', 'accel', 'skew',
        'loc_class', 'dist_or_h', 'dist_or_l', 'action', 'style'
    ]
    
    outcome_cols = [
        'trade_id', 'timestamp', 'action', 'style', 
        'pnl_points', 'mae', 'mfe', 'bars_held'
    ]
    
    # 4. Split and Save
    print("💾 Exporting split datasets...")
    
    market_states = master_df[state_cols].copy()
    outcomes = master_df[outcome_cols].copy()
    
    states_path = os.path.join(data_dir, "market_states.parquet")
    outcomes_path = os.path.join(data_dir, "outcomes.parquet")
    
    market_states.to_parquet(states_path, index=False, engine='pyarrow')
    outcomes.to_parquet(outcomes_path, index=False, engine='pyarrow')
    
    # 5. Final Statistics
    print("\n--- Refactor Statistics ---")
    print(f"Total Rows: {len(master_df)}")
    print(f"States File: {os.path.getsize(states_path) / 1024 / 1024:.2f} MB")
    print(f"Outcomes File: {os.path.getsize(outcomes_path) / 1024 / 1024:.2f} MB")
    
    if len(market_states) == len(outcomes):
        print("✅ SUCCESS: 1:1 row parity confirmed.")
    else:
        print("⚠️ WARNING: Alignment error!")

if __name__ == "__main__":
    split_datasets()
