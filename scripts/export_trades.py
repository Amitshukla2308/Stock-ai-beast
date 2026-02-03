
import sqlite3
import pandas as pd
import json
import sys
import os

def export_trades(session_id, db_path=os.path.join("data", "simulation.db"), output_file='session_trades.json'):
    print(f"📂 Connecting to {db_path}...")
    try:
        conn = sqlite3.connect(db_path, timeout=300)
        conn.execute("PRAGMA journal_mode=WAL")
    except Exception as e:
        print(f"❌ Connection Failed: {e}")
        return

    # Optimized fetch (v2.0)
    query = "SELECT * FROM trades WHERE session_id = ?"
    print(f"🔍 Executing: {query} for {session_id}")
    
    try:
        df = pd.read_sql_query(query, conn, params=(session_id,))
        print(f"✅ Trades found: {len(df)}")
        
        if df.empty:
            print(f"⚠️ No trades found for session {session_id}. Double check session_id or database.")
            # Partial match fallback
            alt_query = "SELECT * FROM trades WHERE trade_id LIKE ?"
            df = pd.read_sql_query(alt_query, conn, params=(f"%{session_id}%",))
            print(f"✅ Partial match fallback found: {len(df)}")
        
        # Convert timestamps
        for col in df.columns:
            if 'time' in col:
                df[col] = df[col].astype(str)
                
        # Save
        df.to_json(output_file, orient='records', indent=4)
        print(f"💾 Saved to {output_file}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python export_trades.py <session_id> [db_path]")
        sys.exit(1)
        
    session_id = sys.argv[1]
    db_path = sys.argv[2] if len(sys.argv) > 2 else 'data/trading.db'
    
    export_trades(session_id, db_path)
