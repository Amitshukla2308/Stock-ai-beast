"""
Super Nova v1: Cluster Engine (Atlas v2)
Unsupervised Learning of Market Regimes from Latent States.
Maps Latent Vectors -> Empirical Regime IDs -> Probability Tables.
"""
import pandas as pd
import numpy as np
import json
import joblib
import os
import logging
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Feature Definition (Must match Latent Encoder Schema)
FEATURES = [
    'trend_strength', 'trend_direction', 'mean_reversion', 
    'volatility_regime', 'momentum_quality', 'structure_type',
    'edge_call', 'edge_put', 'edge_hold', 'risk_state'
]

def train_cluster_model(data_path="atlas_v2/atlas_v2_states.parquet", output_dir="atlas_v2", n_clusters=12):
    """
    Trains K-Means on Latent Vectors and generates Empirical Probability Map.
    """
    try:
        if not os.path.exists(data_path):
            logger.error(f"❌ Dataset not found: {data_path}")
            return
            
        df = pd.read_parquet(data_path)
        logger.info(f"📊 Loaded {len(df)} samples for clustering.")
        
        if len(df) < 50:
            logger.warning("⚠️ Insufficient data for clustering (<50 samples). Skipping.")
            return

        # 1. Preprocess X
        X = df[FEATURES].fillna(0).values
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        
        # 2. Train K-Means
        logger.info(f"🤖 Training K-Means (K={n_clusters})...")
        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        clusters = kmeans.fit_predict(X_scaled)
        
        df['regime_id'] = clusters
        
        # 3. Calculate Empirical Stats per Cluster (The "Atlas" Map)
        cluster_stats = {}
        
        for regime_id in sorted(df['regime_id'].unique()):
            subset = df[df['regime_id'] == regime_id]
            
            # Outcome Stats
            mean_call_mfe = subset['call_mfe'].mean()
            mean_put_mfe = subset['put_mfe'].mean()
            mean_hold_pnl = subset['hold_pnl'].mean()
            
            # Win Rates (using crude MFE > 20 as "win" for now)
            call_win_rate = (subset['call_mfe'] > 20).mean()
            put_win_rate = (subset['put_mfe'] > 20).mean()
            
            # Dominant Tendency
            tendency = "CHOP"
            if call_win_rate > 0.6: tendency = "BULL"
            elif put_win_rate > 0.6: tendency = "BEAR"
            
            stats = {
                "count": int(len(subset)),
                "tendency": tendency,
                "prob_call_win": float(round(call_win_rate, 3)),
                "prob_put_win": float(round(put_win_rate, 3)),
                "mean_call_mfe": float(round(mean_call_mfe, 1)),
                "mean_put_mfe": float(round(mean_put_mfe, 1)),
                "mean_hold_pnl": float(round(mean_hold_pnl, 1))
            }
            cluster_stats[str(regime_id)] = stats
            logger.info(f"   R{regime_id:02d}: {tendency} (n={len(subset)}) CallWin={call_win_rate:.2f} PutWin={put_win_rate:.2f}")

        # 4. Save Artifacts
        os.makedirs(output_dir, exist_ok=True)
        
        model_path = os.path.join(output_dir, "atlas_v2_model.pkl")
        scaler_path = os.path.join(output_dir, "atlas_v2_scaler.pkl")
        stats_path = os.path.join(output_dir, "atlas_v2_cluster_stats.json")
        
        joblib.dump(kmeans, model_path)
        joblib.dump(scaler, scaler_path)
        
        with open(stats_path, 'w') as f:
            json.dump(cluster_stats, f, indent=2)
            
        logger.info(f"✅ Atlas v2 Model Saved!")
        logger.info(f"   Model: {model_path}")
        logger.info(f"   Stats: {stats_path}")
        
    except Exception as e:
        logger.error(f"❌ Clustering Failed: {e}", exc_info=True)

if __name__ == "__main__":
    train_cluster_model()
