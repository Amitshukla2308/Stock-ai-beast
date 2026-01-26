from typing import Dict, Any

# CONFIGURATION: LOCKED (RELAXED MODE)
# RELAXED MODE = 2 Lots for Regime 11 AND 9
SIZING_MODE = "RELAXED"

class ExposureMapper:
    def __init__(self, mode=SIZING_MODE):
        self.mode = mode
        
    def get_lots(self, policy_descriptor: Dict[str, Any]) -> int:
        """
        Maps Policy Outcome -> Fixed Lot Size (0, 1, 2)
        NO INTELLIGENCE ALLOWED. PURE MAPPING.
        """
        # Extract determining fields
        positioning_mode = policy_descriptor.get('positioning_mode', 'DEFENSIVE')
        
        # 1. HARD BLOCKS (Safety First)
        # Includes: HARD_BLOCK, NO_TRADE, OBSERVE_ONLY (from overrides)
        if positioning_mode in ["HARD_BLOCK", "NO_TRADE", "OBSERVE_ONLY"]:
            return 0
            
        # 2. DEFINED POSTURES
        if positioning_mode == "AGGRESSIVE":
            # In RELAXED mode, Regimes 9 & 11 (Aggressive) get 2 lots
            # In STRICT mode, we would need to check regime ID, but Policy Engine
            # already handles the assignment of "AGGRESSIVE" based on the table.
            # Assuming Policy Table v1 correctly maps ONLY 9/11 to AGGRESSIVE.
            return 2
            
        if positioning_mode in ["SELECTIVE", "PRE_POSITION", "NEUTRAL", "DEFENSIVE", "DEFENSIVE_FALLBACK"]:
            return 1
            
        # Default Fallback (Safety)
        return 0

if __name__ == "__main__":
    # Internal Verification
    mapper = ExposureMapper()
    
    test_cases = [
        {"mode": "HARD_BLOCK", "expected": 0},
        {"mode": "OBSERVE_ONLY", "expected": 0},
        {"mode": "PRE_POSITION", "expected": 1},
        {"mode": "SELECTIVE", "expected": 1},
        {"mode": "AGGRESSIVE", "expected": 2},
        {"mode": "UNKNOWN_GARBAGE", "expected": 0}
    ]
    
    print(f"⚖️ Testing Exposure Map ({SIZING_MODE})...")
    for case in test_cases:
        lots = mapper.get_lots({'positioning_mode': case['mode']})
        status = "✅" if lots == case['expected'] else "❌"
        print(f"{status} {case['mode']:<15} -> {lots} lots")
