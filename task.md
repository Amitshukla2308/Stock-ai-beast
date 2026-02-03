# Task: Rebuild Confluence Map (Sovereign 64D)

The goal is to rebuild `confluence_map.json` using the **Sovereign Architecture** (64D Calculators -> 36D PCA -> 64x64 KMeans) on the full 2021-Dec 2025 dataset. The existing `market_states.parquet` is legacy and must be replaced.

## 1. Preparation & Verification
- [x] Analyze `engine/features/calculators.py` to define the exact 64D schema. <!-- id: 0 -->
- [x] Verify `trading.db` has raw 5-minute candles for 2021-2025. <!-- id: 1 -->
- [x] Delete legacy `atlas/data/market_states.parquet` to avoid confusion. <!-- id: 2 -->

## 2. Generate 64D Ground Truth (The Physics Layer)
- [x] Create `scripts/generate_64d_states.py`. <!-- id: 3 -->
    - Must use `PhysicsEngine` and `AtlasFeatures` (Production Code).
    - Iterate `trading.db` from 2021-01-01 to 2025-12-31.
    - Save to `atlas/data/sovereign_states_64d.parquet`.

## 3. Rebuild the Brain (The Map Layer)
- [x] Create `scripts/rebuild_confluence_map.py`. <!-- id: 4 -->
    - Load `sovereign_states_64d.parquet`.
    - Apply `atlas_64d_scaler.joblib` + `atlas_pca.joblib` -> 36D Latent.
    - Apply `kmeans_5m` / `kmeans_15m` -> Cluster IDs.
    - Map Outcomes (PnL, Win/Loss).
    - Generate `confluence_map_sovereign.json`.

## 4. Verification
- [x] Verify the new map contains high-cluster IDs (e.g. 60+). <!-- id: 5 -->
- [x] Compare "Golden Regimes" against known history manually (sanity check). <!-- id: 6 -->
- [x] Promote new map to `confluence_map.json`. <!-- id: 7 -->

## 5. Completion
- [x] Delete `atlas/data/market_states.parquet` (Legacy). <!-- id: 8 -->
- [x] Ensure `atlas/models/confluence_map.json` is the Sovereign version. <!-- id: 9 -->
