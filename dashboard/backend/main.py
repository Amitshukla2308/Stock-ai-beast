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

# Constants
PTS_TO_RUPEES = 27.5  # 1 NIFTY pt = ₹27.5
INITIAL_BALANCE = 30000  # Default starting balance

class SessionInfo(BaseModel):
    session_id: str
    last_update: Optional[datetime] = None
    trade_count: int
    total_pnl: float
    balance_rupees: Optional[float] = None  # Current balance in rupees
    pnl_rupees: Optional[float] = None  # PnL in rupees

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
    max_pnl: Optional[float] = 0.0
    mean_open_pnl: Optional[float] = 0.0

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
    # Frontend expects these specifically
    nugget_good: str
    nugget_bad: str
    bias: str
    feedback: Optional[str] = None


@app.get("/sessions", response_model=List[SessionInfo])
async def get_sessions():
    conn = get_db_conn()
    if not conn: return []
    try:
        # Aggregate stats from trades table
        query = """
            SELECT 
                s.session_id,
                MAX(t.exit_time) as last_update,
                COUNT(t.entry_time) as trade_count,
                COALESCE(SUM(t.pnl), 0) as total_pnl,
                30000 + (COALESCE(SUM(t.pnl), 0) * 27.5) as balance_rupees,
                (COALESCE(SUM(t.pnl), 0) * 27.5) as pnl_rupees
            FROM simulation_sessions s
            LEFT JOIN simulation_trades t ON s.session_id = t.session_id
            GROUP BY s.session_id
            ORDER BY last_update DESC
        """
        rows = conn.execute(query).fetchall()
        return [
            SessionInfo(
                session_id=r[0],
                last_update=r[1] or datetime.now(),
                trade_count=r[2],
                total_pnl=r[3],
                balance_rupees=r[4],
                pnl_rupees=r[5]
            )
            for r in rows
        ]
    except Exception as e:
        logger.error(f"Error fetching sessions: {e}")
        return []
    finally:
        conn.close()

@app.get("/equity/{session_id}")
async def get_equity(session_id: str):
    conn = get_db_conn()
    if not conn: return []
    try:
        # We simulate an equity curve from the trades
        # Or if we have an equity table, use it. 
        # For now, let's build it from trades for robustness if equity table missing
        query = "SELECT entry_time, pnl FROM simulation_trades WHERE session_id = ? ORDER BY entry_time ASC"
        rows = conn.execute(query, (session_id,)).fetchall()
        
        curve = []
        cum_pnl = 0.0
        for r in rows:
            cum_pnl += (r[1] or 0)
            curve.append({
                "time": r[0].strftime("%H:%M:%S") if r[0] else "",
                "pnl": cum_pnl,
                "trade_pnl": r[1]
            })
        return curve
    except Exception as e:
        logger.error(f"Error fetching equity: {e}")
        return []
    finally:
        conn.close()

@app.get("/trades/{session_id}", response_model=List[Trade])
async def get_trades(session_id: str):
    conn = get_db_conn()
    if not conn: return []
    try:
        query = """
            SELECT session_id, timestamp, side, entry_price, exit_price, pnl, reason, 
                   entry_time, exit_time, max_pnl, mean_open_pnl
            FROM simulation_trades 
            WHERE session_id = ? 
            ORDER BY entry_time DESC
        """
        rows = conn.execute(query, (session_id,)).fetchall()
        return [
            Trade(
                session_id=r[0], timestamp=r[1], side=r[2], entry_price=r[3], 
                exit_price=r[4], pnl=r[5], reason=r[6], entry_time=r[7], 
                exit_time=r[8], max_pnl=r[9], mean_open_pnl=r[10]
            )
            for r in rows
        ]
    except Exception as e:
        logger.error(f"Error fetching trades: {e}")
        return []
    finally:
        conn.close()

