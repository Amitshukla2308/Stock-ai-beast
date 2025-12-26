import os
import pandas as pd
import duckdb
from datetime import datetime, timedelta
from dotenv import load_dotenv

# New Import path
from brokers.fyers.connector import get_fyers_model

load_dotenv()

SYMBOLS = ["NSE:NIFTY50-INDEX", "NSE:NIFTYBANK-INDEX"]
DATA_DIR = "data_store" # Rename to avoid conflict with 'data' module if we made one, but user asked for 'data' module? 
# Actually let's keep data stored in 'market_data' folder to be safe.
MARKET_DATA_DIR = "market_data"
DB_FILE = "market_data.duckdb"

def fetch_historical_data(fyers, symbol, resolution="1", range_from=None, range_to=None):
    data = {"symbol": symbol, "resolution": resolution, "date_format": "1", "range_from": range_from, "range_to": range_to, "cont_flag": "1"}
    response = fyers.history(data=data)
    
    if response.get('s') != 'ok':
        print(f"Error fetching {symbol}: {response}")
        return pd.DataFrame()
        
    candles = response.get('candles', [])
    df = pd.DataFrame(candles, columns=['epoch', 'open', 'high', 'low', 'close', 'volume'])
    df['datetime'] = pd.to_datetime(df['epoch'], unit='s').dt.tz_localize('UTC').dt.tz_convert('Asia/Kolkata')
    df.set_index('datetime', inplace=True)
    return df

def update_data():
    os.makedirs(MARKET_DATA_DIR, exist_ok=True)
    try:
        fyers = get_fyers_model()
    except Exception as e:
        print(f"Auth failed: {e}")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=100)).strftime("%Y-%m-%d")

    for symbol in SYMBOLS:
        print(f"Fetching data for {symbol}...")
        df = fetch_historical_data(fyers, symbol, range_from=start_date, range_to=today)
        
        if not df.empty:
            safe_symbol = symbol.replace(":", "_").replace("-", "_")
            file_path = f"{MARKET_DATA_DIR}/{safe_symbol}.parquet"
            df.to_parquet(file_path)
            print(f"Saved {len(df)} rows to {file_path}")
