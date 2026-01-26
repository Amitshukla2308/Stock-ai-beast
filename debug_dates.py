import sqlite3
from datetime import datetime

DB_PATH = "data/trading.db"

def check_dates():
    try:
        conn = sqlite3.connect(DB_PATH)
        # Check start range
        row = conn.execute("SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM candles_5min WHERE symbol='NSE:NIFTY50-INDEX'").fetchone()
        print(f"\n📊 DATA RANGE CHECK:")
        print(f"   First Candle: {row[0]}")
        print(f"   Last Candle:  {row[1]}")
        print(f"   Total Count:  {row[2]}")
        
        # Check specifically before Jan 25, 2021 (Warmup Period)
        prior_row = conn.execute("SELECT COUNT(*) FROM candles_5min WHERE timestamp < '2021-01-25' AND symbol='NSE:NIFTY50-INDEX'").fetchone()
        print(f"   Candles before Jan 25, 2021: {prior_row[0]}")
        
        if prior_row[0] == 0:
            print("\n🚨 CONFIRMED: No warmup data available. Morning Brief zeros are expected.")
        else:
            print("\n✅ Warmup data exists. Something else is breaking the fetch.")
            
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        if 'conn' in locals(): conn.close()

if __name__ == "__main__":
    check_dates()
