import sys
import os
from datetime import datetime
import pandas as pd

sys.path.append(os.getcwd())

from engine.modes.backtest import BacktestMode
from data.database import get_connection

def main():
    print("🛠️ Checking Schema...")
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(trades)")
        columns = [info[1] for info in cursor.fetchall()]
        if "pnl_edge_death" not in columns:
            print("   ➕ Adding pnl_edge_death column...")
            cursor.execute("ALTER TABLE trades ADD COLUMN pnl_edge_death REAL")
        if "etd" not in columns:
            print("   ➕ Adding etd column...")
            cursor.execute("ALTER TABLE trades ADD COLUMN etd REAL")
        conn.commit()
        print("✅ Schema Verified.")
    finally:
        conn.close()

    print("🧪 Starting Backtest...")
    backtest = BacktestMode(
        start_date=datetime(2026, 1, 8),
        end_date=datetime(2026, 1, 12), # 4 days of valid data
        symbol="NIFTY",
        resolution="5",
        initial_balance=100000
    )
    backtest.start()
    
    conn = get_connection()
    try:
        df = pd.read_sql(f"SELECT * FROM trades WHERE session_id = '{backtest.session_id}'", conn)
        if df.empty:
            print("⚠️ No trades.")
        else:
            print(f"✅ Trades: {len(df)}")
            if 'etd' in df.columns:
                print("✅ Columns Exist")
                dead = len(df[df['pnl_edge_death'].notnull()])
                print(f"💀 Edge Death: {dead}")
                inv = len(df[df['exit_reason'] == 'INVALIDATION'])
                print(f"🛑 Invalidation: {inv}")
            else:
                print("❌ Columns Missing")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
