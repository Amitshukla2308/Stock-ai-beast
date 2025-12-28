import duckdb
import os

DB_PATH = "data/trading.db"
conn = duckdb.connect(DB_PATH)
try:
    print("--- Latest Trades with Fidelity Metrics ---")
    query = "SELECT session_id, side, pnl, max_pnl, mean_open_pnl FROM simulation_trades WHERE max_pnl IS NOT NULL ORDER BY timestamp DESC LIMIT 5"
    res = conn.execute(query).fetchall()
    for r in res:
        print(r)
except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