@app.get("/logs/{session_id}", response_model=List[EventLog])
async def get_logs(session_id: str):
    conn = get_db_conn()
    if not conn: return []
    try:
        query = "SELECT session_id, timestamp, event_type, content FROM simulation_logs WHERE session_id = ? ORDER BY timestamp DESC"
        rows = conn.execute(query, (session_id,)).fetchall()
        return [
            EventLog(session_id=r[0], timestamp=r[1], event_type=r[2], content=r[3])
            for r in rows
        ]
    except Exception as e:
        logger.error(f"Error fetching logs: {e}")
        return []
    finally:
        conn.close()

@app.get("/position-status")
async def get_position_status():
    # Only relevant for live trading, return empty for now or connect to database if needed
    # Assuming valid live status is stored or relayed
    return {"has_position": False}

@app.get("/eod-audits/{session_id}", response_model=List[EODAudit])
async def get_eod_audits(session_id: str):
    conn = get_db_conn()
    if not conn: return []
    try:
        # 1. Fetch Daily Stats from trades
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
        logs_query = """
            SELECT timestamp, content FROM simulation_logs 
            WHERE session_id = ? AND event_type = 'EOD_AUDIT'
            ORDER BY timestamp DESC
        """
        logs_rows = conn.execute(logs_query, (session_id,)).fetchall()
        
        # Map logs by date string
        # Content can be legacy string OR new JSON
        audit_map = {}
        for ts, content in logs_rows:
            d_str = ts.strftime('%Y-%m-%d') if hasattr(ts, 'strftime') else str(ts)[:10]
            
            parsed_data = {
                "nugget_good": "-",
                "nugget_bad": "-",
                "bias": "-",
                "feedback": ""
            }

            try:
                # Try JSON first
                data = json.loads(content)
                
                # 1. Nugget Good / What Worked
                # Priority: nugget_good -> what_went_well -> nugget (fallback)
                parsed_data["nugget_good"] = data.get('nugget_good', data.get('what_went_well', data.get('nugget', '-')))
                
                # 2. Nugget Bad / What Failed
                parsed_data["nugget_bad"] = data.get('nugget_bad', data.get('what_went_wrong', '-'))
                
                # 3. Bias
                # Priority: bias -> derived from bias_efficiency? -> default
                raw_bias = data.get('bias', '-')
                if raw_bias == '-' and 'bias_efficiency' in data:
                    # Heuristic: If we don't have explicit bias, maybe we can't guess, 
                    # but let's at least show the efficiency
                    parsed_data["bias"] = f"EFF:{data['bias_efficiency']}"
                else:
                    parsed_data["bias"] = raw_bias

                # 4. Feedback
                # Priority: final_online_feedback -> audit_summary -> nugget
                parsed_data["feedback"] = data.get('final_online_feedback', data.get('audit_summary', data.get('nugget', '')))
                
            except:
                # Fallback to Text Parsing
                # Example: "PnL:0.0 | 1.0 | Nugget:In COMPLACENT VIX regime..."
                
                # Extract Nugget
                if "Nugget:" in content:
                    raw_nugget = content.split("Nugget:")[-1].strip()
                    parsed_data["nugget_good"] = raw_nugget
                elif "Audit:" in content:
                    parsed_data["nugget_good"] = content
                
                # Extract Bias if present textually
                content_lower = content.lower()
                if "neutral bias" in content_lower:
                    parsed_data["bias"] = "NEUTRAL"
                elif "bullish bias" in content_lower:
                     parsed_data["bias"] = "BULLISH"
                elif "bearish bias" in content_lower:
                     parsed_data["bias"] = "BEARISH"
            
            audit_map[d_str] = parsed_data

        audits = []
        for r in stats_rows:
            d_str = str(r[0]) # Date
            audit_data = audit_map.get(d_str, {
                "nugget_good": "No audit recorded.", 
                "nugget_bad": "-", 
                "bias": "-",
                "feedback": ""
            })
            
            audits.append(EODAudit(
                date=d_str,
                trade_count=int(r[1]),
                total_pnl=float(r[2] or 0),
                highest_win=float(r[3] or 0),
                highest_loss=float(r[4] or 0),
                nugget_good=audit_data["nugget_good"],
                nugget_bad=audit_data["nugget_bad"],
                bias=audit_data["bias"],
                feedback=audit_data["feedback"]
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
