"""
v4.0 Regime: The Dimensional Filter Layer
Handles PCA reduction and Hierarchical Clustering.
"""
import os
import joblib
import pandas as pd
import numpy as np
import logging
from typing import Dict, Any, Tuple

logger = logging.getLogger(__name__)

class Regime:
    def __init__(self, artifact_dir: str = "atlas/models"):
        self.artifact_dir = artifact_dir
        self.scaler = None
        self.pca = None
        self.kmeans_5m = None
        self.kmeans_15m = None
        self.pca_features = []
        self._load_models()

    def _load_models(self):
        try:
            self.scaler = joblib.load(os.path.join(self.artifact_dir, "atlas_64d_scaler.joblib"))
            pca_bundle = joblib.load(os.path.join(self.artifact_dir, "atlas_pca.joblib"))
            self.pca = pca_bundle['model']
            self.pca_features = pca_bundle['features']
            
            # AUDIT: CPU Weights
            s_center = getattr(self.scaler, 'mean_', getattr(self.scaler, 'center_', None))
            s_scale = getattr(self.scaler, 'scale_', None)
            
            logger.info(f"[AUDIT-CPU] PID: {os.getpid()} | Path: {os.path.abspath(self.artifact_dir)}")
            logger.info(f"[AUDIT-CPU] Scaler Class: {self.scaler.__class__.__name__}")
            logger.info(f"[AUDIT-CPU] Scaler Center (first 3): {s_center[:3].tolist() if s_center is not None else 'N/A'}")
            logger.info(f"[AUDIT-CPU] Scaler Scale (first 3): {s_scale[:3].tolist() if s_scale is not None else 'N/A'}")
            logger.info(f"[AUDIT-CPU] PCA Comp0 (first 3): {self.pca.components_[0, :3].tolist()}")
            
            self.kmeans_5m = joblib.load(os.path.join(self.artifact_dir, "kmeans_5m.joblib"))
            self.kmeans_15m = joblib.load(os.path.join(self.artifact_dir, "kmeans_15m.joblib"))
            logger.info(f"[REGIME] ✅ Models loaded. PCA purified to {len(self.pca_features)} dimensions.")
        except Exception as e:
            logger.error(f"[REGIME] ❌ Model Initialization Failed: {e}")
            raise

    def identify_clusters(self, df_5m_64d: pd.DataFrame, df_15m_64d: pd.DataFrame) -> Tuple[int, int, list]:
        """
        Takes dataframes with 64D features (X01...X64).
        Runs Scaling, PCA, and Clustering.
        Returns: (c15, c5, physics_vector)
        """
        # 1. Construct 128-d Vector (Direct from Scaler Metadata)
        latest_5m = df_5m_64d.iloc[-1:]
        latest_15m = df_15m_64d.iloc[-1:]
        
        feature_names_128 = self.scaler.feature_names_in_
        all_vals = []
        
        for name in feature_names_128:
            if name.startswith('P_'):
                # Parent feature (Resampled 15m)
                raw_name = name[2:] # Remove 'P_'
                val = float(latest_15m[raw_name].iloc[0]) if raw_name in latest_15m.columns else 0.0
            else:
                # Child feature (5m)
                val = float(latest_5m[name].iloc[0]) if name in latest_5m.columns else 0.0
            all_vals.append(val)

        # TRACE: 1. Raw Inputs
        # logger.info(f"[TRACE-CPU] Raw Input Freq: {len(all_vals)} | Names[0:5]: {feature_names_128[:5].tolist()}")
        # logger.info(f"[TRACE-CPU] Raw Input (first 5): {all_vals[:5]}")
        
        X_128_df = pd.DataFrame([all_vals], columns=feature_names_128)
        X_128_df = X_128_df.fillna(0.0).replace([np.inf, -np.inf], 0.0)
        
        # 2. Scale & Filter
        X_128_scaled = self.scaler.transform(X_128_df)
        X_128_scaled = np.clip(X_128_scaled, -5.0, 5.0)
        
        # TRACE-AUDIT-128: Scaled Vector Truth
        # logger.info(f"[TRACE-AUDIT-128-CPU] Scaled Sum: {np.sum(X_128_scaled):.6f} | Names: {feature_names_128[0]}...{feature_names_128[-1]}")
        
        # 3. Filter for Purified PCA (47 features)
        col_to_idx = {name: i for i, name in enumerate(feature_names_128)}
        child_indices = [col_to_idx[f] for f in self.pca_features if f in col_to_idx]
        parent_indices = [col_to_idx[f"P_{f}"] for f in self.pca_features if f"P_{f}" in col_to_idx]
        
        # TRACE: 3. Splicing
        # logger.info(f"[TRACE-CPU] Child Indices: {child_indices[:3]}...{child_indices[-3:]}")
        
        X_child_purified = X_128_scaled[0, child_indices].reshape(1, -1)
        X_parent_purified = X_128_scaled[0, parent_indices].reshape(1, -1)
        
        # 4. PCA
        pca_mean = self.pca.mean_
        pca_comps = self.pca.components_
        
        # TRACE-AUDIT: High Res State
        # logger.info(f"[TRACE-AUDIT-CPU] Purified Input Sum: {np.sum(X_child_purified):.6f}")
        # logger.info(f"[TRACE-AUDIT-CPU] PCA Mean Sum: {np.sum(pca_mean):.6f}")
        
        X_child_pca = self.pca.transform(X_child_purified)
        X_parent_pca = self.pca.transform(X_parent_purified)
        
        # TRACE: 5. Final PCA
        # logger.info(f"[TRACE-CPU] PCA Output (first 3): {X_child_pca[0, :3].tolist()}")
        
        # 5. Clusters
        c5 = int(self.kmeans_5m.predict(X_child_pca)[0])
        c15 = int(self.kmeans_15m.predict(X_parent_pca)[0])
        
        return c15, c5, X_child_pca[0].tolist()
