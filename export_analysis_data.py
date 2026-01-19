import duckdb
import pandas as pd
import json
import os

# Database Path
DB_PATH = "/app/data/trading.db"
EXPORT_DIR = "backtest_exports"

if not os.path.exists(EXPORT_DIR):
    os.makedirs(EXPORT_DIR)

# Sessions to Export
SESSIONS = [
    'BACKTEST_20260119_055050', # Sniper 
    'BACKTEST_20260118_214047', # High-Freq
    'BACKTEST_20260116_052512'  # Baseline
]

conn = duckdb.connect(DB_PATH)

print(f"📦 Starting Raw Data Export to '{EXPORT_DIR}'...")

# 1. Export Trade Details
print("📝 Exporting Trade Details...")
trades_sql = f"""
    SELECT * 
    FROM simulation_trades 
    WHERE session_id IN ({','.join([f"'{s}'" for s in SESSIONS])})
"""
trades_df = conn.execute(trades_sql).df()
trades_df.to_csv(f"{EXPORT_DIR}/raw_trades_comparison.csv", index=False)

# 2. Export Tactical Logs (Opportunities / Skips)
print("📊 Exporting Tactical Logs (Skips/Reasons)...")
logs_sql = f"""
    SELECT session_id, timestamp, content 
    FROM simulation_logs 
    WHERE event_type = 'TACTICAL' 
    AND session_id IN ({','.join([f"'{s}'" for s in SESSIONS])})
"""
logs = conn.execute(logs_sql).fetchall()

flattened_logs = []
for session_id, ts, content in logs:
    try:
        data = json.loads(content)
        # Extract relevant fields for inspection
        flattened_logs.append({
            "session_id": session_id,
            "timestamp": ts,
            "action": data.get("action"),
            "engine_decision": data.get("engine_decision"),
            "reason": data.get("engine_reason") or data.get("reason"),
            "confidence": data.get("confidence"),
            "close": data.get("close"),
            "selected_style": data.get("selected_style"),
            "regime": data.get("active_regime")
        })
    except:
        continue

logs_df = pd.DataFrame(flattened_logs)
logs_df.to_csv(f"{EXPORT_DIR}/raw_opportunity_logs.csv", index=False)

# 3. Export Market Benchmark (NIFTY 2025)
print("📈 Exporting Market Benchmark (NIFTY)...")
nifty_sql = """
    SELECT timestamp, close 
    FROM candles_5min 
    WHERE symbol = 'NSE:NIFTY50-INDEX' 
    AND timestamp BETWEEN '2025-01-01' AND '2025-12-31' 
    ORDER BY timestamp
"""
nifty_df = conn.execute(nifty_sql).df()
nifty_df.to_csv(f"{EXPORT_DIR}/nifty_benchmark_2025.csv", index=False)

print(f"✅ Export Complete! Files available in '{EXPORT_DIR}/':")
print(f"   - raw_trades_comparison.csv")
print(f"   - raw_opportunity_logs.csv")
print(f"   - nifty_benchmark_2025.csv")

conn.close()
