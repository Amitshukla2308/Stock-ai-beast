import os
import sqlite3
from data.database import get_connection

def check_db():
    db_name = os.environ.get("BEAST_DB_NAME", "trading.db")
    print(f"Checking DB: {db_name}")
    try:
        conn = get_connection(db_name)
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
                print(f"Trade: {t}")
        else:
            print("Table 'trades' does not exist.")
            
        if 'candles_5min' in tables:
            cursor.execute("SELECT timestamp, close FROM candles_5min ORDER BY timestamp DESC LIMIT 5")
            candles = cursor.fetchall()
            print(f"Latest 5m Candles: {candles}")
            
        conn.close()
    except Exception as e:
        print(f"Error checking DB: {e}")

if __name__ == "__main__":
    check_db()
