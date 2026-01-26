"""
v4.0 RiskGuard: The Decision Gate
Prevents low-alpha trades and enforces deterministic geometry.
"""
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class RiskGuard:
    def __init__(self, wr_floor: float = 0.55):
        self.wr_floor = wr_floor

    def validate_alpha(self, alpha_state: Dict[str, Any], current_price: float) -> Dict[str, Any]:
        """
        Validates the confluence bias and sets exit prices.
        Returns a 'decision' dict for the Executor.
        """
        bias = alpha_state.get("bias", "NONE")
        wr = alpha_state.get("win_rate", 0.0)
        conf_id = alpha_state.get("confluence_id", "UNKNOWN")
        is_fallback = alpha_state.get("is_fallback", False)
        
        decision = {
            "action": "HOLD",
            "confidence": wr,
            "selected_style": "ATLAS",
            "is_fallback": is_fallback,
            "reason": f"Cluster {conf_id}",
            "sl": None,
            "target": None
        }

        if bias == "NONE":
            decision["reason"] = f"No Alpha for {conf_id}"
            return decision

        # Baseline floor for all logic (matched to v3.5 validation specs)
        floor = 0.45
        
        if wr < floor:
            decision["reason"] = f"Veto: WR {wr:.2f} < Floor {floor}"
            return decision

        # Set Deterministic Geometry (v4.0 Alpha Standard)
        if bias == "LONG":
            decision["action"] = "BUY_CALL"
            decision["sl"] = current_price - 50
            decision["target"] = current_price + 90
        elif bias == "SHORT":
            decision["action"] = "BUY_PUT"
            decision["sl"] = current_price + 50
            decision["target"] = current_price - 90

        return decision
