import duckdb
import pandas as pd
import json
import os
import numpy as np

# Database Path
DB_PATH = "/app/data/trading.db"
EXPORT_DIR = "comprehensive_exports"

if not os.path.exists(EXPORT_DIR):
    os.makedirs(EXPORT_DIR)

conn = duckdb.connect(DB_PATH)

# 1. Get Latest Session
latest_session = conn.execute("SELECT session_id, start_date, end_date FROM simulation_sessions ORDER BY created_at DESC LIMIT 1").fetchone()
if not latest_session:
    print("❌ No sessions found in database.")
    exit()

session_id, start_date, end_date = latest_session
print(f"📦 Exporting Latest Session: {session_id} ({start_date} to {end_date})")

# 2. Export Trade Details
print("📝 Exporting Trade Details...")
trades_df = conn.execute(f"SELECT * FROM simulation_trades WHERE session_id = '{session_id}'").df()
trades_df.to_csv(f"{EXPORT_DIR}/latest_trades_{session_id}.csv", index=False)

# 3. Export Tactical Logs (Decision Audit Trail)
print("📊 Exporting Tactical Logs (Full Metrics)...")
logs = conn.execute(f"SELECT timestamp, content FROM simulation_logs WHERE session_id = '{session_id}' AND event_type = 'TACTICAL'").fetchall()

flattened_logs = []
for ts, content in logs:
    try:
        data = json.loads(content)
        # Flatten the record
        record = {
            "timestamp": ts,
            "session_id": session_id,
            "current_time_str": data.get("current_time_str"),
            "action": data.get("action"),
            "sentiment": data.get("sentiment"),
            "confidence": data.get("confidence"),
            "close": data.get("close"),
            "style": data.get("selected_style"),
            "engine_decision": data.get("engine_decision"),
            "engine_reason": data.get("engine_reason") or data.get("reason"),
        }
        
        # Add micro_context metrics if available
        mc = data.get("micro_context", {})
        if mc:
            record.update({
                "regime": mc.get("active_regime"),
                "ter": mc.get("trend_efficiency"),
                "net_progress_3": mc.get("net_progress_3"),
                "momentum_slope": mc.get("momentum_slope"),
                "retracement_depth": mc.get("retracement_depth"),
                "velocity_increasing": mc.get("velocity_increasing"),
                "regime_momentum": mc.get("regime_momentum"),
                "v_reversal": mc.get("v_reversal")
            })
            
        flattened_logs.append(record)
    except Exception as e:
        continue

logs_df = pd.DataFrame(flattened_logs)
logs_df.to_csv(f"{EXPORT_DIR}/latest_tactical_audit_{session_id}.csv", index=False)

# 4. Market Benchmark (NIFTY 5-min)
print("📈 Exporting Market Benchmark (NIFTY)...")
nifty_df = conn.execute(f"""
    SELECT timestamp, open, high, low, close 
    FROM candles_5min 
    WHERE symbol = 'NSE:NIFTY50-INDEX' 
    AND timestamp BETWEEN '{start_date}' AND '{end_date}' 
    ORDER BY timestamp
""").df()
nifty_df.to_csv(f"{EXPORT_DIR}/nifty_benchmark.csv", index=False)

# 5. Summary Metrics (Sharpe, PF, etc.)
def calculate_metrics(df):
    if df.empty: return {}
    wins = df[df['pnl'] > 0]
    losses = df[df['pnl'] <= 0]
    
    total_pnl = df['pnl'].sum()
    win_rate = len(wins) / len(df) * 100 if len(df) > 0 else 0
    gross_profit = wins['pnl'].sum()
    gross_loss = abs(losses['pnl'].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    returns = df['pnl']
    daily_returns = returns.groupby(df['timestamp'].dt.date).sum()
    sharpe = (daily_returns.mean() / daily_returns.std() * np.sqrt(252)) if daily_returns.std() > 0 else 0
    
    return {
        "Total_PnL": round(total_pnl, 2),
        "Trade_Count": len(df),
        "Win_Rate_%": round(win_rate, 2),
        "Profit_Factor": round(profit_factor, 2),
        "Sharpe_Ratio": round(sharpe, 2)
    }

def convert_to_serializable(obj):
    if isinstance(obj, dict):
        return {k: convert_to_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_to_serializable(i) for i in obj]
    elif isinstance(obj, (np.float32, np.float64, float)):
        return round(float(obj), 2)
    elif isinstance(obj, (np.int32, np.int64, int)):
        return int(obj)
    return obj

summary = calculate_metrics(trades_df)
outputs = convert_to_serializable(summary)
summary_path = f"{EXPORT_DIR}/session_summary_{session_id}.json"
with open(summary_path, 'w') as f:
    json.dump(outputs, f, indent=4)

print(f"✅ Export Complete! Files available in '{EXPORT_DIR}/':")
print(f"   - latest_trades_{session_id}.csv")
print(f"   - latest_tactical_audit_{session_id}.csv")
print(f"   - nifty_benchmark.csv")
print(f"   - session_summary_{session_id}.json")

conn.close()
