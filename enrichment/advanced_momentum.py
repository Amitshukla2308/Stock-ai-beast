"""
v2.8 Enrichment: Advanced Momentum Physics
Calculates kinematic properties of price action:
- Velocity (First Derivative / Slope)
- Acceleration (Second Derivative / Change in Slope)
- Skew (Distribution Asymmetry)

Mathematical Basis:
- Velocity is derived via Linear Regression Slope (more robust than simple ROC).
- Acceleration is the rate of change of Velocity.
- Skew measures the 'tail risk' or directional bias of the returns distribution.
"""
import statistics
import math
from typing import List, Optional

def calculate_slope(series: List[float]) -> float:
    """
    Calculates the slope of the linear regression line for a series.
    y = mx + c
    Returns 'm'.
    """
    n = len(series)
    if n < 2:
        return 0.0
        
    x = list(range(n))
    mean_x = statistics.mean(x)
    mean_y = statistics.mean(series)
    
    numerator = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, series))
    denominator = sum((xi - mean_x) ** 2 for xi in x)
    
    if denominator == 0:
        return 0.0
        
    return numerator / denominator

def calculate_velocity(candles: List[dict], period: int = 14) -> float:
    """
    Calculates Price Velocity (Points per Bar).
    Uses Linear Regression Slope over the period.
    Positive = Upward Velocity.
    Negative = Downward Velocity.
    """
    if not candles or len(candles) < period:
        return 0.0
        
    closes = [c['c'] for c in candles[-period:]]
    return round(calculate_slope(closes), 2)

def calculate_acceleration(candles: List[dict], period: int = 14) -> float:
    """
    Calculates Price Acceleration (Change in Velocity).
    Compares current velocity vs previous velocity.
    """
    if not candles or len(candles) < period + 1:
        return 0.0
    
    # Needs enough data for two velocity points. 
    # Actually, proper acceleration is the slope of the velocity series.
    # But for efficiency, we often approximate as V_now - V_prev
    
    # We will compute velocity for the current window [t-p : t]
    # And velocity for the previous window [t-p-1 : t-1]
    
    current_window = [c['c'] for c in candles[-period:]]
    prev_window = [c['c'] for c in candles[-(period+1):-1]]
    
    v_now = calculate_slope(current_window)
    v_prev = calculate_slope(prev_window)
    
    acceleration = v_now - v_prev
    return round(acceleration, 4)

def calculate_skew(candles: List[dict], period: int = 20) -> float:
    """
    Calculates statistical Skewness of the returns distribution.
    Negative skew = Frequent small gains, few large losses (Crash risk).
    Positive skew = Frequent small losses, few large gains (Lottery profile).
    """
    if not candles or len(candles) < period + 1:
        return 0.0
        
    # Calculate returns
    returns = []
    for i in range(1, len(candles[-period:])):
        curr = candles[-period:][i]['c']
        prev = candles[-period:][i-1]['c']
        if prev == 0: continue
        ret = (curr - prev) / prev
        returns.append(ret)
        
    if len(returns) < 3:
        return 0.0
        
    try:
        # Fisher-Pearson coefficient of skewness
        n = len(returns)
        mean_r = statistics.mean(returns)
        stdev_r = statistics.stdev(returns)
        
        if stdev_r == 0:
            return 0.0
            
        cubed_deviations = sum((x - mean_r) ** 3 for x in returns)
        skew = (cubed_deviations * n) / ((n - 1) * (n - 2) * (stdev_r ** 3))
        
        return round(skew, 4)
    except Exception:
        return 0.0
