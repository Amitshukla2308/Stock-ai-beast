import pandas as pd
import numpy as np
import os

class FeatureBuilder:
    def __init__(self, data_dir="atlas/data", model_dir="atlas/models", transition_version="v1"):
        self.data_dir = data_dir
        self.model_dir = model_dir
        
        # Load Artifacts
        self.df_clusters = pd.read_parquet(os.path.join(data_dir, "trade_clusters.parquet"))
        self.df_states = pd.read_parquet(os.path.join(data_dir, "market_states.parquet"))
        
        # Load Transition Matrix for Priors
        matrix_path = os.path.join(model_dir, f"regime_transition_matrix_{transition_version}.parquet")
        self.df_matrix = pd.read_parquet(matrix_path)
        self.p_lookup = self.df_matrix.set_index(['from_regime', 'to_regime'])['probability'].to_dict()

    def build_dataset(self, target_regimes=[11, 9], lookahead_k=3):
        print(f"🏗️ Building Dataset for Pre-Alpha Warning (Target={target_regimes}, K={lookahead_k})...")
        
        # 1. Merge and Sort
        df = self.df_states[['trade_id', 'timestamp']].merge(self.df_clusters, on='trade_id')
        df = df.sort_values('timestamp').reset_index(drop=True)
        
        # 2. Lag Features (History)
        # R_t, R_t-1, R_t-2
        df['R_t'] = df['cluster_id']
        df['R_t-1'] = df['cluster_id'].shift(1).fillna(-1).astype(int)
        df['R_t-2'] = df['cluster_id'].shift(2).fillna(-1).astype(int)
        
        # 3. Transition Priors (Structural)
        # P(R_t -> 11), P(R_t -> 9)
        def get_prior(row, target):
            return self.p_lookup.get((row['R_t'], target), 0.0)
            
        df['prior_to_11'] = df.apply(lambda x: get_prior(x, 11), axis=1)
        df['prior_to_9'] = df.apply(lambda x: get_prior(x, 9), axis=1)
        
        # 4. Target Construction (Future)
        # Y=1 if any of next K regimes in target_regimes
        indexer = pd.api.indexers.FixedForwardWindowIndexer(window_size=lookahead_k)
        
        # Create rolling window looking forward
        # We need a custom roll, but for simplicity/speed with pandas:
        # We check if future contains target.
        # Efficient way: Inverse logic or simple shift loop
        
        df['target'] = 0
        for i in range(1, lookahead_k + 1):
            next_r = df['cluster_id'].shift(-i)
            hit = next_r.isin(target_regimes).astype(int)
            df['target'] = np.maximum(df['target'], hit)
            
        # Drop NaN (end of stream)
        df_clean = df.dropna().copy()
        
        # Select Features
        feature_cols = ['R_t', 'R_t-1', 'R_t-2', 'prior_to_11', 'prior_to_9']
        X = df_clean[feature_cols]
        y = df_clean['target']
        
        print(f"✅ Features Built: {X.shape}")
        print(f"📊 Class Balance: {y.mean():.2%} positive samples")
        
        return X, y

if __name__ == "__main__":
    fb = FeatureBuilder()
    X, y = fb.build_dataset()
