"""
v2.8 Risk: Countertrend Policy
Enforces rules about when countertrend trading is allowed.
"""
import logging
from config.config_loader import config

logger = logging.getLogger(__name__)

def is_countertrend_allowed(style: str, regime: str) -> bool:
    """
    Checks config to see if countertrend is permitted for this style/regime.
    """
    ct_config = config.get('risk_rules.countertrend', {})
    allowed_styles = ct_config.get('allowed_styles', [])
    allowed_regimes = ct_config.get('allowed_regimes', [])
    
    return style in allowed_styles and regime in allowed_regimes
