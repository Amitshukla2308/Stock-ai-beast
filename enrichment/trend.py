"""
v2.8 Enrichment: Trend & Momentum
Pure fact-based trend metrics.
"""
import logging

logger = logging.getLogger(__name__)

def calculate_trend_efficiency(bars, window=5):
    """
    TER = abs(NetDisplacement) / SumRanges.
    """
    if not bars or len(bars) < window: 
        return 0.0, "ROTATION", 0.0
        
    try:
        recent_bars = bars[-window:]
        net_displacement = recent_bars[-1]['c'] - recent_bars[0]['o']
        sum_ranges = sum((b['h'] - b['l']) for b in recent_bars)
        
        ter = abs(net_displacement) / max(sum_ranges, 1e-6)
        ter = round(ter, 2)
    except (KeyError, TypeError):
        return 0.0, "ROTATION", 0.0
    
    # Calculate Regime Momentum (Delta in TER)
    regime_momentum = 0.0
    if len(bars) >= (window * 2):
        bars_prev = bars[-(window*2):-window]
        net_prev = bars_prev[-1]['c'] - bars_prev[0]['o']
        sum_ranges_prev = sum((b['h'] - b['l']) for b in bars_prev)
        ter_prev = abs(net_prev) / max(sum_ranges_prev, 1e-6)
        regime_momentum = round(ter - ter_prev, 3)
    
    # Classification (Config Authority)
    from config.config_loader import config as cfg
    trend_cfg = cfg.get_signal_config('trend')
    t_trend = trend_cfg.get('ter_threshold_trend', 0.55)
    t_trans = trend_cfg.get('ter_threshold_transition', 0.30)
    
    regime = "ROTATION"
    if ter > t_trend: 
        regime = "TREND"
    elif ter >= t_trans: 
        regime = "TRANSITION"
        
    return ter, regime, regime_momentum

def calculate_momentum_slope(bars_3):
    """Directional energy over last 3 bars using linear regression slope."""
    if len(bars_3) < 3: 
        return 0.0, 0.0
        
    y = [b['c'] for b in bars_3]
    x = [0, 1, 2]
    n = len(x)
    
    sum_x = sum(x)
    sum_y = sum(y)
    sum_xx = sum(i*i for i in x)
    sum_xy = sum(x[i]*y[i] for i in range(n))
    
    denom = (n * sum_xx - sum_x**2)
    slope = (n * sum_xy - sum_x * sum_y) / denom if denom != 0 else 0.0
    
    consistency = 1.0 if (y[2] > y[1] > y[0]) or (y[2] < y[1] < y[0]) else 0.5
    return round(slope, 2), consistency
