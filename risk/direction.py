"""
v2.8 Risk: Trade Direction & Filters
Decides BUY_CALL vs BUY_PUT and applies structural filters.
"""
import logging
from typing import Dict, Any
from config.config_loader import config

logger = logging.getLogger(__name__)

def decide_direction(selected_style: str, enrichment: Dict[str, Any], signals: Dict[str, Any]) -> Dict[str, Any]:
    """
    Decides the final action (BUY_CALL, BUY_PUT, or HOLD).
    Applies momentum-location conflict filters.
    """
    # 1. Default Direction (In a real select_style call, LLM provides this)
    # Since we're bridging, we'll assume a 'natural' direction if not provided
    # or use the structural break direction for trend styles.
    
    proposed_action = "HOLD"
    
    # Simple logic for now: 
    # REMR looks for reversals at levels
    if selected_style == "REMR":
        if enrichment.get('near_resistance'): proposed_action = "BUY_PUT"
        elif enrichment.get('near_support'): proposed_action = "BUY_CALL"
    
    # ITC follows the trend (break_direction is in SIGNALS, not enrichment)
    elif selected_style == "ITC":
        break_dir = signals.get('break_direction', 'NEUTRAL')
        if break_dir == "BULLISH": proposed_action = "BUY_CALL"
        elif break_dir == "BEARISH": proposed_action = "BUY_PUT"

    elif selected_style in ["ORE", "VBD", "LSRM"]:
        # Follow the breakout direction
        break_dir = signals.get('break_direction', 'NEUTRAL')
        if break_dir == "BULLISH": proposed_action = "BUY_CALL"
        elif break_dir == "BEARISH": proposed_action = "BUY_PUT"

    if proposed_action == "HOLD":
        return {"action": "HOLD", "reason": f"No clear directional signal for {selected_style}"}

    # 2. MOMENTUM-LOCATION CONFLICT FILTERS (v2.8 Authority)
    m_slope = enrichment.get('momentum_slope', 0.0)
    close = enrichment.get('price', 0.0)
    pivot = enrichment.get('pivot', 0.0)
    
    is_short = proposed_action == "BUY_PUT"
    is_long = proposed_action == "BUY_CALL"
    
    # Relaxed for v2.8.2: Use config thresholds and allow style overrides
    risk_cfg = config.get('RISK_RULES.momentum_slope', {})
    slope_threshold = risk_cfg.get('slope_threshold', -2.0)
    
    # Determine if we should enforce strict momentum conflict
    # REMR and VBD are often counter-momentum or volatility driven
    enforce_momentum = selected_style not in ["REMR", "VBD"]
    
    if enforce_momentum:
        # BLOCK short if price > Pivot AND Momentum is strongly upward
        if is_short and m_slope > abs(slope_threshold) and close > pivot:
            reason = f"Momentum Conflict: Put blocked vs strong positive slope ({m_slope})"
            logger.info(f"[RISK] 🛑 BLOCKING Trade: {reason}")
            return {"action": "HOLD", "reason": reason, "engine_decision": "BLOCKED"}
        
        # BLOCK call if price < Pivot AND Momentum is strongly downward
        if is_long and m_slope < slope_threshold and close < pivot:
            reason = f"Momentum Conflict: Call blocked vs strong negative slope ({m_slope})"
            logger.info(f"[RISK] 🛑 BLOCKING Trade: {reason}")
            return {"action": "HOLD", "reason": reason, "engine_decision": "BLOCKED"}

    # Log successful direction
    logger.info(f"[RISK] ✅ ALLOWED: {proposed_action} Style={selected_style} (Slope: {m_slope:.1f}, Pivot: {pivot:.1f})")
    return {"action": proposed_action}
