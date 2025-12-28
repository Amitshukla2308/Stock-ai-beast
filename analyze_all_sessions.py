import duckdb

DB_PATH = "data/trading.db"
conn = duckdb.connect(DB_PATH)
try:
    # Get all sessions that match April 8th backtests
    query = """
        SELECT 
            s.session_id,
            s.created_at,
            COUNT(t.pnl) as total_trades,
            SUM(t.pnl) as total_pnl,
            SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN t.pnl < 0 THEN 1 ELSE 0 END) as losses,
            SUM(CASE WHEN t.pnl = 0 THEN 1 ELSE 0 END) as breakevens,
            AVG(t.pnl) as avg_pnl,
            MAX(t.pnl) as best_trade,
            MIN(t.pnl) as worst_trade
        FROM simulation_sessions s
        LEFT JOIN simulation_trades t ON s.session_id = t.session_id
        WHERE s.session_id LIKE 'BACKTEST_20251228%'
        GROUP BY s.session_id, s.created_at
        ORDER BY total_pnl DESC
    """
    
    results = conn.execute(query).fetchall()
    
    print("="*100)
    print("ALL APRIL 8TH BACKTEST SESSIONS (Sorted by Total PnL)")
    print("="*100)
    print(f"{'Session ID':<30} {'Created':<20} {'Trades':<8} {'Total PnL':<12} {'W/L/BE':<12} {'Avg':<10}")
    print("-"*100)
    
    for row in results:
        session_id, created, trades, total_pnl, wins, losses, be, avg_pnl, best, worst = row
        if total_pnl is None:
            continue
        wlbe = f"{wins or 0}/{losses or 0}/{be or 0}"
        print(f"{session_id:<30} {str(created)[:19]:<20} {trades or 0:<8} {total_pnl:>+11.1f}pts {wlbe:<12} {avg_pnl or 0:>+9.1f}")
    
    print("-"*100)
    
    # Show top 3 in detail
    print("\n" + "="*100)
    print("TOP 3 SESSIONS - DETAILED VIEW")
    print("="*100)
    
    for i, row in enumerate(results[:3], 1):
        session_id, created, trades, total_pnl, wins, losses, be, avg_pnl, best, worst = row
        
        print(f"\n#{i} - {session_id}")
        print(f"  Total PnL: {total_pnl:+.1f} pts")
        print(f"  Win Rate: {wins/trades*100:.1f}% ({wins}W/{losses}L/{be}BE)")
        print(f"  Avg PnL/Trade: {avg_pnl:+.1f} pts")
        print(f"  Best Trade: {best:+.1f} pts | Worst: {worst:+.1f} pts")
        
        # Show first 5 trades from this session
        trades_query = """
            SELECT entry_time, pnl, max_pnl, reason
            FROM simulation_trades
            WHERE session_id = ?
            ORDER BY entry_time
            LIMIT 5
        """
        sample_trades = conn.execute(trades_query, (session_id,)).fetchall()
        print(f"  Sample Trades:")
        for entry, pnl, max_pnl, reason in sample_trades:
            print(f"    {entry} | PnL:{pnl:+6.1f} | Peak:{max_pnl or 0:+6.1f} | {reason}")
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
finally:
    conn.close()
