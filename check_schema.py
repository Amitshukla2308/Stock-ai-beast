import duckdb
import os
import sys
sys.path.append('.')
from engine.journal import Journal

DB_PATH = "data/trading.db"
# Trigger migration
j = Journal(session_id="MIGRATION_TEST")

conn = duckdb.connect(DB_PATH)
try:
    print("--- simulation_trades columns ---")
    res = conn.execute("PRAGMA table_info('simulation_trades')").fetchall()
    for r in res:
        print(r)
except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
