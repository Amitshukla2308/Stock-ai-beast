# 5. Operations Manual & Usage Guide

## Quick Start (CLI)
The system is controlled via `trigger.py`.

### 1. Backtesting (Historical Simulation)
Runs the engine on past data stored in DuckDB.
```bash
python trigger.py backtest --symbol NIFTY --days 5 --balance 100000
```
*   **Auto-Prefill**: If data is missing for the requested days, the system automatically fetches it from Fyers API (if authorized) before running.

### 2. Mock Mode (Adversarial Replay)
Replays recent market days as a "Live Stream" to test the `HotPathExecutor`'s reaction time.
```bash
python trigger.py mock --symbol BANKNIFTY --days 2 --debug
```
*   **--debug**: Runs the schedule in "Fast Forward" (50x speed) to compress a trading day into minutes.

### 3. Live Trading
Connects to Fyers via Broker API.
```bash
python trigger.py live --symbol NIFTY
```
*   **Constraint**: Requires a valid `fyers_token.json` in the root directory.

## Monitoring

### Logs
*   `engine.log`: Main orchestration events.
*   `fyersApi.log`: Raw HTTP requests/responses (for API debugging).
*   `brain_output_log.txt`: Raw JSON outputs from the LLM (useful to check hallucinations).

### Common Errors & Solutions
1.  **"DB Locked"**: 
    *   *Cause*: Multiple processes (Engine + Dashboard) accessing DuckDB. 
    *   *Fix*: The system has built-in retry logic (5 retries). If it persists, kill the dashboard process.
2.  **"Brain Failure: Connection Error"**:
    *   *Cause*: Local LLM (Ollama) or API is down.
    *   *System Action*: Falls back to "Passive Plan" (Defensive mode) and retries next 15m.
3.  **"Wipeout Reset"**:
    *   *Trigger*: Balance drops below ₹10,000.
    *   *Action*: Simulation resets balance to initial to allow continued testing.
