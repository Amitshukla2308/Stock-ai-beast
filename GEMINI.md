<!-- 
WARNING: FUTURE AGENTS
This document is the Single Source of Truth for the System Architecture. 
If you find code that contradicts this document, the CODE IS WRONG and must be fixed.
If you deliberately change the architecture, you MUST update this file immediately.
Do not rely on "Implied" logic. Trace the code manually before editing this.
-->


# 🧠 GEMINI Knowledge Base: The Only Truth Architecture

> [!IMPORTANT]
> **TO ALL AI AGENTS:** This file is your PRIMARY COMPASS.
> 1. **Read this first** before touching any code.
> 2. **Trust this file** over any code comments or "implied" logic.
> 3. **Update this file** if you structurally change the system.
> 4. **Do not hallucinate** features not listed here.

This document serves as the **Long-Term Memory** for developers (AI and Human) working on the Beast. It captures the non-negotiable architectural laws that govern the system to ensure research validity and execution determinism.

## ⚡ The Verified Command Execution Trace (v6.3-SOVEREIGN)
*Traced manually on Feb 02, 2026 for command:* `docker exec beast_engine python -m engine.gateway live ...`

1.  **Entry Point**: `engine/gateway.py` -> `get_engine('backtest')`
    *   Validation: Checks `start_date`, `end_date`, `symbol`.
    *   Prefill: Auto-runs `data/prefill.run()` to ensure `trading.db` has raw candles.

2.  **Initialization**: `engine/modes/backtest.py` -> `BacktestMode()`
    *   Infrastructure: inits `SimBroker` and `Journal`.
    *   Brain: inits `ResearchEngine()` (The Orchestrator).

3.  **The Daily Loop**: `_run_simulation()`
    *   **Context Fetch**: `data/database.fetch_context_data(cutoff=Midnight)` -> Primes 200-bar history.
    *   **Tick LoopStart**: Iterates `candles_5min`.
    *   **Resampling**: `_resample_to_15m(df_5m)` -> Creates **Developing Parent** (09:15-09:30 Gap logic).

4.  **The Brain (Inference)**: `engine/research_engine.py` -> `process_tick()`
    *   **Step A (Physics)**: `PhysicsEngine.add_context()` + `AtlasFeatures.calculate_all()` -> Generates 64D Vector.
    *   **Step B (Regime)**: `Atlas.regime.identify_clusters()` -> Returns `c15` (Parent) and `c5` (Child).
    *   **Step C (Registry)**: `Atlas.registry.get_alpha_state()` -> Checks Static Map; falls back to RAG (`created_at < now`).
    *   **Step D (Risk)**: `RiskGuard.validate_alpha()` -> Checks `WR > 0.0` (Hard Reset) + **Regime Soft Blocks** + **Alpha Amplification** (Dynamic Sizing).

5.  **Execution**: `engine/modes/backtest.py` -> `on_tick()`
    *   **Signal**: If `BUY_CALL/PUT` and `flat`:
        *   `lifecycle.propose_trade()` -> `lifecycle.open_trade()`.
        *   Persist to `trading.db`.
    *   **Monitoring**: If `in_trade`:
        *   `ResearchEngine.process_in_trade_tick()` -> Checks for **Regime Trap**.
        *   If Trap: `lifecycle.close_trade(Reason=INVALIDATION)`.

### 🏛️ The Laws of Sovereignty (v4.2 Update)
1.  **The Physical Authority Principle**: **The Regime Trap (Invalidation)** is a Control Primitive, not a suggestion. If the Transition Monitor detects a Trap (e.g., `WR < 0.25` in a Bull Trade), the system must exit immediately. No narrative authority override is permitted.
2.  **The D2 Formation Constraint**: Strategies target specific Regime Formations. We trade the **Shift**, not the static state.
3.  **The Alpha-TGT Boundary**: In high-alpha regimes, static `Targets` are dynamic. In Phase-3, Alpha trades run until the **Physics Engine** (Edge Death) or **Risk Layer** (SL/MFE) terminates them.
4.  **Governance Hierarchy**: `SL (Safety) > EDGE_STATE (Physics) > ALPHA_AMPLIFICATION (Sizing) > REGIME (Context) > MFE (Math)`.

### 🏛️ Data Persistence & Epistemology Store ⭐ UPDATED v4.2

