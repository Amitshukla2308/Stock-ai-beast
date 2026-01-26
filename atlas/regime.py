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
            self.pca_features = pca_bundle['features'] # List of valid purified features
            
            self.kmeans_5m = joblib.load(os.path.join(self.artifact_dir, "kmeans_5m.joblib"))
            self.kmeans_15m = joblib.load(os.path.join(self.artifact_dir, "kmeans_15m.joblib"))
            
            logger.info(f"[REGIME] ✅ Models loaded. PCA purified to {len(self.pca_features)} dimensions.")
        except Exception as e:
            logger.error(f"[REGIME] ❌ Model Load Failed: {e}")

    def identify_clusters(self, df_5m_64d: pd.DataFrame, df_15m_64d: pd.DataFrame) -> Tuple[int, int, list]:
        """
        Takes dataframes with 64D features (X01...X64).
        Runs Scaling, PCA, and Clustering.
        Returns: (c15, c5, physics_vector)
        """
        # 1. Construct 128-d Vector (Child + Parent)
        # We need the exact patterns used in the scaler
        # Patterns for AtlasFeatures: X01_Pivot_Dist, etc.
        patterns = {
            f"X{i:02d}": name for i, name in enumerate([
                "Pivot_Dist", "VWAP_Dist", "DayOpen_Bias", "Mom_1H", "Price_Pressure", "Squeeze",
                "Efficiency", "Internal_Strength", "Vol_Trend", "Acceleration", "Log_Ret", "ZScore",
                "Skew", "Kurt", "Chop_Index", "Autocorr", "Bar_Density", "IQR_Norm", "MAD_Norm", "Entropy",
                "ROC", "MACD_Hist", "CCI", "CMO", "StochK", "AO", "TRIX", "KST_Proxy", "ADX", "DI_Spread",
                "ROC_Accel", "WillR", "StochD", "EMA200_Dist", "Mom_Div", "ATR_Ratio", "GK_Vol", "Park_Vol",
                "BB_Width", "BB_PctB", "Kelt_Pos", "Donch_Pos", "VRP_Proxy", "Ulcer_Idx", "Chaikin_Vol",
                "MFI", "OBV_Slope", "CMF", "Vol_ZScore", "Force_Idx", "EOM", "VWMA_Diff", "ADL_Flow",
                "Vol_ROC", "V_Trend", "VIX_Level", "VIX_Delta", "VIX_ZScore", "NIFTY_VIX_Corr", "Expiry_Prox",
                "Session_Prog", "Gap_Size", "Color_Persist", "Range_Ratio"
            ], 1)
        }
        
        latest_5m = df_5m_64d.iloc[-1:]
        latest_15m = df_15m_64d.iloc[-1:]
        
        feature_names_128 = []
        all_vals = []
        
        # Child 64
        for i in range(1, 65):
            feat_key = f"X{i:02d}"
            name = f"X{i:02d}_{patterns[feat_key]}"
            feature_names_128.append(name)
            all_vals.append(latest_5m[name].iloc[0] if name in latest_5m.columns else 0.0)
            
        # Parent 64
        for i in range(1, 65):
            feat_key = f"X{i:02d}"
            name = f"P_X{i:02d}_{patterns[feat_key]}"
            feature_names_128.append(name)
            all_vals.append(latest_15m[name.replace('P_', '')].iloc[0] if name.replace('P_', '') in latest_15m.columns else 0.0)

        X_128_df = pd.DataFrame([all_vals], columns=feature_names_128)
        X_128_df = X_128_df.fillna(0.0).replace([np.inf, -np.inf], 0.0)
        
        # 2. Scale & Filter
        X_128_scaled = self.scaler.transform(X_128_df)
        X_128_scaled = np.clip(X_128_scaled, -5.0, 5.0)
        
        # 3. Filter for Purified PCA (47 features)
        col_to_idx = {name: i for i, name in enumerate(feature_names_128)}
        child_indices = [col_to_idx[f] for f in self.pca_features if f in col_to_idx]
        parent_indices = [col_to_idx[f"P_{f}"] for f in self.pca_features if f"P_{f}" in col_to_idx]
        
        X_child_purified = X_128_scaled[0, child_indices].reshape(1, -1)
        X_parent_purified = X_128_scaled[0, parent_indices].reshape(1, -1)
        
        # 4. PCA
        X_child_pca = self.pca.transform(X_child_purified)
        X_parent_pca = self.pca.transform(X_parent_purified)
        
        # 5. Clusters
        c5 = int(self.kmeans_5m.predict(X_child_pca)[0])
        c15 = int(self.kmeans_15m.predict(X_parent_pca)[0])
        
        return c15, c5, X_child_pca[0].tolist()
