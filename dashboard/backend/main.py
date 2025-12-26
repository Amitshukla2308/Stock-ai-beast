from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import duckdb
import os
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from datetime import datetime, date
import subprocess
import time
import logging
import json

app = FastAPI(title="Stock-AI-Beast Analytics API")

# Enable CORS for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("DB_PATH", "/app/data/trading.db")
SHADOW_DB_DIR = "/tmp/db_shadow"
SHADOW_DB_PATH = os.path.join(SHADOW_DB_DIR, "trading.db")

def _ensure_schema(conn):
    """Ensures that the simulation_sessions table exists to prevent JOIN crashes."""
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS simulation_sessions (
                session_id VARCHAR PRIMARY KEY,
                symbol VARCHAR,
                start_date VARCHAR,
                end_date VARCHAR,
                created_at TIMESTAMP
            )
        """)
    except Exception as e:
        logger.error(f"Schema initialization failed: {e}")

def get_db_conn():
    if not os.path.exists(DB_PATH):
        logger.error(f"❌ DB_PATH not found: {DB_PATH}")
        return None
    
    try:
        # Create shadow directory if missing
        os.makedirs(SHADOW_DB_DIR, exist_ok=True)
        
        # Shadow Copy Strategy using Shell 'cp'
        # Copy both the main DB and the WAL file to ensure consistent state
        if not os.path.exists(SHADOW_DB_PATH) or (time.time() - os.path.getmtime(SHADOW_DB_PATH) > 10):
            logger.info("🔄 Refreshing shadow copy of database...")
            # Use shell=True to support glob patterns (*)
            subprocess.run(f"cp {DB_PATH}* {SHADOW_DB_DIR}/", shell=True, check=True)
        
        logger.info(f"🔌 Connecting to shadow DB: {SHADOW_DB_PATH}")
        # Note: We can't run DDL (CREATE TABLE) in read_only=True mode.
        # So we connect in read-write mode initially to the shadow copy to ensure schema,
        # then proceed.
        conn = duckdb.connect(SHADOW_DB_PATH, read_only=False)
        _ensure_schema(conn)
        return conn
    except Exception as e:
        logger.error(f"💥 Database connection failed: {str(e)}")
        if os.path.exists(SHADOW_DB_PATH):
            try:
                # Fallback to read-only on the shadow if RW fails
                return duckdb.connect(SHADOW_DB_PATH, read_only=True)
            except:
                return None
        return None

class SessionInfo(BaseModel):
    session_id: str
    last_update: Optional[datetime] = None
    trade_count: int
    total_pnl: float

class Trade(BaseModel):
    session_id: str
    timestamp: Optional[datetime] = None
    side: str
    entry_price: float
    exit_price: float
    pnl: float
    reason: str
    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None

class EventLog(BaseModel):
    session_id: str
    timestamp: Optional[datetime] = None
    event_type: str
    content: str

class EODAudit(BaseModel):
    date: str
    trade_count: int
    total_pnl: float
    highest_win: float
    highest_loss: float
    nugget: str

@app.get("/")
async def root():
    return {"status": "online", "db_connected": os.path.exists(DB_PATH)}

@app.get("/sessions", response_model=List[SessionInfo])
async def get_sessions():
    conn = get_db_conn()
    if not conn: return []
    try:
        query = """
            SELECT 
                t.session_id, 
                s.symbol,
                s.start_date,
                s.end_date,
                MAX(t.timestamp) as last_update,
                COUNT(*) as trade_count,
                SUM(t.pnl) as total_pnl
            FROM simulation_trades t
            LEFT JOIN simulation_sessions s ON t.session_id = s.session_id
            WHERE t.session_id IS NOT NULL
            GROUP BY 1, 2, 3, 4
            ORDER BY last_update DESC
        """
        res = conn.execute(query).fetchall()
        return [
            SessionInfo(
                session_id=str(r[0]), 
                symbol=r[1],
                start_date=r[2],
                end_date=r[3],
                last_update=r[4], 
                trade_count=int(r[5]), 
                total_pnl=float(r[6] or 0)
            )
            for r in res
        ]
    except Exception as e:
        logger.error(f"Error in get_sessions: {e}")
        return []
    finally:
        conn.close()

@app.get("/trades/{session_id}", response_model=List[Trade])
async def get_trades(session_id: str):
    conn = get_db_conn()
    if not conn: return []
    try:
        # Explicitly name columns to avoid ordering issues
        query = """
            SELECT session_id, timestamp, side, entry_price, exit_price, pnl, reason, entry_time, exit_time 
            FROM simulation_trades 
            WHERE session_id = ? 
            ORDER BY exit_time ASC
        """
        res = conn.execute(query, (session_id,)).fetchall()
        return [
            Trade(
                session_id=str(r[0]), timestamp=r[1], side=str(r[2]), entry_price=float(r[3] or 0), 
                exit_price=float(r[4] or 0), pnl=float(r[5] or 0), reason=str(r[6] or ""), 
                entry_time=r[7], exit_time=r[8]
            ) for r in res
        ]
    except Exception as e:
        logger.error(f"Error in get_trades: {e}")
        return []
    finally:
        conn.close()

@app.get("/logs/{session_id}", response_model=List[EventLog])
async def get_logs(session_id: str):
    conn = get_db_conn()
    if not conn: return []
    try:
        query = "SELECT session_id, timestamp, event_type, content FROM simulation_logs WHERE session_id = ? ORDER BY timestamp DESC"
        res = conn.execute(query, (session_id,)).fetchall()
        return [
            EventLog(session_id=str(r[0]), timestamp=r[1], event_type=str(r[2]), content=str(r[3] or ""))
            for r in res
        ]
    except Exception as e:
        logger.error(f"Error in get_logs: {e}")
        return []
    finally:
        conn.close()

@app.get("/equity/{session_id}")
async def get_equity_curve(session_id: str):
    conn = get_db_conn()
    if not conn: return []
    try:
        query = "SELECT pnl, exit_time FROM simulation_trades WHERE session_id = ? ORDER BY exit_time ASC"
        res = conn.execute(query, (session_id,)).fetchall()
        
        curve = []
        cumulative = 0
        for pnl, ts in res:
            pnl_val = float(pnl or 0)
            cumulative += pnl_val
            curve.append({
                "time": ts.isoformat() if hasattr(ts, 'isoformat') else str(ts), 
                "pnl": round(cumulative, 2), 
                "trade_pnl": pnl_val
            })
        return curve
    except Exception as e:
        logger.error(f"Error in get_equity_curve: {e}")
        return []
    finally:
        conn.close()

@app.get("/eod-audits/{session_id}", response_model=List[EODAudit])
async def get_eod_audits(session_id: str):
    conn = get_db_conn()
    if not conn: return []
    try:
        # 1. Fetch Daily Stats from trades
        # DuckDB: date_trunc('day', exit_time) OR CAST(exit_time AS DATE)
        stats_query = """
            SELECT 
                CAST(exit_time AS DATE) as trade_date,
                COUNT(*) as count,
                SUM(pnl) as pnl,
                MAX(pnl) as max_win,
                MIN(pnl) as max_loss
            FROM simulation_trades
            WHERE session_id = ? AND exit_time IS NOT NULL
            GROUP BY 1
            ORDER BY 1 DESC
        """
        stats_rows = conn.execute(stats_query, (session_id,)).fetchall()
        
        # 2. Fetch EOD Audits from logs
        # We'll map them by date
        logs_query = """
            SELECT timestamp, content FROM simulation_logs 
            WHERE session_id = ? AND event_type = 'EOD_AUDIT'
            ORDER BY timestamp DESC
        """
        logs_rows = conn.execute(logs_query, (session_id,)).fetchall()
        
        # Map logs by date string
        # Content format might be "Backtest Audit | Day: 2024-01-01 ... Nugget: ..."
        # OR it might be a JSON if brain returned dict.
        nugget_map = {}
        for ts, content in logs_rows:
            d_str = ts.strftime('%Y-%m-%d') if hasattr(ts, 'strftime') else str(ts)[:10]
            nugget = ""
            if "Nugget:" in content:
                nugget = content.split("Nugget:")[-1].strip()
            elif "Audit:" in content:
                 # Fallback to something meaningful if nugget keyword missing
                 nugget = content
            nugget_map[d_str] = nugget

        audits = []
        for r in stats_rows:
            d_str = str(r[0]) # Date
            audits.append(EODAudit(
                date=d_str,
                trade_count=int(r[1]),
                total_pnl=float(r[2] or 0),
                highest_win=float(r[3] or 0),
                highest_loss=float(r[4] or 0),
                nugget=nugget_map.get(d_str, "No nugget recorded.")
            ))
            
        return audits
    except Exception as e:
        logger.error(f"Error in get_eod_audits: {e}")
        return []
    finally:
        conn.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
