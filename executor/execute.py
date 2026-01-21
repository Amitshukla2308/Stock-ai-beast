"""
v2.9 Executor: The Final Gate
ONLY responsibility: Propose trades to Trade Engine.
Does NOT: track positions, manage exits, compute PnL, write to DB.
All that is now handled by trade/ subsystem.
"""
import logging
from datetime import datetime
from typing import Dict, Any

logger = logging.getLogger(__name__)


class Executor:
    """
    Minimal executor that only proposes trades.
    Trade Engine handles all state, exits, and metrics.
    """
    
    def __init__(self, broker=None):
        self.broker = broker
        # NO trade_ledger
        # NO open_position
        # NO PnL tracking
    
    def propose_entry(self, instructions: Dict[str, Any], context: Dict[str, Any], timestamp: datetime) -> Dict[str, Any]:
        """
        Propose an entry based on decision.
        Returns the proposal dict for Trade Engine to process.
        Does NOT execute or track anything.
        """
        action = instructions.get('action')
        
        if action not in ["BUY_CALL", "BUY_PUT"]:
            return {"proposed": False, "reason": "No valid action"}
        
        price = instructions.get('entry_price', context.get('close', 0))
        
        # Build proposal
        proposal = {
            "proposed": True,
            "action": action,
            "direction": "CALL" if action == "BUY_CALL" else "PUT",
            "symbol": context.get('symbol', 'NSE:NIFTY50-INDEX'),
            "entry_price": price,
            "sl": instructions.get('sl'),
            "target": instructions.get('target'),
            "confidence": instructions.get('confidence', 0),
            "selected_style": instructions.get('selected_style', 'UNKNOWN'),
            "reason": instructions.get('reason', 'Signal'),
            "timestamp": timestamp,
            
            # Context for Trade Engine
            "regime": context.get('trend_regime', 'UNKNOWN'),
            "session_phase": context.get('session_phase', 'UNKNOWN'),
            "trend_efficiency": context.get('trend_efficiency', 0),
            "atr": context.get('atr', 0),
            "or_range": context.get('or_range', 0),
            "location_class": context.get('location_class', 'UNKNOWN'),
        }
        
        logger.info(f"[EXEC] ✅ Proposed: {action} @ {price} | Style: {proposal['selected_style']} | Conf: {proposal['confidence']}")
        
        return proposal


# Factory for compatibility
def create_executor(broker=None) -> Executor:
    return Executor(broker=broker)
