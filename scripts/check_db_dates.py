
import duckdb
conn = duckdb.connect('data/trading.db', read_only=True)

# Check what dates exist in candles_5min
print("=== Date Range in candles_5min ===")
result = conn.execute("SELECT MIN(timestamp), MAX(timestamp) FROM candles_5min WHERE symbol = 'NSE:NIFTY50-INDEX'").fetchall()
print(f"Min: {result[0][0]}, Max: {result[0][1]}")

# Check count for Jan 17 specifically
print("\n=== Candles for 2026-01-17 (using IST market hours) ===")
result = conn.execute("""
    SELECT COUNT(*) FROM candles_5min 
    WHERE symbol = 'NSE:NIFTY50-INDEX' 
      AND timestamp >= '2026-01-17 09:15:00' 
      AND timestamp <= '2026-01-17 15:30:00'
""").fetchall()
print(f"Count: {result[0][0]}")

# Check what dates have data
print("\n=== Distinct Dates with Data ===")
result = conn.execute("""
    SELECT DISTINCT CAST(timestamp AS DATE) as dt, COUNT(*) as cnt
    FROM candles_5min 
    WHERE symbol = 'NSE:NIFTY50-INDEX'
    GROUP BY 1 ORDER BY 1 DESC LIMIT 10
""").fetchall()
for row in result:
    print(f"  {row[0]}: {row[1]} candles")

conn.close()
