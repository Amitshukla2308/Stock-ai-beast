"""
v2.8 Enrichment: Location & Proximity
Calculates price relationship to key levels.
"""
import logging
from config.config_loader import config

logger = logging.getLogger(__name__)

def calculate_proximity(current_price, levels_dict, or_range, atr):
    """
    Calculates NEAR flags based on config-driven thresholds for ALL provided levels.
    """
    proximity_limit = config.get_proximity_threshold('REMR', or_range, atr)
    
    results = {
        "near_htf": False,
        "nearest_level_name": "NONE",
        "nearest_level_dist": 999999.0,
        "proximity_limit": proximity_limit
    }
    
    # Check all levels in the dict
    for name, val in levels_dict.items():
        if val is None or val <= 0: continue
        
        dist = abs(current_price - val)
        if dist < results["nearest_level_dist"]:
            results["nearest_level_dist"] = dist
            results["nearest_level_name"] = name.upper()
            
        if dist <= proximity_limit:
            results[f"near_{name}"] = True
            results["near_htf"] = True
        else:
            results[f"near_{name}"] = False
            
    return results

def classify_location(current_price, levels_dict, proximity_limit):
    """
    Classifies absolute location based on the full level hierarchy.
    """
    # Find the nearest level
    min_dist = 999999.0
    nearest_name = "MID_RANGE"
    
    for name, val in levels_dict.items():
        if val is None or val <= 0: continue
        dist = abs(current_price - val)
        if dist < min_dist:
            min_dist = dist
            nearest_name = name.upper()
            
    # Classification Logic
    if min_dist < 5:
        location = f"OPTIMAL_{nearest_name}"
    elif min_dist <= proximity_limit:
        location = f"NEAR_{nearest_name}"
    else:
        location = "MID_RANGE"
        
    return {
        "location_class": location,
        "nearest_structural_level": nearest_name,
        "dist_to_nearest": round(min_dist, 2),
        "all_levels_dist": {name: round(abs(current_price - val), 2) for name, val in levels_dict.items() if val > 0}
    }
