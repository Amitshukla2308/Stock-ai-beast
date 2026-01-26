import sqlite3

DB_PATH = "data/trading.db"

def list_tables():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        print(f"\n📊 TABLES IN DB: {tables}")
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        if 'conn' in locals(): conn.close()

if __name__ == "__main__":
    list_tables()
