# Developer Handoff: Mock Mode & Data Infrastructure

## 🚨 Critical Fixes Implemented (Jan 30, 2026)

### 1. Mock Mode Data Source (Solved)
*   **Issue:** `stream_producer.py` was failing to connect to Redis (`Name or service not known`) and Mock Mode ticks were not persisting to DB, causing "Stale Data" in Engine Cycle.
*   **Fix 1 (Connectivity):** Implemented **Robust Redis Discovery**. The system now attempts to connect to `beast_redis` (Docker), `redis` (Service), `172.19.0.3` (IP), and `localhost` (Fallback) in sequence.
*   **Fix 2 (Replay Fidelity):** Upgraded `StreamProducer` to use **1-minute Granularity** (from `candles_1min`) instead of wicking 5m candles.
*   **Fix 3 (Persistence):** Implemented `_aggregate_candle` in `LiveMode`. All incoming ticks (Live or Replay) are now **upserted to `candles_1min` and `candles_5min`** in real-time. This ensures the Engine Cycle sees the latest data.

### 2. Explicit Mock Control
*   **Usage:**
    *   `python -m engine.gateway mock`: Paper Trading (Live Fyers Feed).
    *   `python -m engine.gateway mock --replay`: Adversarial Replay (Historical Data).
*   **Startup:** Both modes automatically run `prefill(days=7)` for both 1m and 5m resolutions.

## ⚠️ Known Issues / Next Steps

### 1. Redis "ConnectionRefused" on localhost
*   The fallback to `localhost` inside the container might still fail if the host port binding isn't accessible. However, the `beast_redis` or IP connection should now succeed first.
*   **Action:** If `ConnectionRefused` persists, ensure `docker-compose.llm.yml` has `ports: "6379:6379"` (Confirmed).

### 2. Verify Data Flow
*   The persistence logic (`_aggregate_candle`) is new. Monitor `candles_1min` size during replay to ensure specific rows are being added.
*   `sqlite3 trading.db "SELECT count(*) FROM candles_1min"`

## 🧪 How to Test
1.  **Start Replay:**
    ```bash
    python -m engine.gateway mock --replay --debug-schedule
    ```
2.  **Watch Logs:**
    *   Look for `✅ [Redis] Connected...`
    *   Look for `Target:` timestamp advancing every 5 minutes.

## 📂 Key Modified Files
*   `engine/modes/live.py`: Redis Discovery, `_aggregate_candle`, Replay Flag.
*   `workers/stream_producer.py`: Redis Discovery, 1min Replay Logic.
*   `engine/gateway.py`: `--replay` argument.
