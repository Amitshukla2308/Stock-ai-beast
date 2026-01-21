
import sqlite3
import os
from datetime import datetime, timedelta

def get_connection():
    return sqlite3.connect('data/trading.db')

def test_queries():
    conn = get_connection()
    symbol = "NSE:NIFTY50-INDEX"
    ts_str = "2026-01-16 09:30:00"
    
    table = "candles_5min"
    
    print(f"Testing queries on {table}...")
    
    # 1. Check if we can fetch data
    q = f"SELECT COUNT(*) FROM {table} WHERE symbol = ?"
    count = conn.execute(q, (symbol,)).fetchone()[0]
    print(f"Total rows for {symbol}: {count}")
    
    # 2. Check Today's 5min aggregation
    q = f"""
        SELECT 
            datetime((strftime('%s', timestamp) / 300) * 300, 'unixepoch') AS bucket,
            open, MAX(high), MIN(low), close, SUM(volume)
        FROM {table}
        WHERE symbol = ? 
          AND date(timestamp) = '2026-01-16'
          AND timestamp <= ?
        GROUP BY bucket
        ORDER BY bucket ASC
    """
    rows = conn.execute(q, (symbol, ts_str)).fetchall()
    print(f"Rows for 2026-01-16 up to 09:30: {len(rows)}")
    
    # Simulate fetch_context_data logic
    # 1. Opening Range (Expected 09:15 to 10:00 IST)
    # The timestamps in DB are UTC (03:45 to 10:00)
    or_bars = [r for r in rows if "03:45:00" <= r[0].split(' ')[1] <= "04:30:00"]
    print(f"Opening Range Bars (03:45-04:30 UTC): {len(or_bars)}")
    if or_bars:
        or_high = max(r[2] for r in or_bars)
        or_low = min(r[3] for r in or_bars)
        print(f"  OR High: {or_high}, OR Low: {or_low}, Range: {or_high - or_low}")

    # 2. ATR Calculation (using intraday rows)
    # Fetch some history for ATR
    q_hist = f"SELECT timestamp, open, high, low, close FROM {table} WHERE symbol = ? AND timestamp <= ? ORDER BY timestamp DESC LIMIT 30"
    hist_rows = conn.execute(q_hist, (symbol, ts_str)).fetchall()
    print(f"History rows for ATR: {len(hist_rows)}")
    
    if len(hist_rows) >= 15:
        true_ranges = []
        for i in range(len(hist_rows) - 1):
            curr = hist_rows[i]   # Newer
            prev = hist_rows[i+1] # Older
            tr = max(curr[2] - curr[3], abs(curr[2] - prev[4]), abs(curr[3] - prev[4]))
            true_ranges.append(tr)
        atr_14 = round(sum(true_ranges[:14]) / 14, 2)
        print(f"  Calculated ATR 14: {atr_14}")
    
    # 3. Daily 3 Aggregation
    q_daily = f"""
        SELECT 
            date(timestamp) as day,
            open, MAX(high), MIN(low), close, SUM(volume)
        FROM {table}
        WHERE symbol = ? 
          AND timestamp < '2026-01-16 03:45:00'
        GROUP BY day
        ORDER BY day DESC LIMIT 3
    """
    daily_rows = conn.execute(q_daily, (symbol,)).fetchall()
    print(f"Daily 3 rows (before 2026-01-16): {len(daily_rows)}")
    for d in daily_rows:
        print(f"  {d}")

    conn.close()

if __name__ == "__main__":
    test_queries()
