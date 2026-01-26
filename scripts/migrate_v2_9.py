import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from data.database import get_connection

def migrate():
    conn = get_connection() # Uses retries and timeout
    try:
        cursor = conn.cursor()
        
        # Check existing columns
        cursor.execute("PRAGMA table_info(trades)")
        columns = [info[1] for info in cursor.fetchall()]
        
        if "pnl_edge_death" not in columns:
            print("🛠️ Adding pnl_edge_death column...")
            cursor.execute("ALTER TABLE trades ADD COLUMN pnl_edge_death REAL")
        else:
            print("✅ pnl_edge_death already exists.")
            
        if "etd" not in columns:
            print("🛠️ Adding etd column...")
            cursor.execute("ALTER TABLE trades ADD COLUMN etd REAL")
        else:
            print("✅ etd already exists.")
            
        conn.commit()
        print("✅ Migration Complete.")
    except Exception as e:
        print(f"❌ Migration Failed: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
