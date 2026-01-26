import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler
import pickle
import os

def run_feature_normalization(data_dir="atlas/data", model_dir="atlas/models"):
    print("🚀 Phase 2: Recalibrating Feature Space (Pruning + Rolling)...")
    
    # 1. Load Data
    states_path = os.path.join(data_dir, "market_states.parquet")
    if not os.path.exists(states_path):
        print(f"❌ Error: {states_path} not found!")
        return
        
    df = pd.read_parquet(states_path)
    
    # Pruned Feature Set (User request: Drop entropy_vol, skew, vol_ratio)
    numeric_cols = [
        'ter', 'dist_or_h', 'dist_or_l', 'mom_slope', 'velocity', 'accel',
        'atr', 'vix', 'or_range', 'entropy_price'
    ]
    
    # 2. Categorical Encoding (loc_class)
    LOC_RANK = {
        'OPTIMAL_S2': 0, 'NEAR_S2': 1,
        'OPTIMAL_S1': 2, 'NEAR_S1': 3,
        'OPTIMAL_BC': 4, 'NEAR_BC': 5,
        'OPTIMAL_PIVOT': 6, 'NEAR_PIVOT': 6,
        'OPTIMAL_TC': 7, 'NEAR_TC': 8,
        'OPTIMAL_R1': 9, 'NEAR_R1': 10,
        'OPTIMAL_R2': 11, 'NEAR_R2': 12,
        'MID_RANGE': 6
    }
    
    print("🧩 Encoding categorical loc_class...")
    df['loc_idx'] = df['loc_class'].map(LOC_RANK).fillna(6).astype(float)
    
    # 3. Global Robust Normalization
    # Expert Insight: Rolling normalization hides regimes. Global Robust Scaling preserves distinct phases.
    print("⚖️ Applying Global RobustScaler (Quantile Range 25-75)...")
    from sklearn.preprocessing import RobustScaler
    
    scaler = RobustScaler()
    
    # Select cols
    X = df[numeric_cols + ['loc_idx']].replace([np.inf, -np.inf], np.nan).fillna(0)
    
    # Fit Transform
    X_scaled = scaler.fit_transform(X)
    
    df_norm = pd.DataFrame(X_scaled, columns=numeric_cols + ['loc_idx'])
    df_norm['trade_id'] = df['trade_id'].values
    
    # 4. Save Artifacts
    if not os.path.exists(model_dir): 
        os.makedirs(model_dir)
    
    norm_path = os.path.join(data_dir, "market_states_normalized.parquet")
    df_norm.to_parquet(norm_path, index=False)
    
    scaler_path = os.path.join(model_dir, "feature_scaler.pkl")
    metadata = {
        'scaler': scaler,
        'features': numeric_cols + ['loc_idx'],
        'loc_map': LOC_RANK,
        'method': 'RobustScaler',
        'version': '2.8.3-ExpertPartition'
    }
    with open(scaler_path, 'wb') as f:
        pickle.dump(metadata, f)
        
    print(f"✅ SUCCESS: Normalized {len(df_norm)} states via RobustScaler.")
    print(f"📊 Features used: {', '.join(numeric_cols + ['loc_idx'])}")
    print(f"💾 Saved normalized state space to {norm_path}")

if __name__ == "__main__":
    run_feature_normalization()
