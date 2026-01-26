import sqlite3
import pandas as pd
import os
from tabulate import tabulate

DB_PATH = "data/trading.db"

def get_connection():
    if not os.path.exists(DB_PATH):
        # Try Docker path
        if os.path.exists("/app/data/trading.db"):
            return sqlite3.connect("/app/data/trading.db")
    return sqlite3.connect(DB_PATH)

def analyze_sessions(limit=2):
    conn = get_connection()
    
    # Get last N sessions
    query_sessions = """
        SELECT DISTINCT session_id 
        FROM trades 
        ORDER BY created_at DESC 
        LIMIT ?
    """
    try:
        sessions = [r[0] for r in conn.execute(query_sessions, (limit,)).fetchall()]
    except Exception as e:
        print(f"Error fetching sessions: {e}")
        return

    if not sessions:
        print("No sessions found in trades table.")
        return

    results = []
    
    for sess in sessions:
        df = pd.read_sql_query("SELECT * FROM trades WHERE session_id = ?", conn, params=(sess,))
        
        if df.empty:
            continue
            
        # Metrics
        total_trades = len(df)
        wins = len(df[df['pnl_points'] > 0])
        total_pnl = df['pnl_points'].sum()
        
        # Max DD
        df['equity'] = df['pnl_points'].cumsum()
        df['peak'] = df['equity'].cummax()
        df['dd'] = df['peak'] - df['equity']
        max_dd = df['dd'].max()
        
        # Time in Market (Bars Held)
        avg_bars = df['bars_held'].mean()
        
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
        
        # Determine Variant (Heuristic based on chronology)
        # We assume the user runs them sequentially.
        
        results.append({
            "Session ID": sess,
            "Trades": total_trades,
            "PnL (pts)": round(total_pnl, 2),
            "Win Rate": f"{win_rate:.1f}%",
            "Max DD": round(max_dd, 2),
            "Avg Bars": round(avg_bars, 1)
        })
        
    print("\n=== Paired Comparison (Latest Sessions) ===")
    for r in results:
        print(f"Session: {r['Session ID']}")
        print(f"  Trades: {r['Trades']}")
        print(f"  PnL:    {r['PnL (pts)']}")
        print(f"  MaxDD:  {r['Max DD']}")
        print(f"  WinRate:{r['Win Rate']}")
        print("-" * 30)
        
    if len(results) >= 2:
        # results[0] is latest (B), results[1] is previous (A)
        sess_b = results[0]
        sess_a = results[1]
        
        print("\n=== DELTA (Variant B - Variant A) ===")
        print(f"Trades Diff:   {sess_b['Trades'] - sess_a['Trades']:+d}")
        print(f"PnL Diff:      {sess_b['PnL (pts)'] - sess_a['PnL (pts)']:+.2f} pts")
        print(f"Max DD Diff:   {sess_b['Max DD'] - sess_a['Max DD']:+.2f} pts")
        
        wr_b = float(sess_b['Win Rate'].strip('%'))
        wr_a = float(sess_a['Win Rate'].strip('%'))
        print(f"Win Rate Diff: {wr_b - wr_a:+.1f}%")
        print("=====================================")

if __name__ == "__main__":
    analyze_sessions()
