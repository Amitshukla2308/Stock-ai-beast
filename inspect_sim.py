import duckdb
import pandas as pd
from data.database import get_connection

def inspect_simulations():
    conn = get_connection()
    try:
        print("🔍 Checking Simulation Sessions:")
        sessions = conn.execute("SELECT * FROM simulation_sessions ORDER BY created_at DESC LIMIT 5").fetchdf()
        print(sessions.to_string(index=False))
        
        if not sessions.empty:
            latest_session = sessions.iloc[0]['session_id']
            print(f"\n🔍 Checking Trades for Latest Session: {latest_session}")
            trades_count = conn.execute(f"SELECT COUNT(*) FROM simulation_trades WHERE session_id = '{latest_session}'").fetchone()[0]
            print(f"✅ Total Trades in latest session: {trades_count}")
            
            if trades_count > 0:
                recent_trades = conn.execute(f"SELECT * FROM simulation_trades WHERE session_id = '{latest_session}' ORDER BY timestamp DESC LIMIT 3").fetchdf()
                print("\n🔍 Recent 3 Trades:")
                print(recent_trades.to_string(index=False))
        else:
            print("⚠️ No simulation sessions found in database.")
            
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    inspect_simulations()
