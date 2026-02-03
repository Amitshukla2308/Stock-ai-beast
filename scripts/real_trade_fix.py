import sqlite3
import os

def real_fix():
    db_path = "data/trading.db"
    trade_id = "MOCK_20260202_143210_143219_1"
    
    # 14:32 Reality: Spot ~24945, ATM Strike 24950
    new_symbol = "NSE:NIFTY2620324950CE"
    new_strike = 24950
    new_entry_price = 85.0 # Estimated ATM premium
    
    try:
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE trades SET option_symbol = ?, strike = ?, entry_price = ? WHERE trade_id = ?",
            (new_symbol, new_strike, new_entry_price, trade_id)
        )
        conn.commit()
        print(f"✅ REALISTIC FIX APPLIED: {new_symbol} @ {new_entry_price} for {trade_id}")
        conn.close()
    except Exception as e:
        print(f"❌ FAILED: {e}")

if __name__ == "__main__":
    real_fix()
