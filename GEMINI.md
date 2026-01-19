# 🧠 GEMINI Knowledge Base: Efficiency & Architectural Guardrails

This document serves as the **Long-Term Memory** for developers (AI and Human) working on the Beast. It captures critical pitfalls, philosophy, and strategies to implement complex business logic changes faster.

> [!TIP]
> **End-to-End Data Flow**: For a visual and technical map of how data moves from Market -> Enrichment -> LLM -> Engine -> Executor, see **[SYSTEM_FLOW.md](file://wsl.localhost/Ubuntu-24.04/home/beast/projects/stock-ai-beast/SYSTEM_FLOW.md)**.

## 🏛️ Core Philosophy: Authority Split
The system is divided into two distinct authorities. Understanding this is critical for any logic change.

1.  **The Brain (LLM)**: Responsible for **Qualitative Strategy**.
    *   **Role**: Analyzes Context, Sentiment, and Structure. Suggests "Action" and "Style".
    *   **Location**: [llm_client.py](file://wsl.localhost/Ubuntu-24.04/home/beast/projects/stock-ai-beast/brain/llm_client.py) (Logic), [prompts.py](file://wsl.localhost/Ubuntu-24.04/home/beast/projects/stock-ai-beast/brain/prompts.py) (Instructions).
2.  **The Executor (Deterministic Algo)**: Responsible for **Quantitative Execution**.
    *   **Role**: Receives Style from Brain. **ENFORCES hard-coded geometric rules** (SL/Target).
    *   **Power**: Overrides LLM's suggested stops with mathematical precision.
    *   **Location**: [executor.py](file://wsl.localhost/Ubuntu-24.04/home/beast/projects/stock-ai-beast/hot_path/executor.py) ([_apply_style_geometry](file://wsl.localhost/Ubuntu-24.04/home/beast/projects/stock-ai-beast/hot_path/executor.py#L85-124)).

## ⚡ Speed Guidelines: How to implement 2x Faster

### 1. Contract-First Logic Changes
**Problem**: Time lost chasing `KeyError` or `NameError` due to mismatched keys between enrichment and policy.
**Solution**: Before touching logic, write down the *Data Contract*.
- **Task**: "Add OR Regime to Policy."
- **Contract**: [calculate_style_eligibility](file://wsl.localhost/Ubuntu-24.04/home/beast/projects/stock-ai-beast/engine/enrichment.py#L632) now REQUIRES `today_5min`.
- **Action**: Immediately grep all call sites and inject the new dependency *before* implementing the logic.

### 2. Proactive Signature Audits
**Problem**: Standard Python `locals()` or implicit context leads to silent failures.
**Solution**: Never assume a variable (like `context`) exists in the local scope of a helper function.
- **Rule**: If a function needs data from the "outside," pass it explicitly in the signature.
- **Workflow**: Change signature -> Mandatory Grep Callers -> Implement Logic.

### 3. Log-Driven Verification (Short-Circuit)
**Problem**: Waiting for full backtests is slow.
**Solution**: Insert `logger.info("[INTERFACE] Passing X to Y")` and run with `--debug` for a 15-minute slice.
- Verify the *interface bridge* works, then let the full backtest run in the background.

---

## 🏗️ Architectural Pitfalls (Phase 2.5 Learnings)

### The "REMR Rejection" Rule
- **Logic**: Price at S/R is **Location**; a wick/body rejection pattern is **Behavior**.
- **The Gate**: Never allow a Mean Reversion (REMR) entry unless [detect_rejection_pattern](file://wsl.localhost/Ubuntu-24.04/home/beast/projects/stock-ai-beast/engine/enrichment.py#L79) returns a valid pattern.

### The "Trend Energy" Requirement
- **Logic**: Entering a trend without energy is "fighting the drift."
- **The Gate**: `TREND` acceptance strictly requires [Impulse OR ExpandVol](file://wsl.localhost/Ubuntu-24.04/home/beast/projects/stock-ai-beast/brain/llm_client.py#L827).

### Momentum-Location Conflict
- **The Rule**: If `Close > Pivot` AND `MomentumSlope > 0`, **all Shorts are blocked** regardless of REMR signals.
- **Pointer**: Implemented as a universal filter in [get_tactical_update](file://wsl.localhost/Ubuntu-24.04/home/beast/projects/stock-ai-beast/brain/llm_client.py#L843).

### Frozen State Prevention
- **The Pitfall**: `open_position` metadata is snapshotted at **Entry**. Changing configuration files mid-trade will NOT affect it.
- **The Fix**: Manually patch `self.open_position` in [executor.py](file://wsl.localhost/Ubuntu-24.04/home/beast/projects/stock-ai-beast/hot_path/executor.py) for live fixes on ongoing trades.

### The "Cold Start" Index Trap
- **The Pitfall**: Accessing `daily_3[0]` (previous day) assumes history exists. On Day 1 of a long backtest (e.g., 720 days), `daily_3` is empty `[]`.
- **The Fix**: Always use safe extraction: `prev_day = daily_3[0] if daily_3 else {}`.
- **Impact**: Caused `IndexError: list index out of range` repeatedly during initialization.

### The "Look-Ahead" Data Leakage
- **The Pitfall**: `daily_3` comes from the DB. In a backtest, this list can include "Today's Candle" (partially or fully formed) because the DB query is simply "Latest 3 candles".
- **The Symptom**: `prev_close` becomes Today's Close. Gap calculation logic breaks (Gap = Open - TodayClose), often resulting in tiny or inverse gaps (e.g., -0.4 pts).
- **The Fix**: In `backtest.py`, always filter `daily_3` to find the first candle where `date < current_sim_date`.

### The "Silent Default" Bug (Data Echo vs Authority)
- **The Pitfall**: Reading computed metrics like `retracement_depth` or `momentum_slope` from the LLM's response (`data.get('micro_context')`).
- **The Risk**: The LLM often omits these nested keys or hallucinations values. Usage falls back to the default (e.g., "UNCERTAIN", 0.0), bypassing critical logic gates silently.
- **The Fix**: ALWAYS read these metrics from the local `micro_context` variable calculated by `enrichment.py` at the top of `get_tactical_update`.
- **Rule**: `data[...]` is for LLM Decisions (Action/Style). `micro_context[...]` is for Engine Facts.

---

---

## 🛡️ Maintenance Rules
1. **Grep Before Edit**: Always grep the function name before changing its arguments.
2. **Unified Keys**: Use `reference_levels` (support/pivot/resistance) consistently across `llm_client.py` and `enrichment.py`.
3. **Counterfactual Consistency**: If you change `STYLE_PARAMS`, you MUST update [counterfactual_truth.py](file://wsl.localhost/Ubuntu-24.04/home/beast/projects/stock-ai-beast/counterfactual_truth.py) or the reports will be inaccurate.

---

## 🚀 Phase 2.6: Advanced Reversals & Robustness

### LLM JSON Regex Fallback
- **The Pitfall**: LLMs often truncate output or hallucinate nested braces, causing `json.loads` to fail even after heuristic fixing.
- **The Solution**: Implemented a **Regex Last Resort** in [_query_model](file://wsl.localhost/Ubuntu-24.04/home/beast/projects/stock-ai-beast/brain/llm_client.py#L165-180).
- **Rule**: If JSON parsing fails, use regex to extract critical keys (`notes`, `reference_levels`) before giving up.

### The "V-Reversal" Intelligence
- **Logic**: Sharp turns often happen after extreme stretch without a standard consolidation ("V-Bottom").
- **The Gate**: `detect_v_reversal` triggers if `Exhaustion @ EM Low + Behavioral Rejection + Fast recovery`.
- **Policy**: ITC style is explicitly whitelisted for counter-trend reversals if `v_reversal=True`.
- **Location**: Implemented in [enrichment.py](file://wsl.localhost/Ubuntu-24.04/home/beast/projects/stock-ai-beast/engine/enrichment.py#L152-180).

### Intraday Directional Consistency
- **Problem**: Micro-momentum (`net_progress_3`) is too noisy for determining global trend alignment on large gap days.
- **Solution**: Use **Progress Since Open** (`Current Close - Intraday Open`) as the authoritative baseline for alignment.
- **Rule**: A `BUY_CALL` override only triggers if price is ABOVE the intraday open, regardless of micro-vips.
- **Location**: Updated in [get_tactical_update](file://wsl.localhost/Ubuntu-24.04/home/beast/projects/stock-ai-beast/brain/llm_client.py#L916-925).

### UI & Log Refinement Protocol
- **The Pitfall**: Assuming `JSON` payload keys automatically translate to visible text in Telegram/UI.
- **The Reality**: Third-party services (n8n, frontends) often use hardcoded templates or only extract specific fields. Adding a new key like `'balance'` to the JSON is useless if the `message` string isn't updated to include it.
- **The Fix**: **Explicit Text Injection**. If you want data to be visible, inject it directly into the `message` (Status) or `reason` (Trace) string fields.
- **Verification Rule**: Use `print(f"<<<TELEGRAM {type}>>> {json_str} <<<END>>>")` in `base_mode.py` to visually inspect the exact payload leaving the engine. Do not guess.

### The "Tuple Unpacking" Trap (Phase 2.7 Learning)
- **The Pitfall**: `ValueError: not enough values to unpack (expected 3, got 2)` after changing a function signature.
- **Wrong Assumption**: Docker container caching `.pyc` files, Python module import issues, need to restart/rebuild.
- **Reality**: An **early return statement** in the function still used the old signature.
- **The Mistake**: Wasted 10+ minutes on Docker restarts, cache clearing, when the fix was a single line of code.
- **The Fix**: When changing function return values, **grep ALL return statements** in that function first.
- **Example**: Changed `calculate_trend_efficiency` to return `(ter, regime, regime_momentum)`, but line 193 early return still had `return 0.0, "ROTATION"` (missing 3rd value).
- **Rule**: `git grep "return" <filename>` before assuming infrastructure issues. Code first, Docker second.

### 🚨 CASE STUDY: The "Premature Return" Dead Code Trap (Phase 2.7)
- **The Pitfall**: Implementing complex logic changes (like Phase 2.6 Symmetric Gating) but seeing **zero changes** in system behavior or logs during backtests.
- **The Symptom**: Backtests for known problematic days (e.g., Jan 9th) continued to show 0 trades despite adding new "Regime Momentum" filters. 
- **Root Cause Analysis (RCA)**: A legacy `return data` statement remained at line 928 of `llm_client.py` from a previous refactor. 
- **Impact**: ~800 lines of downstream logic—including all Phase 2.6 Metric Authority, Trend Acceptance, and Phase 2.7 fixes—were rendered **unreachable**.
- **The Lesson**: When a function evolves into multiple layers, an early return can silently kill entire features.
- **The Fix**: Consolidate functional layers. Instead of returning mid-function, use state variables (e.g., `data['action'] = "HOLD"`) and allow the function to reach its final, authoritative return point.
- **Verification Rule**: If you add new `logger` lines and they **NEVER** appear in the logs (even when they should be triggered), assume the code execution path is broken. Check for early returns or exception blocks that swallow the flow.
