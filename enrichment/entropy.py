"""
v2.8 Enrichment: Market Entropy
Quantifies the 'disorder' or 'information content' of price/volume series.
Used to distinguish between Structured Trends (Low Entropy) and Random Chop (High Entropy).
"""
import math
from typing import List, Union

def calculate_shannon_entropy(data: List[float], num_bins: int = 10) -> float:
    """
    Calculates Shannon Entropy of a data series.
    H(X) = -sum(p(x) * log2(p(x)))
    
    Args:
        data: List of numerical values (e.g., price changes, volume).
        num_bins: Number of bins for discretization histogram.
        
    Returns:
        float: Entropy value (bits). higher = more random/complex.
    """
    if not data or len(data) < 2:
        return 0.0
        
    # 1. Discretize data into bins
    min_val = min(data)
    max_val = max(data)
    
    if min_val == max_val:
        return 0.0
        
    range_val = max_val - min_val
    bin_width = range_val / num_bins
    
    # Histogram count
    bins = [0] * num_bins
    for x in data:
        # Determine bin index
        idx = int((x - min_val) / bin_width)
        # Handle edge case where x == max_val
        if idx == num_bins:
            idx -= 1
        bins[idx] += 1
        
    # 2. Calculate Probabilities and Entropy
    total_count = len(data)
    entropy = 0.0
    
    for count in bins:
        if count > 0:
            p = count / total_count
            entropy -= p * math.log2(p)
            
    return round(entropy, 4)

def calculate_price_entropy(candles: List[dict], period: int = 60) -> float:
    """
    Calculates entropy of the *Price Location* within the range.
    High Entropy = Price spent equal time everywhere (Chop/Range).
    Low Entropy = Price spent time clustered (Trend/Breakout).
    """
    if not candles or len(candles) < period:
        return 0.0
        
    # Extract closes
    closes = [c['c'] for c in candles[-period:]]
    
    # We want the distribution of locations relative to the window range
    return calculate_shannon_entropy(closes, num_bins=10)

def calculate_volume_entropy(candles: List[dict], period: int = 60) -> float:
    """
    Calculates entropy of Volume distribution.
    Uniform volume = High Entropy.
    Spiky volume (events) = Low Entropy.
    """
    if not candles or len(candles) < period:
        return 0.0
        
    volumes = [float(c.get('v', 0)) for c in candles[-period:]]
    return calculate_shannon_entropy(volumes, num_bins=10)
