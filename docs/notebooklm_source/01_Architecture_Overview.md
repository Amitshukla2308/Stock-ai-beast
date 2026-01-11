# 1. Architecture Overview: The Dual-Path System

## The Core Philosophy
Stock AI Beast (v4.0) operates on a "Dual-Path" architecture, designed to solve the two primary failures of automated trading:
1.  **AI Latency**: LLMs take 2-5 seconds to think. Markets move in milliseconds.
2.  **AI Hallucination**: LLMs can output invalid JSON or dangerous instructions (e.g., "Sell at 0").

To solve this, the system splits into:
*   **The Cold Path (Strategic)**: High-latency, High-intelligence. (Runs every 15m)
*   **The Hot Path (Tactical)**: Zero-latency, Deterministic. (Runs every tick)

## System Components

### 1. The Brain (Cold Path)
*   **Role**: Fund Manager / Strategist.
*   **Models**: Qwen 2.5 14B (Strategic), Qwen 2.5 1.5B (Tactical).
*   **Frequency**: 
    - 09:20 AM: Morning Brief (Gap Analysis)
    - Every 15m: Tactical Update (Entry/Exit signals)
    - 15:30 PM: EOD Audit (Post-mortem analysis)
*   **Output**: It never executes trades directly. It outputs "Instructions" (e.g., "Enter CALL if price > 24500").

### 2. The HotPathExecutor (Hot Path)
*   **Role**: The Bodyguard / Execution Algo.
*   **Rules**: Written in Pure Python. No LLM calls.
*   **Frequency**: Tick-by-tick (100ms).
*   **Responsibilities**:
    - **Entry validation**: Ensures price is actually at the entry level.
    - **Risk Guardrails**: Rejects trades if Confidence < Threshold or if SL > 50pts.
    - **Trailing**: Manages dynamic Stop Losses locally.
    - **Momentum Check**: Prevents entering if the intraday move is already "Exhausted" (avg3 threshold).

### 3. The Data Vault
*   **DuckDB**: Stores 5-year historical candles (5min/1min) for backtesting context.
*   **Redis**: Streaming buffer for live ticks from Fyers.
*   **Schema**:
    - `candles_1min`: Raw OHLCV
    - `knowledge_nuggets`: Extracted lessons from previous trade sessions.

## Execution Flow Loop
1.  **Ingest**: Data arrives via Redis (Live) or DuckDB (Backtest).
2.  **Context**: `feature_eng.py` calculates ATR, VIX, and Greeks.
3.  **Think (Cold)**: `llm_client.py` sends context to Qwen. Qwen returns a JSON Instruction.
4.  **Validate**: `HotPathExecutor` checks the instruction against risk limits (e.g., "Is SL too wide?").
5.  **monitor & Execute (Hot)**: The Executor watches the tick stream. If specific entry conditions are met (price > entry), it triggers the order.
6.  **Learn**: At EOD, the Auditor reviews the trade log and saves "Nuggets" to the DB.
