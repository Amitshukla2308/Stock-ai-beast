import duckdb
import json
from data.database import get_connection

def scan_brain():
    conn = get_connection()
    try:
        print("\n🧠 BRAIN ACTIVITY LOG (Recent 5 Events)\n" + "="*50)
        # Fetch recent logs
        rows = conn.execute("""
            SELECT timestamp, event_type, content 
            FROM simulation_logs 
            ORDER BY timestamp DESC 
            LIMIT 5
        """).fetchall()
        
        for ts, event, content in rows:
            print(f"\n⏰ {ts} | [{event}]")
            try:
                # Pretty print JSON content
                if isinstance(content, str):
                    data = json.loads(content)
                    print(json.dumps(data, indent=2))
                else:
                    print(content)
            except:
                print(content)
                
    except Exception as e:
        print(f"❌ Error reading logs: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    scan_brain()
