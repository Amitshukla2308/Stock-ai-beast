"""
v2.8 Eligibility: Style Logic
Determines allowed styles based on Enrichment + Signals + Config.
First Decision Layer.
Migrated from hot_path/executor.py (Phase 2 Refactor).
"""
from typing import Dict, Any
from config.config_loader import config

def evaluate_eligibility(enrichment: Dict[str, Any], signals: Dict[str, Any]) -> Dict[str, bool]:
    """
    Determine which styles are ELIGIBLE for this tick.
    Input: Enrichment Facts, Signal Patterns.
    Output: { "REMR": True, "ITC": False, ... }
    """
    eligibility = {
        "REMR": False,
        "ITC": False,
        "ORE": False,
        "VBD": False,
        "LSRM": False
    }
    
    # --- 1. REMR LOGIC (The Only Truth) ---
    # Enhanced v2.8: Use generic near_htf flag (covers S1/S2/R1/R2/Pivot/CPR)
    near_htf = enrichment.get('near_htf', False)
    
    # Check Signals
    reversion_trigger = signals.get('stall') or signals.get('rejection') or signals.get('compression')
    
    if near_htf and reversion_trigger:
        # Momentum Guard: Don't fade extremely strong momentum
        remr_cfg = config.get_remr_config()
        max_fade_slope = remr_cfg.get('max_fade_slope_atr_ratio', 0.5) * enrichment.get('atr', 15.0)
        m_slope = enrichment.get('momentum_slope', 0.0)
        
        if abs(m_slope) <= max_fade_slope:
            eligibility["REMR"] = True
        else:
            import logging
            logger = logging.getLogger(__name__)
            logger.debug(f"[ELIG] REMR blocked by strong momentum: {m_slope:.1f} > {max_fade_slope:.1f}")
        
    # --- 2. ITC LOGIC ---
    # Enhanced v2.8: Gated by CPR boundaries
    itc_cfg = config.get_itc_config()
    ter = enrichment.get('trend_efficiency', 0)
    regime = enrichment.get('trend_regime', 'ROTATION')
    min_ter = itc_cfg.get('min_TER', 0.55)
    
    # CPR Gate: Trend is prioritized when price is OUTSIDE the CPR
    price = enrichment.get('price', 0.0)
    bc, tc = enrichment.get('bc', 0.0), enrichment.get('tc', 0.0)
    outside_cpr = (price > tc or price < bc) if (tc > 0 and bc > 0) else True
    
    if outside_cpr:
        if (regime == 'TREND' and ter >= min_ter) or (regime == 'TRANSITION' and ter >= 0.40):
             eligibility["ITC"] = True

    # --- 3. ORE LOGIC (Opening Range Entry) ---
    # Time based breakout
    # FIX: Use 'time' key from enrichment instead of 'time_str'
    time_str = enrichment.get('time', '15:30')
    session_phase = enrichment.get('session_phase', config.get_session_phase(time_str))
    is_opening_phase = session_phase in ["OPENING_NOTE", "AM_SESSION"]
    range_break = signals.get('range_break', False)
    
    if is_opening_phase and range_break:
        eligibility["ORE"] = True

    # --- 4. VBD LOGIC (Volatility Breakout) ---
    # Compression + Breakout
    compression = signals.get('compression', False)
    
    if compression and range_break:
        eligibility["VBD"] = True
        
    # --- 5. LSRM LOGIC (Late Session Reversal Momentum) ---
    # Catch end-of-day squeeze or reversal
    is_late_session = session_phase in ["PM_SESSION", "CLOSING_SESSION"]
    strong_impulse = signals.get('impulse_detected', False)
    
    if is_late_session and strong_impulse:
        eligibility["LSRM"] = True

    # --- 6. MID-RANGE BLOCKING ---
    entry_loc = enrichment.get('location_class', 'UNKNOWN')
    if entry_loc == 'MID_RANGE':
        # VBD is specifically for mid-range breakouts
        if not eligibility["VBD"] and not config.get_global_switch('ALLOW_ROTATIONAL_EXECUTION'):
             eligibility["REMR"] = False
             eligibility["ORE"] = False
    
    return eligibility
