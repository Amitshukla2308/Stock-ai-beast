# Project Atlas Implementation Plan

## Goal Description
Implement "Project Atlas" - a market intelligence training system that learns the phase space of the market. This involves a new `learn` mode where the system logs a rich "State Vector" and trade outcomes without active PnL optimization, to be used for offline clustering and regime discovery.

## Proposed Changes

### 1. Enrichment Expansion (The Physics)
New modules to support the 11-dimensional State Vector.
#### [NEW] `enrichment/entropy.py`
- `calculate_entropy(series, period)` using Shannon entropy on quantized price/volume.

#### [NEW] `enrichment/advanced_momentum.py`
- `calculate_velocity(price, period)`
- `calculate_acceleration(price, period)`
- `calculate_skew(price, period)`



### 2. Atlas Core Components
#### [NEW] `atlas/eligibility.py`
- `AtlasEligibility` class.
- Logic:
    - If `regime` in `[TREND, TRANSITION]`: Allow `ITC`.
    - If `regime` in `[ROTATION, TRANSITION]`: Allow `REMR`.
    - Returns permissive list.

#### [NEW] `atlas/risk.py`
- `AtlasRisk` class.
- Pass-through logic (no veto).
- Scales position size based on uncertainty (placeholder: returns 1.0).

#### [MODIFY] `atlas/state_logger.py`
- Update to write to `atlas/data/states_YYYYMMDD.parquet` using pandas `to_parquet` (for performance/compression).

### 3. System Integration
#### [MODIFY] `engine/gateway.py`
- Add `mode='learn'` handling.
- Instantiates `AtlasEligibility`, `AtlasRisk`, `AtlasStateLogger` when in `learn` mode.

#### [MODIFY] `core/orchestrator.py`
- In `run_tick()`:
    - If `mode == 'learn'`:
        - Use Atlas Eligibility.
        - Log State Vector at start of tick.
        - Execute permissive trades.
        - Log outcomes for active trades.

### 4. Atlas Layer 2 (Model Builder)
#### [NEW] `atlas/model_builder/cluster_engine.py` (Implementation)
- Load Parquet data.
- Normalize features (Z-Score).
- Run HDBSCAN (or KMeans fallback).
- Save `state_clusters.pkl`.

#### [NEW] `atlas/model_builder/profit_mapper.py` (Implementation)
- Load `state_clusters.pkl` and `market_states.parquet` (for outcomes).
- Aggregate PnL stats per cluster.
- Generate `cluster_stats.json`.

## Verification Plan

### Automated Verification
Create a new test script `tests/verify_atlas_learn.py`.
1.  **Setup**: Initialize `Orchestrator` in `learn` mode with a mock data feed (1 day of data).
2.  **Execution**: Run the loop.
3.  **Assertions**:
    - Check that `atlas/data/` directory is created.
    - Check that state logs are generated.
    - Verify State Vector columns exist (even if some are 0.0).
    - Verify trades were "simulated" (or mocked) and logged.

### Manual Verification
1.  Run `python tests/verify_atlas_learn.py`.
2.  Inspect the generated CSV logs manually to confirm vector density.
