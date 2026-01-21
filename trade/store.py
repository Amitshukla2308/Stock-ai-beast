"""
Trade Engine v2.8: Store
SQLite persistence layer. Single responsibility: Store and retrieve trades.
"""
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from data.database import get_connection
from trade.models import Trade, TradeStatus, ExitReason

logger = logging.getLogger(__name__)


class TradeStore:
    """
    Persistence layer for trades.
    No logic. No decisions. Just I/O.
    """
    
    def __init__(self):
        # self._ensure_schema()
        pass
    
    def _ensure_schema(self):
        """Ensure trades table exists with all required columns"""
        conn = get_connection()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    trade_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    style TEXT,
                    direction TEXT,
                    entry_time TEXT,
                    entry_price REAL,
                    sl_price REAL,
                    target_price REAL,
                    quantity INTEGER,
                    confidence REAL,
                    regime TEXT,
                    session_phase TEXT,
                    trend_efficiency REAL,
                    atr REAL,
                    or_range REAL,
                    location TEXT,
                    reason TEXT,
                    status TEXT,
                    exit_time TEXT,
                    exit_price REAL,
                    exit_reason TEXT,
                    bars_held INTEGER,
                    pnl_points REAL,
                    pnl_rupees REAL,
                    mfe REAL,
                    mae REAL,
                    config_hash TEXT,
                    system_version TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
        finally:
            conn.close()
    
    def insert_trade(self, trade: Trade) -> bool:
        """Insert a new trade record"""
        conn = get_connection()
        try:
            conn.execute("""
                INSERT INTO trades (
                    trade_id, session_id, symbol, style, direction,
                    entry_time, entry_price, sl_price, target_price, quantity,
                    confidence, regime, session_phase, trend_efficiency,
                    atr, or_range, location, reason, status,
                    config_hash, system_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade.trade_id,
                trade.session_id,
                trade.symbol,
                trade.style,
                trade.direction,
                trade.entry_time.isoformat() if trade.entry_time else None,
                trade.entry_price,
                trade.sl_price,
                trade.target_price,
                trade.quantity,
                trade.confidence,
                trade.regime,
                trade.session_phase,
                trade.trend_efficiency,
                trade.atr,
                trade.or_range,
                trade.location,
                trade.reason,
                trade.status.value,
                trade.config_hash,
                trade.system_version
            ))
            conn.commit()
            logger.debug(f"[STORE] Inserted trade {trade.trade_id}")
            return True
        except Exception as e:
            logger.error(f"[STORE] Insert failed: {e}")
            return False
        finally:
            conn.close()
    
    def update_trade(self, trade_id: str, fields: Dict[str, Any]) -> bool:
        """Update specific fields of a trade"""
        if not fields:
            return False
        
        set_clause = ", ".join([f"{k} = ?" for k in fields.keys()])
        values = list(fields.values()) + [trade_id]
        
        conn = get_connection()
        try:
            conn.execute(f"UPDATE trades SET {set_clause} WHERE trade_id = ?", values)
            conn.commit()
            logger.debug(f"[STORE] Updated trade {trade_id}")
            return True
        except Exception as e:
            logger.error(f"[STORE] Update failed: {e}")
            return False
        finally:
            conn.close()
    
    def close_trade(self, trade: Trade) -> bool:
        """Update trade with exit data"""
        return self.update_trade(trade.trade_id, {
            "status": trade.status.value,
            "exit_time": trade.exit_time.isoformat() if trade.exit_time else None,
            "exit_price": trade.exit_price,
            "exit_reason": trade.exit_reason.value if trade.exit_reason else None,
            "bars_held": trade.bars_held,
            "pnl_points": trade.pnl_points,
            "pnl_rupees": trade.pnl_rupees,
            "mfe": trade.mfe,
            "mae": trade.mae
        })
    
    def get_open_trades(self, session_id: Optional[str] = None) -> List[Dict]:
        """Get all currently open trades"""
        conn = get_connection()
        try:
            query = "SELECT * FROM trades WHERE status = 'OPEN'"
            if session_id:
                query += f" AND session_id = '{session_id}'"
            cursor = conn.execute(query)
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in rows]
        finally:
            conn.close()
    
    def get_session_trades(self, session_id: str) -> List[Dict]:
        """Get all trades for a session"""
        conn = get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM trades WHERE session_id = ? ORDER BY entry_time",
                (session_id,)
            )
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in rows]
        finally:
            conn.close()


# Global instance
trade_store = TradeStore()
