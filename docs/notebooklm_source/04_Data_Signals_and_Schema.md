# 4. Data Signals & Database Schema

The system uses **DuckDB** (`data/trading.db`) as its core analytical engine.

## Database Schema

### 1. Market Data Tables
*   `candles_1min`: Raw OHLCV data. (Source of truth)
    *   `timestamp` (PK), `symbol`, `open`, `high`, `low`, `close`, `volume`.
*   `candles_5min`: Aggregated view for indicators.
*   `candles_vix`: Dedicated table for India VIX 1-min data.

### 2. Experience & Learning
*   `experience_replay`: Stores the full session context for Reinforcement Learning (RL) or Fine-Tuning.
    *   `market_state` (JSON): Daily context.
    *   `trades` (JSON): Full ledger of executions.
    *   `eod_audit` (JSON): The Brain's self-reflection.
*   `knowledge_nuggets`: The "Long Term Memory".
    *   `category`: 'GOOD' or 'BAD'.
    *   `condition_tags`: e.g., "HIGH_VIX, GAP_UP".
    *   `lesson`: Text nugget (e.g., "Do not short on Gap Up days until 10:30").

## Feature Engineering (`data/database.py` & `feature_eng.py`)

### 1. Context Slice (The Input Vector)
The brain receives a dictionary object called `context` containing:
*   `daily_3`: Last 3 days of D-Candles (OHLC).
*   `last_15min`: Last 20 15-min candles (for trend identification).
*   `vix_spot` & `vix_pct`: Current volatility & change from yesterday.
*   `vol_ratio`: Current 5-min volume vs Volume SMA. (Detection of volume spikes).

### 2. Indicators
*   **ATR_14**: Calculated on 15-min timeframe (Wilder's Smoothing).
*   **Current Range**: High - Low of the active trading session.
*   **Volume Regime**:
    *   `vol_ratio > 150`: High Volume Impulse.
    *   `vol_ratio < 60`: Dry/Anemic Market.
