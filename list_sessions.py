import duckdb
import json
import os

db_path = "/app/data/trading.db"
conn = duckdb.connect(db_path)

print("Listing Major Backtest Sessions:")
sessions = conn.execute("""
    SELECT 
        session_id, 
        count(*) as trade_count, 
        min(entry_time) as start_date, 
        max(exit_time) as end_date,
        sum(pnl) as total_pnl
    FROM simulation_trades 
    GROUP BY session_id 
    HAVING trade_count > 10
    ORDER BY trade_count DESC
""").fetchall()

for s in sessions:
    print(f"Session: {s[0]} | Trades: {s[1]} | Span: {s[2]} to {s[3]} | PnL: {s[4]:.2f}")

conn.close()
