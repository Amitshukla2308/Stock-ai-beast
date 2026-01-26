
import sqlite3
import logging
from data.database import get_connection

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate():
    conn = get_connection()
    cursor = conn.cursor()
    
    # Missing columns for Knowledge Nuggets (Sage v3 / Spec-002)
    missing_columns = [
        ("vix", "REAL"),
        ("atr", "REAL"),
        ("regime_id", "INTEGER"),
        ("call_mfe", "REAL"),
        ("call_mae", "REAL"),
        ("put_mfe", "REAL"),
        ("put_mae", "REAL"),
        ("state_vector", "TEXT")
    ]
    
    logger.info("Migrating 'knowledge_nuggets' table (Supplemental)...")
    for col, dtype in missing_columns:
        try:
            cursor.execute(f"ALTER TABLE knowledge_nuggets ADD COLUMN {col} {dtype}")
            logger.info(f"Added {col}")
        except Exception as e:
            if "duplicate column" in str(e): logger.info(f"{col} already exists")
            else: logger.warning(f"Error adding {col}: {e}")

    conn.commit()
    conn.close()
    logger.info("✅ Migration V4.2 Supplemental Complete")

if __name__ == "__main__":
    migrate()
