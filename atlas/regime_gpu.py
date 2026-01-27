"""
v4.4 Regime GPU: cuML-Accelerated Cluster Identification
"""
import os
import joblib
import cudf
import cuml
import numpy as np
import pandas as pd
import cupy as cp
import logging
from typing import Dict, Any, Tuple
from cuml.internals.array import CumlArray

logger = logging.getLogger(__name__)

class RegimeGPU:
    def __init__(self, artifact_dir: str = "atlas/models"):
        self.artifact_dir = artifact_dir
        self.scaler = None
        self.pca_gpu = None
        self.kmeans_5m_gpu = None
        self.kmeans_15m_gpu = None
        self.cpu_fallback = None
        self.pca_features = []
        self._load_and_convert_models()

    def _load_and_convert_models(self):
        """Loads CPU models and converts them to cuML for VRAM inference."""
        try:
            from atlas.regime import Regime
            self.cpu_fallback = Regime(self.artifact_dir)
            
            # Load standard artifacts
            self.scaler = joblib.load(os.path.join(self.artifact_dir, "atlas_64d_scaler.joblib"))
            pca_bundle = joblib.load(os.path.join(self.artifact_dir, "atlas_pca.joblib"))
            self.pca_features = pca_bundle['features']
            
            # 1. ATTEMPT GPU CONVERSION (cuML)
            try:
                # Convert PCA to cuML
                cpu_pca = pca_bundle['model']
                n_feat = int(cpu_pca.components_.shape[1])
                target_comp = int(cpu_pca.n_components_)
                logger.debug(f"[REGIME-GPU] Initializing PCA with {target_comp} components (Fitted Count)")
                self.pca_gpu = cuml.PCA(n_components=target_comp)
                
                # IMPORTANT: Dummy fit to initialize C++ handle and internal metadata
                dummy_X = cp.zeros((200, n_feat), dtype=cp.float32)
                self.pca_gpu.fit(dummy_X)
                
                # Standardizing to pure cupy arrays (Inject true weights)
                comps_cp = cp.array(cpu_pca.components_, dtype=cp.float32)
                mean_cp = cp.array(cpu_pca.mean_, dtype=cp.float32)
                
                self.pca_gpu.components_ = CumlArray(comps_cp)
                self.pca_gpu.mean_ = CumlArray(mean_cp)
                self.pca_gpu.n_features_in_ = n_feat
                self.pca_gpu.n_components_ = target_comp
                
                self.pca_comps_gpu = comps_cp
                self.pca_mean_gpu = mean_cp
                
                # AUDIT: GPU Weights
                s_center = getattr(self.scaler, 'mean_', getattr(self.scaler, 'center_', None))
                s_scale = getattr(self.scaler, 'scale_', None)
                
                logger.info(f"[AUDIT-GPU] PID: {os.getpid()} | Path: {os.path.abspath(self.artifact_dir)}")
                logger.info(f"[AUDIT-GPU] Scaler Class: {self.scaler.__class__.__name__}")
                logger.info(f"[AUDIT-GPU] Scaler Center (first 3): {s_center[:3].tolist() if s_center is not None else 'N/A'}")
                logger.info(f"[AUDIT-GPU] Scaler Scale (first 3): {s_scale[:3].tolist() if s_scale is not None else 'N/A'}")
                logger.info(f"[AUDIT-GPU] PCA Comp0 (first 3): {self.pca_comps_gpu[0, :3].tolist()}")
                
                # CASCADED DUMMY: Get PCA output to prime KMeans
                dummy_centered = dummy_X - self.pca_mean_gpu
                dummy_pca_out = cp.matmul(dummy_centered, self.pca_comps_gpu.T)
                
                # Convert KMeans to cuML
                cpu_km5 = joblib.load(os.path.join(self.artifact_dir, "kmeans_5m.joblib"))
                self.kmeans_5m_gpu = cuml.KMeans(n_clusters=cpu_km5.n_clusters)
                self.kmeans_5m_gpu.fit(dummy_pca_out)
                
                centers_5m = cp.array(cpu_km5.cluster_centers_, dtype=cp.float32)
                self.kmeans_5m_gpu.cluster_centers_ = CumlArray(centers_5m)
                self.kmeans_5m_gpu.n_features_in_ = target_comp
                
                cpu_km15 = joblib.load(os.path.join(self.artifact_dir, "kmeans_15m.joblib"))
                self.kmeans_15m_gpu = cuml.KMeans(n_clusters=cpu_km15.n_clusters)
                self.kmeans_15m_gpu.fit(dummy_pca_out)
                
                centers_15m = cp.array(cpu_km15.cluster_centers_, dtype=cp.float32)
                self.kmeans_15m_gpu.cluster_centers_ = CumlArray(centers_15m)
                self.kmeans_15m_gpu.n_features_in_ = target_comp
                
                logger.info("[REGIME-GPU] 🚀 cuML Pipeline Initialized (Cascaded Dummy Fit + Weight Injection).")
            except Exception as gpu_err:
                logger.warning(f"[REGIME-GPU] ⚠️ cuML Hardware Mismatch: {gpu_err}. Falling back to CPU regime logic.")
                self.pca_gpu = None
        except Exception as e:
            logger.error(f"[REGIME-GPU] ❌ Model Initialization Failed: {e}")
            raise

    def identify_clusters_batch(self, df_5m: pd.DataFrame, df_15m: pd.DataFrame) -> pd.DataFrame:
        """
        Vectorized version of identify_clusters for massive backtests/audits.
        Alignt 5m/15m and predicts clusters for all rows in one pass.
        Returns DataFrame with ['c15', 'c5']
        """
        if not self.pca_gpu:
            raise RuntimeError("GPU Models not loaded for batch prediction.")

        # 1. Align 5m and 15m (Forward fill parent state onto child ticks)
        # We assume both have a 'timestamp' column
        df_5m = df_5m.sort_values('timestamp')
        df_15m = df_15m.sort_values('timestamp').rename(columns={c: f"P_{c}" for c in df_15m.columns if c != 'timestamp'})
        
        df_merged = pd.merge_asof(df_5m, df_15m, on='timestamp', direction='backward')
        
        # 2. Extract 128D Matrix
        feature_names_128 = self.scaler.feature_names_in_
        X_raw = df_merged[feature_names_128].fillna(0.0).replace([np.inf, -np.inf], 0.0)
        
        # 3. Scale and Clip (Bulk)
        X_scaled = self.scaler.transform(X_raw)
        X_scaled = np.clip(X_scaled, -5.0, 5.0)
        
        # 4. Prepare Sliced Inputs for PCA
        col_to_idx = {name: i for i, name in enumerate(feature_names_128)}
        child_indices = [col_to_idx[f] for f in self.pca_features if f in col_to_idx]
        parent_indices = [col_to_idx[f"P_{f}"] for f in self.pca_features if f"P_{f}" in col_to_idx]
        
        X_child_cp = cp.array(X_scaled[:, child_indices], dtype=cp.float32)
        X_parent_cp = cp.array(X_scaled[:, parent_indices], dtype=cp.float32)
        
        # 5. PCA Projection (Bulk matmul)
        X_c_pca = cp.matmul(X_child_cp - self.pca_mean_gpu, self.pca_comps_gpu.T)
        X_p_pca = cp.matmul(X_parent_cp - self.pca_mean_gpu, self.pca_comps_gpu.T)
        
        # 6. KMeans Predict (Bulk)
        c5_res = self.kmeans_5m_gpu.predict(X_c_pca)
        c15_res = self.kmeans_15m_gpu.predict(X_p_pca)
        
        # 7. Format Output
        df_out = pd.DataFrame({
            'timestamp': df_merged['timestamp'],
            'c15': cp.asnumpy(c15_res).astype(int),
            'c5': cp.asnumpy(c5_res).astype(int)
        })
        
        return df_out

    def identify_clusters(self, df_5m_64d: Any, df_15m_64d: Any) -> Tuple[int, int, list]:
        """Runs the cluster identification. Hybrid CPU/GPU support."""
        if not self.pca_gpu:
            p5 = df_5m_64d.to_pandas() if hasattr(df_5m_64d, 'to_pandas') else df_5m_64d
            p15 = df_15m_64d.to_pandas() if hasattr(df_15m_64d, 'to_pandas') else df_15m_64d
            return self.cpu_fallback.identify_clusters(p5, p15)

        try:
            # PHASE A: HOIST DATA
            p5 = df_5m_64d.to_pandas() if hasattr(df_5m_64d, 'to_pandas') else df_5m_64d
            p15 = df_15m_64d.to_pandas() if hasattr(df_15m_64d, 'to_pandas') else df_15m_64d
            
            # PHASE A: Construct 128-d Vector (Direct from Scaler Metadata)
            latest_5m = p5.iloc[-1:]
            latest_15m = p15.iloc[-1:]
            
            feature_names_128 = self.scaler.feature_names_in_
            all_vals = []
            
            for name in feature_names_128:
                if name.startswith('P_'):
                    raw_name = name[2:]
                    val = float(latest_15m[raw_name].iloc[0]) if raw_name in latest_15m.columns else 0.0
                else:
                    val = float(latest_5m[name].iloc[0]) if name in latest_5m.columns else 0.0
                all_vals.append(val)

            # DEBUG: Log model types
            logger.debug(f"[DEBUG-GPU] Scaler Type: {type(self.scaler)} | PCA Type: {type(self.pca_gpu)}")
            
            # TRACE: 1. Raw Inputs
            # logger.info(f"[TRACE-GPU] Raw Input Freq: {len(all_vals)} | Names[0:5]: {feature_names_128[:5].tolist()}")
            # logger.info(f"[TRACE-GPU] Raw Input (first 5): {all_vals[:5]}")
            
            # PHASE B: SCALE
            X_128_df = pd.DataFrame([all_vals], columns=feature_names_128)
            X_128_df = X_128_df.fillna(0.0).replace([np.inf, -np.inf], 0.0)
            X_128_scaled = self.scaler.transform(X_128_df)
            X_128_scaled = np.clip(X_128_scaled, -5.0, 5.0)
            
            # TRACE-AUDIT-128-GPU: Scaled Vector Truth
            # logger.info(f"[TRACE-AUDIT-128-GPU] Scaled Sum: {np.sum(X_128_scaled):.6f} | Names: {feature_names_128[0]}...{feature_names_128[-1]}")
            
            # PHASE C: GPU TRANSFER
            col_to_idx = {name: i for i, name in enumerate(feature_names_128)}
            child_indices = [col_to_idx[f] for f in self.pca_features if f in col_to_idx]
            parent_indices = [col_to_idx[f"P_{f}"] for f in self.pca_features if f"P_{f}" in col_to_idx]
            
            # TRACE: 3. Splicing
            # logger.info(f"[TRACE-GPU] Child Indices: {child_indices[:3]}...{child_indices[-3:]}")
            
            X_child_cp = cp.array(X_128_scaled[0, child_indices].reshape(1, -1), dtype=cp.float32)
            X_parent_cp = cp.array(X_128_scaled[0, parent_indices].reshape(1, -1), dtype=cp.float32)
            
            # PHASE D: PCA (Direct CuPy Projection for absolute parity with CPU)
            X_c_centered = X_child_cp - self.pca_mean_gpu
            X_c_pca = cp.matmul(X_c_centered, self.pca_comps_gpu.T)
            
            X_p_centered = X_parent_cp - self.pca_mean_gpu
            X_p_pca = cp.matmul(X_p_centered, self.pca_comps_gpu.T)
            
            # TRACE-AUDIT-GPU: High Res State
            # logger.info(f"[TRACE-AUDIT-GPU] Purified Input Sum: {float(cp.sum(X_child_cp)):.6f}")
            # logger.info(f"[TRACE-AUDIT-GPU] PCA Mean Sum: {float(cp.sum(self.pca_mean_gpu)):.6f}")
            
            # TRACE: 4. Final PCA
            v_np = cp.asnumpy(X_c_pca) if hasattr(X_c_pca, '__cuda_array_interface__') else X_c_pca
            # logger.info(f"[TRACE-GPU] PCA Output (first 3): {v_np[0, :3].tolist()}")
            
            # PHASE E: KMEANS
            # Inputs to KMeans also need consistent wrapping
            X_c_pca_cuml = CumlArray(X_c_pca) if not isinstance(X_c_pca, CumlArray) else X_c_pca
            X_p_pca_cuml = CumlArray(X_p_pca) if not isinstance(X_p_pca, CumlArray) else X_p_pca
            
            c5_res = self.kmeans_5m_gpu.predict(X_c_pca_cuml)
            c15_res = self.kmeans_15m_gpu.predict(X_p_pca_cuml)
            
            # PHASE F: EXTRACT LABELS
            # Convert GPU results back to CPU/Python scalars
            c5_np = cp.asnumpy(c5_res) if hasattr(c5_res, '__cuda_array_interface__') else c5_res
            c15_np = cp.asnumpy(c15_res) if hasattr(c15_res, '__cuda_array_interface__') else c15_res
            
            c5 = int(float(c5_np[0])) if hasattr(c5_np, '__getitem__') else int(float(c5_np))
            c15 = int(float(c15_np[0])) if hasattr(c15_np, '__getitem__') else int(float(c15_np))
            
            # PHASE G: EXTRACT PHYSICS
            # Standardize physics vector format
            v_np = cp.asnumpy(X_c_pca) if hasattr(X_c_pca, '__cuda_array_interface__') else X_c_pca
            physics_vector = v_np[0].tolist() if hasattr(v_np, 'ndim') and v_np.ndim > 1 else v_np.tolist()
            
            return c15, c5, physics_vector

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            logger.warning(f"[REGIME-GPU] ⚠️ Inference Fail: {e}. Fallback to CPU.\n{tb}")
            return self.cpu_fallback.identify_clusters(df_5m_64d, df_15m_64d)
