import pandas as pd
import numpy as np
import os
import argparse

ALPHA_REGIMES = [9, 11] # Locked per specification

def mine_precursors(model_dir="atlas/models", version="v1"):
    print(f"⛏️ Mining Precursors for Alpha Regimes {ALPHA_REGIMES} ({version})...")
    
    # 1. Load Transition Matrix
    matrix_path = os.path.join(model_dir, f"regime_transition_matrix_{version}.parquet")
    if not os.path.exists(matrix_path):
        print(f"❌ Error: {matrix_path} not found. Run matrix_builder.py first.")
        return
        
    df_matrix = pd.read_parquet(matrix_path)
    
    # 2. Mine 1-Step Precursors (Direct)
    print("⚡ Analyzing Direct (1-Step) Transitions...")
    # Filter for Average -> Alpha
    precursors = df_matrix[df_matrix['to_regime'].isin(ALPHA_REGIMES)].copy()
    
    # Sort by target and probability
    precursors = precursors.sort_values(['to_regime', 'probability'], ascending=[True, False])
    
    # Rank within target group
    precursors['rank'] = precursors.groupby('to_regime')['probability'].rank(ascending=False, method='dense').astype(int)
    
    # Clean up columns
    precursors_1step = precursors.rename(columns={
        'from_regime': 'current_regime',
        'to_regime': 'target_regime',
        'probability': 'p_transition'
    })[['current_regime', 'target_regime', 'p_transition', 'rank']]
    
    # 3. Mine 2-Step Precursors (Indirect)
    # P(Regime_t+2 = Alpha | Regime_t) = Sum( P(Regime_t -> X) * P(X -> Alpha) )
    print("🕵️ Analyzing Indirect (2-Step) Transitions...")
    
    # Logic: Join Matrix(t->t+1) with Matrix(t+1->t+2)
    # We want t+2 to be Alpha
    
    # Left: t -> mid
    # Right: mid -> target (alpha)
    
    step1 = df_matrix.rename(columns={'to_regime': 'mid_regime', 'probability': 'p1'})
    step2 = df_matrix[df_matrix['to_regime'].isin(ALPHA_REGIMES)].rename(columns={
        'from_regime': 'mid_regime', 
        'to_regime': 'target_regime',
        'probability': 'p2'
    })
    
    merged = step1.merge(step2, on='mid_regime')
    merged['p_combined'] = merged['p1'] * merged['p2']
    
    # Group by t -> target
    precursors_2step_raw = merged.groupby(['from_regime', 'target_regime'])['p_combined'].sum().reset_index()
    
    # Rank
    precursors_2step_raw = precursors_2step_raw.sort_values(['target_regime', 'p_combined'], ascending=[True, False])
    precursors_2step_raw['rank'] = precursors_2step_raw.groupby('target_regime')['p_combined'].rank(ascending=False, method='dense').astype(int)
    
    precursors_2step = precursors_2step_raw.rename(columns={
        'from_regime': 'current_regime',
        'p_combined': 'p_transition'
    })[['current_regime', 'target_regime', 'p_transition', 'rank']]
    
    # 4. Save Artifacts
    p1_path = os.path.join(model_dir, f"regime_precursors_{version}.parquet")
    p2_path = os.path.join(model_dir, f"regime_precursors_2step_{version}.parquet")
    
    precursors_1step.to_parquet(p1_path, index=False)
    precursors_2step.to_parquet(p2_path, index=False)
    
    print(f"✅ SUCCESS: 1-Step Precursors saved to {p1_path}")
    print(f"✅ SUCCESS: 2-Step Precursors saved to {p2_path}")
    
    # 5. Preview
    print("\n--- TOP ALPHA PRECURSORS (1-Step) ---")
    print(precursors_1step.head(10).to_string(index=False))
    
    print("\n--- TOP ALPHA PRECURSORS (2-Step) ---")
    print(precursors_2step.head(10).to_string(index=False))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", type=str, default="v1", help="Version tag for the artifact")
    args = parser.parse_args()
    
    mine_precursors(version=args.version)
