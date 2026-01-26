"""
Project Atlas: Pass-Through Risk
Purpose:
In 'learn' mode, Risk Layer must NOT block trades based on opinion.
It can only scale size based on uncertainty.
Blocking destroys learning signal.
"""

from typing import Dict, Any

class AtlasRisk:
    """
    Permissive risk engine for Atlas Learning Mode.
    """
    @staticmethod
    def assess_risk(style: str, enrichment: Dict[str, Any], signals: Dict[str, Any]) -> Dict[str, Any]:
        """
        Always returns a valid direction.
        Scales size if necessary (Placeholder: Always 1.0).
        """
        
        # Default: Allow implementation
        return {
            "action": "ALLOW",
            "scale_factor": 1.0,
            "reason": "Atlas Exploration Probing"
        }
