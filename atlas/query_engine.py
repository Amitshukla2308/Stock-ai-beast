import pandas as pd
import numpy as np
import pickle
import os
import json
import joblib

class AtlasQueryEngine:
    def __init__(self, atlas_dir="atlas"):
        self.model_dir = os.path.join(atlas_dir, "models")
        self.v2_dir = "atlas_v2"
        self.scaler_meta = None
        self.pca_meta = None
        self.cluster_model = None
        self.world_model = None
        
        # V2 Components
        self.v2_model = None
        self.v2_scaler = None
        self.v2_stats = None
        
        self.load_artifacts()

    def load_artifacts(self):
        print("🔧 Loading Atlas World Model components...")
        
        # Load Scaler
        try:
            with open(os.path.join(self.model_dir, "feature_scaler.pkl"), 'rb') as f:
                self.scaler_meta = pickle.load(f)
                
            # Load K-Means Model (nifty_kmeans_model.pkl)
            self.cluster_model = joblib.load(os.path.join(self.model_dir, "nifty_kmeans_model.pkl"))
                
            # Load Profit Mapping
            with open(os.path.join(self.model_dir, "cluster_stats.json"), 'r') as f:
                self.world_model = json.load(f)
                
            print(f"✅ Atlas Ready: {self.world_model.get('total_probes', 0)} probes.")
        except Exception as e:
            print(f"⚠️ Atlas v1 Load Failed: {e}")

        # Try Loading Atlas v2 (Latent)
        v2_model_path = os.path.join(self.v2_dir, "atlas_v2_model.pkl")
        if os.path.exists(v2_model_path):
            try:
                self.v2_model = joblib.load(v2_model_path)
                self.v2_scaler = joblib.load(os.path.join(self.v2_dir, "atlas_v2_scaler.pkl"))
                with open(os.path.join(self.v2_dir, "atlas_v2_cluster_stats.json"), 'r') as f:
                    self.v2_stats = json.load(f)
                print("✅ Atlas v2 (Latent) Model Loaded.")
            except Exception as e:
                print(f"⚠️ Atlas v2 Load Failed: {e}")

    def query(self, current_state_dict, latent_vector=None):
        """
        Takes raw market state, returns expected profit/risk profile.
        If latent_vector is provided and v2 model exists, uses v2.
        """
        # --- SUPER NOVA v1 PATH ---
        if latent_vector:
            if self.v2_model:
                return self._query_v2(latent_vector)
            else:
                 # EPISTEMIC ISOLATION: Do NOT fallback to Physics.
                 # Return "Collecting" state.
                 return {
                    "cluster_id": 999, # Special ID for "Collecting"
                    "source": "ATLAS_V2_COLLECTING"
                 }

        # --- LEGACY v1 PATH ---
        return self._query_v1(current_state_dict)

    def _query_v2(self, latent_vector):
        """Query using Latent Vector (Super Nova)"""
        if not self.v2_model: return {"cluster_id": -1}
        
        # Match schema in training
        features = [
            'trend_strength', 'trend_direction', 'mean_reversion', 
            'volatility_regime', 'momentum_quality', 'structure_type',
            'edge_call', 'edge_put', 'edge_hold', 'risk_state'
        ]
        
        vec = []
        for feat in features:
            vec.append(latent_vector.get(feat, 0))
            
        X = np.array(vec).reshape(1, -1)
        X_scaled = self.v2_scaler.transform(X)
        cluster_id = int(self.v2_model.predict(X_scaled)[0])
        
        # Get Stats
        stats = self.v2_stats.get(str(cluster_id), {})
        
        return {
            "cluster_id": cluster_id,
            "source": "ATLAS_V2_LATENT",
            "stats": stats
        }

    def _query_v1(self, current_state_dict):
        """Query using Physics Vector (Standard)"""
        if not self.cluster_model: return {"cluster_id": 0, "source": "FALLBACK"}
        
        # 1. Build Feature Vector
        features = self.scaler_meta['features']
        raw_vec = []
        
        # Mapping for loc_class
        loc_map = self.scaler_meta['loc_map']
        
        for feat in features:
            if feat == 'loc_idx':
                val = loc_map.get(current_state_dict.get('loc_class', 'MID_RANGE'), 6)
            else:
                val = current_state_dict.get(feat, 0.0)
            raw_vec.append(val)
            
        # 2. Normalize
        X_raw = np.array(raw_vec).reshape(1, -1)
        
        # 3. Normalize (Pass as DataFrame to silence warnings)
        X_df = pd.DataFrame(X_raw, columns=features)
        X_scaled = self.scaler_meta['scaler'].transform(X_df)
        
        # 3. Predict Cluster (Directly on Scaled Data, No PCA)
        cluster_id = int(self.cluster_model.predict(X_scaled)[0])
        
        # Calculate distance to centroid as confidence proxy (1 / (1 + distance))
        centroid = self.cluster_model.cluster_centers_[cluster_id]
        dist = np.linalg.norm(X_scaled - centroid)
        confidence = 1.0 / (1.0 + dist)
        
        # 4. Fetch Stats
        matches = []
        if self.world_model:
            matches = [r for r in self.world_model['regimes'] if r['cluster_id'] == cluster_id]
    
        return {
            "cluster_id": cluster_id,
            "cluster_confidence": round(confidence, 4),
            "stats": matches,
            "match_count": len(matches),
            "source": "ATLAS_V1_PHYSICS"
        }

if __name__ == "__main__":
    # Test with mockup state
    engine = AtlasQueryEngine()
    test_state = {
        'ter': 0.8, 'dist_or_h': 100, 'dist_or_l': 50, 'mom_slope': 1.5,
        'velocity': 1.2, 'accel': 0.1, 'skew': -0.5, 'atr': 20,
        'vix': 12, 'or_range': 150, 'vol_ratio': 1.1, 
        'entropy_price': 2.5, 'entropy_vol': 2.5,
        'loc_class': 'NEAR_TC'
    }
    res = engine.query(test_state)
    print("\n--- Atlas Query Test ---")
    print(f"Regime ID: {res['cluster_id']}")
    print(f"Source: {res['source']}")
