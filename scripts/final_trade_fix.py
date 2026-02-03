from engine.auth_fyers import get_fyers_instance
from brokers.simulator.option_utils import find_nearest_expiry_with_ltp
import sqlite3
import os

def final_fix():
    try:
        fyers = get_fyers_instance()
        # Search for a symbol using current spot (around 25000)
        # The trade was NIFTY CALL.
        sym, ltp, stk = find_nearest_expiry_with_ltp(fyers, 25078.0, "CALL")
        
        if sym:
            print(f"🎯 Found valid symbol: {sym} | Strike: {stk}")
            db_path = "data/trading.db"
            trade_id = "MOCK_20260202_143210_143219_1"
            
            conn = sqlite3.connect(db_path)
            conn.execute(
                "UPDATE trades SET option_symbol = ?, strike = ? WHERE trade_id = ?",
                (sym, stk, trade_id)
            )
            conn.commit()
            print(f"✅ DB UPDATED: {sym} for {trade_id}")
            conn.close()
        else:
            print("❌ Could not find valid symbol via Fyers")
            
    except Exception as e:
        print(f"ERORR: {e}")

if __name__ == "__main__":
    final_fix()
