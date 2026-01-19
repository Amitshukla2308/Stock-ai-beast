
import unittest
from engine.enrichment import calculate_micro_context

class TestBreakPersistence(unittest.TestCase):
    def test_ephemeral_break_failure(self):
        """
        Demonstrate that a pause candle kills the structural break signal
        in the current implementation.
        """
        # 1. Setup a Strong Bearish Trend (3 bars down)
        # 09:15 - 10:00
        bars = [
            {'o': 100, 'h': 102, 'l': 90, 'c': 90, 'volume': 100}, # Big Red
            {'o': 90, 'h': 92, 'l': 80, 'c': 80, 'volume': 100},   # Big Red
            {'o': 80, 'h': 82, 'l': 70, 'c': 70, 'volume': 100},   # Big Red (Break Triggered here)
        ]
        
        # Check Break at T=3
        # Signature: bars, current_price, support, resistance, pivot, atr, or_range
        ctx = calculate_micro_context(bars, 70.0, 50.0, 150.0, 100.0, 10.0, or_range=20.0)
        self.assertTrue(ctx['structural_break'], "Break should be detected at T=3")
        self.assertEqual(ctx['break_direction'], "BEARISH")

        # 2. Add a Consolidation Candle (Green Doji)
        # 10:00 - 10:15
        bars.append(
            {'o': 70, 'h': 72, 'l': 68, 'c': 71, 'volume': 50} # Small Green Pause
        )
        
        # Check Break at T=4
        # In current logic, this will FAIL (return False) because last 3 bars are not all red
        ctx = calculate_micro_context(bars, 71.0, 50.0, 150.0, 100.0, 10.0, or_range=20.0)
        
        # We WANT this to be True (Persistence).
        # Since we updated the logic to look back 6 bars, this should now be TRUE.
        self.assertTrue(ctx['structural_break'], "Break signal FAILED to persist (Fix Failed)")
        self.assertEqual(ctx['break_direction'], "BEARISH")

if __name__ == '__main__':
    unittest.main()
