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
            FROM candles_1min 
            WHERE symbol = ? AND timestamp < ?
            GROUP BY 1
        )
        SELECT * FROM daily ORDER BY date DESC LIMIT 3
    """
    
    # 2. Last 14 15-min Candles
    intraday_15min_query = """
        SELECT 
            time_bucket(INTERVAL '15 minutes', timestamp) AS ts,
            first(open) as open,
            max(high) as high,
            min(low) as low,
            last(close) as close,
            sum(volume) as volume
        FROM candles_1min
        WHERE symbol = ? AND timestamp <= ?
        GROUP BY 1
        ORDER BY ts DESC 
        LIMIT 20
    """

    # 3. Today's 5-min Candles (Aggregated from 1min)
    today_5min_query = """
        SELECT 
            time_bucket(INTERVAL '5 minutes', timestamp) AS ts,
            first(open) as open,
            max(high) as high,
            min(low) as low,
            last(close) as close,
            sum(volume) as volume
        FROM candles_1min 
        WHERE symbol = ? 
          AND DATE(timestamp) = DATE(CAST(? AS TIMESTAMP))
          AND timestamp <= ?
        GROUP BY 1
        ORDER BY ts ASC
    """
    
    # 4. Today's 15-min Candles (Aggregated from 1min)
    today_15min_query = """
        SELECT 
            time_bucket(INTERVAL '15 minutes', timestamp) AS ts,
            first(open) as open,
            max(high) as high,
            min(low) as low,
            last(close) as close,
            sum(volume) as volume
        FROM candles_1min 
        WHERE symbol = ? 
          AND DATE(timestamp) = DATE(CAST(? AS TIMESTAMP))
          AND timestamp <= ?
        GROUP BY 1
        ORDER BY ts ASC
    """
    
    try:
        daily_rows = conn.execute(daily_query, (symbol, ts_utc)).fetchall()
        # 15min rows needs simple query
        last_15min_rows = conn.execute(intraday_15min_query, (symbol, ts_utc)).fetchall()
        # Today 5min
        today_5min_rows = conn.execute(today_5min_query, (symbol, ts_utc, ts_utc)).fetchall()
        # Today 15min (for tactical decisions)
        today_15min_rows = conn.execute(today_15min_query, (symbol, ts_utc, ts_utc)).fetchall()
        
        # VIX Spot: Get the latest VIX reading up to the current simulation time
        # VIX Spot & Delta
        vix_query = """
            SELECT close FROM candles_vix 
            WHERE symbol = 'NSE:INDIAVIX-INDEX' AND timestamp <= ? 
            ORDER BY timestamp DESC LIMIT 2
        """
        vix_rows = conn.execute(vix_query, (ts_utc,)).fetchall()
        vix_spot = vix_rows[0][0] if len(vix_rows) > 0 else None
        vix_prev = vix_rows[1][0] if len(vix_rows) > 1 else vix_spot
        vix_pct = round(((vix_spot - vix_prev) / vix_prev * 100), 2) if vix_spot and vix_prev else 0.0

        # --- CALCULATE ATR & CURRENT RANGE ---
        # 1. ATR_14 (using 15-min candles with Wilder's True Range)
        atr_14 = None
        if len(last_15min_rows) >= 15:  # Need 15 to get 14 true ranges
            true_ranges = []
            for i in range(1, len(last_15min_rows)):
                curr = last_15min_rows[i]
                prev = last_15min_rows[i-1]
                high = curr[2]
                low = curr[3]
                prev_close = prev[4]
                # True Range = max(H-L, |H-PrevClose|, |L-PrevClose|)
                tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
                true_ranges.append(tr)
            # ATR = average of last 14 true ranges
            atr_14 = round(sum(true_ranges[-14:]) / 14, 2)
        
        # 2. Current Range (High-Low of last 3 15-min candles of today)
        current_range = None
        vol_ratio = 100.0
        if today_15min_rows:
            # Use last 3 (or fewer if early in day) 15-min candles
            recent_15min = today_15min_rows[-3:] if len(today_15min_rows) >= 3 else today_15min_rows
            range_high = max(r[2] for r in recent_15min)  # Highest high
            range_low = min(r[3] for r in recent_15min)   # Lowest low
            current_range = round(range_high - range_low, 2)
        
        # 3. Last 2 5-min closes for breakout confirmation
        last_2_5min_closes = []
        if len(today_5min_rows) >= 2:
            last_2_5min_closes = [today_5min_rows[-2][4], today_5min_rows[-1][4]]
        elif len(today_5min_rows) == 1:
            last_2_5min_closes = [today_5min_rows[-1][4]]
            
        # Volume SMA Ratio (Last 10 5-min candles)
        if today_5min_rows:
            last_tick = today_5min_rows[-1]
            if len(today_5min_rows) >= 10:
                recent_vols = [r[5] for r in today_5min_rows[-10:]]
                vol_sma = sum(recent_vols) / len(recent_vols)
                if vol_sma > 0:
                    vol_ratio = round((last_tick[5] / vol_sma) * 100, 1)

        # 4. Relative Volatility (ATR as % of price)
        vol_regime = "NORMAL"
        volatility_pct = 0.0
        if atr_14 and today_5min_rows:
            price = today_5min_rows[-1][4]
            volatility_pct = (atr_14 / price) * 100
            if volatility_pct < 0.05: vol_regime = "LOW"
            elif volatility_pct > 0.15: vol_regime = "HIGH"
        
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
            'today_15min': [
                {'ts': to_ist(r[0]), 'o': r[1], 'h': r[2], 'l': r[3], 'c': r[4]}
                for r in today_15min_rows
            ],
            'vix_spot': vix_spot,
            'vix_pct': vix_pct,
            'atr_14': atr_14,
            'current_range': current_range,
            'vol_ratio': vol_ratio,
            'vol_regime': vol_regime,
            'last_2_5min_closes': last_2_5min_closes
        }
        return context
        
    except Exception as e:
        print(f"❌ DB Context Fetch Error: {e}")
        return {'daily_3': [], 'last_15min': [], 'today_5min': [], 'today_15min': [], 'vix_spot': None, 'atr_14': None, 'current_range': None, 'vol_regime': 'NORMAL'}
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()
