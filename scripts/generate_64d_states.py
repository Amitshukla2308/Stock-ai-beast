
import pandas as pd
import numpy as np
import logging
import time
from pathlib import Path
from datetime import date as dt_date

# Adjust path to find engine modules
import sys
import os
sys.path.append(os.getcwd())

from data.database import get_connection
from engine.features.physics_engine import PhysicsEngine
from engine.features.calculators import AtlasFeatures

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("sovereign_gen")

def generate_sovereign_dataset():
    """
    Generates the 5-year 64D dataset using the Sovereign Architecture.
    Range: 2021-01-01 to 2025-12-31.
    """
    logger.info("🚀 Starting 64D Sovereign Dataset Generation...")
    start_time = time.time()
    
    # 1. Fetch Raw Data
    logger.info("📦 Fetching raw 5m candles from trading.db...")
    conn = get_connection()
    query = """
    SELECT timestamp, open, high, low, close, volume 
    FROM candles_5min 
    WHERE timestamp >= '2021-01-01' AND timestamp <= '2025-12-31'
    ORDER BY timestamp ASC
    """
    df = pd.read_sql(query, conn)
    conn.close()
    
    if df.empty:
        logger.error("❌ No data found in the specified range!")
        return
        
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    # TZ Correction: DB is UTC, Code expects IST (e.g. 9:15 AM)
    # Convert UTC -> IST -> Naive
    if df['timestamp'].dt.tz is None:
        df['timestamp'] = df['timestamp'].dt.tz_localize('UTC')
        
    df['timestamp'] = df['timestamp'].dt.tz_convert('Asia/Kolkata').dt.tz_localize(None)
    
    logger.info(f"✅ Loaded {len(df)} candles. Range (IST): {df['timestamp'].min()} to {df['timestamp'].max()}")
    
    # DEBUG: Check types
    logger.info(f"Dtypes:\n{df.dtypes}")
    
    # Force generic types to avoid object issues
    cols = ['open', 'high', 'low', 'close', 'volume']
    for c in cols:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    
    logger.info("✅ Forced numeric types.")
    
    # 2. Physics Layer (Geometric Context)
    logger.info("⚛️ Measuring Physics (VWAP, Pivots, Daily Open)...")
    # PhysicsEngine.add_context expects a dataframe and does groupbys.
    # It handles the full dataframe correctly (vectorized).
    df_physics = PhysicsEngine.add_context(df)
    
    # 3. Validation: Check for Warmup Gaps
    # Physics Engine requires previous day for Pivot. First day will have NaNs for Pivot.
    # VWAP starts fresh each day.
    
    # 4. Feature Calculation (64D)
    logger.info("🧠 Calculating 64D Features (AtlasFeatures)...")
    # This might be slow on CPU for 93k rows if not fully vectorized, but AtlasFeatures IS vectorized.
    df_64d = AtlasFeatures.calculate_all(df_physics)
    
    # 5. Post-Processing & Cleanup
    # Fix 'date' column for Parquet (converted to string)
    if 'date' in df_64d.columns:
        df_64d['date'] = df_64d['date'].astype(str)
        
    # Drop rows with NaNs (Warmup period)
    initial_len = len(df_64d)
    df_64d_clean = df_64d.dropna()
    dropped_count = initial_len - len(df_64d_clean)
    
    logger.info(f"🧹 Dropped {dropped_count} rows due to warmup (NaNs). Remaining: {len(df_64d_clean)}")
    
    # Identify 64D columns
    feature_cols = [c for c in df_64d_clean.columns if c.startswith('X')]
    if len(feature_cols) != 64:
        logger.warning(f"⚠️ Warning: Found {len(feature_cols)} feature columns. Expected 64.")
    else:
        logger.info("✅ Verified 64 feature columns (X01-X64).")
    
    # 6. NaN Audit
    nan_counts = df_64d_clean[feature_cols].isna().sum().sum()
    if nan_counts > 0:
        logger.error(f"❌ FATAL: Found {nan_counts} NaNs in feature columns AFTER dropna!")
        return
    else:
        logger.info("✅ NaN Audit Passed: 0 nulls in feature vectors.")
        
    # 7. Save Parquet (5m)
    output_path = Path("atlas/data/sovereign_states_64d.parquet")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df_64d_clean.to_parquet(output_path, index=False)
    logger.info(f"💾 Saved Sovereign 64D Dataset (5m) to {output_path}")

    # ================= 15M GENERATION =================
    logger.info("⚡ Generating 15m Sovereign Dataset (Resampling)...")
    
    # Resample
    df_15m = df.set_index('timestamp').resample('15min').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna().reset_index()
    
    logger.info(f"✅ Resampled {len(df_15m)} 15m candles.")
    
    # Physics 15m
    df_15m_physics = PhysicsEngine.add_context(df_15m)
    
    # Features 15m
    df_15m_64d = AtlasFeatures.calculate_all(df_15m_physics)
    
    # Cleanup 15m
    if 'date' in df_15m_64d.columns:
        df_15m_64d['date'] = df_15m_64d['date'].astype(str)
        
    df_15m_clean = df_15m_64d.dropna()
    
    # Save 15m
    output_path_15 = Path("atlas/data/sovereign_states_64d_15m.parquet")
    df_15m_clean.to_parquet(output_path_15, index=False)
    logger.info(f"💾 Saved Sovereign 64D Dataset (15m) to {output_path_15}")
    
    elapsed = time.time() - start_time
    logger.info(f"💾 Saved Sovereign 64D Dataset to {output_path}")
    logger.info(f"⏱️ Total Time: {elapsed:.2f}s")
    
if __name__ == "__main__":
    try:
        generate_sovereign_dataset()
    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.error(f"FATAL: {e}")
        sys.exit(1)
