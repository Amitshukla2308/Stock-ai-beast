import duckdb
import json

DB_PATH = "data/trading.db"
conn = duckdb.connect(DB_PATH)
try:
    # Get latest session first
    latest_session = conn.execute("SELECT session_id FROM simulation_sessions ORDER BY created_at DESC LIMIT 1").fetchone()
    if not latest_session:
        print("No sessions found!")
        conn.close()
        exit()
        
    session_id = latest_session[0]
    print("="*80)
    print(f"LAST BACKTEST RESULTS - {session_id}")
    print("="*80)
    
    query = f"""
        SELECT entry_time, exit_time, side, entry_price, exit_price, pnl, max_pnl, mean_open_pnl, reason
        FROM simulation_trades 
        WHERE session_id = '{session_id}'
        ORDER BY entry_time ASC 
        LIMIT 20
    """
    res = conn.execute(query).fetchall()
    
    for i, r in enumerate(res, 1):
        entry_time, exit_time, side, entry, exit, pnl, max_pnl, mean_pnl, reason = r
        greed_gap = max_pnl - pnl
        
        print(f"\nTrade #{i}: {side}")
        print(f"  Entry: {entry_time} @ {entry:.1f}")
        print(f"  Exit:  {exit_time} @ {exit:.1f}")
        print(f"  PnL:   {pnl:+.1f} pts")
        print(f"  Peak:  {max_pnl:+.1f} pts (Max profit reached)")
        print(f"  Mean:  {mean_pnl:+.1f} pts (Avg when green)")
        print(f"  Gap:   {greed_gap:.1f} pts (Profit left on table)")
        print(f"  Exit:  {reason}")
        
        # Analysis
        if pnl < 0:
            if max_pnl > 0:
                print(f"  ⚠️  ANALYSIS: Trade was up {max_pnl:.1f} pts but turned into a loss!")
            else:
                print(f"  ⚠️  ANALYSIS: Never got into profit. Immediate reversal.")
        elif pnl > 0 and greed_gap > pnl:
            print(f"  ⚠️  ANALYSIS: Left {greed_gap:.1f} pts on table (more than final profit!)")
            
except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
