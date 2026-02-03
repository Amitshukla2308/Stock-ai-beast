# Implementation Plan - Rebuild Confluence Map (Sovereign 64D)

The goal is to rebuild `atlas/models/confluence_map.json` using the verifiable **Sovereign Architecture** on the full 2021-Dec 2025 dataset. This ensures the "Map" (Win Rates) perfectly matches the "Territory" (Live Engine Decisions).

## User Review Required
> [!IMPORTANT]
> This process involves **Generating 5 Years of 64D Vectors** using the Python Engine. This is a computation-heavy operation (~93k bars).
> We will generate a NEW parquet file `atlas/data/sovereign_states_64d.parquet` and DELETE the legacy `market_states.parquet` to remove confusion.

## Proposed Changes

### 1. Generate 64D Ground Truth (The Physics Layer)
We need to run the production `AtlasFeatures.calculate_all()` on 5 years of history to create the training set.

#### [NEW] [scripts/generate_64d_states.py](file:///wsl.localhost/Ubuntu-24.04/home/beast/projects/stock-ai-beast/scripts/generate_64d_states.py)
- **Inputs**: `trading.db` (NIFTY 5m Candles).
- **Process**:
    - Iterates dates from 2021-01-01 to 2025-12-31.
    - Feeds candles into `PhysicsEngine` (Maintains 200-bar warmup context).
    - Calls `AtlasFeatures.calculate_all()` to get the exact 64D vector used in Live.
- **Output**: `atlas/data/sovereign_states_64d.parquet`.

### 2. Rebuild the Brain (The Map Layer)
We map the 64D space to Cluster IDs and Outcomes.

#### [NEW] [scripts/rebuild_confluence_map.py](file:///wsl.localhost/Ubuntu-24.04/home/beast/projects/stock-ai-beast/scripts/rebuild_confluence_map.py)
- **Inputs**: `sovereign_states_64d.parquet`, `atlas_64d_scaler.joblib`, `atlas_pca.joblib`, `kmeans_5m/15m.joblib`.
- **Process**:
    1. **Purify**: Filter 64D -> 47D (Correlation Pruning / Feature Selection, matching `regime.py`).
    2. **Transform**: 47D -> Scaler -> PCA (36D) -> KMeans -> `(c15, c5)`.
    3. **Outcome**: Calculate 30m/60m Forward Returns, MAE, MFE for every row.
    4. **Aggregate**: Group by `(c15, c5)` to find Win Rate, Expectancy.
- **Output**: `atlas/models/confluence_map.json` (Replacing the old one).

### 3. Cleanup
#### [DELETE] `atlas/data/market_states.parquet` (Legacy File)

## Verification Plan

### Automated Verification
1.  **Parquet Check**: Verify `sovereign_states_64d.parquet` has 64 columns starting with `X01`...`X64`.
2.  **Map Integrity**: Verify `confluence_map.json` contains valid Cluster IDs (0-63) and reasonable Win Rates.

### Manual Verification
- Run the scripts inside the Docker container (as data access requires it).
- Inspect the output JSON to confirm "Golden Regimes" (e.g. Cluster 60+) exist.
