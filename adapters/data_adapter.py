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
            conn = get_connection()
            df = pd.read_sql_query(query, conn)
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
        
        # We rely on 1min data for precise close, even if running 5min backtest
        # Fallback logic not originally present, keeping simple
        query = f"""
            SELECT close FROM candles_1min 
            WHERE symbol = '{full_symbol}'
              AND timestamp >= '{prev_day_str} 09:45:00' 
              AND timestamp <= '{prev_day_str} 10:00:00'
            ORDER BY timestamp DESC LIMIT 1
        """
        try:
            conn = get_connection()
            result = conn.execute(query).fetchone()
            conn.close()
            
            if result:
                return result[0]
            return None
        except Exception as e:
            logger.error(f"Prev Close Fetch Error: {e}")
            return None

# Global instance
data_adapter = DataAdapter()