| File | Role | Location | Purpose |
| :--- | :--- | :--- | :--- |
| **`trading.db`** | **The Spine** | `data/` | **GOLD SOURCE.** Contains NIFTY 5m candles (2021-2026). |
| **`knowledge_nuggets`** | **The Mind** | `data/` | Semantic memory of past regime outcomes (RAG). |
| **`sovereign_states_64d.parquet`** | **The Features (X)** | `atlas/data/` | **SOVEREIGN TRUTH (64D).** Generated from `calculators.py` (2021-2025). |
| **`trading_audit.db`** | **The Judge** | `data/` | Simulation logs and counterfactual records. |

### North Star Invariants
If any of these are violated, the system is invalid:
1.  **No file > 300 LOC**.
2.  **No threshold exists in Python code** (Must be in Config or Model).
3.  **Every trade decision is traceable end-to-end to a specific Regime ID**.
4.  **Zero-trade day must explain exactly why** (Traceability).
5.  **Modes are Adapters**: `backtest.py` and `live.py` only feed candles; they never calculate indicators.
6.  **Temporal Integrity**: RAG lookups must STRICTLY use `WHERE created_at < current_sim_time`.
7.  **Sovereignty**: `confluence_map.json` MUST be rebuilt using `sovereign_states_64d.parquet` (64D) via `rebuild_confluence_map.py`.

---

## 🗺️ The Canonical Logic Map (v4.2)

### 1. Market Physics (Enrichment)
**Where**: `engine/features/calculators.py`
**Role**: "What is reality?" (Facts only, Numbers only, No Decisions)
*   **Dimensions**: 64-Dimensional "Market Biology" Vector (Physics, Hurst, Entropy, Volatility, Conviction).
*   **Source**: `PhysicsEngine` + `AtlasFeatures`.

### 2. Regime Engine (The Map)
**Where**: `atlas/regime.py`
**Role**: "Where are we?" (Context Classification)
*   **Purification**: **64D $\to$ 47D** (Correlation Pruning). Removes redundant signals (e.g. echoes of volatility).
*   **Compression**: **47D $\to$ 36D** (PCA). Retains >98% variance.
*   **Architecture**: **Dual-Scale Hierarchical Clustering** (The "Dream Architecture").
*   **The Grid**:
    *   **15m Structural Boss**: Maps to one of 64 structural clusters.
    *   **5m Execution Worker**: Maps to one of 64 tactical clusters.
    *   **Confluence**: Creates a $64 \times 64$ grid of 4,096 possible market states.
*   **Weights**: `atlas/models/kmeans_5m.joblib` and `kmeans_15m.joblib` (K=64).

### 3. Registry Layer (The Memory)
**Where**: `atlas/registry.py`
**Role**: "What happened last time?" (Probabilistic Lookup)
*   **Gold Regimes**: Identifies high-probability confluences (e.g., 9:39 Long, 53:10 Short).
*   **RAG**: Queries `knowledge_nuggets` for similar past contexts.
*   **Confluence**: Checks if Child and Parent regimes agree on direction.

### 4. Strategy Logic (Decision Layer)
**Where**: `engine/research_engine.py` (Orchestrator)
**Role**: "Should we act?" (Signal Generation)
*   **Signal**: `BUY_CALL` / `BUY_PUT` / `HOLD`.
*   **Transition Engine**: Monitors 5m Cluster ID in real-time. If state transitions to a neutral/negative cluster, trade is invalidated (Regime-Stop).

### 5. Risk Guard (The Sheriff)
**Where**: `engine/risk_guard.py`
**Role**: "Is this safe?" (Final Gate)
*   **Policies**:
    *   **Single Trade**: Only 1 open position allowed.
    *   **R:R Check**: Must target > 1.0 R.
    *   **In-Trade Monitor**: Monitors Active Trades every 5 mins for **Regime Traps**.

### 6. Trade Engine (The Executor)
**Where**: `trade/lifecycle.py`
**Role**: "Execute and Record" (Reality)
*   **Status**: `PROPOSED` → `OPEN` → `CLOSED`.
*   **Persistence**: Writes to `trading.db` (`trades` table) immediately.

---

## ⚡ The True Execution Flow (Daily Mantra)

```mermaid
graph TD
    Data[Data Layer\n(Trading.db)] --> Physics[Physics Engine\n(Calculators.py)]
    Physics --> Enrichment[Enrichment Layer\n(Normalization)]
    Enrichment --> Regime[Regime Engine\n(Cluster Identification)]
    Regime --> Registry[Registry Layer\n(RAG / History Lookup)]
    Registry --> Strategy[Strategy Logic\n(Confluence / Signal)]
    Strategy --> Risk[Risk Guard\n(Policy / Sizing)]
    Risk --> Executor[Trade Lifecycle\n(Executor)]
    Executor --> Ledger[Ledger - In-Memory Truth]
    Executor --> Store[Store - DB Persistence]
```

