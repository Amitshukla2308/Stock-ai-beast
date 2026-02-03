import sqlite3
import os
import pytz
import json
from datetime import datetime, timedelta

IST = pytz.timezone('Asia/Kolkata')
UTC = pytz.utc

DB_NAME = os.getenv("BEAST_DB_NAME", "trading.db")
DB_PATH = os.path.join("data", DB_NAME)

SYMBOL_MAP = {
    "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
    "NIFTY": "NSE:NIFTY50-INDEX",
    "FINNIFTY": "NSE:FINNIFTY-INDEX"
}

def get_fyers_symbol(symbol):
    """Map internal names to Fyers tickers."""
    return SYMBOL_MAP.get(symbol, symbol)

def get_connection(db_name=None):
    """
    Returns a connection to the SQLite database with busy timeout.
    """
    actual_db = db_name if db_name else DB_NAME
    db_path = os.path.join("data", actual_db)
    db_path = os.path.abspath(db_path)
    
    # Common container paths fallback
    if not os.path.exists(db_path):
        for alt_path in ["/app/data/trading.db", "trading.db", "data/trading.db"]:
            if os.path.exists(alt_path):
                db_path = os.path.abspath(alt_path)
                break
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    # Increase timeout significantly for WSL locks (30s -> 300s)
    # check_same_thread=False allows sharing connection across threads (e.g. logging)
    conn = sqlite3.connect(db_path, timeout=300, check_same_thread=False) 
    conn.row_factory = sqlite3.Row 
    
    # Performance & Concurrency Pragmas (Per Connection)
    conn.execute("PRAGMA synchronous = NORMAL;") 
    # WAL mode is persistent, but setting it ensures we are in the right mode if it was reset
    conn.execute("PRAGMA journal_mode = WAL;")
    
    return conn
    
import time

