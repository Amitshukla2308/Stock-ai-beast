import duckdb
from datetime import datetime

def inspect():
    conn = duckdb.connect('data/trading.db')
    date_str = '2021-12-17'
    print(f"Inspecting data for {date_str}...")
    
    # Check all symbols and counts for that day
    rows = conn.execute(f"SELECT symbol, count(*) FROM candles_5min WHERE DATE(timestamp) = '{date_str}' GROUP BY symbol").fetchall()
    print(f"Counts per symbol: {rows}")
    
    # Check first few timestamps for NSE:NIFTYBANK-INDEX
    rows = conn.execute(f"SELECT timestamp FROM candles_5min WHERE symbol = 'NSE:NIFTYBANK-INDEX' AND DATE(timestamp) = '{date_str}' ORDER BY timestamp LIMIT 5").fetchall()
    print(f"Sample timestamps: {rows}")
    
    conn.close()

if __name__ == "__main__":
    inspect()
