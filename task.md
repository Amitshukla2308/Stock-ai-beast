# Project Atlas Implementation Checklist

- [ ] **Phase 1: Enrichment & State Vector Foundation**
    - [x] Create `enrichment/entropy.py` (Price/Volume Entropy).
    - [x] Create `enrichment/advanced_momentum.py` (Velocity, Acceleration, Skew).

    - [ ] Update `enrichment/loader.py` (or equivalent) to expose new metrics.

- [ ] **Phase 2: Atlas Core Components**
    - [x] Create `atlas/` directory.
    - [x] Implement `atlas/eligibility.py` (Permissive Logic).
    - [x] Implement `atlas/risk.py` (Pass-through).
    - [/] Implement `atlas/state_logger.py` (Update to support `.parquet`).

- [ ] **Phase 3: System Integration**
    - [x] Update `engine/gateway.py` to support `mode="learn"`.
    - [x] Update `core/orchestrator.py` to route `learn` mode.
    - [x] Ensure `engine/modes/backtest.py` can run in 'learn' mode.

- [ ] **Phase 4: Atlas Layer 2 (Model Builder)**
    - [ ] Create `atlas/model_builder/` directory.
    - [/] Move and Implement `atlas/model_builder/cluster_engine.py` (HDBSCAN Logic).
    - [/] Move and Implement `atlas/model_builder/profit_mapper.py` (PnL Mapping).

- [ ] **Phase 5: Verification**
    - [x] Run a short backtest in `learn` mode.
    - [ ] Verify `atlas_state_log.parquet` generation.
    - [ ] Run `cluster_engine.py` on generated data.
