import sqlite3

DB_PATH = "data/trading.db"

def check_schema():
    try:
        conn = sqlite3.connect(DB_PATH)
        print("\n📊 TABLE: trades")
        cursor = conn.execute("PRAGMA table_info(trades)")
        columns = [row[1] for row in cursor.fetchall()]
        print(f"   Columns: {columns}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        if 'conn' in locals(): conn.close()

if __name__ == "__main__":
    check_schema()
