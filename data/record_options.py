# Add project root to path
import sys
import os
# Ensure we are adding the project root (one level up from data/)
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import duckdb
import time
from datetime import datetime, time as dt_time, timedelta
from data.database import get_connection
from brokers.fyers.connector import get_fyers_model

def init_db():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS option_chain (
            timestamp TIMESTAMP,
            symbol VARCHAR,
            spot_price DOUBLE,
            strike_price DOUBLE,
            option_type VARCHAR,
            ltp DOUBLE,
            volume BIGINT,
            oi BIGINT
        )
    """)
    conn.close()

def get_market_status():
    now = datetime.now()
    cutoff_open = dt_time(9, 15)
    cutoff_close = dt_time(15, 30)
    
    if now.weekday() > 4: # Sat/Sun
        return False
        
    current_time = now.time()
    if current_time >= cutoff_open and current_time <= cutoff_close:
        return True
    return False

def record_data():
    try:
        fyers = get_fyers_model()
    except Exception as e:
        print(f"❌ Broker Connect Failed: {e}")
        return

    print("📡 Connected to Fyers. Starting Option Chain Recorder (NIFTY)...")
    
    while True:
        if not get_market_status():
            print("💤 Market Closed. Sleeping 60s...")
            time.sleep(60)
            continue
            
        try:
            # 1. Get Spot Price
            quotes = fyers.quotes(data={"symbols": "NSE:NIFTY50-INDEX"})
            if 'd' not in quotes or not quotes['d']:
                print("⚠️ No Quote Data")
                time.sleep(5)
                continue
                
            spot_price = quotes['d'][0]['v']['lp']
            timestamp = datetime.now()
            
            # 2. Generate Strikes (ATM +/- 5)
            # Nifty Strike Step = 50
            atm_strike = round(spot_price / 50) * 50
            strikes = []
            for i in range(-5, 6):
                strikes.append(atm_strike + (i * 50))
            
            # 3. Build Symbols
            symbols = []
            strike_map = {} # symbol -> strike/type
            
            # Calculate Expiry (Nearest Thursday for Nifty)
            today = datetime.now()
            # 0=Mon, 3=Thu. 
            days_to_thu = (3 - today.weekday()) % 7
            if days_to_thu == 0 and today.hour >= 15: days_to_thu = 7
            expiry = today + timedelta(days=days_to_thu)
            
            y_str = expiry.strftime('%y')
            m_str = expiry.strftime('%b').upper()
            d_str = expiry.strftime('%d')
            
            for k in strikes:
                for opt_type in ['CE', 'PE']:
                    # Example: NSE:NIFTY28DEC24000CE
                    sym = f"NSE:NIFTY{y_str}{m_str}{d_str}{k}{opt_type}"
                    symbols.append(sym)
                    strike_map[sym] = {'strike': k, 'type': opt_type}
            
            # 4. Fetch Quotes Batch
            # Fyers limit is 50 symbols per call. We have 22.
            sym_str = ",".join(symbols)
            chain_quotes = fyers.quotes(data={"symbols": sym_str})
            
            if 'd' in chain_quotes:
                rows = []
                for item in chain_quotes['d']:
                    s = item['n']
                    v = item['v']
                    ltp = v.get('lp', 0)
                    vol = v.get('volume', 0)
                    oi = v.get('open_interest', 0) # Fyers might handle OI differently
                    
                    meta = strike_map.get(s)
                    if meta:
                        rows.append((
                            timestamp, s, spot_price, 
                            meta['strike'], meta['type'], 
                            ltp, vol, oi
                        ))
                
                # 5. Insert to DB
                conn = get_connection()
                conn.executemany("INSERT INTO option_chain VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
                conn.close()
                print(f"   [{timestamp.strftime('%H:%M:%S')}] 💾 Saved {len(rows)} ticks. NIFTY: {spot_price}")
            
        except Exception as e:
            print(f"⚠️ Error: {e}")
            
        time.sleep(60) # Record every minute

if __name__ == "__main__":
    init_db()
    record_data()
