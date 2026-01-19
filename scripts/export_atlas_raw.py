import duckdb
import pandas as pd
import os

DB_PATH = '/app/data/trading.db'
EXPORT_DIR = '/app/atlas_raw'

if not os.path.exists(EXPORT_DIR):
    os.makedirs(EXPORT_DIR)

conn = duckdb.connect(DB_PATH)

print("🚀 Exporting NIFTY 5-min candles...")
nifty_df = conn.execute("SELECT timestamp, open, high, low, close, volume FROM candles_5min WHERE symbol = 'NSE:NIFTY50-INDEX' ORDER BY timestamp").df()
nifty_df.to_csv(os.path.join(EXPORT_DIR, 'nifty_5min_raw.csv'), index=False)
print(f"✅ Exported {len(nifty_df)} NIFTY candles.")

print("🚀 Exporting VIX data...")
vix_df = conn.execute("SELECT timestamp, close as vix FROM candles_vix ORDER BY timestamp").df()
vix_df.to_csv(os.path.join(EXPORT_DIR, 'vix_raw.csv'), index=False)
print(f"✅ Exported {len(vix_df)} VIX data points.")

conn.close()
