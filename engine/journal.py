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
                exit_time TIMESTAMP
            )
        """)
        
        # 2. LLM Decision Log Re-init/Migration
        conn.execute("""
            CREATE TABLE IF NOT EXISTS simulation_logs (
                session_id VARCHAR,
                timestamp TIMESTAMP,
                event_type VARCHAR, -- 'MORNING', 'TACTICAL', 'EOD'
                content VARCHAR     -- JSON string or text summary
            )
        """)

        # 3. SCHEMA MIGRATION: Auto-add session_id if missing (for existing DBs)
        try:
            cols_trades = [r[0] for r in conn.execute("PRAGMA table_info('simulation_trades')").fetchall()]
            if 'session_id' not in cols_trades:
                print("   🛠️ Migrating 'simulation_trades': Adding session_id column...")
                conn.execute("ALTER TABLE simulation_trades ADD COLUMN session_id VARCHAR")
            
            cols_logs = [r[0] for r in conn.execute("PRAGMA table_info('simulation_logs')").fetchall()]
            if 'session_id' not in cols_logs:
                print("   🛠️ Migrating 'simulation_logs': Adding session_id column...")
                conn.execute("ALTER TABLE simulation_logs ADD COLUMN session_id VARCHAR")
        except Exception as e:
            print(f"   ⚠️ Migration Warning: {e}")

        conn.close()

    def log_trade(self, trade):
        """Log a closed trade"""
        conn = get_connection()
        conn.execute("""
            INSERT INTO simulation_trades (
                session_id, timestamp, side, entry_price, exit_price, pnl, reason, entry_time, exit_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            self.session_id,
            datetime.now(), # Log time
            trade['side'],
            trade['entry_price'],
            trade['exit_price'],
            trade['pnl'],
            trade['reason'],
            trade['entry_time'],
            trade['exit_time']
        ))
        conn.close()

    def log_event(self, timestamp, event_type, content):
        """Log an LLM interaction or system event"""
        conn = get_connection()
        import json
        if isinstance(content, dict):
            content = json.dumps(content)
        
        conn.execute("""
            INSERT INTO simulation_logs (session_id, timestamp, event_type, content) 
            VALUES (?, ?, ?, ?)
        """, (self.session_id, timestamp, event_type, content))
        conn.close()
