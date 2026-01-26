"""
v2.9 Enrichment: Research Diagnostics (State Engine)
Generates DETERMINISTIC Truth about trade quality, edge timelines, and execution delta.
Used to feed the LLM with facts, preventing hallucination.
"""
from typing import Dict, Any, List
from trade.models import Trade
from enrichment.edge_logic import check_edge_is_alive
from enrichment.advanced_momentum import calculate_velocity
from enrichment.entropy import calculate_price_entropy

def classify_regime_class(regime_id: int) -> str:
    """Map Regime ID to abstract class"""
    mapping = {
        11: "ALPHA", 9: "ALPHA",
        4: "TREND", 10: "TREND",
        0: "NOISE", 1: "NOISE", 2: "NOISE",
        7: "TRAP", 5: "TRANSITION", 6: "DRAG", 8: "DRAG", 3: "PRECURSOR"
    }
    return mapping.get(int(regime_id), "UNKNOWN")

def analyze_trade_physics(trade: Trade, previous_bars: List[dict]) -> Dict[str, Any]:
    """
    Compute physics vectors at valid moments (Entry context).
    Uses 'physics_ctx' from Trade if available (State Capture),
    otherwise attempts replay (Legacy/Backup).
    """
    # 1. Prefer Live Capture
    if hasattr(trade, 'physics_ctx') and trade.physics_ctx:
        ctx = trade.physics_ctx
        velocity = ctx.get('velocity', 0.0)
        entropy = ctx.get('entropy', 0.0) # check key name
        if 'entropy' not in ctx: entropy = ctx.get('entropy_price', 0.0)
    else:
        # 2. Replay Backup
        if not previous_bars:
            return {"velocity": 0.0, "entropy": 0.0, "supported": False}
        velocity = calculate_velocity(previous_bars, period=6)
        entropy = calculate_price_entropy(previous_bars, period=12)
    
    # Heuristic Support Check (Trend Logic)
    supported = False
    if trade.style == "ITC":
        if trade.direction == "CALL" and velocity > 0 and entropy < 1.8: supported = True
        if trade.direction == "PUT" and velocity < 0 and entropy < 1.8: supported = True
    elif trade.style == "REMR":
        # REMR likes extremes. High Vel (Climax) + ?
        # Or High Entropy (Chop)?
        if entropy > 2.0: supported = True 
        
    return {
        "velocity": velocity,
        "entropy": entropy,
        "supported": supported
    }

def replay_edge_timeline(trade: Trade, bars: List[dict] = None) -> Dict[str, Any]:
    """
    Compute edge timeline metrics using captured state.
    Returns: {edge_alive_bars, bars_held_post_death, etd_pnl, missed_exit}
    """
    death_bar = trade.edge_death_bar
    total_bars = trade.bars_held
    
    is_dead = death_bar is not None
    
    # 1. Edge Vitality
    # If it never died, it was alive for all bars
    alive_bars = death_bar if is_dead else total_bars
    drag_bars = (total_bars - death_bar) if is_dead else 0
    
    return {
        "edge_alive_bars": alive_bars,
        "drag_bars": drag_bars,
        "pnl_at_death": trade.pnl_edge_death,
        "etd_pnl": trade.etd,
        "missed_exit": drag_bars > 3 # Logic: Held > 3 bars after death is a "Miss"
    }

def compute_research_state(trade: Trade, context_bars: List[dict] = None) -> Dict[str, Any]:
    """
    Main entry point for Research State Generation.
    """
    try:
        regime_id = int(trade.regime)
    except:
        regime_id = -1
        
    r_class = classify_regime_class(regime_id)
    
    # Physics (Prefer Live Capture)
    physics = analyze_trade_physics(trade, context_bars if context_bars else [])
    
    # Timeline (Deterministic)
    timeline = replay_edge_timeline(trade)
    
    return {
        "trade_id_short": trade.trade_id[-4:],
        "regime_class": r_class,
        "regime_id": regime_id,
        "fitness_score": 1.0 if r_class in ["ALPHA", "TREND"] and trade.style == "ITC" else 0.5,
        "physics": physics,
        "timeline": timeline,
        "competency": {
            "brain_override": False, 
            "shadow_delta": trade.shadow_pnl - trade.pnl_points if trade.shadow_pnl is not None else 0.0
        }
    }
