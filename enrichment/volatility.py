"""
v2.8 Enrichment: Volatility & Ranges
Pure fact-based volatility metrics.
"""
import logging

logger = logging.getLogger(__name__)

def calculate_opening_range(today_5min):
    """Extracts High and Low between 09:15 and 10:00 IST."""
    if not today_5min: return None
    or_bars = []
    for b in today_5min:
        try:
            time_str = b['ts'][11:16] if 'ts' in b else ""
            if "09:15" <= time_str <= "10:00": 
                or_bars.append(b)
        except: 
            continue
            
    if not or_bars: return None
    or_high = max(b['h'] for b in or_bars)
    or_low = min(b['l'] for b in or_bars)
    return {
        "or_high": round(or_high, 1), 
        "or_low": round(or_low, 1), 
        "or_range": round(or_high - or_low, 1)
    }

def calculate_expected_move_envelope(or_range, prior_day_range):
    """Calculates EM envelope based on OR range relative to prior day range."""
    if not or_range or not prior_day_range: 
        return {
            "or_range": 0, 
            "volatility_of_day": "NORMAL", 
            "expected_move_low": 10, 
            "expected_move_high": 40
        }
        
    # Canonical thresholds for volatility classification
    vol = "NORMAL"
    if or_range >= 0.35 * prior_day_range:
        vol = "HIGH"
    elif or_range <= 0.20 * prior_day_range:
        vol = "LOW"
        
    return {
        "or_range": or_range, 
        "volatility_of_day": vol, 
        "expected_move_low": int(0.6 * or_range), 
        "expected_move_high": int(1.2 * or_range)
    }

def calculate_atr(candles, period=14):
    """
    Calculates Average True Range (ATR) from a list of candles.
    Uses Simple Moving Average (SMA) of True Range for robustness.
    """
    if not candles or len(candles) < period + 1:
        return 0.0
        
    # Calculate True Ranges
    true_ranges = []
    for i in range(1, len(candles)):
        curr = candles[i]
        prev = candles[i-1]
        
        h, l, c = curr.get('h', 0), curr.get('l', 0), curr.get('c', 0)
        pc = prev.get('c', 0)
        
        tr = max(h - l, abs(h - pc), abs(l - pc))
        true_ranges.append(tr)
        
    if len(true_ranges) < period:
        return 0.0
        
    # Return SMA of last 'period' TRs
    recent_tr = true_ranges[-period:]
    atr = sum(recent_tr) / period
    return round(atr, 2)
