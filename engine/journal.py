from datetime import datetime
from data.database import get_connection

class Journal:
    def __init__(self, session_id=None):
        self.session_id = session_id or datetime.now().strftime('%Y%m%d_%H%M%S')
        self._init_db()

    def _init_db(self):
        conn = get_connection()
        
        # 1. Trade Log Re-init/Migration
        conn.execute("""
            CREATE TABLE IF NOT EXISTS simulation_trades (
                session_id VARCHAR,
                timestamp TIMESTAMP,
                side VARCHAR,
                entry_price FLOAT,
                exit_price FLOAT,
                pnl FLOAT,
                reason VARCHAR,
                entry_time TIMESTAMP,
                exit_time TIMESTAMP,
                max_pnl FLOAT,
                mean_open_pnl FLOAT
            )
        """)
        
        # 2. LLM Decision Log Re-init/Migration
        conn.execute("""
            CREATE TABLE IF NOT EXISTS simulation_logs (
                session_id VARCHAR,
                timestamp TIMESTAMP,
                event_type VARCHAR, -- 'MORNING', 'TACTICAL', 'EOD'
                content VARCHAR,     -- JSON string or text summary
                market_micro_context VARCHAR, -- JSON
                economic_context VARCHAR      -- JSON
            )
        """)

        # 3. Session Metadata Table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS simulation_sessions (
                session_id VARCHAR PRIMARY KEY,
                symbol VARCHAR,
                start_date VARCHAR,
                end_date VARCHAR,
                created_at TIMESTAMP
            )
        """)

        # 3. SCHEMA MIGRATION: Auto-add session_id if missing (for existing DBs)
        try:
            cols_trades = [r[1] for r in conn.execute("PRAGMA table_info('simulation_trades')").fetchall()]
            if 'session_id' not in cols_trades:
                print("   🛠️ Migrating 'simulation_trades': Adding session_id column...")
                conn.execute("ALTER TABLE simulation_trades ADD COLUMN session_id VARCHAR")
            
            if 'max_pnl' not in cols_trades:
                print("   🛠️ Migrating 'simulation_trades': Adding max_pnl column...")
                conn.execute("ALTER TABLE simulation_trades ADD COLUMN max_pnl FLOAT")
            
            if 'mean_open_pnl' not in cols_trades:
                print("   🛠️ Migrating 'simulation_trades': Adding mean_open_pnl column...")
                conn.execute("ALTER TABLE simulation_trades ADD COLUMN mean_open_pnl FLOAT")

            cols_logs = [r[1] for r in conn.execute("PRAGMA table_info('simulation_logs')").fetchall()]
            if 'session_id' not in cols_logs:
                print("   🛠️ Migrating 'simulation_logs': Adding session_id column...")
                conn.execute("ALTER TABLE simulation_logs ADD COLUMN session_id VARCHAR")
            
            if 'market_micro_context' not in cols_logs:
                print("   🛠️ Migrating 'simulation_logs': Adding market_micro_context column...")
                conn.execute("ALTER TABLE simulation_logs ADD COLUMN market_micro_context VARCHAR")
                
            if 'economic_context' not in cols_logs:
                print("   🛠️ Migrating 'simulation_logs': Adding economic_context column...")
                conn.execute("ALTER TABLE simulation_logs ADD COLUMN economic_context VARCHAR")
        except Exception as e:
            print(f"   ⚠️ Migration Warning: {e}")

        conn.close()

    def log_trade(self, trade):
        """Log a closed trade"""
        conn = get_connection()
        conn.execute("""
            INSERT INTO simulation_trades (
                session_id, timestamp, side, entry_price, exit_price, pnl, reason, entry_time, exit_time, max_pnl, mean_open_pnl
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            self.session_id,
            datetime.now(), # Log time
            trade['side'],
            trade['entry_price'],
            trade['exit_price'],
            trade['pnl'],
            trade['reason'],
            trade['entry_time'],
            trade['exit_time'],
            trade.get('max_pnl', 0),
            trade.get('mean_open_pnl', 0)
        ))
        conn.close()

    def log_event(self, timestamp, event_type, content, micro_context=None, economic_context=None):
        """Log an LLM interaction or system event"""
        conn = get_connection()
        import json
        if isinstance(content, dict):
            # Use default=str to handle non-serializable objects (time, datetime, etc.)
            content = json.dumps(content, default=str)
        
        micro_str = json.dumps(micro_context, default=str) if micro_context else None
        econ_str = json.dumps(economic_context, default=str) if economic_context else None
        
        conn.execute("""
            INSERT INTO simulation_logs (session_id, timestamp, event_type, content, market_micro_context, economic_context) 
            VALUES (?, ?, ?, ?, ?, ?)
        """, (self.session_id, timestamp, event_type, content, micro_str, econ_str))
        conn.close()

    def register_session(self, symbol, start_date, end_date):
        """Register session metadata at the start of a run"""
        conn = get_connection()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO simulation_sessions (session_id, symbol, start_date, end_date, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (self.session_id, symbol, str(start_date), str(end_date), datetime.now()))
        except Exception as e:
            print(f"   ⚠️ Session Registration Error: {e}")
        finally:
            conn.close()
