"""
Config Loader for v2.8 Research Engine
Loads and validates trading_config.json
Provides type-safe access to all config values
"""
import json
import os
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class TradingConfig:
    """Singleton config loader with validation and helper methods"""
    
    _instance = None
    _config = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._config is None:
            self.load()
    
    def load(self, config_path: str = "config/trading_config.json"):
        """Load and validate config from JSON"""
        try:
            # Handle relative path from project root
            if not os.path.isabs(config_path):
                project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                config_path = os.path.join(project_root, config_path)
            
            with open(config_path, 'r') as f:
                self._config = json.load(f)
            
            self._validate_schema()
            logger.info(f"✅ Config loaded from {config_path}")
            logger.info(f"   Version: {self._config.get('_metadata', {}).get('version', 'unknown')}")
            
        except FileNotFoundError:
            logger.error(f"❌ Config file not found: {config_path}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"❌ Invalid JSON in config: {e}")
            raise
    
    def _validate_schema(self):
        """Basic schema validation"""
        required_sections = [
            'GLOBAL', 'REMR', 'ITC', 'ORE', 'VBD', 'LSRM', 'RISK_RULES'
        ]
        
        for section in required_sections:
            if section not in self._config:
                raise ValueError(f"Missing required config section: {section}")
        
        logger.info("✅ Config schema validated")
    
    # === Helper Methods for Common Accesses ===
    
    def get_remr_config(self) -> Dict[str, Any]:
        """Get authoritative REMR config"""
        return self._config['REMR']

    def get_itc_config(self) -> Dict[str, Any]:
        """Get authoritative ITC config"""
        return self._config['ITC']
        
    def get_global_switch(self, switch_name: str) -> Any:
        """Get global switch value"""
        return self._config['GLOBAL'].get(switch_name)

    def get_signal_config(self, signal_type: str) -> Dict[str, Any]:
        """Get config for a specific signal type (trend, rejection, etc.)"""
        return self._config['SIGNALS'].get(signal_type, {})

    def get_proximity_threshold(self, style: str, or_range: float, atr: float) -> float:
        """
        Calculate proximity threshold for a specific style.
        Currently only defined for REMR in strict schema.
        Returns: max(or_pct * OR, atr_pct * ATR, min_points)
        """
        style_cfg = self._config.get(style, {})
        threshold_cfg = style_cfg.get('near_threshold')
        
        if not threshold_cfg:
            # Fallback for styles without specific proximity rules
            return 5.0
            
        or_component = threshold_cfg['or_pct'] * or_range if or_range > 0 else 0
        atr_component = threshold_cfg['atr_pct'] * atr if atr else 0
        floor = threshold_cfg['min_points']
        
        return max(or_component, atr_component, floor)
    
    def get_style_rules(self, style: str) -> Dict[str, Any]:
        """
        Get rules configuration for a style.
        """
        return self._config.get(style, {})
        
    def get_confidence_floor(self, style: str) -> float:
        """
        Get confidence floor for a style.
        """
        style_cfg = self._config.get(style, {})
        return style_cfg.get('confidence_floor', 0.70)

    def get_session_phase(self, time_str: str) -> str:
        """
        Determine session phase (OPENING, AM, NOON, PM, CLOSING)
        """
        if not time_str or time_str == "N/A": return "UNKNOWN"
        try:
            parts = list(map(int, time_str.split(':')))
            t = parts[0] * 60 + parts[1] # Minutes from midnight
            
            # 09:15 = 555
            # 09:45 = 585
            # 10:30 = 630
            # 13:00 = 780
            # 14:30 = 870
            
            if t < 555: return "PRE_OPEN"
            if t < 585: return "OPENING_NOTE"
            if t < 630: return "AM_SESSION"
            if t < 780: return "NOON_SESSION"
            if t < 870: return "PM_SESSION"
            return "CLOSING_SESSION"
        except:
            return "UNKNOWN"
    
    # === Raw Config Access ===
    
    @property
    def raw(self) -> Dict[str, Any]:
        """Get raw config dict (use sparingly)"""
        return self._config
    
    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Get nested config value using dot notation.
        Example: cfg.get('REMR.confidence_floor') => 0.40
        """
        keys = key_path.split('.')
        value = self._config
        
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        
        return value


# Global singleton instance
config = TradingConfig()
