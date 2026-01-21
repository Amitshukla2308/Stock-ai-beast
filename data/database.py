import sqlite3
import os
import pytz
import json
from datetime import datetime, timedelta

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
    Returns a connection to the SQLite database with busy timeout.
    """
    db_path = os.path.abspath(DB_PATH)
    
    # Common container paths fallback
    if not os.path.exists(db_path):
        for alt_path in ["/app/data/trading.db", "trading.db", "data/trading.db"]:
            if os.path.exists(alt_path):
                db_path = os.path.abspath(alt_path)
                break

    # Ensure directory exists
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    conn = sqlite3.connect(db_path, timeout=30) 
    conn.row_factory = sqlite3.Row 
    
    return conn

def init_db():
    """
    Initialize the database schema for SQLite.
    """
    conn = get_connection()
    
    # 5-minute candles table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS candles_5min (
            timestamp TIMESTAMP,
            symbol TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            PRIMARY KEY (timestamp, symbol)
        )
    """)
    
    # 1-minute candles table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS candles_1min (
            timestamp TIMESTAMP,
            symbol TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            PRIMARY KEY (timestamp, symbol)
        )
    """)

    # India VIX candles table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS candles_vix (
            timestamp TIMESTAMP,
            symbol TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            PRIMARY KEY (timestamp, symbol)
        )
    """)

    # 1-day candles table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS candles_1day (
            timestamp TIMESTAMP,
            symbol TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            PRIMARY KEY (timestamp, symbol)
        )
    """)
    
    # Experience Replay Table (for RL/SFT)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS experience_replay (
            session_id TEXT PRIMARY KEY,
            date DATE,
            symbol TEXT,
            market_state TEXT,       -- JSON string
            morning_plan TEXT,       -- JSON string
            trades TEXT,             -- JSON string
            daily_stats TEXT,        -- JSON string
            eod_audit TEXT,          -- JSON string
            total_pnl REAL
        )
    """)

    # Knowledge Nuggets Table (for RAG)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_nuggets (
            id INTEGER PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            session_id TEXT,
            category TEXT,        -- 'GOOD' (Reinforce) or 'BAD' (Avoid)
            condition_tags TEXT,  -- e.g., "GAP_UP, HIGH_VIX, TRENDING"
            lesson TEXT,             -- The actual text nugget
            embedding BLOB           -- Placeholder for vector embedding
        )
    """)
    
    # Simulation Trades table (Legacy support for modes/backtest.py)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS simulation_trades (
            trade_id TEXT PRIMARY KEY,
            session_id TEXT,
            symbol TEXT,
            side TEXT,
            entry_time TIMESTAMP,
            exit_time TIMESTAMP,
            entry_price REAL,
            exit_price REAL,
            pnl REAL,
            max_pnl REAL,
            mean_open_pnl REAL,
            reason TEXT
        )
    """)

    # Simulation Logs table (Legacy support for modes/backtest.py)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS simulation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            timestamp TIMESTAMP,
            event_type TEXT,
            content TEXT
        )
    """)

    # Enable WAL mode for performance and concurrency
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
    except sqlite3.OperationalError as e:
        print(f"   ⚠️ Could not set WAL mode (Locked): {e}")

    conn.commit()
    conn.close()
    print(f"✅ SQLite Database initialized at {DB_PATH}")

def fetch_context_data(timestamp, symbol="NIFTY", resolution=None):
    """
    Fetch context for the Brain using SQLite compatible queries.
    """
    symbol = get_fyers_symbol(symbol)
    
    # Standardize timestamp to string for SQLite comparison
    if hasattr(timestamp, 'tzinfo') and timestamp.tzinfo is not None:
        ts_utc = timestamp.astimezone(UTC).replace(tzinfo=None)
    else:
        ts_utc = IST.localize(timestamp).astimezone(UTC).replace(tzinfo=None)
    
    ts_str = ts_utc.strftime('%Y-%m-%d %H:%M:%S')
    day_str = ts_utc.strftime('%Y-%m-%d')
    start_30d = (ts_utc - timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
    start_7d = (ts_utc - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
        
    conn = get_connection()
    
    # Detect which table has data for this symbol to avoid expensive UNION
    table = "candles_5min" # Default fallback
    try:
        # Quick check for 1min data
        res = conn.execute("SELECT 1 FROM candles_1min WHERE symbol = ? LIMIT 1", (symbol,)).fetchone()
        if res:
            table = "candles_1min"
    except:
        pass

    # 1. Daily Aggregation (Polyfill for date_trunc)
    daily_query = f"""
        SELECT 
            date(timestamp) as day,
            open, MAX(high), MIN(low), close, SUM(volume)
        FROM {table}
        WHERE symbol = ? 
          AND timestamp < ?
          AND timestamp > ?
        GROUP BY day
        ORDER BY day DESC LIMIT 6
    """
    
    # 2. Last 15-min Candles (Warmup)
    intraday_query = f"""
        SELECT 
            datetime((strftime('%s', timestamp) / 900) * 900, 'unixepoch') AS bucket,
            open, MAX(high), MIN(low), close, SUM(volume)
        FROM {table}
        WHERE symbol = ? 
          AND timestamp <= ?
          AND timestamp > ?
        GROUP BY bucket
        ORDER BY bucket DESC 
        LIMIT 60
    """

    # 3. Today's 5-min Candles (Aggregated)
    today_5min_query = f"""
        SELECT 
            datetime((strftime('%s', timestamp) / 300) * 300, 'unixepoch') AS bucket,
            open, MAX(high), MIN(low), close, SUM(volume)
        FROM {table}
        WHERE symbol = ? 
          AND date(timestamp) = date(?)
          AND timestamp <= ?
        GROUP BY bucket
        ORDER BY bucket ASC
    """
    
    # 4. Today's 15-min Candles (Aggregated)
    today_15min_query = f"""
        SELECT 
            datetime((strftime('%s', timestamp) / 900) * 900, 'unixepoch') AS bucket,
            open, MAX(high), MIN(low), close, SUM(volume)
        FROM {table}
        WHERE symbol = ? 
          AND date(timestamp) = date(?)
          AND timestamp <= ?
        GROUP BY bucket
        ORDER BY bucket ASC
    """
    
    try:
        daily_rows = conn.execute(daily_query, (symbol, ts_str, start_30d)).fetchall()
        last_15min_rows = conn.execute(intraday_query, (symbol, ts_str, start_7d)).fetchall()
        today_5min_rows = conn.execute(today_5min_query, (symbol, ts_str, ts_str)).fetchall()
        today_15min_rows = conn.execute(today_15min_query, (symbol, ts_str, ts_str)).fetchall()
        
        vix_query = """
            SELECT close FROM candles_vix 
            WHERE symbol = 'NSE:INDIAVIX-INDEX' AND timestamp <= ? 
            ORDER BY timestamp DESC LIMIT 2
        """
        vix_rows = conn.execute(vix_query, (ts_str,)).fetchall()
        vix_spot = vix_rows[0][0] if len(vix_rows) > 0 else None
        vix_prev = vix_rows[1][0] if len(vix_rows) > 1 else vix_spot
        vix_pct = round(((vix_spot - vix_prev) / vix_prev * 100), 2) if vix_spot and vix_prev else 0.0

        # ATR & Current Range (Fixed logic: Chronological walk)
        atr_14 = None
        if len(last_15min_rows) >= 15:
            # last_15min_rows is DESC (newest first)
            # tr = max(High - Low, abs(High - PrevClose), abs(Low - PrevClose))
            true_ranges = []
            for i in range(len(last_15min_rows) - 1):
                curr = last_15min_rows[i]   # Newer
                prev = last_15min_rows[i+1] # Older
                tr = max(curr[2] - curr[3], abs(curr[2] - prev[4]), abs(curr[3] - prev[4]))
                true_ranges.append(tr)
            atr_14 = round(sum(true_ranges[:14]) / 14, 2)
        
        day_high = max(r[2] for r in today_5min_rows) if today_5min_rows else None
        day_low = min(r[3] for r in today_5min_rows) if today_5min_rows else None
        
        recent_range = 0
        if today_15min_rows:
            recent_15min = today_15min_rows[-3:]
            recent_range = round(max(r[2] for r in recent_15min) - min(r[3] for r in recent_15min), 2)
        
        last_2_5min_closes = [r[4] for r in today_5min_rows[-2:]] if len(today_5min_rows) >= 2 else ([today_5min_rows[-1][4]] if today_5min_rows else [])
            
        vol_ratio = 100.0
        if today_5min_rows:
            recent_vols = [r[5] for r in today_5min_rows[-10:]]
            vol_sma = sum(recent_vols) / len(recent_vols)
            if vol_sma > 0:
                vol_ratio = round((today_5min_rows[-1][5] / vol_sma) * 100, 1)

        vol_regime = "NORMAL"
        volatility_pct = 0.0
        if daily_rows and atr_14 and today_5min_rows:
            prev_close = daily_rows[0][4]
            price = today_5min_rows[-1][4]
            if prev_close and price:
                volatility_pct = (atr_14 / float(prev_close)) * 100
                if volatility_pct < 0.05: vol_regime = "LOW"
                elif volatility_pct > 0.15: vol_regime = "HIGH"
        
        def to_ist_str(ts_val):
            if ts_val is None: return None
            # SQLite datetime strings are already UTC naive
            dt = datetime.fromisoformat(ts_val).replace(tzinfo=UTC)
            return dt.astimezone(IST).strftime('%Y-%m-%d %H:%M:%S')

        context = {
            'daily_3': [{'date': r[0], 'o': r[1], 'h': r[2], 'l': r[3], 'c': r[4], 'volume': r[5]} for r in daily_rows],
            'last_15min': [{'ts': to_ist_str(r[0]), 'o': r[1], 'h': r[2], 'l': r[3], 'c': r[4], 'volume': r[5]} for r in last_15min_rows[::-1]],
            'today_5min': [{'ts': to_ist_str(r[0]), 'o': r[1], 'h': r[2], 'l': r[3], 'c': r[4], 'volume': r[5]} for r in today_5min_rows],
            'today_15min': [{'ts': to_ist_str(r[0]), 'o': r[1], 'h': r[2], 'l': r[3], 'c': r[4], 'volume': r[5]} for r in today_15min_rows],
            'vix_spot': vix_spot,
            'vix_pct': vix_pct,
            'atr_14': atr_14,
            'day_high': day_high,
            'day_low': day_low,
            'current_range': recent_range,
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

def save_experience(session_id, date, symbol, market_state, plan, trades, stats, audit):
    """
    Save the full day's experience using SQLite.
    """
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO experience_replay 
            (session_id, date, symbol, market_state, morning_plan, trades, daily_stats, eod_audit, total_pnl)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (session_id) DO UPDATE SET 
                total_pnl = excluded.total_pnl,
                eod_audit = excluded.eod_audit
        """, (
            session_id, 
            date, 
            symbol, 
            json.dumps(market_state, default=str), 
            json.dumps(plan, default=str), 
            json.dumps(trades, default=str), 
            json.dumps(stats, default=str), 
            json.dumps(audit, default=str),
            stats.get('total_pnl', 0.0)
        ))
        
        # Extract Nuggets
        nuggets = []
        if audit.get('nugget_good') and audit['nugget_good'] != 'N/A': nuggets.append(('GOOD', audit['nugget_good']))
        if audit.get('nugget_bad') and audit['nugget_bad'] != 'N/A': nuggets.append(('BAD', audit['nugget_bad']))
        
        for item in audit.get('what_went_well', []):
            if isinstance(item, dict) and item.get('lesson'): nuggets.append(('GOOD', item['lesson']))
        for item in audit.get('what_went_wrong', []):
             if isinstance(item, dict) and item.get('lesson'): nuggets.append(('BAD', item['lesson']))

        tags = ",".join([plan.get(k, 'UNKNOWN') for k in ['market_personality', 'vix_regime', 'primary_bias'] if plan])
        
        import random
        for cat, lesson in nuggets:
            nugget_id = random.randint(1, 2147483647)
            conn.execute("""
                INSERT INTO knowledge_nuggets (id, session_id, category, condition_tags, lesson)
                VALUES (?, ?, ?, ?, ?)
            """, (nugget_id, session_id, cat, tags, lesson))
            
        conn.commit()
    except Exception as e:
        print(f"❌ Failed to save experience: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()
