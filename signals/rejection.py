"""
v2.8 Signals: Behavioral Rejection
Detects wick-based rejection signatures with volume confirmation.
"""
import logging

logger = logging.getLogger(__name__)

def detect_rejection_pattern(bar, prev_bars=None):
    """
    Behavioral Rejection Signature (Canonical Phase-2.5)
    Requires: Wick > Body AND Close in extreme 40% AND Volume support.
    """
    h, l, o, c = bar.get('h'), bar.get('l'), bar.get('o'), bar.get('c')
    if None in (h, l, o, c): return "NONE"
    range_pts = h - l
    if range_pts <= 0: return "NONE"
    
    body = abs(c - o)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    
    # Volume Check
    rel_vol = 1.0
    if prev_bars and len(prev_bars) >= 5:
        avg_vol = sum(b.get('volume', 0) for b in prev_bars[-5:]) / 5
        rel_vol = bar.get('volume', 0) / avg_vol if avg_vol > 0 else 1.0
    
    # Rejection Logic (Config Authority)
    from config.config_loader import config as cfg
    rej_cfg = cfg.get_signal_config('rejection')
    wick_ratio_Limit = rej_cfg.get('wick_ratio', 0.60)
    body_limit = rej_cfg.get('body_range_pct', 0.40)
    
    wick_ratio_top = upper_wick / range_pts
    is_top_rejection = (wick_ratio_top > wick_ratio_Limit) and (c <= l + body_limit * range_pts) and (rel_vol >= 1.0)
    
    wick_ratio_bottom = lower_wick / range_pts
    is_bottom_rejection = (wick_ratio_bottom > wick_ratio_Limit) and (c >= h - body_limit * range_pts) and (rel_vol >= 1.0)
    
    if is_top_rejection: return "TOP_REJECTION"
    if is_bottom_rejection: return "BOTTOM_REJECTION"
    return "NONE"
