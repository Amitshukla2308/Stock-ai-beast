import sqlite3
import os
import json

def show_recent_nuggets():
    db_path = "data/trading.db"
    if not os.path.exists(db_path):
        print(f"❌ Database not found at {db_path}")
        return
        
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        query = "SELECT id, created_at, category, regime_id, lesson FROM knowledge_nuggets ORDER BY created_at DESC LIMIT 5;"
        rows = conn.execute(query).fetchall()
        
        if not rows:
            print("📭 No nuggets found in the database.")
            return
            
        print("\n" + "="*80)
        print("🧠 RECENT KNOWLEDGE NUGGETS (LAST 5)")
        print("="*80)
        
        for r in rows:
            print(f"[{r['created_at']}] ID: {r['id']} | CAT: {r['category']} | REGIME: {r['regime_id']}")
            print(f"💡 LESSON: {r['lesson']}")
            print("-" * 80)
            
    except Exception as e:
        print(f"❌ Error fetching nuggets: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    show_recent_nuggets()
