import time
from datetime import datetime, timedelta
import pandas as pd
from brokers.fyers.connector import get_fyers_model
from data.database import get_connection, init_db
import argparse

def fetch_history(fyers, symbol, start_date, end_date, resolution="5"):
    """
    Fetch history for a specific range.
    """
    data_input = {
        "symbol": symbol,
        "resolution": resolution,
        "date_format": "1",
        "range_from": start_date.strftime('%Y-%m-%d'),
        "range_to": end_date.strftime('%Y-%m-%d'),
        "cont_flag": "1"
    }
    
    try:
        response = fyers.history(data=data_input)
    except Exception as e:
        print(f"   ❌ API Request Failed: {e}")
        return []

    if response.get('s') != 'ok':
        # Don't print error for "no data" on holidays, just debug
        msg = response.get('message', '')
        if "no data" in msg.lower():
             pass # Normal for holidays
        else:
             print(f"   ⚠️ API Message ({start_date.date()}): {msg}")
        return []
    
    return response.get('candles', [])

def ensure_data(symbol, days=5, resolution="5"):
    """
    Ensure we have data for the last N days. 
    Uses INSERT OR IGNORE to fill gaps without duplication.
    """
    try:
        fyers = get_fyers_model()
    except Exception as e:
        print(f"❌ Could not connect to Fyers: {e}")
        return

    conn = get_connection()
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    print(f"📥 Prefilling {symbol} (Last {days} days) for Simulation Reliability...")
    
    # We fetch in 30-day chunks to be safe, though 'days' usually small
    chunk_size = 30
    current_start = start_date
    total_added = 0
    
    # Determine table based on symbol/resolution
    table_name = "candles_5min"
    if "VIX" in symbol: table_name = "candles_vix"
    
    # --- OPTIMIZATION: Check Existing Coverage ---
    # Calculate expected candles (approx 75 per day for 5-min resolution in NSE)
    # We use a 40-candle-per-day threshold to be safe with holidays/weekends
    expected_min = days * 40 
    
    count_query = f"SELECT count(*) FROM {table_name} WHERE symbol = ? AND timestamp >= ? AND timestamp <= ?"
    initial_count = conn.execute(count_query, (symbol, start_date, end_date)).fetchone()[0]
    
    if initial_count >= expected_min:
        print(f"   ✨ {symbol}: Already has {initial_count} candles in range. Skipping API fetch.")
        conn.close()
        return

    # --- FETCH & INSERT ---
    while current_start < end_date:
        current_end = min(current_start + timedelta(days=chunk_size), end_date)
        
        candles = fetch_history(fyers, symbol, current_start, current_end, resolution)
        
        if candles:
            df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['symbol'] = symbol
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
            
            # Batch insert
            rows_to_insert = []
            for _, row in df.iterrows():
                rows_to_insert.append((
                    row['timestamp'].strftime('%Y-%m-%d %H:%M:%S'), 
                    row['symbol'], 
                    row['open'], row['high'], row['low'], row['close'], row['volume']
                ))

            try:
                conn.executemany(f"INSERT OR IGNORE INTO {table_name} VALUES (?, ?, ?, ?, ?, ?, ?)", rows_to_insert)
            except Exception as e:
                print(f"   ⚠️ Insert Error: {e}")
        
        current_start = current_end + timedelta(days=1)
        time.sleep(0.1) 
        
    final_count = conn.execute(count_query, (symbol, start_date, end_date)).fetchone()[0]
    conn.close()
    
    total_added = final_count - initial_count
    if total_added > 0:
        print(f"   ✅ {symbol}: Added {total_added} new candles (Total: {final_count}).")
    else:
        print(f"   ✨ {symbol}: Database is up to date.")

SYMBOL_MAP = {
    "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
    "NIFTY": "NSE:NIFTY50-INDEX",
    "FINNIFTY": "NSE:FINNIFTY-INDEX"
}

def run(days=5, symbol="BANKNIFTY"):
    # Ensure tables exist with correct schema
    init_db()
    
    # Add 7 days of historical padding to ensure 'Daily 3D' context is filled
    # even for the first day of the simulation.
    padded_days = days + 7
    
    fyers_symbol = SYMBOL_MAP.get(symbol, symbol) # Fallback to literal if not in map
    
    # Target Symbol 5min
    ensure_data(fyers_symbol, days=padded_days, resolution="5")
    
    # India VIX 5min (for context)
    ensure_data("NSE:INDIAVIX-INDEX", days=padded_days, resolution="5")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=5, help="Number of days to ensure")
    parser.add_argument("--symbol", type=str, default="BANKNIFTY", help="Symbol to prefill")
    args = parser.parse_args()
    
    run(days=args.days, symbol=args.symbol)
