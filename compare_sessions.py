import duckdb

DB_PATH = "data/trading.db"
conn = duckdb.connect(DB_PATH)
try:
    # Original session (no trailing SL)
    original_session = "BACKTEST_20251228_040232"
    
    # Latest session (with 30% breakeven)
    current_session = "BACKTEST_20251228_044146"
    
    for session_id, label in [(original_session, "ORIGINAL (No Trailing SL)"), 
                               (current_session, "CURRENT (30% Breakeven)")]:
        print(f"\n{'='*60}")
        print(f"{label}")
        print(f"Session: {session_id}")
        print(f"{'='*60}")
        
        query = """
            SELECT 
                COUNT(*) as total_trades,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losses,
                SUM(CASE WHEN pnl = 0 THEN 1 ELSE 0 END) as breakevens,
                SUM(pnl) as total_pnl,
                AVG(pnl) as avg_pnl,
                MAX(pnl) as best_trade,
                MIN(pnl) as worst_trade,
                AVG(max_pnl) as avg_peak,
                SUM(max_pnl - pnl) as total_greed_gap
            FROM simulation_trades 
            WHERE session_id = ?
        """
        
        result = conn.execute(query, (session_id,)).fetchone()
        
        if result:
            total, wins, losses, breakevens, total_pnl, avg_pnl, best, worst, avg_peak, greed_gap = result
            
            print(f"Total Trades: {total}")
            print(f"Wins: {wins} | Losses: {losses} | Breakevens: {breakevens}")
            print(f"Win Rate: {(wins/total*100):.1f}%")
            print(f"\n💰 PROFITABILITY:")
            print(f"  Total PnL: {total_pnl:+.1f} pts")
            print(f"  Avg PnL/Trade: {avg_pnl:+.1f} pts")
            print(f"  Best Trade: {best:+.1f} pts")
            print(f"  Worst Trade: {worst:+.1f} pts")
            print(f"\n📊 FIDELITY:")
            print(f"  Avg Peak Profit: {avg_peak:+.1f} pts")
            print(f"  Total Greed Gap: {greed_gap:.1f} pts (left on table)")
            print(f"  Greed Gap per Trade: {greed_gap/total:.1f} pts")
        else:
            print("No data found")
    
    print(f"\n{'='*60}")
    print("COMPARISON")
    print(f"{'='*60}")
    
except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
