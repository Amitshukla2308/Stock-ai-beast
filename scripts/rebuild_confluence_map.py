
import pandas as pd
import numpy as np
import logging
import joblib
import json
import os
import time
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("rebuild_map")

def rebuild_confluence_map():
    logger.info("🚀 Starting Confluence Map Rebuild (Sovereign Architecture)...")
    start_time = time.time()
    
    # 1. Load Data
    data_dir = Path("atlas/data")
    path_5m = data_dir / "sovereign_states_64d.parquet"
    path_15m = data_dir / "sovereign_states_64d_15m.parquet"
    
    if not path_5m.exists() or not path_15m.exists():
        logger.error("❌ Sovereign datasets not found! Run generate_64d_states.py first.")
        return

    logger.info("📦 Loading datasets...")
    df_5m = pd.read_parquet(path_5m)
    df_15m = pd.read_parquet(path_15m)
    
    # Sort just in case
    df_5m = df_5m.sort_values('timestamp').reset_index(drop=True)
    df_15m = df_15m.sort_values('timestamp').reset_index(drop=True)
    
    # 2. Load Models
    model_dir = Path("atlas/models")
    try:
        logger.info("🧠 Loading Brain Models...")
        scaler = joblib.load(model_dir / "atlas_64d_scaler.joblib")
        pca_bundle = joblib.load(model_dir / "atlas_pca.joblib")
        pca = pca_bundle['model']
        pca_features = pca_bundle['features'] # The 47 Purified Features
        
        kmeans_5m = joblib.load(model_dir / "kmeans_5m.joblib")
        kmeans_15m = joblib.load(model_dir / "kmeans_15m.joblib")
        logger.info(f"✅ Models Loaded. PCA Features: {len(pca_features)}")
    except Exception as e:
        logger.error(f"❌ Failed to load models: {e}")
        return

    # 3. Construct 128D Vector (Vectorized)
    logger.info("🧬 Constructing 128D Feature Matrix (Child + Parent)...")
    
    # Align Parent to Child (Forward Fill / Merge on flooring timestamp)
    # 5m timestamp: 09:20 -> Parent 15m is 09:15 (Closed)? No, Parent is developing or prev loop?
    # Logic in Regime: `latest_15m = df_15m.iloc[-1:]`. It takes the latest available.
    # We will merge based on "Previous 15m Close" to be safe/causal?
    # Actually, verify Regime logic: It uses whatever is passed as `df_15m`.
    # In live `process_tick`, `df_15m` is resampled up to `ts_now`.
    # So we should match `5m` timestamp to the corresponding `15m` bucket.
    
    df_5m['ts_15m'] = df_5m['timestamp'].dt.floor('15min')
    
    # Merge 15m features into 5m
    # Rename 15m cols to P_*
    cols_15m = [c for c in df_15m.columns if c.startswith('X')]
    rename_map = {c: f"P_{c}" for c in cols_15m}
    df_15m_renamed = df_15m[['timestamp'] + cols_15m].rename(columns={'timestamp': 'ts_15m'}).rename(columns=rename_map)
    
    # Merge
    # usage of merge_asof is safer for causality but floor-merge is OK if timestamps align perfectly
    df_merged = pd.merge(df_5m, df_15m_renamed, on='ts_15m', how='left')
    
    # Drop rows where Parent is missing (start of data)
    df_merged = df_merged.dropna(subset=[f"P_{cols_15m[0]}"])
    logger.info(f"✅ Merged Data. Rows: {len(df_merged)}")
    
    # 4. Transform Pipeline
    # Get feature names from scaler
    feature_names_128 = scaler.feature_names_in_
    
    # Extract only needed columns in correct order
    X_128 = df_merged[feature_names_128].fillna(0.0).values
    
    # Scale
    logger.info("⚖️ Scaling...")
    X_128_scaled = scaler.transform(X_128)
    X_128_scaled = np.clip(X_128_scaled, -5.0, 5.0)
    
    # Purify (47D selection)
    logger.info("🧹 Purifying (Correlation Pruning)...")
    col_to_idx = {name: i for i, name in enumerate(feature_names_128)}
    
    # Identify indices for Child and Parent parts of the 47 features
    # pca_features names (e.g. 'X01...') need to map to Child and Parent cols
    child_indices = [col_to_idx[f] for f in pca_features if f in col_to_idx]
    parent_indices = [col_to_idx[f"P_{f}"] for f in pca_features if f"P_{f}" in col_to_idx]
    
    # Creating separate arrays for Child and Parent 36D projection logic?
    # Wait, Regime logic:
    # X_child_purified = X_128_scaled[0, child_indices]
    # X_parent_purified = X_128_scaled[0, parent_indices]
    # X_child_pca = self.pca.transform(X_child_purified)
    
    X_child_purified = X_128_scaled[:, child_indices]
    X_parent_purified = X_128_scaled[:, parent_indices]
    
    # PCA (36D)
    logger.info("📐 PCA Projection (36D)...")
    X_child_pca = pca.transform(X_child_purified)
    X_parent_pca = pca.transform(X_parent_purified)
    
    # Clusters
    logger.info("🏷️ Clustering (KMeans)...")
    c5_labels = kmeans_5m.predict(X_child_pca)
    c15_labels = kmeans_15m.predict(X_parent_pca)
    
    df_merged['c5'] = c5_labels
    df_merged['c15'] = c15_labels
    
    # 5. Outcome Mapping (Oracle Truth)
    logger.info("🔮 Mapping Outcomes (Oracle)...")
    
    # Define Win: Next 60 mins PnL > 0
    # Add lookahead columns
    horizon = 12 # 12 * 5m = 60 mins
    df_merged['close_future'] = df_merged['close'].shift(-horizon)
    df_merged['high_future'] = df_merged['high'].rolling(horizon).max().shift(-horizon)
    df_merged['low_future'] = df_merged['low'].rolling(horizon).min().shift(-horizon)
    
    # Drop last horizon rows
    df_final = df_merged.dropna(subset=['close_future'])
    
    # Calculate Metrics
    # Long
    df_final['pnl_long'] = df_final['close_future'] - df_final['close']
    df_final['mfe_long'] = df_final['high_future'] - df_final['close']
    df_final['mae_long'] = df_final['close'] - df_final['low_future']
    df_final['win_long'] = (df_final['pnl_long'] > 0).astype(int)
    
    # Short
    df_final['pnl_short'] = df_final['close'] - df_final['close_future']
    df_final['mfe_short'] = df_final['close'] - df_final['low_future']
    df_final['mae_short'] = df_final['high_future'] - df_final['close']
    df_final['win_short'] = (df_final['pnl_short'] > 0).astype(int)
    
    # 6. Aggregation
    logger.info("📊 Aggregating Confluence Map...")
    
    stats_long = df_final.groupby(['c15', 'c5']).agg(
        count=('win_long', 'count'),
        win_rate_long=('win_long', 'mean'),
        avg_mfe_long=('mfe_long', 'mean'),
        avg_mae_long=('mae_long', 'mean'),
        expectancy_long=('pnl_long', 'mean')
    ).reset_index()
    
    stats_short = df_final.groupby(['c15', 'c5']).agg(
        count=('win_short', 'count'),
        win_rate_short=('win_short', 'mean'),
        avg_mfe_short=('mfe_short', 'mean'),
        avg_mae_short=('mae_short', 'mean'),
        expectancy_short=('pnl_short', 'mean')
    ).reset_index()
    
    # 7. Format Output
    long_edges = stats_long[stats_long['win_rate_long'] > 0.45].to_dict('records') # Only keep actionable?
    # User requested full map, but registry uses > 0.45 to act. 
    # Let's keep all significant edges (count > 5?)
    long_edges = stats_long[stats_long['count'] >= 10].to_dict('records')
    short_edges = stats_short[stats_short['count'] >= 10].to_dict('records')
    
    # Rename for JSON compatibility with registry
    for e in long_edges:
        e['cluster_15m'] = int(e['c15'])
        e['cluster_5m'] = int(e['c5'])
        del e['c15'], e['c5']
        
    for e in short_edges:
        e['cluster_15m'] = int(e['c15'])
        e['cluster_5m'] = int(e['c5'])
        del e['c15'], e['c5']
        
    output = {
        "metadata": {
            "version": "Sovereign-64D-2025",
            "timestamp": str(pd.Timestamp.now()),
            "description": "Rebuilt on 2021-2025 Sovereign Data",
            "total_rows_processed": len(df_final)
        },
        "long_edges": long_edges,
        "short_edges": short_edges
    }
    
    output_path = model_dir / "confluence_map_sovereign.json"
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=4)
        
    logger.info(f"✅ Rebuild Complete! Saved to {output_path}")
    logger.info(f"Long Edges: {len(long_edges)} | Short Edges: {len(short_edges)}")
    logger.info(f"⏱️ Total Time: {time.time() - start_time:.2f}s")
    
if __name__ == "__main__":
    try:
        rebuild_confluence_map()
    except Exception as e:
        import traceback
        traceback.print_exc()
