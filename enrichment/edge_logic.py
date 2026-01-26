"""
v2.9 Enrichment: Edge Logic (Deterministic Authority)
Shared logic for evaluating if an Alpha Edge is still valid.
Used by:
1. Trade Engine (Live Execution Kill Switch)
2. Research Engine (Post-Mortem Autopsy)
"""
from typing import Dict, Any, Optional

def check_edge_is_alive(
    entry_regime: int,
    current_regime: int,
    bars_held: int,
    current_pnl: float,
    d2_prob: float,
    trade_style: str = "ITC"
) -> bool:
    """
    Evaluate if the Alpha Edge is still valid. (SPEC-002)
    EDGE_ALIVE = (regime_valid AND d2_not_collapsed AND volatility_supportive)
    
    Args:
        entry_regime: The regime ID at entry.
        current_regime: The current regime ID.
        bars_held: Number of bars since entry.
        current_pnl: Unrealized PnL (points).
        d2_prob: Current D2 Probability (0.0-1.0).
        trade_style: "ITC" or "REMR".
        
    Returns:
        bool: True if edge is ALIVE, False if DEAD.
    """
    
    # 1. Regime Validity
    # Simplified: If current regime is NOT the entry regime (and not a known friend), it's invalid.
    # Friend map: R4->R9->R11->R5(Climax)
    
    valid_regime = True 
    
    if entry_regime in [9, 11]:
        # Strict Alpha Transition Rules
        valid_regime = False
        if current_regime == entry_regime: valid_regime = True
        if current_regime in [9, 11, 5]: valid_regime = True # Allow Climax/Transition
        if current_regime == 4: valid_regime = True # Allow soft degradation to Trend
            
    elif entry_regime in [4, 10]:
        # Trend Regimes
        # Die if chop (R2) or Reversal (R7)
        if current_regime in [2, 7]: valid_regime = False
        
    # 2. D2 Not Collapsed (Only applicable if we are tracking an Alpha Spike)
    d2_collapsed = False 
    if entry_regime in [9, 11] and d2_prob < 0.2: d2_collapsed = True
    
    # 3. PnL Threshold (Validation)
    # If after 5 bars, PnL < 0, edge is dubious.
    pnl_valid = True
    if bars_held > 5 and current_pnl < 0: pnl_valid = False
    
    is_alive = valid_regime and (not d2_collapsed) and pnl_valid
    return is_alive
