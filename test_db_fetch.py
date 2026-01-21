
import logging
from datetime import datetime
from data.database import fetch_context_data

logging.basicConfig(level=logging.INFO)

def test_fetch():
    target_date = datetime(2026, 1, 16, 9, 30)
    symbol = "NIFTY"
    print(f"Testing fetch_context_data for {target_date}...")
    context = fetch_context_data(target_date, symbol)
    
    print(f"Daily 3 count: {len(context.get('daily_3', []))}")
    print(f"Last 15min count: {len(context.get('last_15min', []))}")
    print(f"VIX: {context.get('vix_spot')}")
    print(f"ATR: {context.get('atr_14')}")
    
    if len(context.get('last_15min', [])) > 0:
        print("Success! Data found.")
    else:
        print("Still no data. Check table selection/union logic.")

if __name__ == "__main__":
    test_fetch()
