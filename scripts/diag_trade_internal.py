import sqlite3
import os

def diag():
    db_path = "data/trading.db"
    if not os.path.exists(db_path):
        print(f"DB not found at {db_path}")
        return

    try:
        conn = sqlite3.connect(db_path, timeout=60)
        conn.row_factory = sqlite3.Row
        trade = conn.execute("SELECT * FROM trades WHERE status='OPEN'").fetchone()
        if trade:
            print("TRADE_FOUND")
            for key in trade.keys():
                print(f"{key}: {trade[key]}")
        else:
            print("NO_OPEN_TRADE_FOUND")
        conn.close()
    except Exception as e:
        print(f"ERORR: {e}")

if __name__ == "__main__":
    diag()
