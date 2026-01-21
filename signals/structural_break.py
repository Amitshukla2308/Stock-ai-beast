"""
v2.8 Signals: Structural Break & Impulse
Detects multi-bar impulse moves and structural breaks.
"""
import logging

logger = logging.getLogger(__name__)

from config.config_loader import config

def detect_impulse(bars_15min, atr_14):
    """
    Impulse = 3+ bars in same direction with range expansion.
    """
    if not bars_15min or len(bars_15min) < 3 or not atr_14:
        return False, "NEUTRAL"
        
    try:
        b1, b2, b3 = bars_15min[-3:]
        
        # Bullish Impulse: 3 rising closes + last bar range exceeds ATR
        is_bull = (b3['c'] > b2['c'] > b1['c']) and ((b3['h'] - b3['l']) > atr_14)
        
        # Bearish Impulse: 3 falling closes + last bar range exceeds ATR
        is_bear = (b3['c'] < b2['c'] < b1['c']) and ((b3['h'] - b3['l']) > atr_14)
        
        direction = "BULLISH" if is_bull else "BEARISH" if is_bear else "NEUTRAL"
        return (is_bull or is_bear), direction
    except (KeyError, TypeError):
        return False, "NEUTRAL"

def detect_structural_break(last_close, or_high, or_low, atr):
    """
    Detects if price has broken out of the Opening Range with momentum.
    """
    if or_high is None or or_low is None or not atr:
        return False, "NONE"
        
    buffer_ratio = config.get_signal_config('structural_break').get('buffer_ratio', 0.2)
    buffer = buffer_ratio * atr
    
    if last_close > (or_high + buffer):
        return True, "UP"
    if last_close < (or_low - buffer):
        return True, "DOWN"
        
    return False, "NONE"
