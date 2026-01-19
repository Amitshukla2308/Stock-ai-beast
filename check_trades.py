import duckdb

conn = duckdb.connect('data/trading.db', read_only=True)
# session_id = 'BACKTEST_20260117_231636'
# Fetch latest session ID automatically
session_id = conn.execute("SELECT session_id FROM simulation_sessions ORDER BY created_at DESC LIMIT 1").fetchone()[0]

print(f"Checking Session: {session_id}")

# 1. Count Trades
count = conn.execute(f"SELECT count(*) FROM simulation_trades WHERE session_id='{session_id}'").fetchone()[0]
print(f"Trade Count: {count}")

# 2. Check for BLOCKED logs
blocked = conn.execute(f"SELECT timestamp, content FROM simulation_logs WHERE session_id='{session_id}' AND content LIKE '%BLOCKED%' LIMIT 10").fetchall()
if blocked:
    print("\nBlocked Decisions:")
    for row in blocked:
        print(f"{row[0]}: {row[1][:200]}...") # Print first 200 chars
else:
    print("\nNo BLOCKED logs found.")

# 3. Check for MODIFIED logs (Engine Geometry)
modified = conn.execute(f"SELECT timestamp, content FROM simulation_logs WHERE session_id='{session_id}' AND content LIKE '%MODIFIED%' LIMIT 10").fetchall()
if modified:
    print("\nModified Decisions (Trace):")
    for row in modified:
        print(f"{row[0]}: {row[1][:200]}...")

# 4. Check for HOLD actions
hold_count = conn.execute(f"SELECT count(*) FROM simulation_logs WHERE session_id='{session_id}' AND content LIKE '%\"action\": \"HOLD\"%'").fetchone()[0]
print(f"\nHOLD Action Count: {hold_count}")

# 5. Sample LLM Output
sample = conn.execute(f"SELECT content FROM simulation_logs WHERE session_id='{session_id}' AND content LIKE '%\"action\": \"HOLD\"%' LIMIT 1").fetchone()
if sample:
    print(f"\nSample LOG: {sample[0]}")

conn.close()
