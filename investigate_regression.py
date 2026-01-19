import duckdb
import json

conn = duckdb.connect('data/trading.db', read_only=True)
# Fetch latest session (Jan 12 run)
session_id = conn.execute("SELECT session_id FROM simulation_sessions ORDER BY created_at DESC LIMIT 1").fetchone()[0]

print(f"Investigating Session: {session_id}")

# Fetch logs that contain 'WORKER INPUT' (Input to LLM) and 'BRAIN OUTPUT' (LLM Decision)
# limiting to a few examples around 10:00 AM - 11:00 AM usually active times
logs = conn.execute(f"SELECT timestamp, content FROM simulation_logs WHERE session_id='{session_id}' AND (content LIKE '%WORKER INPUT%' OR content LIKE '%BRAIN OUTPUT%') LIMIT 10").fetchall()

for row in logs:
    print(f"\n--- {row[0]} ---")
    try:
        # Try to parse as JSON if possible, otherwise print raw
        print(row[1][:1000]) # Limit length
    except:
        print(row[1])

conn.close()
