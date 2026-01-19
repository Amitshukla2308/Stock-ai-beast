import duckdb
from datetime import datetime
import pytz
from data.database import get_connection

DATE_STR = '2026-01-12'
# 09:45 IST -> 04:15 UTC
ist = pytz.timezone('Asia/Kolkata')
dt = ist.localize(datetime.strptime(f"{DATE_STR} 09:45:00", "%Y-%m-%d %H:%M:%S"))
utc_dt = dt.astimezone(pytz.utc).replace(tzinfo=None)

print(f"--- MINIMAL DEBUG FOR {utc_dt} UTC ---")

conn = get_connection()

# 1. Simple Select (Prove data in range)
print("1. Simple Select (timestamp <= 04:15)")
q1 = "SELECT timestamp, close FROM candles_5min WHERE symbol='NSE:NIFTY50-INDEX' AND timestamp <= ? ORDER BY timestamp DESC LIMIT 5"
res1 = conn.execute(q1, (utc_dt,)).fetchall()
for r in res1: print(r)

# 2. Time Bucket (Prove bucketing)
print("\n2. Time Bucket")
q2 = "SELECT time_bucket(INTERVAL '15 minutes', timestamp) AS ts, last(close) FROM candles_5min WHERE symbol='NSE:NIFTY50-INDEX' AND timestamp <= ? GROUP BY 1 ORDER BY ts DESC LIMIT 5"
try:
    res2 = conn.execute(q2, (utc_dt,)).fetchall()
    for r in res2: print(r)
except Exception as e:
    print(f"Bucket Error: {e}")

conn.close()
