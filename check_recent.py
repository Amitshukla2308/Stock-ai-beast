import duckdb

DB_PATH = "data/trading.db"
conn = duckdb.connect(DB_PATH)
try:
    # Get latest 3 sessions
    sessions = conn.execute("""
        SELECT session_id, created_at 
        FROM simulation_sessions 
        ORDER BY created_at DESC 
        LIMIT 3
    """).fetchall()
    
    print("Recent Sessions:")
    for sid, ts in sessions:
        query = """
            SELECT 
                COUNT(*) as total,
                SUM(pnl) as total_pnl
            FROM simulation_trades 
            WHERE session_id = ?
        """
        result = conn.execute(query, (sid,)).fetchone()
        total, pnl = result
        print(f"\n{sid}")
        print(f"  Created: {ts}")
        print(f"  Trades: {total}")
        print(f"  Total PnL: {pnl:+.1f} pts")
        
except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
