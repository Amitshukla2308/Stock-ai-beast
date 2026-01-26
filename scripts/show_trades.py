import sqlite3
import os

def show_recent_trades():
    db_path = "data/trading.db"
    if not os.path.exists(db_path):
        print(f"❌ Database not found at {db_path}")
        return
        
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        query = "SELECT trade_id, entry_time, style, direction, pnl_points FROM trades ORDER BY created_at DESC LIMIT 5;"
        rows = conn.execute(query).fetchall()
        
        if not rows:
            print("📭 No trades found in the database.")
            return
            
        print("\n" + "="*80)
        print("🚀 RECENT TRADES (LAST 5)")
        print("="*80)
        
        for r in rows:
            print(f"[{r['entry_time']}] {r['trade_id']} | {r['style']} | {r['direction']} | PnL: {r['pnl_points']:+.1f}")
            print("-" * 80)
            
    except Exception as e:
        print(f"❌ Error fetching trades: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    show_recent_trades()
