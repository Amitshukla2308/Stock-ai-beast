"""
v2.8 Signals: Momentum Exhaustion
Detects if market has exceeded statistical movement thresholds.
Migrated from hot_path/executor.py (Phase 2 Refactor).
Boolean/Enum ONLY. No trading decisions.
"""
from typing import Dict
from config.config_loader import config

def check_exhaustion(momentum_state: Dict[str, float], direction: str) -> str:
    """
    Check signal: Is momentum exhausted?
    Args:
        momentum_state: Output from enrichment.momentum
        direction: "UP" or "DOWN" (direction of trade interest)
    Returns:
        "FRESH" | "AVG1" | "AVG2" | "AVG3" | "EXCEEDED"
    """
    # 1. Get Thresholds from Config Authority
    thresholds = config.get_signal_config('momentum')
    if not thresholds:
        return "FRESH" # Safe fallback

    avg1 = thresholds.get('avg1', 400)
    avg2 = thresholds.get('avg2', 560)
    avg3 = thresholds.get('avg3', 780)
    
    # 2. Get relevant movement
    movement = 0.0
    if direction == "UP":
        movement = momentum_state.get('upward_movement', 0.0)
    elif direction == "DOWN":
        movement = momentum_state.get('downward_movement', 0.0)
    
    # 3. Classify
    if movement >= avg3:
        return "EXCEEDED"
    elif movement >= avg2:
        return "AVG3"
    elif movement >= avg1:
        return "AVG2"
    else:
        return "FRESH"
