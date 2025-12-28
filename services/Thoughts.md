Hybrid Precision Implementation
1. Data Offloading (Mathematical Stabilization)

Problem: The LLM currently hallucinates ATR values (varying from 12.5 to 123.4 in stable markets), leading to "suicide stops". Action: Do not ask the LLM to calculate math. Compute these in your Python script and pass them as static constants.


Python Task: Calculate ATR_14 (Rolling 15-min) and Current_Range (Current 5-min candle).

Prompt Variable: Replace # Instructions for Internal Calculation with:

Fixed Technicals:

Current ATR: {{atr_val}}

Relative Volatility: [LOW | MED | HIGH]

Distance to Support: {{pts}} pts

2. Context Pruning (Latency Reduction)

Problem: Tactical latency is hitting 4.9s. Scalping Nifty requires <1s execution to avoid slippage. Action: The "Tactical Brain" does not need 14 bars of history.


Keep: Last 3 candles (5-Min) + Morning Pivot Levels.


Drop: The 15-min rolling history for tactical prompts.

Result: Expected token reduction of ~60%, dropping latency to sub-2s on your 5090.

3. Sampling Optimization (Determinism)
Problem: High variance in SL/Target output due to Temperature: 0.7. Action: Force deterministic output.

Temperature: 0.0 or 0.1.

Top_P: 0.9.

Frequency Penalty: 0.0 (Technical terms like "SL" and "HOLD" should not be penalized).

4. Implementation Constraints (Safety)
Inject these strict logic guards directly into your system message:

Buffer Guard: Action: BUY_CALL is invalid if SL > (Entry - (0.5 * ATR)).

Stall Filter: If Action: HOLD for 3 consecutive 5-min ticks, force Action: EXIT if PnL is flat.

JSON Schema: Use a single-level JSON structure. Nested objects increase parsing errors and latency.

⚠️ Cautions & Skips
Feature	Action	Risk if Ignored
Math Offloading	MANDATORY	
Hallucinated SLs will wipe out your account. 


Context Pruning	HIGHLY RECOMMENDED	High latency will lead to "late entries" on momentum bursts.
Multi-Model Routing	SKIP (Architectural)	If setting up a 7B/32B router is too complex, skip it. Stick to the 32B Boss but use AWQ 4-bit quantization for speed.
VIX Delta Filter	OPTIONAL	If your data feed doesn't provide VIX in real-time, skip the intraday VIX logic and only use the Morning VIX value.

Export to Sheets

Final Recommended Tactical Output Schema
JSON

{
    "decision": "BUY_CALL",
    "entry": 17275.0,
    "sl": 17255.0,
    "target": 17315.0,
    "logic_code": "MOMENTUM_BREAKOUT",
    "confidence": 0.85
}
Pro-Tip for Amit:
Since you are on an RTX 5090, ensure you are using vLLM with enforce_eager=True. This reduces memory overhead for shorter, tactical prompts and significantly improves the "Time to First Token," which is your most critical metric for scalping.