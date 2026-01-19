import duckdb
import pandas as pd
import json
import os
import numpy as np

# Database Path
DB_PATH = "/app/data/trading.db"
SESSION_ID = "BACKTEST_20260119_150947"

if not os.path.exists("audits"):
    os.makedirs("audits")

conn = duckdb.connect(DB_PATH)

print(f"🕵️  REMR Counterfactual Audit: {SESSION_ID}")

# 1. Extract Tactical Logs
print("📥 Fetching Tactical Logs...")
logs = conn.execute(f"""
    SELECT timestamp, content 
    FROM simulation_logs 
    WHERE session_id = '{SESSION_ID}' 
    AND event_type = 'TACTICAL'
""").fetchall()

opportunities = []
for ts, content in logs:
    data = json.loads(content)
    # Check if LLM initially wanted REMR (selected_style or in reason)
    # The 'selected_style' from LLM is in the tactical log.
    style = data.get('selected_style', 'NONE')
    action = data.get('action', 'HOLD')
    reason = data.get('reason', '')
    
    # We look for cases where either the style was REMR but action was HOLD,
    # OR the reason specifically mentions a REMR block.
    if style == 'REMR' and action == 'HOLD':
        opportunities.append({
            "timestamp": ts,
            "data": data
        })
    elif "REMR" in reason and "Blocked" in reason:
        opportunities.append({
            "timestamp": ts,
            "data": data
        })

print(f"🎯 Identified {len(opportunities)} blocked REMR opportunities.")

# 2. Analyze Each Opportunity
audit_results = []
audit_count = 0

for opt in opportunities:
    ts = opt['timestamp']
    data = opt['data']
    
    entry_price = data.get('close')
    if not entry_price: continue
    
    # We need to guess the direction. REMR trades usually mean-revert.
    # If price is at resistance, it's a PUT. If at support, a CALL.
    loc = data.get('location_context', {}).get('location', 'MID')
    action = "BUY_PUT" if "RESISTANCE" in loc or "TOP" in loc else "BUY_CALL"
    
    # ATR for geometry
    atr = data.get('atr', 100)
    # REMR Geometry: SL = 0.7 * ATR, TGT = 1.4 * ATR
    # Note: Phase 2.8 and legacy REMR parameters might vary, but 1.4/0.7 is the standard baseline we use in executor.py
    sl_dist = 0.7 * atr
    tgt_dist = 1.4 * atr
    
    if action == "BUY_CALL":
        tgt_price = entry_price + tgt_dist
        sl_price = entry_price - sl_dist
    else:
        tgt_price = entry_price - tgt_dist
        sl_price = entry_price + sl_dist
        
    from datetime import datetime, timedelta
    if isinstance(ts, str):
        # ts format is "2025-12-10 11:45:00" (IST)
        ts_dt = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
    else:
        ts_dt = ts
        
    # Convert IST to UTC (-5.5h)
    ts_utc = ts_dt - timedelta(hours=5, minutes=30)
    ts_str_utc = ts_utc.strftime('%Y-%m-%d %H:%M:%S')
    session_date_utc = ts_utc.strftime('%Y-%m-%d')
    
    # Fetch subsequent candles for the same day (In UTC)
    candles_query = f"""
        SELECT timestamp, high, low, close 
        FROM candles_5min 
        WHERE symbol = 'NSE:NIFTY50-INDEX' 
        AND timestamp > '{ts_str_utc}' 
        AND date(timestamp) = '{session_date_utc}'
        ORDER BY timestamp
    """
    candles = conn.execute(candles_query).df()
    
    if audit_count < 5:
        print(f"   🔍 Signal @ {ts} (IST) | UTC: {ts_str_utc} | Entry: {entry_price} | Candles found: {len(candles)}")
    audit_count += 1
    
    outcome = "EOD"
    pnl = 0
    exit_time = None
    exit_reason = "EOD_CLOSE"
    
    for _, row in candles.iterrows():
        if action == "BUY_CALL":
            if row['high'] >= tgt_price:
                pnl = tgt_dist
                outcome = "TP"
                exit_time = row['timestamp']
                break
            if row['low'] <= sl_price:
                pnl = -sl_dist
                outcome = "SL"
                exit_time = row['timestamp']
                break
        else: # BUY_PUT
            if row['low'] <= tgt_price:
                pnl = tgt_dist
                outcome = "TP"
                exit_time = row['timestamp']
                break
            if row['high'] >= sl_price:
                pnl = -sl_dist
                outcome = "SL"
                exit_time = row['timestamp']
                break
                
    if not exit_time and not candles.empty:
        # EOD Exit
        final_close = candles.iloc[-1]['close']
        pnl = (final_close - entry_price) if action == "BUY_CALL" else (entry_price - final_close)
        exit_time = candles.iloc[-1]['timestamp']
        
    audit_results.append({
        "timestamp": ts,
        "entry_price": entry_price,
        "action": action,
        "outcome": outcome,
        "pnl": pnl,
        "location": loc,
        "reason": data.get('reason', data.get('engine_reason', 'N/A')),
        "wick_ratio": data.get('micro_context', {}).get('last_body_ratio', 'N/A'), # Body ratio is (1 - wick ratio) basically
        "dist_to_level": data.get('location_context', {}).get('distance_to_resistance' if action == 'BUY_PUT' else 'distance_to_support', 0)
    })

# 3. Report
report_df = pd.DataFrame(audit_results)
if not report_df.empty:
    print(f"\n📊 Audit Summary:")
    print(f"Win Rate: {(report_df['outcome'] == 'TP').mean()*100:.1f}%")
    print(f"Total Missed PnL: {report_df['pnl'].sum():.1f} pts")
    print(f"Avg PnL per Signal: {report_df['pnl'].mean():.1f} pts")
    
    # Save to CSV
    report_df.to_csv(f"audits/remr_missed_alpha_{SESSION_ID}.csv", index=False)
    print(f"✅ Audit saved to audits/remr_missed_alpha_{SESSION_ID}.csv")
else:
    print("⚠️ No valid REMR opportunities found to audit.")

conn.close()
