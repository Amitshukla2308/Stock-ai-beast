
import sqlite3
import sys

def list_tables(db_path):
    print(f"Connecting to {db_path}")
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cur.fetchall()
        print(f"Tables: {tables}")
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    db_path = sys.argv[1] if len(sys.argv) > 1 else 'data/simulation.db'
    list_tables(db_path)
