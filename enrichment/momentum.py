"""
v2.8 Enrichment: Momentum State
Tracks intraday momentum accumulation (upward/downward movement).
Migrated from hot_path/executor.py (Phase 2 Refactor).
Fact-based ONLY. No decisions.
"""
from typing import Dict, Any, Optional

class MomentumTracker:
    def __init__(self):
        self.reset()
        
    def reset(self):
        self.day_open: Optional[float] = None
        self.day_high: Optional[float] = None
        self.day_low: Optional[float] = None
        self.total_upward_movement: float = 0.0
        self.total_downward_movement: float = 0.0
        self.current_date = None

    def update(self, tick: Dict[str, Any]):
        """
        Update state with new tick.
        Handles daily reset detection.
        """
        price = tick['close']
        timestamp = tick['timestamp']
        
        # Determine date (handle both datetime object and string implications if needed)
        # Assuming timestamp is datetime based on system standards
        tick_date = timestamp.date()
        
        # Reset on new day
        if self.current_date != tick_date:
            self.reset()
            self.current_date = tick_date
            self.day_open = tick.get('open', price)
            self.day_high = tick.get('high', price)
            self.day_low = tick.get('low', price)
        else:
            # Update extremes
            if self.day_high is None or price > self.day_high:
                self.day_high = price
            if self.day_low is None or price < self.day_low:
                self.day_low = price
            
            # Use tick high/low if available for better accuracy
            if 'high' in tick:
                self.day_high = max(self.day_high, tick['high'])
            if 'low' in tick:
                self.day_low = min(self.day_low, tick['low'])
        
        # Calculate Accumulated Momentum
        if self.day_open:
            self.total_upward_movement = max(0.0, self.day_high - self.day_open)
            self.total_downward_movement = max(0.0, self.day_open - self.day_low)

    def get_state(self) -> Dict[str, float]:
        """Return pure facts about momentum state"""
        return {
            "day_open": self.day_open,
            "day_high": self.day_high,
            "day_low": self.day_low,
            "upward_movement": self.total_upward_movement,
            "downward_movement": self.total_downward_movement
        }

# Global instance for pipeline continuity
momentum_tracker = MomentumTracker()
