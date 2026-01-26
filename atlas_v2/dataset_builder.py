"""
Super Nova v1: Dataset Builder
Joins Latent Market States (X) with Oracle Ground Truth (y) to create the Atlas v2 Training Set.
"""
import pandas as pd
import sqlite3
import os
import logging
from datetime import datetime

# Setup Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_PATH = os.path.join("data", "trading.db")

def build_dataset(output_path="atlas_v2/atlas_v2_states.parquet"):
    """
    Joins market_latent_states + oracle_outcomes into a single Parquet file.
    """
    try:
        conn = sqlite3.connect(DB_PATH, timeout=60)
        
        logger.info("📡 Fetching Latent States (X)...")
        df_x = pd.read_sql("SELECT * FROM market_latent_states", conn)
        
        logger.info("📡 Fetching Oracle Outcomes (y)...")
        df_y = pd.read_sql("SELECT * FROM oracle_outcomes", conn)
        
        conn.close()
        
        if df_x.empty or df_y.empty:
            logger.warning("⚠️ Empty source tables. Run 'train' mode first to generate data.")
            return
            
        # Convert timestamps to datetime for proper joining
        df_x['timestamp'] = pd.to_datetime(df_x['timestamp'])
        df_y['timestamp'] = pd.to_datetime(df_y['timestamp'])
        
        # Join on Key
        logger.info("🔗 Joining Datasets on (timestamp, symbol)...")
        df_joined = pd.merge(df_x, df_y, on=['timestamp', 'symbol'], how='inner')
        
        if df_joined.empty:
            logger.warning("⚠️ No matching rows found between X and y. Check timestamps.")
            return

        # Feature Engineering (Optional derived columns)
        # e.g. "Edge Winner" Class for supervised learning
        def classify_winner(row):
            outcomes = {'CALL': row['call_mfe'] - row['call_mae'], 'PUT': row['put_mfe'] - row['put_mae'], 'HOLD': row['hold_pnl']}
            # Simple Net PnL proxy (MFE-MAE is crude, but strictly MFE dominance might be better)
            
            # Better Oracle Definition:
            # CALL Win if MFE > 40 and MAE < 20
            # PUT Win if MFE > 40 and MAE < 20
            # ELSE HOLD
            
            call_win = row['call_mfe'] > 40 and row['call_mae'] < 20
            put_win = row['put_mfe'] > 40 and row['put_mae'] < 20
            
            if call_win and not put_win: return 1 # CALL
            if put_win and not call_win: return -1 # PUT
            return 0 # HOLD/CHOP
            
        df_joined['oracle_verdict'] = df_joined.apply(classify_winner, axis=1)

        # Save
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        df_joined.to_parquet(output_path)
        
        logger.info(f"✅ Atlas v2 Dataset Built: {len(df_joined)} samples saved to {output_path}")
        logger.info(f"   Distribution: {df_joined['oracle_verdict'].value_counts().to_dict()}")
        
    except Exception as e:
        logger.error(f"❌ Dataset Build Failed: {e}", exc_info=True)

if __name__ == "__main__":
    build_dataset()
