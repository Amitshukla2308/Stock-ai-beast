"""
v2.8 Signals: Range Break
Detects high-conviction breakout candles.
"""
import logging

logger = logging.getLogger(__name__)

from config.config_loader import config

def detect_range_break(last_bar):
    """
    Detects if the current candle is a high-body 'conviction' break.
    Rule: Body > Configured Ratio of Range.
    """
    h, l, o, c = last_bar.get('h'), last_bar.get('l'), last_bar.get('o'), last_bar.get('c')
    if None in (h, l, o, c): return False
    range_pts = h - l
    if range_pts <= 0: return False
    
    body = abs(c - o)
    ratio = config.get_signal_config('range_break').get('conviction_ratio', 0.6)
    return (body / range_pts) > ratio
