def construct_prompt(technical_state, news_summary=""):
    """
    Legacy prompt generator used by main_cxo.py.
    Updated to align with the new institutional-grade logic.
    """
    atr = technical_state.get('atr', 'N/A')
    
    prompt = f"""
# Role: Intraday Scalper (The Beast)
Your goal: Maximize PnL by generating precise entry/exit signals.

# Current Market State
- Price: {technical_state.get('current_price', 'N/A')}
- Trend: {technical_state.get('trend', 'UNKNOWN')}
- RSI: {technical_state.get('rsi', 50):.2f}
- ATR: {atr}
- Volatility: {technical_state.get('volatility', 0):.2f}%

# Macro Context
{news_summary if news_summary else "No major news updates."}

# Logic Guards
1. BUY_CALL is INVALID if SL > (Entry - (0.5 * {atr if atr != 'N/A' else 50})).
2. STALL FILTER: If Action is HOLD for 3 consecutive intervals, force Action: EXIT if PnL is flat.

# Output (JSON Only)
{{
    "action": "BUY_CALL" | "BUY_PUT" | "EXIT" | "HOLD",
    "entry": <float>,
    "sl": <float>,
    "target": <float>,
    "confidence": <0.0-1.0>,
    "reasoning": "Short technical justification."
}}
"""
    return prompt
