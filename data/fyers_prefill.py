import time
from datetime import datetime, timedelta
import pandas as pd
from brokers.fyers.connector import get_fyers_model
from data.database import get_connection

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
    
    response = fyers.history(data=data_input)
    if response.get('s') != 'ok':
        print(f"❌ Error fetching {start_date.date()} to {end_date.date()}: {response.get('message')}")
        return []
    
    return response.get('candles', [])

    return response.get('candles', [])

def prefill_symbol(symbol, table_name, years=5, resolution="5"):
    """
    Prefill a single symbol into a specific table.
    """
    try:
        fyers = get_fyers_model()
    except Exception as e:
        print(f"❌ Could not connect to Fyers: {e}")
        return

    conn = get_connection()
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=years*365)
    
    print(f"🚀 Starting Prefill for {symbol} ({resolution}m) -> {table_name}")
    
    chunk_size = 30
    current_start = start_date
    total_candles = 0
    
    while current_start < end_date:
        current_end = min(current_start + timedelta(days=chunk_size), end_date)
        
        # print(f"   Fetching {current_start.date()} -> {current_end.date()}...", end="", flush=True)
        try:
            candles = fetch_history(fyers, symbol, current_start, current_end, resolution)
        except Exception as e:
             print(f"Error fetching chunk: {e}")
             candles = []

        if candles:
            # print(f" ✅ {len(candles)} candles")
            
            df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['symbol'] = symbol
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
            
            # Batch insert
            for _, row in df.iterrows():
                try:
                    conn.execute(f"INSERT OR IGNORE INTO {table_name} VALUES (?, ?, ?, ?, ?, ?, ?)", (
                        row['timestamp'], row['symbol'], 
                        row['open'], row['high'], row['low'], row['close'], row['volume']
                    ))
                except Exception:
                    pass
            
            total_candles += len(candles)
        else:
             pass
             # print(" ⚠️ No Data")
        
        current_start = current_end + timedelta(days=1)
        time.sleep(0.2) 
        
    conn.close()
    print(f"🏁 {symbol} Complete. Total: {total_candles}")

def run_prefill():
    # 1. Nifty Bank
    prefill_symbol("NSE:NIFTYBANK-INDEX", "candles_5min", years=1, resolution="5")
    
    # 2. India VIX (Daily or 5min? VIX moves fast, let's try 5min if available, else 1D)
    # Fyers VIX symbol: NSE:INDIAVIX-INDEX
    # We will try 5min to match our Nifty candles for precise greeks
    prefill_symbol("NSE:INDIAVIX-INDEX", "candles_vix", years=1, resolution="5")

if __name__ == "__main__":
    run_prefill()
