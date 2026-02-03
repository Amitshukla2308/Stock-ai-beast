# Atlas: The Regime Engine

Atlas is the "Brain" of the Beast. It is responsible for classifying Market Regimes (The "Map") and providing probabilistic context for trading decisions.

## 🏛️ Sovereign Architecture (v4.2)
Atlas operates on a verifiable, determinstic pipeline known as the **Sovereign Architecture**.

### The Pipeline
1.  **Physics (64D)**: `engine.features.calculators.py` generates a 64-dimensional biology vector for every 5-minute candle.
    *   *Source*: `atlas/data/sovereign_states_64d.parquet` (Generated from `trading.db`).
2.  **Purification (47D)**: Correlation Pruning removes redundant features (e.g., highly correlated volatility metrics) to reduce noise.
3.  **Compression (36D)**: PCA reduces the 47D purified vector to a 36D Latent Manifold, retaining >98% variance.
4.  **Clustering (Dual-Scale)**:
    *   **Parent (15m)**: Structural Cluster (K=64).
    *   **Child (5m)**: Tactical Cluster (K=64).
    *   This creates a $64 \times 64 = 4096$ state grid.

## 📂 Directory Structure

| File/Folder | Purpose |
| :--- | :--- |
| `regime.py` | **Core Runtime**. Loads models and executes the Pipeline (Transform -> Predict). |
| `registry.py` | **Epistemology**. Looks up historical Win Rates/Edges for the current Regime ID. |
| `models/` | Contains the Brain Binaries (`joblib` files) and the Map (`confluence_map.json`). |
| `data/` | Contains the Ground Truth datasets (`sovereign_states_64d.parquet`). |

## 🛠️ Maintenance Scripts
*   `scripts/generate_64d_states.py`: Regenerates the 5-year Ground Truth dataset from `trading.db`.
*   `scripts/rebuild_confluence_map.py`: Re-runs the ML Pipeline on the Ground Truth to rebuild `confluence_map.json`.

## ⚠️ Legacy Note
The `model_builder/` directory contains legacy scripts (v2.x) used for initial research. They are **NOT** part of the production Sovereign Pipeline. Do not use them to generate production models.
