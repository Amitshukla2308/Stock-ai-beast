"""
v2.8 Signals: Stall Detection
Detects absorption and failure to extend.
"""
import logging

logger = logging.getLogger(__name__)

def detect_stall(last_bar, near_level=False):
    """
    Detects price 'stalling' at levels.
    Rule: Small body + high volume relative to range.
    """
    # Simple heuristic for now: Body < 20% of Range AND near important level
    # This represents absorption (heavy fighting, little progress)
    # This represents absorption (heavy fighting, little progress)
    h, l, o, c = last_bar.get('h'), last_bar.get('l'), last_bar.get('o'), last_bar.get('c')
    if None in (h, l, o, c): return False
    range_pts = h - l
    if range_pts <= 0: return False
    
    body = abs(c - o)
    is_small_body = (body / range_pts) < 0.25
    
    return is_small_body and near_level
