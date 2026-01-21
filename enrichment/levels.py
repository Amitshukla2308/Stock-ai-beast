"""
v2.8 Enrichment: Levels & Structural Benchmarks
Handles S/R, Pivot, and VWAP facts.
"""
import logging

logger = logging.getLogger(__name__)

def calculate_vwap(bars):
    """Calculates VWAP from a list of bars."""
    if not bars: return 0.0
    cum_pv = 0.0
    cum_vol = 0.0
    for b in bars:
        price = (b['h'] + b['l'] + b['c']) / 3
        vol = b.get('volume', 0)
        cum_pv += price * vol
        cum_vol += vol
    return round(cum_pv / cum_vol, 2) if cum_vol > 0 else 0.0

def get_reference_levels(plan):
    """
    Extracts support, resistance, pivot, and CPR levels from plan.
    Returns a unified dict of levels.
    """
    if not plan: 
        return {
            'pivot': 0.0, 's1': 0.0, 's2': 0.0, 'r1': 0.0, 'r2': 0.0,
            'bc': 0.0, 'tc': 0.0
        }
    
    levels = plan.get('reference_levels', {})
    
    # Support backward compatibility while migrating
    pivot = levels.get('pivot', 0.0)
    s1 = levels.get('s1', levels.get('support', 0.0))
    r1 = levels.get('r1', levels.get('resistance', 0.0))
    
    return {
        'pivot': pivot,
        's1': s1,
        's2': levels.get('s2', 0.0),
        'r1': r1,
        'r2': levels.get('r2', 0.0),
        'bc': levels.get('bc', 0.0),
        'tc': levels.get('tc', 0.0)
    }
