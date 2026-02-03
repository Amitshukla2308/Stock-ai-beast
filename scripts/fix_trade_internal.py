import sqlite3
import os

def fix_trade():
    db_path = "data/trading.db"
    trade_id = "MOCK_20260202_143210_143219_1"
    # Estimated premium for NIFTY 24950 CE at 24961 spot
    new_entry_price = 155.0 
    
    try:
        conn = sqlite3.connect(db_path, timeout=60)
        # Update the entry price to a premium so is_premium_entry becomes True
        conn.execute(
            "UPDATE trades SET entry_price = ? WHERE trade_id = ?",
            (new_entry_price, trade_id)
        )
        conn.commit()
        print(f"✅ SUCCESSFULLY UPDATED trade {trade_id} with entry_price 155.0")
        conn.close()
    except Exception as e:
        print(f"❌ FAILED TO UPDATE: {e}")

if __name__ == "__main__":
    fix_trade()
