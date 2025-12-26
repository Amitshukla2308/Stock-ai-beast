import duckdb
import os
import pytz

IST = pytz.timezone('Asia/Kolkata')
UTC = pytz.utc

DB_PATH = os.path.join("data", "trading.db")

SYMBOL_MAP = {
    "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
    "NIFTY": "NSE:NIFTY50-INDEX",
    "FINNIFTY": "NSE:FINNIFTY-INDEX"
}

def get_fyers_symbol(symbol):
    """Map internal names to Fyers tickers."""
    return SYMBOL_MAP.get(symbol, symbol)

def get_connection():
    """
    Returns a connection to the DuckDB database.
    """
    print(f"   📂 Connecting to DB: {os.path.abspath(DB_PATH)}")
    if os.path.exists(DB_PATH):
        print(f"   ✅ File Exists. Size: {os.path.getsize(DB_PATH)} bytes")
    else:
        print(f"   ⚠️ File NOT Found. Creating new one.")
    conn = duckdb.connect(DB_PATH)
    return conn

def init_db():
    """
    Initialize the database schema.
    """
    conn = get_connection()
    
    # 5-minute candles table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS candles_5min (
            timestamp TIMESTAMP,
            symbol VARCHAR,
            open FLOAT,
            high FLOAT,
            low FLOAT,
            close FLOAT,
            volume BIGINT,
            PRIMARY KEY (timestamp, symbol)
        )
    """)
    
    # 1-minute candles table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS candles_1min (
            timestamp TIMESTAMP,
            symbol VARCHAR,
            open FLOAT,
            high FLOAT,
            low FLOAT,
            close FLOAT,
            volume BIGINT,
            PRIMARY KEY (timestamp, symbol)
        )
    """)

    # India VIX candles table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS candles_vix (
            timestamp TIMESTAMP,
            symbol VARCHAR,
            open FLOAT,
            high FLOAT,
            low FLOAT,
            close FLOAT,
            volume BIGINT,
            PRIMARY KEY (timestamp, symbol)
        )
    """)
    
    # Features table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS features (
            timestamp TIMESTAMP PRIMARY KEY,
            symbol VARCHAR,
            
            -- Trend
            sma_fast FLOAT,
            sma_slow FLOAT,
            trend VARCHAR,
            
            -- Momentum
            rsi FLOAT,
            
            -- Volatility
            atr FLOAT,
            volatility FLOAT,
            bb_upper FLOAT,
            bb_lower FLOAT,
            
            -- Greeks (Simulated)
            delta FLOAT,
            gamma FLOAT,
            theta FLOAT,
            vega FLOAT,
            
            -- Metadata
            regime VARCHAR
        )
    """)
    
    conn.close()
    print(f"✅ Database initialized at {DB_PATH}")

def fetch_context_data(timestamp, symbol="BANKNIFTY"):
    """
    Fetch context for the Brain:
    1. Last 3 Days (Daily Aggregated OHLC)
    2. Last 14 Candles (15-min aggregated)
    3. Today's All Candles (5-min)
    """
    # Standardize symbol to Fyers ticker
    symbol = get_fyers_symbol(symbol)
    # Ensure input timestamp is naive UTC for DB comparison
    if hasattr(timestamp, 'tzinfo') and timestamp.tzinfo is not None:
        ts_utc = timestamp.astimezone(UTC).replace(tzinfo=None)
    else:
        # If naive, assume it was intended as IST and convert
        ts_utc = IST.localize(timestamp).astimezone(UTC).replace(tzinfo=None)
        
    conn = get_connection()
    # print(f"      🔍 DB Context Fetch for {ts_utc} UTC")
    
    # 1. Daily Aggregation (Last 3 Full days before current timestamp)
    daily_query = """
        WITH daily AS (
            SELECT 
                date_trunc('day', timestamp) as date,
                first(open) as open,
                max(high) as high,
                min(low) as low,
                last(close) as close,
                sum(volume) as volume
            FROM candles_5min 
            WHERE symbol = ? AND timestamp < ?
            GROUP BY 1
        )
        SELECT * FROM daily ORDER BY date DESC LIMIT 3
    """
    
    # 2. Last 14 15-min Candles
    # Bucket 5-min candles into 15-min chunks
    intraday_15min_query = """
        SELECT 
            time_bucket(INTERVAL '15 minutes', timestamp) AS ts,
            first(open) as open,
            max(high) as high,
            min(low) as low,
            last(close) as close,
            sum(volume) as volume
        FROM candles_5min
        WHERE symbol = ? AND timestamp <= ?
        GROUP BY 1
        ORDER BY ts DESC 
        LIMIT 14
    """

    # 3. Today's 5-min Candles (from start of day up to Now)
    # CRITICAL: Use DATE() comparison to match simulation day regardless of time
    today_5min_query = """
        SELECT timestamp, open, high, low, close, volume 
        FROM candles_5min 
        WHERE symbol = ? 
          AND DATE(timestamp) = DATE(CAST(? AS TIMESTAMP))
          AND timestamp <= ?
        ORDER BY timestamp ASC
    """
    
    try:
        daily_rows = conn.execute(daily_query, (symbol, ts_utc)).fetchall()
        # 15min rows needs simple query
        last_15min_rows = conn.execute(intraday_15min_query, (symbol, ts_utc)).fetchall()
        # Today 5min
        today_5min_rows = conn.execute(today_5min_query, (symbol, ts_utc, ts_utc)).fetchall()
        
        # VIX Spot: Get the latest VIX reading up to the current simulation time
        vix_query = """
            SELECT close FROM candles_vix 
            WHERE symbol = 'NSE:INDIAVIX-INDEX' AND timestamp <= ? 
            ORDER BY timestamp DESC LIMIT 1
        """
        vix_row = conn.execute(vix_query, (ts_utc,)).fetchone()
        vix_spot = vix_row[0] if vix_row else None
        
        def to_ist(dt):
            if dt is None: return None
            if dt.tzinfo is None:
                dt = UTC.localize(dt)
            return dt.astimezone(IST).strftime('%Y-%m-%d %H:%M:%S')

        context = {
            'daily_3': [
                {'date': str(r[0]), 'o': r[1], 'h': r[2], 'l': r[3], 'c': r[4]} 
                for r in daily_rows[::-1] 
            ],
            'last_15min': [
                {'ts': to_ist(r[0]), 'o': r[1], 'h': r[2], 'l': r[3], 'c': r[4]}
                for r in last_15min_rows[::-1] 
            ],
            'today_5min': [
                {'ts': to_ist(r[0]), 'o': r[1], 'h': r[2], 'l': r[3], 'c': r[4]}
                for r in today_5min_rows
            ],
            'vix_spot': vix_spot
        }
        return context
        
    except Exception as e:
        print(f"❌ DB Context Fetch Error: {e}")
        return {'daily_3': [], 'last_15min': [], 'today_5min': [], 'vix_spot': None}
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()
