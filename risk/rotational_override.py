"""
v2.8 Risk: Rotational Override
Handles bypassing directional alignment in rotational regimes.
"""
import logging
from config.config_loader import config

logger = logging.getLogger(__name__)

def should_bypass_alignment(style: str, regime: str) -> bool:
    """
    Checks if style/regime permits bypassing momentum/trend alignment.
    """
    if not config.is_rotational_execution_allowed():
        return False
        
    rot_styles = config.get_rotational_styles()
    rot_regimes = config.get_rotational_regimes()
    
    return style in rot_styles and regime in rot_regimes
