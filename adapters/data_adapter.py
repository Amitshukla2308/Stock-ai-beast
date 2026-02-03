"""
v2.8 Adapter: Data Loader
Handles data fetching from DB for Backtest Mode.
Migrated from engine/modes/backtest.py.
"""
import logging
import pandas as pd
import pytz
from datetime import datetime, timedelta
from typing import Optional
from data.database import get_connection, get_fyers_symbol

IST = pytz.timezone('Asia/Kolkata')
logger = logging.getLogger(__name__)

class DataAdapter:
    def __init__(self, db_path: str = 'trading.db'):
        self.db_path = db_path
        
    def fetch_data_for_day(self, date: datetime, symbol: str, resolution: str) -> pd.DataFrame:
        """
        Fetch candles for the specific day (UTC -> IST conversion included).
        Returns DataFrame with IST timezone-aware timestamps.
        """
        date_str = date.strftime('%Y-%m-%d')
        # 09:15 IST = 03:45 UTC
        # 15:30 IST = 10:00 UTC
        full_symbol = get_fyers_symbol(symbol)
        
        table_name = "candles_5min" if str(resolution) == '5' else "candles_1min"
        
        query = f"""
            SELECT * FROM {table_name}
            WHERE symbol = '{full_symbol}'
              AND timestamp >= '{date_str} 03:45:00' 
              AND timestamp <= '{date_str} 10:00:00'
            ORDER BY timestamp ASC
        """
        try:
            conn = get_connection("trading.db")
            # print(f"   [DB] Querying: {query}")
            df = pd.read_sql_query(query, conn)
            
            if df.empty:
                print(f"   [DB] ⚠️ No data found for {full_symbol} on {date_str} in {table_name}")
                # Diagnostic: What symbols DO exist?
                try:
                    sym_query = f"SELECT DISTINCT symbol FROM {table_name}"
                    available_syms = pd.read_sql_query(sym_query, conn)
                    sym_list = available_syms['symbol'].tolist()
                    print(f"   [DB] ℹ️ Symbols in {table_name}: {len(sym_list)} total")
                    for s in sym_list[:20]: # Show first 20
                        print(f"      - {s}")
                except Exception as e:
                    print(f"   [DB] ❌ Diagnostic query failed: {e}")
            else:
                print(f"   [DB] ✅ Found {len(df)} candles for {full_symbol}")
            
            conn.close()
            
            if not df.empty:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                # Ensure UTC first
                if df['timestamp'].dt.tz is None:
                    df['timestamp'] = df['timestamp'].dt.tz_localize('UTC')
                # Convert to IST
                df['timestamp'] = df['timestamp'].dt.tz_convert(IST)
                
            return df
        except Exception as e:
            logger.error(f"Data Fetch Error: {e}")
            return pd.DataFrame()

    def fetch_prev_close(self, current_date: datetime, symbol: str) -> Optional[float]:
        """
        Fetch Previous Day Close for Gap Analysis.
        Lookback 1 day.
        """
        # Simple lookback - better would be to find last available status
        # but matching original logic for now
        prev_day = current_date - timedelta(days=1)
        prev_day_str = prev_day.strftime('%Y-%m-%d')
        full_symbol = get_fyers_symbol(symbol)
        
        # Try candles_5min first if that's the requested resolution, or as fallback
        tables = ["candles_5min", "candles_1min"]
        
        last_result = None
        for table in tables:
            query = f"""
                SELECT close FROM {table} 
                WHERE symbol = '{full_symbol}'
                  AND timestamp >= '{prev_day_str} 09:30:00' 
                  AND timestamp <= '{prev_day_str} 10:00:00'
                ORDER BY timestamp DESC LIMIT 1
            """
            try:
                conn = get_connection("trading.db")
                result = conn.execute(query).fetchone()
                conn.close()
                if result:
                    return result[0]
            except:
                continue
        return None

# Global instance
data_adapter = DataAdapter()
