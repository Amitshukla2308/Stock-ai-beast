import sqlite3
import os

def check_db():
    db_path = "data/trading.db"
    print(f"Checking DB directly: {db_path}")
    if not os.path.exists(db_path):
        print(f"File not found: {db_path}")
        return
        
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        conn.execute("PRAGMA busy_timeout = 30000;")
        cursor = conn.cursor()
        
        # Check tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [t[0] for t in cursor.fetchall()]
        print(f"Tables: {tables}")
        
        if 'trades' in tables:
            cursor.execute("SELECT * FROM trades")
            trades = cursor.fetchall()
            print(f"Total Trades: {len(trades)}")
            for t in trades:
                print(f"Trade record: {t}")
        else:
            print("Table 'trades' does not exist.")
            
        if 'candles_5min' in tables:
            cursor.execute("SELECT timestamp, close FROM candles_5min ORDER BY timestamp DESC LIMIT 10")
            candles = cursor.fetchall()
            print(f"Latest 10 (5m) Candles: {candles}")
            
        conn.close()
    except Exception as e:
        print(f"Error checking DB: {e}")

if __name__ == "__main__":
    check_db()
