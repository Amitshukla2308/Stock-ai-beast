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
        if not msg or "no data" in msg.lower():
             pass # Normal for holidays or empty errors
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

def run(days=5, symbol="BANKNIFTY", resolution="5", start_date=None, end_date=None):
    # Ensure tables exist with correct schema
    init_db()
    
    # Add padding if using 'days' logic
    padded_days = days + 7 if days else 7
    
    fyers_symbol = SYMBOL_MAP.get(symbol, symbol) 
    
    # Determine table name based on resolution
    table_name = "candles_5min"
    if resolution == "1":
        table_name = "candles_1min"
    elif "VIX" in fyers_symbol:
        table_name = "candles_vix"
        
    # Target Symbol Data
    ensure_data_v2(fyers_symbol, days=padded_days, resolution=resolution, table_name=table_name, start_date=start_date, end_date=end_date)
    
    # India VIX 5min (for context)
    ensure_data_v2("NSE:INDIAVIX-INDEX", days=padded_days, resolution="5", table_name="candles_vix", start_date=start_date, end_date=end_date)

def ensure_data_v2(symbol, days=5, resolution="5", table_name="candles_5min", start_date=None, end_date=None):
    """
    Version 2 of ensure_data that accepts table_name and explicit dates.
    """
    try:
        fyers = get_fyers_model()
    except Exception as e:
        print(f"❌ Could not connect to Fyers: {e}")
        return

    conn = get_connection()
    
    if start_date and end_date:
        # Use explicit range with padding
        padding = timedelta(days=7)
        effective_start = start_date - padding
        effective_end = end_date
        print(f"📥 Prefilling {symbol} ({resolution}m) into {table_name} (Range: {effective_start.date()} to {effective_end.date()})...")
    else:
        # Fallback to last N days
        effective_end = datetime.now()
        effective_start = effective_end - timedelta(days=days)
        print(f"📥 Prefilling {symbol} ({resolution}m) into {table_name} (Last {days} days)...")
    
    # Calculate actual days for threshold
    diff_days = (effective_end - effective_start).days
    if diff_days < 1: diff_days = 1

    # Optimization: Check if we have enough data (NSE: ~375 ticks/day for 1m, ~75 for 5m)
    ticks_per_day = 375 if resolution == "1" else 75
    expected_min = diff_days * (ticks_per_day * 0.7) # 70% threshold
    
    count_query = f"SELECT count(*) FROM {table_name} WHERE symbol = ? AND timestamp >= ? AND timestamp <= ?"
    initial_count = conn.execute(count_query, (symbol, effective_start, effective_end)).fetchone()[0]
    
    if initial_count >= expected_min:
        print(f"   ✨ {symbol}: Already has {initial_count} candles in range. Skipping.")
        conn.close()
        return

    # Fetch in 1-day chunks for 1-minute data 
    chunk_size = 1 if resolution == "1" else 30
    current_start = effective_start
    total_added = 0
    
    while current_start < effective_end:
        current_end = min(current_start + timedelta(days=chunk_size), effective_end)
        if resolution == "1":
            print(f"      ⏳ {current_start.date()}...", end="\r")

        candles = fetch_history(fyers, symbol, current_start, current_end, resolution)
        
        if candles:
            df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['symbol'] = symbol
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
            
            rows_to_insert = []
            for _, row in df.iterrows():
                rows_to_insert.append((
                    row['timestamp'].strftime('%Y-%m-%d %H:%M:%S'), 
                    row['symbol'], 
                    row['open'], row['high'], row['low'], row['close'], row['volume']
                ))

            try:
                conn.executemany(f"INSERT OR IGNORE INTO {table_name} VALUES (?, ?, ?, ?, ?, ?, ?)", rows_to_insert)
                total_added += len(rows_to_insert)
            except Exception as e:
                print(f"   ⚠️ Insert Error: {e}")
        
        current_start = current_end
        time.sleep(0.5 if resolution == "1" else 0.1) 
    
    if total_added > 0:
        print(f"   ✅ {symbol}: Added {total_added} new candles.")
    else:
        print(f"   ✨ {symbol}: Database is up to date.")
        
    conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=5, help="Number of days to ensure")
    parser.add_argument("--symbol", type=str, default="BANKNIFTY", help="Symbol to prefill")
    parser.add_argument("--res", type=str, default="5", help="Resolution (1 or 5)")
    args = parser.parse_args()
    
    run(days=args.days, symbol=args.symbol, resolution=args.res)
