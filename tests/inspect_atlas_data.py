import pandas as pd
import sys
import os

df_path = 'atlas/data/states_20260121.parquet'
if not os.path.exists(df_path):
    print(f"Error: {df_path} not found")
    sys.exit(1)

df = pd.read_parquet(df_path)

print("--- ATLAS DATA VERIFICATION ---")
print(f"Total Rows: {len(df)}")
print(f"Total Columns: {len(df.columns)}")
print(f"Unique Timestamps: {df['timestamp'].nunique()}")
print(f"Average Probes per Tick: {len(df)/df['timestamp'].nunique():.2f}")

print("\n--- CAPTURED FEATURES (FULL LIST) ---")
print(df.columns.tolist())

print("\n--- SAMPLE VIEW (Rounded PnL) ---")
cols = ['timestamp', 'price', 'style', 'direction', 'pnl_points', 'mfe', 'mae']
available_cols = [c for c in cols if c in df.columns]
print(df[available_cols].tail(8))

print("\n--- METRICS VALIDATION ---")
metrics = ['entropy_price', 'velocity', 'skew', 'ter', 'atr', 'vix']
for m in metrics:
    if m in df.columns:
        zeros = (df[m] == 0).sum()
        pct_zeros = (zeros / len(df)) * 100
        print(f"{m:15}: Avg={df[m].mean():.4f}, Zeros={zeros} ({pct_zeros:.1f}%)")

print("\n--- PnL ROUNDING CHECK ---")
if 'pnl_points' in df.columns:
    print(f"EOD Sample PnL: {df['pnl_points'].tail(4).tolist()}")
