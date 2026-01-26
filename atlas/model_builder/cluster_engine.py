import pandas as pd
import numpy as np
from sklearn.cluster import KMeans
import joblib
import json
import os

def run_clustering(data_dir="atlas/data", model_dir="atlas/models", k=12):
    print(f"🧬 Phase 4: Clustering & Profiling (The Grand Partition K={k})...")
    
    # 1. Load Scaled Data (Normalized, not just Embedded)
    # The Profiler used Normalized Parquet directly.
    # The Benchmark used Embedded.
    # Standardizing on Normalized for Profiling to access features for DNA, 
    # BUT for consistent distance, we should usually cluster on Embedding.
    # However, to preserve the exact logic of "The Grand Partition" succesful run:
    # atlas_profiler.py used: data_path="atlas/data/market_states_normalized.parquet".
    # So we stick to that source.
    
    norm_path = os.path.join(data_dir, "market_states_normalized.parquet")
    if not os.path.exists(norm_path):
        print(f"❌ Error: {norm_path} not found!")
        return
        
    df = pd.read_parquet(norm_path)
    
    # Ensure X only contains features (drop trade_id and any existing regime_id)
    features = [c for c in df.columns if c not in ['trade_id', 'regime_id', 'cluster_id']]
    X = df[features].values
    
    # 2. Final K-Means Fit (Stable Voronoi Partition)
    print(f"⚡ Partitioning space into {k} regions via KMeans...")
    km = KMeans(n_clusters=k, init='k-means++', n_init=10, random_state=42)
    regime_ids = km.fit_predict(X)
    
    # Store IDs for processing
    df['regime_id'] = regime_ids
    
    # 3. Calculate Regime DNA (Centroids & Stats)
    print("🧬 Generating Regime DNA Profiles...")
    orig_path = os.path.join(data_dir, "market_states.parquet")
    if not os.path.exists(orig_path):
        print("❌ Original market states not found.")
        return
        
    df_orig = pd.read_parquet(orig_path)
    df_orig['regime_id'] = regime_ids
    
    regime_profiles = {}
    
    for r_id in range(k):
        subset = df_orig[df_orig['regime_id'] == r_id]
        if subset.empty:
            continue
            
        # Capture the DNA of this regime
        profile = {
            "avg_vix": round(subset['vix'].mean(), 2),
            "avg_velocity": round(subset['velocity'].mean(), 4),
            "avg_entropy": round(subset['entropy_price'].mean(), 4),
            "vol_ratio": round(subset['vol_ratio'].mean(), 2) if 'vol_ratio' in subset.columns else 0.0,
            "sample_count": int(len(subset)),
            "dominating_action": str(subset['action'].mode()[0]) if not subset['action'].mode().empty else "NONE"
        }
        regime_profiles[f"Regime_{r_id}"] = profile
        
    # 4. Save Artifacts
    if not os.path.exists(model_dir): 
        os.makedirs(model_dir)
    
    # Save the model
    model_path = os.path.join(model_dir, "nifty_kmeans_model.pkl")
    joblib.dump(km, model_path)
    
    # Save the Profile JSON for RAG
    profile_path = os.path.join(model_dir, "regime_profiles.json")
    with open(profile_path, "w") as f:
        json.dump(regime_profiles, f, indent=4)
        
    # Save mapping for Profit Mapper Phase
    # profit_mapper expects 'cluster_id' and 'trade_id' in trade_clusters.parquet
    mapping_df = pd.DataFrame({'trade_id': df['trade_id'], 'cluster_id': df['regime_id']})
    mapping_path = os.path.join(data_dir, "trade_clusters.parquet")
    mapping_df.to_parquet(mapping_path, index=False)
        
    print(f"✅ SUCCESS: {k} Regimes profiled.")
    print(f"💾 Model saved to: {model_path}")
    print(f"💾 Profiles saved to: {profile_path}")
    print(f"💾 Mapping saved to: {mapping_path}")
    
    # Quick Preview
    print("\n--- REGIME PREVIEW ---")
    for rid, p in list(regime_profiles.items())[:5]:
        print(f"{rid}: VIX={p['avg_vix']} | Count={p['sample_count']} | Action={p['dominating_action']}")

if __name__ == "__main__":
    run_clustering(k=12)
