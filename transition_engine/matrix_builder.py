import pandas as pd
import numpy as np
import os
import argparse

def build_transition_matrix(data_dir="atlas/data", model_dir="atlas/models", version="v1"):
    print(f"🔄 Building Regime Transition Matrix ({version})...")
    
    # 1. Load Data
    states_path = os.path.join(data_dir, "market_states.parquet")
    clusters_path = os.path.join(data_dir, "trade_clusters.parquet")
    
    if not os.path.exists(states_path) or not os.path.exists(clusters_path):
        print("❌ Error: Missing input artifacts (market_states or trade_clusters).")
        return
        
    df_states = pd.read_parquet(states_path)
    df_clusters = pd.read_parquet(clusters_path)
    
    # 2. Merge and Sort (Reconstruct Time Sequence)
    # Market states has timestamp, clusters has mapping
    print("⏳ Reconstructing temporal sequence...")
    df = df_states[['trade_id', 'timestamp']].merge(df_clusters, on='trade_id')
    df = df.sort_values('timestamp')
    
    # 3. Compute Transitions
    print("🔗 Computing transition probabilities...")
    df['next_regime'] = df['cluster_id'].shift(-1)
    
    # Drop N/A (last row)
    df_clean = df.dropna(subset=['next_regime']).copy()
    df_clean['next_regime'] = df_clean['next_regime'].astype(int)
    
    # Aggregate: Count(from -> to)
    counts = (
        df_clean.groupby(['cluster_id', 'next_regime'])
        .size()
        .reset_index(name='count')
    )
    
    # Normalize: P(to | from) = Count(from->to) / Count(from)
    # We group by source regime ('cluster_id') and calculate percentage
    counts["probability"] = (
        counts["count"] /
        counts.groupby("cluster_id")["count"].transform("sum")
    )
    
    # Rename columns for clarity in the artifact
    matrix_df = counts.rename(columns={
        'cluster_id': 'from_regime', 
        'next_regime': 'to_regime'
    })
    
    # 4. Save Artifact
    if not os.path.exists(model_dir):
        os.makedirs(model_dir)
        
    output_filename = f"regime_transition_matrix_{version}.parquet"
    output_path = os.path.join(model_dir, output_filename)
    
    matrix_df.to_parquet(output_path, index=False)
    
    print(f"✅ SUCCESS: Transition Matrix persisted to {output_path}")
    print(f"📊 Matrix Entries: {len(matrix_df)}")
    
    # 5. Quick Diagnostic Preview
    print("\n--- MATRIX SNAPSHOT (Top Transitions) ---")
    print(matrix_df.sort_values('probability', ascending=False).head(10).to_string(index=False))
    
    # Check Integrity (Sum of probs should be ~1.0 for each from_regime)
    sums = matrix_df.groupby('from_regime')['probability'].sum()
    if not np.allclose(sums, 1.0, atol=1e-5):
        print("⚠️ WARNING: Probability sums deviate from 1.0!")
        print(sums[~np.allclose(sums, 1.0, atol=1e-5)])
    else:
        print("✅ INTEGRITY CHECK: Probabilities sum to 1.0 per regime.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", type=str, default="v1", help="Version tag for the artifact")
    args = parser.parse_args()
    
    build_transition_matrix(version=args.version)
