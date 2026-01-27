# 🐉 Stock AI Beast (v4.2)
**The Sovereign Algorithmic Trading Engine**

> **Current Status:** Stable Backtest & Mock Cycles | Live Execution Ready
> **Last Updated:** 2026-01-27
> **Architecture:** Sovereign (Physics > Regime > Strategy > Risk)

---

## 🏛️ Architecture Overview

The "Beast" (v4.2) is a **Deterministic Dimensional Engine**. It abandons the "LLM Fund Manager" approach (v4.0) in favor of a rigorous, sovereign mathematical stack where **Physics** and **Regime** are the final authorities.

### The Sovereign Stack (Data Flow)

The system operates in a strictly hierarchical pipeline. Data flows DOWN, decisions flow UP.

```mermaid
graph TD
    Data[Data Layer\n(Trading.db / Fyers)] --> Physics[Physics Engine\n(Calculators.py)]
    Physics --> Enrichment[Enrichment Layer\n(Normalization)]
    Enrichment --> Regime[Regime Engine\n(Cluster Identification)]
    Regime --> Registry[Registry Layer\n(RAG / History Lookup)]
    Registry --> Strategy[Strategy Logic\n(Confluence / Signal)]
    Strategy --> Risk[Risk Guard\n(Policy / Sizing)]
    Risk --> Execution[Trade Lifecycle\n(Executor)]
```

### 1. Physics Engine ( The Authority)
*   **Role**: Defines "Reality".
*   Calculates the **64-Dimensional Market State Vector** (Volatility, Entropy, VRP, Structure).
*   **Authority**: If Physics says the trend is weak (Low TER), no trade can occur, regardless of what the strategy "thinks".

### 2. Regime Engine (The Map)
*   **Role**: Contextual Awareness.
*   Classifies the market into specific **Cluster Pairs** (e.g., `Parent=6` / `Child=29`) using pre-trained KMeans models.
*   **Philosophy**: We trade the **Shift**, not the static price.

### 3. Registry Layer (The Memory)
*   **Role**: Experience Retrieval (RAG).
*   Queries the `knowledge_nuggets` database for: *"What happened the last 100 times we were in Regime 29:6?"*
*   **Temporal Integrity**: Strictly enforces `created_at < current_sim_time` to prevent look-ahead bias.

### 4. Risk Guard (The Sheriff)
*   **Role**: Final Gatekeeper.
*   **Sovereign Laws**:
    *   **Regime Trap**: If a trade's thesis is invalidated (e.g., WinRate drops < 25%), it MUST exit immediately.
    *   **Capital Preservation**: 50pt Hard SL / 90pt Target / Max 1 Open Position.

---

## 🚀 Key Capabilities

### 🌓 Execution Modes
*   **`backtest`**: Multi-year historical simulation with instant warmup (93k+ candles preloaded).
*   **`mock`**: Adversarial replay mode for stress testing.
*   **`live`**: Zero-latency execution via Fyers API (Active).

### 🧠 Core Features
*   **Development Parent Logic**: Trades correctly during the 09:15-09:30 gap using "Partial Candles".
*   **Dynamic Targets**: Targets adjust based on Regime "Alpha" (High-Prob Regimes = Let Runners Run).
*   **Self-Healing Data**: Automatic prefill and repair of `trading.db`.

---

## 📁 Repository Structure

```text
stock-ai-beast/
├── atlas/            # The Dimensional Mind
│   ├── regime.py         # KMeans Cluster Prediction
│   ├── registry.py       # RAG Memory Lookup
│   └── models/           # Pre-trained .joblib models
├── engine/           # The Orchestrator
│   ├── features/         # Physics Calculators
│   ├── research_engine.py# Main Brain Loop
│   └── risk_guard.py     # Safety Policeman
├── data/             # The Gold Source
│   ├── database.py       # DuckDB Interface
│   └── trading.db        # The Truth (Candles + Trades)
├── trade/            # The Executor
│   ├── lifecycle.py      # Trade State Machine
│   └── ledger.py         # PnL Tracking
└── brokers/          # Connectivity (Sim/Live)
```

---

## 🛠️ Usage

### Quick Start (Backtest)
**Recommended**: Run via Docker for environment determinism.

```bash
# Run a specific day
docker exec beast_engine python -m engine.gateway backtest --symbol NIFTY --start-date 2026-01-21 --end-date 2026-01-21

# Run a range
docker exec beast_engine python -m engine.gateway backtest --symbol NIFTY --start-date 2026-01-01 --end-date 2026-01-31
```

### Mock Replay
```bash
docker exec beast_engine python -m engine.gateway mock --symbol BANKNIFTY --days 2
```

---

## 📊 Performance Principles
*   **Win Rate is Vanity**: We optimize for **Expectancy**.
*   **Drawdown is Reality**: Max DD > 5% triggers a "Circuit Breaker" review.
*   **Traceability**: Every trade is linked to a specific `Regime ID`.

---
*Maintained by the Antigravity Team (v4.2)*