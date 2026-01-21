"""
v2.8 Signals: Range Compression
Detects tight consolidation periods.
"""
import logging

logger = logging.getLogger(__name__)

from config.config_loader import config

def detect_compression(last_range, atr_14):
    """
    Detects if the current range is compressed relative to ATR.
    Rule: Range < Configured Ratio * ATR.
    """
    if not atr_14 or atr_14 <= 0: return False
    
    ratio = config.get_signal_config('compression').get('ratio', 0.5)
    return last_range < (ratio * atr_14)
