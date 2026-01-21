import time
from datetime import datetime, timedelta
import pandas as pd
from brokers.fyers.connector import get_fyers_model
from engine.auth_fyers import trigger_login_flow
from data.database import get_connection, init_db
import argparse
import pytz

IST = pytz.timezone('Asia/Kolkata')
UTC = pytz.utc

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

def run(days=5, symbol="NIFTY", resolution="5", start_date=None, end_date=None):
    # Ensure tables exist with correct schema
    init_db()
    
    # Add padding if using 'days' logic
    padded_days = days + 7 if days else 7
    
    fyers_symbol = SYMBOL_MAP.get(symbol, symbol) 
    
    # Determine table name based on resolution
    table_name = "candles_5min"
    if resolution == "1":
        table_name = "candles_1min"
    elif resolution == "1D" or resolution == "D":
        table_name = "candles_1day"
    elif "VIX" in fyers_symbol:
        table_name = "candles_vix"
        
    # Target Symbol Data
    ensure_data_v2(fyers_symbol, days=padded_days, resolution=resolution, table_name=table_name, start_date=start_date, end_date=end_date)
    
    # India VIX 5min (for context)
    ensure_data_v2("NSE:INDIAVIX-INDEX", days=padded_days, resolution="5", table_name="candles_vix", start_date=start_date, end_date=end_date)

def ensure_data_v2(symbol, days=5, resolution="5", table_name="candles_5min", start_date=None, end_date=None):
    """
    Version 2 of ensure_data that accepts table_name and explicit dates.
    Standardizes on UTC storage.
    """
    conn = get_connection()
    
    now_ist = datetime.now(IST)
    
    if start_date and end_date:
        # User provides date - usually intended as IST
        if start_date.tzinfo is None: start_date = IST.localize(start_date)
        if end_date.tzinfo is None: end_date = IST.localize(end_date)
        
        padding = timedelta(days=7)
        effective_start = start_date - padding
        effective_end = end_date
        print(f"📥 Prefilling {symbol} ({resolution}m) into {table_name} (Range: {effective_start.date()} to {effective_end.date()})...")
    else:
        # Fallback to last N days
        effective_end = now_ist
        effective_start = effective_end - timedelta(days=days)
        print(f"📥 Prefilling {symbol} ({resolution}m) into {table_name} (Last {days} days)...")
    
    # DB CONVERSION: Standardize filters to UTC for SQL comparison
    eff_start_utc = effective_start.astimezone(UTC).replace(tzinfo=None)
    eff_end_utc = effective_end.astimezone(UTC).replace(tzinfo=None)

    # Calculate actual days for threshold
    diff_days = (effective_end - effective_start).days
    if diff_days < 1: diff_days = 1

    # Optimization: Check if we have enough data (NSE: ~375 ticks/day for 1m, ~75 for 5m)
    ticks_per_day = 375 if resolution == "1" else (75 if resolution != "1D" and resolution != "D" else 1)
    expected_min = diff_days * (ticks_per_day * 0.7) # 70% threshold
    
    count_query = f"SELECT count(*) FROM {table_name} WHERE symbol = ? AND timestamp >= ? AND timestamp <= ?"
    initial_count = conn.execute(count_query, (symbol, eff_start_utc, eff_end_utc)).fetchone()[0]
    
    if initial_count >= expected_min:
        print(f"   ✨ {symbol}: Already has {initial_count} candles in range. Skipping.")
        conn.close()
        return

    # Fetch in 1-day chunks for 1-minute data 
    # 1. Check if we have any data at all for this symbol in the range
    check_query = f"SELECT EXISTS(SELECT 1 FROM {table_name} WHERE symbol = ? AND timestamp >= ? AND timestamp <= ?)"
    has_any = conn.execute(check_query, (symbol, eff_start_utc, eff_end_utc)).fetchone()[0]
    
    if not has_any:
        print(f"      🔎 No data found for {symbol} in range. Full sync required.")
        sync_start_date = effective_start
    else:
        # Optimized: Get the latest timestamp to see how much we need to fill
        max_ts_query = f"SELECT MAX(timestamp) FROM {table_name} WHERE symbol = ? AND timestamp <= ?"
        latest_ts_str = conn.execute(max_ts_query, (symbol, eff_end_utc)).fetchone()[0]
        
        if latest_ts_str:
            latest_ts = datetime.fromisoformat(latest_ts_str).replace(tzinfo=UTC).astimezone(IST)
            # If the latest data is older than the target end date (by more than 1 day), sync from there
            if latest_ts < (effective_end - timedelta(days=1)):
                print(f"      🔎 Latest data for {symbol} is {latest_ts.date()}. Syncing from there...")
                sync_start_date = latest_ts
            else:
                # Still check for Today to get latest partial data
                today_str = now_ist.strftime('%Y-%m-%d')
                if latest_ts.strftime('%Y-%m-%d') == today_str:
                     print(f"      🔎 Updating Today ({today_str}) for latest data...")
                     sync_start_date = latest_ts
                else:
                     print(f"      ✨ {symbol} appears up to date (Latest: {latest_ts.date()}).")
                     sync_start_date = None
        else:
            sync_start_date = effective_start
        
    total_added = 0
    # 3. Fetch from sync_start_date to effective_end (if sync needed)
    if sync_start_date:
        # LAZY CONNECTION: Only connect to Fyers if we actually need to sync
        try:
            fyers = get_fyers_model()
        except Exception as e:
            if "No valid Fyers token" in str(e) or "No valid token" in str(e):
                trigger_login_flow(reason="Prefill requires fresh data")
            else:
                print(f"❌ Could not connect to Fyers: {e}")
            conn.close()
            return

        print(f"      📥 Fetching range: {sync_start_date.date()} ➡ {effective_end.date()} ...")
        
        # --- CHUNKED FETCHING IMPLEMENTATION ---
        chunk_days = 90
        if resolution == "1D" or resolution == "D":
            chunk_days = 360
            
        current_chunk_start = sync_start_date
        
        while current_chunk_start < effective_end:
            current_chunk_end = min(current_chunk_start + timedelta(days=chunk_days), effective_end)
            
            try:
                candles = fetch_history(fyers, symbol, current_chunk_start, current_chunk_end, resolution)
                
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

                    conn.executemany(f"INSERT OR IGNORE INTO {table_name} VALUES (?, ?, ?, ?, ?, ?, ?)", rows_to_insert)
                    total_added += len(rows_to_insert)
                    conn.commit() # Commit after every chunk to release locks
                    
            except Exception as e:
                print(f"   ⚠️ Chunk Error ({current_chunk_start.date()}): {e}")
            
            current_chunk_start = current_chunk_end + timedelta(days=1)
            time.sleep(0.1) 
            
    else:
        print(f"      ✨ All data present and up-to-date. Skipping.") 
    
    if total_added > 0:
        print(f"   ✅ {symbol}: Added {total_added} new candles.")
        conn.commit()
    else:
        print(f"   ✨ {symbol}: Database is up to date.")
        
    conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=5, help="Number of days to ensure")
    parser.add_argument("--symbol", type=str, default="NIFTY", help="Symbol to prefill")
    parser.add_argument("--res", type=str, default="5", help="Resolution (1 or 5)")
    args = parser.parse_args()
    
    run(days=args.days, symbol=args.symbol, resolution=args.res)
