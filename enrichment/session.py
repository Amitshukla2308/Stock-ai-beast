"""
v2.8 Enrichment: Session & Time Context
Pure fact-based session metrics.
"""
import logging
from datetime import datetime, time
from config.config_loader import config

logger = logging.getLogger(__name__)

def calculate_time_context(current_time_str):
    """
    Compute session phase and minutes since market open.
    """
    try:
        if not current_time_str or current_time_str == "N/A":
            return _default_context()
            
        parts = list(map(int, current_time_str.split(':')))
        hour, minute = parts[0], parts[1]
        current_time = datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
        today_date = current_time.date()
        
        # Market open (09:15)
        market_open = datetime.combine(today_date, time(9, 15))
        
        minutes_since_open = (current_time - market_open).total_seconds() / 60
        
        # Bias Decay (Weight decays from 1.0 to 0.0 over 60 minutes)
        bias_weight = max(0.0, 1.0 - (minutes_since_open / 60.0))
        if minutes_since_open > 60: 
            bias_weight = 0.0      
        
        # Classify session phase using config helper
        session_phase = config.get_session_phase(current_time_str)
        
        return {
            "minutes_since_open": int(minutes_since_open),
            "session_phase": session_phase,
            "bias_weight": round(bias_weight, 2)
        }
    except Exception as e:
        logger.error(f"Error calculating time context: {e}")
        return _default_context()

def _default_context():
    return {
        "minutes_since_open": 0,
        "session_phase": "UNKNOWN",
        "bias_weight": 1.0
    }

def calculate_morning_context(daily_hist, current_price, support, resistance, pivot, vix, atr_14):
    """
    Generate situational awareness for the Morning Brief.
    """
    if not daily_hist: return {}
    recent = daily_hist[:3]
    greens = sum(1 for d in recent if (d.get('c', 0) > d.get('o', 0)))
    reds = sum(1 for d in recent if (d.get('c', 0) < d.get('o', 0)))
    bias = 'BULLISH' if greens >= 2 else 'BEARISH' if reds >= 2 else 'NEUTRAL'
    
    expected_range = int(atr_14 * 1.5) if atr_14 else 200
    
    return {
        'primary_bias': bias,
        'bias_strength': 'STRONG' if (greens == 3 or reds == 3) else 'FRAGILE',
        'expected_range_pts': expected_range,
        'vix_regime': 'NORMAL' if 13 <= vix <= 18 else 'PANIC' if vix > 18 else 'COMPLACENT'
    }
