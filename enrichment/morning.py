"""
v2.8 Enrichment: Morning Context
Enrichment logic for Morning Briefing (09:20).
Calculates Pivots, Gaps, and Authoritative Expectations.
Migrated from brain/llm_client.py.
"""
from typing import Dict, Any, List

def calculate_pivots(daily_data: List[Dict[str, Any]]) -> Dict[str, float]:
    """
    Calculate Standard Pivots (S2 to R2) from Prior Day.
    Input: List of daily candles (Index 0 = Previous Day).
    """
    if not daily_data:
        return {'pivot': 0.0, 's1': 0.0, 's2': 0.0, 'r1': 0.0, 'r2': 0.0}
        
    prev_day = daily_data[0]
    h = float(prev_day.get('h', prev_day.get('high', 0)))
    l = float(prev_day.get('l', prev_day.get('low', 0)))
    c = float(prev_day.get('c', prev_day.get('close', 0)))
    
    if h and l and c:
        p = round((h + l + c) / 3, 1)
        r1 = round(2 * p - l, 1)
        s1 = round(2 * p - h, 1)
        r2 = round(p + (h - l), 1)
        s2 = round(p - (h - l), 1)
        return {
            'pivot': p,
            's1': s1, 's2': s2,
            'r1': r1, 'r2': r2
        }
    
    return {'pivot': 0.0, 's1': 0.0, 's2': 0.0, 'r1': 0.0, 'r2': 0.0}

def calculate_cpr(daily_data: List[Dict[str, Any]]) -> Dict[str, float]:
    """
    Calculate Central Pivot Range (CPR) - BC and TC.
    Formula:
    Pivot = (H+L+C)/3
    BC = (H+L)/2
    TC = (Pivot - BC) + Pivot
    """
    if not daily_data:
        return {'pivot': 0.0, 'bc': 0.0, 'tc': 0.0}
        
    prev_day = daily_data[0]
    h = float(prev_day.get('h', prev_day.get('high', 0)))
    l = float(prev_day.get('l', prev_day.get('low', 0)))
    c = float(prev_day.get('c', prev_day.get('close', 0)))
    
    if h and l and c:
        p = (h + l + c) / 3
        bc = (h + l) / 2
        tc = (p - bc) + p
        
        # Ensure tc is always the higher one for consistency in logic
        actual_tc = max(tc, bc)
        actual_bc = min(tc, bc)
        
        return {
            'pivot': round(p, 1),
            'bc': round(actual_bc, 1),
            'tc': round(actual_tc, 1)
        }
        
    return {'pivot': 0.0, 'bc': 0.0, 'tc': 0.0}

def analyze_gap(current_open: float, prev_close: float) -> Dict[str, Any]:
    """
    Analyze Morning Gap.
    """
    if not prev_close or not current_open:
        return {'points': 0.0, 'percent': 0.0, 'direction': 'FLAT'}
        
    gap_points = round(current_open - prev_close, 2)
    gap_direction = "UP" if gap_points >= 0 else "DOWN"
    gap_pct = round((gap_points / prev_close) * 100, 2)
    
    gap_type = 'NORMAL'
    if abs(gap_pct) >= 3.0: gap_type = 'EXTREME'
    elif abs(gap_pct) >= 1.5: gap_type = 'SIGNIFICANT'
    
    return {
        'points': gap_points,
        'percent': gap_pct,
        'direction': gap_direction,
        'type': gap_type
    }

def get_prior_candles(daily_data: List[Dict[str, Any]]) -> Dict[str, float]:
    """Format Last 3 Daily Candles for Prompt"""
    d_candles = {}
    for i, idx in enumerate([2, 1, 0]):
        key_idx = i + 1
        d_candles[f'd{key_idx}_open'] = 0.0
        d_candles[f'd{key_idx}_high'] = 0.0
        d_candles[f'd{key_idx}_low'] = 0.0
        d_candles[f'd{key_idx}_close'] = 0.0
        
        if len(daily_data) > idx:
            d = daily_data[idx]
            d_candles[f'd{key_idx}_open'] = d.get('o', d.get('open', 0))
            d_candles[f'd{key_idx}_high'] = d.get('h', d.get('high', 0))
            d_candles[f'd{key_idx}_low'] = d.get('l', d.get('low', 0))
            d_candles[f'd{key_idx}_close'] = d.get('c', d.get('close', 0))
            
    return d_candles