## 🐛 Root Cause Analysis (RCA): v4.2 Fixes

### 1. The "Developing Parent" Logic (09:15-09:30 Gap)
*   **Issue**: 15m candle doesn't close until 09:30, leaving a "blind spot" at open.
*   **Solution**: `BacktestMode` creates a **Partial 15m Candle** (resampled from 09:15-09:20 5m bars).
*   **Implication**: The system trades *immediately* at 09:20 using this developing context. This is intentional for speed.

### 2. Historical Data Restoration
*   **Issue**: `trading.db` only had 900 candles (Jan 2026).
*   **Fix**: Restored 5-year history (93k candles) from stash.
*   **Result**: Instant warmup (no delay) on any simulation start date.

### 3. Timestamp Clarity in Logs
*   **Issue**: Users confused by UTC timestamp `Target: ... 18:30:00`.
*   **Fix**: Logs now explicitly show `(UTC) / (IST)` equivalents.

### 4. SimBroker Balance Drift
*   **Issue**: `SimBroker` wasn't updating `self.balance` after `execute_exit`.
*   **Fix**: Added `update_balance(amount)` hooks in `TradeLifecycle` and `SimBroker`.

### 5. Alpha Leakage (v5.1-v5.3 Forge)
*   **Issue**: Specific 'toxic' regimes (e.g., 55:63, 3:18) causing high churn and drawdown.
*   **Solution**: Triple-snapshot optimization:
    - **v5.1**: Pruned Top 10 toxic regimes.
    - **v5.2**: Hard-blocked 20 diagnostic regimes + Semantic Sterilization.
    - **v5.3**: Doubled size for 'Golden Regimes' (e.g., 32:8) via Alpha Amplification.
*   **Result**: +₹156k PnL (+245% vs Baseline), PF 1.62.

### 6. Sovereign Compliance (v6.2 Live Parity)
*   **Issue**: `LiveMode` was missing the "Regime Trap" (In-Trade Monitor) and used legacy interfaces, creating a "Reality Gap" vs Backtest.
*   **Solution**:
    - **Interface Unity**: `LiveMode` now constructs `df_5m`/`df_15m` via `_prepare_dataframes` exactly as `BacktestMode` does.
    - **Closed Loop**: `LiveMode` now runs `ResearchEngine.process_in_trade_tick()` every cycle.
*   **Verification**: `tests/verify_live_backtest_parity.py` confirmed bit-for-bit identical decisions (Regime/Action) on historical data snapshots.

### 7. Mock Mode Fidelity (v6.3 Updates)
*   **Issue**: Mock mode used stale data and synthetic options pricing, leading to unrealistic PnL.
*   **Solution**:
    - **Real Options**: Switched to `market_data_cache` for option quotes.
    - **State Sync**: Implemented `Broker <-> Ledger` handshake on startup to catch restore drifts.
    - **EOD Grace**: Added forced exit at 15:30 and Entry Guard at 15:15.
*   **Result**: Mock PnL matches live execution logic with tick-level pricing accuracy.

### 8. Project Vajra (v6.0 Reporting Standard)
*   **Objective**: Remove "Analyst Subjectivity" from Backtest Reports.
*   **Implementation**: `trade/reporter.py` rewritten.
    - **Deterministic Verdict**: Uses `Stability Score` (SQN Proxy) to classify system as ROBUST/FRAGILE.
    - **Forensics**: Tracks "Regime Transition" reliability and "Friction Drag".
    - **Account Summary**: Tracks Capital Growth and Drawdown peaks.


---

## 🛠️ Maintenance Protocols

### 1. Adding a New Feature
1.  **Modify** `engine/features/calculators.py`.
2.  **Regenerate** Ground Truth: `python scripts/generate_64d_states.py`.
3.  **Rebuild** Map: `python scripts/rebuild_confluence_map.py`.

### 2. Debugging a "Missing Trade"
Follow the Trace Chain in logs:
1.  **Warmup**: Is the system past 200 bars? (`[ATLAS] ⏳ Warmup: ...`)
2.  **Regime**: What is the current ID? (e.g., `Regime: 22:15`)
3.  **Probability**: Is `WR > 0.45`? (Check `atlas/models/confluence_map.json`)
4.  **Risk**: Did `RiskGuard` block it? (e.g., "R:R < 1.0" or "Max Drawdown Reached")

---

*This document is the supreme law of the codebase. Any code violating these layers is a bug.*
