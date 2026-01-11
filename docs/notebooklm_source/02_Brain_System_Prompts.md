# 2. Brain System Prompts & Logic

The "Brain" is driven by three specialized prompt architectures defined in `brain/prompts.py`. These prompts are engineered for "Chain of Command" rather than "Chain of Thought" to reduce latency and hallucination.

## 1. Morning Brief (Strategic)
**Trigger**: 09:20 AM (Pre-market/Market open)
**Goal**: Define the "Market Personality" and "Bias".

### Key Logic:
*   **Gap Analysis**:
    *   `< 1.5%`: Normal Gap (Fill likely)
    *   `1.5% - 3%`: Significant Gap (Wait for confirmation)
    *   `> 3%`: Extreme Gap (Ride momentum, do not fade)
*   **VIX Regime**:
    *   `< 13`: Complacent (Tight SLs)
    *   `13-18`: Normal
    *   `> 18`: Panic (Wide SLs)
*   **Pivot Calculation**: Uses Classic Pivot Points (P, R1, S1) based on the previous 3 days of OHLC.

## 2. Tactical Update (Command)
**Trigger**: Every 15 minutes (09:30, 09:45, ...)
**Goal**: Issue `BUY_CALL`, `BUY_PUT`, or `HOLD` commands.

### Decision Rules (Embedded in Prompt):
*   **Bias Alignment**: If `Morning Bias = BULLISH`, penalize PUT signals (reduce confidence by 20%).
*   **Time Factor**:
    *   10:00 - 12:30: Prime Time (+15% Confidence)
    *   > 13:30: Risk Zone (-20% Confidence)
*   **Level Respect**:
    *   Do NOT buy PUTs if within 20pts of Support.
    *   Do NOT buy CALLs if within 20pts of Resistance.
*   **SL/Target Math**:
    *   `SL = 0.4 * Daily_Range * VIX_Multiplier`
    *   `Target = 2.5 * SL` (Trending) or `2.0 * SL` (Choppy)

## 3. EOD Auditor (Reflection)
**Trigger**: 15:30 PM
**Goal**: Learn from mistakes.

### Tasks:
1.  **Greed Gap Analysis**: Did we have a large unrealized profit (Peak PnL) but exit for a loss? Why?
2.  **Root Cause Classification**:
    *   `SL_HUNT`: Stop was too tight for the VIX regime.
    *   `WRONG_BIAS`: The morning predictions were incorrect.
    *   `LATE_EXIT`: Held too long.
3.  **Nugget Extraction**:
    *   Generates a text "Nugget" (e.g., "Avoid breakout entries when VIX < 12") which is saved to `knowledge_nuggets` table.

## JSON Recovery System
Located in `brain/llm_client.py`, the `_query_model` function includes a "Self-Healing" parser:
*   **Truncation Repair**: If the LLM cuts off mid-JSON, it heuristically adds closing braces `}` and quotes `"` to make it valid.
*   **Hallucination Fixes**: regex replacements for common LLM errors (e.g., converting `""trade""` to `"trade"`).
