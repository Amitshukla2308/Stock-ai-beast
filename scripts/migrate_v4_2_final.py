
import sqlite3
import logging
from data.database import get_connection

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate():
    conn = get_connection()
    cursor = conn.cursor()
    
    # 1. Update Trades Table
    try:
        logger.info("Migrating 'trades' table...")
        cursor.execute("ALTER TABLE trades ADD COLUMN pnl_edge_death REAL")
        logger.info("Added pnl_edge_death")
    except Exception as e:
        if "duplicate column" in str(e): logger.info("pnl_edge_death already exists")
        else: logger.warning(f"Error adding pnl_edge_death: {e}")

    try:
        cursor.execute("ALTER TABLE trades ADD COLUMN etd REAL")
        logger.info("Added etd")
    except Exception as e:
        if "duplicate column" in str(e): logger.info("etd already exists")
        else: logger.warning(f"Error adding etd: {e}")
        
    # 2. Update Knowledge Nuggets Table (Sage v3 Schema)
    nugget_columns = [
        ("action", "TEXT"),
        ("confidence", "REAL"),
        ("call_pnl", "REAL"),
        ("put_pnl", "REAL"),
        ("hold_pnl", "REAL"),
        ("outcome", "TEXT")
    ]
    
    logger.info("Migrating 'knowledge_nuggets' table...")
    for col, dtype in nugget_columns:
        try:
            cursor.execute(f"ALTER TABLE knowledge_nuggets ADD COLUMN {col} {dtype}")
            logger.info(f"Added {col}")
        except Exception as e:
            if "duplicate column" in str(e): logger.info(f"{col} already exists")
            else: logger.warning(f"Error adding {col}: {e}")

    conn.commit()
    conn.close()
    logger.info("✅ Migration V4.2 Complete")

if __name__ == "__main__":
    migrate()
