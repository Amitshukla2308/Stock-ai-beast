"""
Project Atlas: Cluster Engine (Offline)
Purpose:
Discover empirical market regimes by clustering the State Vector space.
Input: atlas/data/states_*.parquet
Output: atlas/atomic_clusters.pkl

Logic:
1. Load State Vectors (Parquet).
2. Normalize (Z-Score).
3. Dimensionality Reduction (UMAP/PCA) - Optional.
4. Clustering (HDBSCAN or KMeans).
5. Labeling (Assign Cluster ID to every row).
"""

import os
import pandas as pd
import glob
import pickle
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans

class ClusterEngine:
    def __init__(self, data_dir="atlas/data"):
        self.data_dir = data_dir
        self.scaler = StandardScaler()
        
    def load_data(self):
        """
        Load all state logs into one DataFrame. Supports Parquet.
        """
        files = glob.glob(os.path.join(self.data_dir, "states_*.parquet"))
        if not files:
            print("⚠️ No Atlas Parquet data found.")
            return None
            
        dfs = []
        for f in files:
            try:
                df = pd.read_parquet(f)
                dfs.append(df)
            except Exception as e:
                print(f"Error reading {f}: {e}")
                
        if not dfs: return None
        
        master_df = pd.concat(dfs, ignore_index=True)
        print(f"✅ Loaded {len(master_df)} market states.")
        return master_df

    def run_clustering(self):
        """
        Run clustering on loaded state vectors.
        """
        df = self.load_data()
        if df is None: return
        
        # Features to cluster on (Must match state_logger.py)
        features = [
            'ter', 'mom_slope', 'atr', 'or_range', 'vol_ratio',
            'entropy_price', 'entropy_vol', 'velocity', 'accel', 'skew',
            'dist_or_h', 'dist_or_l'
        ]
        
        # Filter available columns
        valid_cols = [c for c in features if c in df.columns]
        X = df[valid_cols].fillna(0)
        
        print(f"🔬 Scaling {len(valid_cols)} features...")
        X_scaled = self.scaler.fit_transform(X)
        
        print("🔬 Clustering using KMeans (Default)...")
        # Fallback to KMeans if HDBSCAN not installed or for initial discovery
        clusterer = KMeans(n_clusters=8, random_state=42, n_init=10)
        labels = clusterer.fit_predict(X_scaled)
        
        df['cluster_id'] = labels
        
        # Save results
        output_path = os.path.join(self.data_dir, "clustered_states.pkl")
        df.to_pickle(output_path)
        
        # Save scaler for online inference later
        scaler_path = os.path.join(self.data_dir, "atlas_scaler.pkl")
        with open(scaler_path, 'wb') as f:
            pickle.dump(self.scaler, f)
            
        print(f"✅ Clustering complete. Results saved to {output_path}")
        return df

if __name__ == "__main__":
    engine = ClusterEngine()
    engine.run_clustering()
