"""
Project Atlas: Permissive Eligibility
Purpose:
In 'learn' mode, we want to probe the market in ALL interesting states.
We do NOT filter by location, volume, or patterns strictly.
We only gate by broad Regime compatibility to avoid probing square pegs in round holes.

Logic:
- TREND/TRANSITION -> Allow ITC (Impulse Trend Continuation)
- ROTATION/TRANSITION -> Allow REMR (Reversion)
"""

from typing import Dict, Any, List

class AtlasEligibility:
    """
    Permissive eligibility engine for Atlas Learning Mode.
    """
    @staticmethod
    def evaluate(enrichment: Dict[str, Any]) -> Dict[str, bool]:
        """
        Returns a permissive list of styles based on Regime.
        """
        regime = enrichment.get('trend_regime', 'ROTATION')
        
        # Default permissive map
        eligibility = {
            "ITC": False,
            "REMR": False,
            "VBD": False, # Future use
            "LSRM": False # Future use
        }
        
        # Unconditional Eligibility for Learning
        # We want to Probe EVERYTHING.
        # "Is this a good trade?" -> NO.
        # "What happens if I push here?" -> YES.
        
        return {
            "ITC": True,
            "REMR": True,
            "VBD": False, 
            "LSRM": False
        }
