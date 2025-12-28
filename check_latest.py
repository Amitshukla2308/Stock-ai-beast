import duckdb

DB_PATH = "data/trading.db"
conn = duckdb.connect(DB_PATH)
try:
    # Get latest session
    latest_session = conn.execute("SELECT session_id FROM simulation_sessions ORDER BY created_at DESC LIMIT 1").fetchone()
    if latest_session:
        session_id = latest_session[0]
        print(f"Latest Session: {session_id}\n")
        
        # Get trades from this session
        query = """
            SELECT entry_time, exit_time, pnl, max_pnl, mean_open_pnl, reason
            FROM simulation_trades 
            WHERE session_id = ?
            ORDER BY entry_time ASC 
            LIMIT 3
        """
        trades = conn.execute(query, (session_id,)).fetchall()
        
        for i, (entry, exit, pnl, max_pnl, mean_pnl, reason) in enumerate(trades, 1):
            print(f"Trade #{i}:")
            print(f"  Entry: {entry}")
            print(f"  Exit: {exit}")
            print(f"  PnL: {pnl:.1f}")
            print(f"  Max PnL: {max_pnl:.1f}")
            print(f"  Mean PnL: {mean_pnl:.1f}")
            print(f"  Reason: {reason}")
            print()
    else:
        print("No sessions found")
except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
