import sqlite3
import pandas as pd

def read_candles():
    conn = sqlite3.connect('data/trading.db')
    query = "SELECT timestamp, close FROM candles_5min WHERE timestamp >= '2026-02-02 14:00:00' ORDER BY timestamp ASC"
    df = pd.read_sql(query, conn)
    print(df.to_string())
    conn.close()

if __name__ == "__main__":
    read_candles()
