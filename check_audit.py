import duckdb
import json

DB_PATH = "data/trading.db"
conn = duckdb.connect(DB_PATH)
try:
    print("--- Session-specific EOD Audits ---")
    session_id = "BACKTEST_20251228_040232"
    query = "SELECT timestamp, content FROM simulation_logs WHERE session_id = ? AND event_type = 'EOD_AUDIT' ORDER BY timestamp DESC"
    res = conn.execute(query, (session_id,)).fetchall()
    
    for ts, content in res:
        print(f"\n[{ts}] Content:")
        try:
            data = json.loads(content)
            print(json.dumps(data, indent=2))
        except:
            print(content)
            
except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
