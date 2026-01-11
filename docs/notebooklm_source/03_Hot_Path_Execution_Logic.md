# 3. Hot Path Execution Logic

The `HotPathExecutor` (`hot_path/executor.py`) is the deterministic core. It receives "Instructions" from the Brain but has the authority to veto them based on risk rules.

## The Instruction Logic
When the Brain sends `{"action": "BUY_CALL", "entry": 24000, "sl": 23950}`, the Executor does NOT buy immediately.
1.  **Wait**: It monitors the live tick price.
2.  **Trigger**:
    *   If price crosses `24000` from below (for CALL), it triggers.
    *   **Favorable Entry**: If price is between `24000` and `24010` (slippage buffer), it executes.
    *   **Skip**: If price gaps to `24050` (too far), it cancels the order to avoid chasing.

## Filters & Guardrails

### 1. Momentum Exhaustion Check
The system tracks the total unidirectional movement of the day.
*   **Thresholds** (Derived from `data/momentum_thresholds.json`):
    *   `avg1`: Average daily move.
    *   `avg2`: 1SD above average.
    *   `avg3`: 2SD (Extreme extension).
*   **Logic**:
    *   If current move > `avg3` (e.g., Nifty moved 400pts up): **REJECT** all new BUY_CALL instructions. Only Reversals (PUTs) are allowed.

### 2. VIX Adaptive Stops
Even if the Brain suggests a tight SL, the Executor enforces floors/ceilings:
*   **Min SL**: 15 pts (Absolute floor).
*   **Max SL**: 50 pts (Absolute ceiling, to prevent account blowouts).
*   **Fallback**: If LLM sends no SL, default to 30 pts.

### 3. Trailing Logic (The "Security Guard")
Once a trade is open, the Executor manages it locally:
*   **Lock-in Rule**: If Profit reaches 60% of Target, move SL to Lock 50% of the profit.
    *   *Example*: Target is +60pts. Price hits +36pts. SL moves to +30pts.
*   **Smart Exit**: If the Brain sends `EXIT_NOW` (reversal detected), the Executor cuts the trade immediately, regardless of PnL.

## Scalping Mode
If `Confidence > 0.65` AND `Entry = OPTIMAL`:
*   The system enters **Scalping Mode**.
*   **Target**: Fixed at 30 pts.
*   **SL**: Fixed at 15 pts.
*   **Max Hold Time**: 15 minutes.
*   *Goal*: Quick snipes in high-conviction zones without waiting for large trends.