def init_db():
    conn = get_connection()
    try:
        # 1. Main Trades Table (Row-Level Execution Log - Legacy/Active)
        # Ensure daily_journal exists for Session-Level Summaries
        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_journal (
                session_id TEXT PRIMARY KEY,
                date TEXT,
                symbol TEXT,
                market_state TEXT,
                morning_plan TEXT,
                trades_summary TEXT, -- JSON list of trades
                daily_stats TEXT,
                eod_audit TEXT,
                total_pnl REAL,
                created_at TEXT
            )
        """)
        
        # 2. Knowledge Nuggets (Experiences for RAG)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_nuggets (
                id INTEGER PRIMARY KEY,
                session_id TEXT,
                created_at TEXT,
                category TEXT, -- GOOD / BAD / ORACLE
                condition_tags TEXT,
                lesson TEXT,
                embedding BLOB,
                vix REAL,
                atr REAL,
                regime_id INTEGER,
                call_pnl REAL,
                put_pnl REAL,
                hold_pnl REAL,
                call_mfe REAL,
                call_mae REAL,
                put_mfe REAL,
                put_mae REAL,
                state_vector TEXT -- FULL JSON State + Reasonings
            )
        """)

        # 3. Super Nova v1: Latent Market States
        conn.execute("""
            CREATE TABLE IF NOT EXISTS market_latent_states (
                timestamp TEXT,
                symbol TEXT,
                trend_strength REAL,
                trend_direction INTEGER,
                mean_reversion REAL,
                volatility_regime INTEGER,
                momentum_quality REAL,
                structure_type INTEGER,
                edge_call REAL,
                edge_put REAL,
                edge_hold REAL,
                edge_horizon INTEGER,
                risk_state INTEGER,
                PRIMARY KEY (timestamp, symbol)
            )
        """)

        # 4. Super Nova v1: Oracle Outcomes
        # Ground Truths for Supervised Learning
        conn.execute("""
            CREATE TABLE IF NOT EXISTS oracle_outcomes (
                timestamp TEXT,
                symbol TEXT,
                call_mfe REAL,
                call_mae REAL,
                put_mfe REAL,
                put_mae REAL,
                hold_pnl REAL,
                edge_survival_5 INTEGER,  -- 1 or 0
                edge_survival_10 INTEGER, -- 1 or 0
                PRIMARY KEY (timestamp, symbol)
            )
        """)

        # 5. Market Data (Bootstrap Schema for Fresh Environments)
        # Required for Mock Mode / First-Time Setup on simulation.db
        conn.execute("""
            CREATE TABLE IF NOT EXISTS candles_1min (
                timestamp TEXT,
                symbol TEXT,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                PRIMARY KEY (timestamp, symbol)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS candles_5min (
                timestamp TEXT,
                symbol TEXT,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                PRIMARY KEY (timestamp, symbol)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS candles_15min (
                timestamp TEXT,
                symbol TEXT,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                PRIMARY KEY (timestamp, symbol)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS candles_1day (
                timestamp TEXT,
                symbol TEXT,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                PRIMARY KEY (timestamp, symbol)
            )
        """)
        
        conn.execute("""
            CREATE TABLE IF NOT EXISTS candles_vix (
                timestamp TEXT,
                symbol TEXT,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                PRIMARY KEY (timestamp, symbol)
            )
        """)
        
        conn.commit()
    finally:
        conn.close()

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
    start_30d = (ts_utc - timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
    start_7d = (ts_utc - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
    
    # Debug logs (Clarified Timezones v4.2)
    ts_ist_str = ts_utc.replace(tzinfo=UTC).astimezone(IST).strftime('%Y-%m-%d %H:%M:%S')
    print(f"\n[DB] Fetching context for {symbol} | Target: {ts_str} (UTC) / {ts_ist_str} (IST) | Res: {resolution}")
        
    # Use dynamic DB connection (respects BEAST_DB_NAME env var)
    conn = get_connection()
    
    # Smart Table Detection
    table = "candles_5min" # Default fallback
    if resolution == "1" or resolution == "1min":
        table = "candles_1min"
    elif resolution == "5" or resolution == "5min":
        table = "candles_5min"
    else:
        try:
            res = conn.execute("SELECT 1 FROM candles_1min WHERE symbol = ? LIMIT 1", (symbol,)).fetchone()
            if res:
                table = "candles_1min"
        except:
            pass
    
    # 1. Daily Aggregation
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
    
    # 2. Last 5-min Candles (Warmup for 64D Engine)
    last_5min_query = f"""
        SELECT 
            datetime((strftime('%s', timestamp) / 300) * 300, 'unixepoch') AS bucket,
            open, MAX(high), MIN(low), close, SUM(volume)
        FROM {table}
        WHERE symbol = ? 
          AND timestamp < ?
          AND timestamp > ?
        GROUP BY bucket
        ORDER BY bucket DESC 
        LIMIT 200
    """

    # 3. Last 15-min Candles (Warmup for Parent)
    intraday_query = f"""
        SELECT 
            datetime((strftime('%s', timestamp) / 900) * 900, 'unixepoch') AS bucket,
            open, MAX(high), MIN(low), close, SUM(volume)
        FROM {table}
        WHERE symbol = ? 
          AND timestamp < ?
          AND timestamp > ?
        GROUP BY bucket
        ORDER BY bucket DESC 
        LIMIT 200
    """

    # 4. Today's 5-min Candles
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
    
    # 5. Today's 15-min Candles
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
        
        last_5min_rows = conn.execute(last_5min_query, (symbol, ts_str, start_7d)).fetchall()
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
        vix_pct = 0.0 if (abs(vix_pct) > 100) else vix_pct

        atr_14 = None
        if len(last_15min_rows) >= 15:
            true_ranges = []
            for i in range(len(last_15min_rows) - 1):
                curr = last_15min_rows[i]
                prev = last_15min_rows[i+1]
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
            # Use robust parsing for mixed naive/aware strings
            from dateutil import parser
            dt = parser.parse(ts_val)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(IST).strftime('%Y-%m-%d %H:%M:%S')

        context = {
            'daily_3': [{'date': r[0], 'o': r[1], 'h': r[2], 'l': r[3], 'c': r[4], 'volume': r[5]} for r in daily_rows],
            'last_5min': [{'timestamp': datetime.fromisoformat(r[0]).replace(tzinfo=UTC).astimezone(IST), 'open': r[1], 'high': r[2], 'low': r[3], 'close': r[4], 'volume': r[5]} for r in last_5min_rows[::-1]],
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

def save_experience(session_id, date, symbol, market_state, plan, trades, stats, audit, timestamp, tech_context=None, counterfactuals=None):
    """
    Persist Daily Performance + Sage Wisdom (SPEC-002, Phase 6).
    Writes to 'daily_journal' to avoid conflict with row-level 'trades' table.
    """
    create_ts_str = timestamp.strftime('%Y-%m-%d %H:%M:%S') if hasattr(timestamp, 'strftime') else str(timestamp)
    
    # 1. Prep Data
    nuggets = []
    if audit.get('technical_lesson'): nuggets.append(('SAGE', audit['technical_lesson']))
        
    tags = ",".join([plan.get(k, 'UNKNOWN') for k in ['market_personality', 'vix_regime', 'primary_bias'] if plan])
    vix = tech_context.get('vix') if tech_context else None
    atr = tech_context.get('atr') if tech_context else None
    regime_id = tech_context.get('regime_id') if tech_context else None
    
    c_pnl = counterfactuals.get('call_pnl') if counterfactuals else None
    p_pnl = counterfactuals.get('put_pnl') if counterfactuals else None
    h_pnl = counterfactuals.get('hold_pnl') if counterfactuals else None

    # 2. Persist with Retry Loop
    import random
    max_retries = 5
    for attempt in range(max_retries):
        conn = get_connection()
        try:
            # Main Session Record -> daily_journal
            conn.execute("""
                INSERT INTO daily_journal 
                (session_id, date, symbol, market_state, morning_plan, trades_summary, daily_stats, eod_audit, total_pnl, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (session_id) DO UPDATE SET 
                    total_pnl = excluded.total_pnl,
                    eod_audit = excluded.eod_audit
            """, (session_id, date, symbol, json.dumps(market_state, default=str), json.dumps(plan, default=str), 
                  json.dumps(trades, default=str), json.dumps(stats, default=str), json.dumps(audit, default=str), stats.get('total_pnl', 0.0), create_ts_str))
            
            # Technical Nuggets
            for cat, lesson in nuggets:
                nugget_id = random.randint(1, 2147483647)
                conn.execute("""
                    INSERT INTO knowledge_nuggets 
                    (id, session_id, created_at, category, condition_tags, lesson, vix, atr, regime_id, call_pnl, put_pnl, hold_pnl)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (nugget_id, session_id, create_ts_str, cat, tags, lesson, vix, atr, regime_id, c_pnl, p_pnl, h_pnl))
                
            conn.commit()
            return # Success
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and attempt < max_retries - 1:
                time.sleep((attempt + 1) * random.uniform(0.2, 0.6))
                continue
            if "no such table" in str(e).lower():
                # Lazy Init if table missing (Schema Evolution)
                init_db()
                continue
            print(f"❌ Experience Save Error: {e}")
            break
        except Exception as e:
            print(f"❌ Experience Save Error: {e}")
            break
        finally:
            conn.close()

def save_oracle_outcome(session_id, timestamp, tech_context, counterfactuals):
    """
    Save aligned Training Samples for objective inference (SPEC-002, Phase 7).
    """
    create_ts_str = timestamp.strftime('%Y-%m-%d %H:%M:%S') if hasattr(timestamp, 'strftime') else str(timestamp)
    
    # 1. Prepare Data
    outcomes = {"CALL": counterfactuals.get('CALL_PNL') or -999, "PUT": counterfactuals.get('PUT_PNL') or -999, "HOLD": counterfactuals.get('HOLD', 0.0)}
    winner = max(outcomes, key=outcomes.get)
    regime_id = tech_context.get('regime_id')
    
    aligned_data = {
        "physics": tech_context.get('full_state', {}),
        "reasoning_paths": tech_context.get('full_state', {}).get('parallel_theses', {}),
        "ground_truth": {"winner": winner, "outcomes": outcomes, "metrics": {"call": {"mfe": counterfactuals.get('CALL_MFE'), "mae": counterfactuals.get('CALL_MAE')}, "put": {"mfe": counterfactuals.get('PUT_MFE'), "mae": counterfactuals.get('PUT_MAE')}}}
    }
    state_json = json.dumps(aligned_data, default=str)
    
    # 2. Persist with Retry Loop
    import random
    max_retries = 5
    for attempt in range(max_retries):
        conn = get_connection()
        try:
            nugget_id = random.randint(1, 2147483647)
            conn.execute("""
                INSERT INTO knowledge_nuggets 
                (id, session_id, created_at, category, condition_tags, lesson, vix, atr, regime_id, 
                 call_pnl, put_pnl, hold_pnl, call_mfe, call_mae, put_mfe, put_mae, state_vector)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (nugget_id, session_id, create_ts_str, 'ORACLE', tech_context.get('tags', 'SAGE'), f"WINNER:{winner}_R{regime_id}", 
                  tech_context.get('vix'), tech_context.get('atr'), regime_id, 
                  counterfactuals.get('CALL_PNL'), counterfactuals.get('PUT_PNL'), counterfactuals.get('HOLD', 0.0), 
                  counterfactuals.get('CALL_MFE'), counterfactuals.get('CALL_MAE'), counterfactuals.get('PUT_MFE'), counterfactuals.get('PUT_MAE'), state_json))
            conn.commit()
            return # Success
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and attempt < max_retries - 1:
                wait = (attempt + 1) * random.uniform(0.1, 0.5)
                time.sleep(wait)
                continue
            print(f"❌ Oracle Save Error: {e}")
            break
        except Exception as e:
            print(f"❌ Oracle Save Error: {e}")
            break
        finally:
            conn.close()

def save_latent_state(timestamp, symbol, latent_vector):
    """
    SUPER NOVA v1: Persist Latent Market State
    """
    create_ts_str = timestamp.strftime('%Y-%m-%d %H:%M:%S') if hasattr(timestamp, 'strftime') else str(timestamp)
    
    import random
    max_retries = 5
    for attempt in range(max_retries):
        conn = get_connection()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO market_latent_states
                (timestamp, symbol, trend_strength, trend_direction, mean_reversion, volatility_regime,
                 momentum_quality, structure_type, edge_call, edge_put, edge_hold, edge_horizon, risk_state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (create_ts_str, symbol, 
                  latent_vector.get('trend_strength'), latent_vector.get('trend_direction'),
                  latent_vector.get('mean_reversion'), latent_vector.get('volatility_regime'),
                  latent_vector.get('momentum_quality'), latent_vector.get('structure_type'),
                  latent_vector.get('edge_call'), latent_vector.get('edge_put'), latent_vector.get('edge_hold'),
                  latent_vector.get('edge_horizon'), latent_vector.get('risk_state')))
            conn.commit()
            return # Success
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and attempt < max_retries - 1:
                time.sleep((attempt + 1) * random.uniform(0.1, 0.5))
                continue
            if "no such table" in str(e).lower():
                init_db()
                continue
            print(f"❌ Latent Save Error: {e}")
            break
        except Exception as e:
            print(f"❌ Latent Save Error: {e}")
            break
        finally:
            conn.close()

def save_oracle_truth(timestamp, symbol, outcomes):
    """
    SUPER NOVA v1: Persist Oracle Ground Truth
    """
    create_ts_str = timestamp.strftime('%Y-%m-%d %H:%M:%S') if hasattr(timestamp, 'strftime') else str(timestamp)
    
    import random
    max_retries = 5
    for attempt in range(max_retries):
        conn = get_connection()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO oracle_outcomes
                (timestamp, symbol, call_mfe, call_mae, put_mfe, put_mae, hold_pnl, edge_survival_5, edge_survival_10)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (create_ts_str, symbol, 
                  outcomes.get('call_mfe'), outcomes.get('call_mae'),
                  outcomes.get('put_mfe'), outcomes.get('put_mae'),
                  outcomes.get('hold_pnl'), outcomes.get('edge_survival_5'), outcomes.get('edge_survival_10')))
            conn.commit()
            return # Success
        except sqlite3.OperationalError as e:
             if "locked" in str(e).lower() and attempt < max_retries - 1:
                time.sleep((attempt + 1) * random.uniform(0.1, 0.5))
                continue
             if "no such table" in str(e).lower():
                init_db()
                continue
             print(f"❌ Oracle Truth Save Error: {e}")
             break
        except Exception as e:
            print(f"❌ Oracle Truth Save Error: {e}")
            break
        finally:
            conn.close()

def retrieve_relevant_nuggets(tags: list, cutoff_time: datetime, limit=5):
    """
    Backtest-Safe RAG Retrieval.
    """
    # Format cutoff for SQLite
    if hasattr(cutoff_time, 'tzinfo') and cutoff_time.tzinfo is not None:
        ts_utc = cutoff_time.astimezone(UTC).replace(tzinfo=None)
    else:
        ts_utc = cutoff_time
        
    ts_str = ts_utc.strftime('%Y-%m-%d %H:%M:%S')
    
    conn = get_connection("trading.db")
    try:
        query = """
            SELECT created_at, category, lesson, condition_tags, call_pnl, put_pnl, hold_pnl, vix, regime_id
            FROM knowledge_nuggets
            WHERE created_at < ?
            ORDER BY created_at DESC
            LIMIT ?
        """
        
        rows = conn.execute(query, (ts_str, limit * 3)).fetchall()
        
        nuggets = []
        for r in rows:
            nuggets.append({
                "created_at": r[0],
                "category": r[1],
                "lesson": r[2],
                "tags": r[3],
                "call_pnl": r[4],
                "put_pnl": r[5],
                "hold_pnl": r[6],
                "vix": r[7],
                "regime_id": r[8]
            })
            
        return nuggets[:limit]
        
    except Exception as e:
        print(f"❌ RAG Retrieval Failed: {e}")
        return []
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()
