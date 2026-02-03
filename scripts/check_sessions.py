
import sqlite3
import os

def check_db(name):
    path = os.path.join("data", name)
    if not os.path.exists(path):
        print(f"❌ {name} not found.")
        return
    
    print(f"🔍 Checking {name}...")
    try:
        conn = sqlite3.connect(path)
        cursor = conn.execute("SELECT DISTINCT session_id FROM trades ORDER BY rowid DESC LIMIT 5;")
        sessions = cursor.fetchall()
        for s in sessions:
            print(f"  - {s[0]}")
        conn.close()
    except Exception as e:
        print(f"❌ Error checking {name}: {e}")

if __name__ == "__main__":
    check_db("trading.db")
    check_db("simulation.db")
