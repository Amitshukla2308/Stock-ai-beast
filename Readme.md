# 🐉 Stock AI Beast (v4.0)
**The Sovereign Algorithmic Trading Engine**

> **Current Status:** Stable Backtest & Mock Cycles | Live Execution Ready
> **Last Updated:** 2026-01-10

---

## 🏛️ Architecture Overview

The "Beast" is built on a **Dual-Path Architecture** that separates high-latency intelligence from low-latency execution.

### 1. The Cold Path (Strategic Intelligence)
Powered by a multi-model LLM setup (Qwen family), this layer acts as the "Fund Manager."
- **Brain (Strategic)**: Analyzes pre-market gaps, VIX regimes, and multi-day price action to set the "Morning Brief."
- **Worker (Tactical)**: Every 15 minutes, it digests the current price action against the Morning Brief to issue entry/exit instructions.
- **Auditor (Learning)**: At 15:30 IST, it reviews all trades, performs a "Greed Gap Analysis," and extracts **Knowledge Nuggets** for long-term memory.

### 2. The Hot Path (Deterministic Execution)
The **HotPathExecutor** is a zero-latency rules engine that enforces the Brain's instructions.
- **Real-time Monitoring**: Once a trade is entered, it manages trailing stops and targets every millisecond.
- **Safety Guardrails**: Implements circuit breakers (max loss per day, consecutive SL limits) and ensures no trade is held against a rapid reversal.
- **Zero Hallucination**: No LLM calls are made during the milliseconds of trade execution.

---

## 🚀 Key Capabilities

### 🌓 Execution Modes
- **`backtest`**: Multi-year historical simulation with automated DuckDB data prefilling.
- **`mock`**: Adversarial replay mode. Replays recent days through a stream producer to test engine stability.
- **`live`**: Full-throttle automated execution via Fyers Websocket integration.

### 🧠 Adaptive Intelligence
- **VIX-Regime Awareness**: Dynamically adjusts SL/Target distance (Panic = 50pt SL, Complacent = 30pt SL).
- **Gap Intelligence**: Early classification of gaps (Normal, Significant, Extreme) at 09:20 IST to trigger proactive strategy shifts.
- **Self-Healing JSON**: A robust parser with heuristic truncation and brace-balancing to handle LLM artifacts without crashing the session.
- **Experience RAG**: Captures daily lessons (Nuggets) into a structured dataset for future fine-tuning and retrieval-augmented reasoning.

### 💰 Portfolio Engineering
- **BalanceMonitor**: Tracks capital growth, drawdown, and implements "Wipeout Protection" (automated resets).
- **PTS-to-Rupee Logic**: Accurate conversion of index points to real capital impact based on delta and lot sizes.

---

## 📁 Repository Structure

```text
stock-ai-beast/
├── brain/            # AI Headquarters
│   ├── llm_client.py     # Multi-model routing & JSON recovery
│   ├── prompts.py        # Triple-layer prompt engineering
│   └── prompt_manager.py # Context orchestration
├── engine/           # The Engine Room
│   ├── modes/            # [backtest, live, mock] implementations
│   ├── gateway.py        # Mode factory & auto-prefill logic
│   ├── journal.py        # Event recording & auditing
│   └── portfolio_mgr.py  # Risk & Capital tracking
├── hot_path/         # Low-latency execution logic
├── data/             # The Memory Vault
│   ├── database.py       # DuckDB & Redis interfaces
│   ├── prefill.py        # Automated Fyers data ingestion
│   └── feature_eng.py    # Indicator & technical logic
├── workers/          # I/O Services
│   ├── stream_producer.py # Live WebSocket & Mock replay
│   └── oms.py            # Order Management System
├── trigger.py        # The Master Switch (Control Plane)
└── Dashboard/        # Visual monitoring & reporting
```

---

## 🛠️ Usage

### Quick Start (Backtest)
```powershell
python trigger.py backtest --symbol NIFTY --days 5 --balance 30000
```

### Mock Replay (Adversarial Test)
```powershell
python trigger.py mock --symbol BANKNIFTY --days 2 --debug
```

### Live Trading (Caution Required)
```powershell
python trigger.py live --symbol NIFTY
```

---

## 📊 Performance Tracking
The Beast generates a **Final Backtest Report** including:
- **Win Rate & Profit Factor**
- **Max Drawdown (PTS & ₹)**
- **Wipeout Frequency**
- **Fidelity Metrics**: Mean Open PnL vs. Peak Profit (MFE).
- **Knowledge Base**: A list of extracted learnings from the session.

---
*Built for precision. Optimized for profit. Controlled by logic.*