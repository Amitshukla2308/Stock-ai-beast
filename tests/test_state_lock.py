
import unittest
from datetime import datetime, time
import pandas as pd
from engine.enrichment import calculate_time_context, calculate_micro_context

class TestStateLockFixes(unittest.TestCase):
    def test_bias_decay(self):
        """Verify bias weight decays over first hour."""
        # 09:15
        t0 = datetime.now().replace(hour=9, minute=15)
        ctx0 = calculate_time_context(t0.strftime("%H:%M"))
        self.assertAlmostEqual(ctx0['bias_weight'], 1.0)
        
        # 09:45 (30m elapsed) -> 0.5 weight
        t1 = datetime.now().replace(hour=9, minute=45)
        ctx1 = calculate_time_context(t1.strftime("%H:%M"))
        self.assertAlmostEqual(ctx1['bias_weight'], 0.5)

        # 10:15 (60m elapsed) -> 0.0 weight
        t2 = datetime.now().replace(hour=10, minute=15)
        ctx2 = calculate_time_context(t2.strftime("%H:%M"))
        self.assertEqual(ctx2['bias_weight'], 0.0)

    def test_structural_break(self):
        """Verify structural break detection (3 closes or 1.2 ATR move)."""
        # Mock 15m bars
        # 3 Consecutive Closes UP
        bars = [
            {'o': 100, 'h': 110, 'l': 90, 'c': 105, 'volume': 100},
            {'o': 105, 'h': 115, 'l': 100, 'c': 110, 'volume': 100},
            {'o': 110, 'h': 120, 'l': 105, 'c': 115, 'volume': 100},
            {'o': 115, 'h': 125, 'l': 110, 'c': 120, 'volume': 100} # Candle -1
        ]
        # or_range = 10 (used as proxy)
        # Net progress = 120 - 105 = 15. > 1.2 * 10 (12).
        # Signature: bars, current_price, support, resistance, pivot, atr, or_range
        ctx = calculate_micro_context(bars, 120.0, 90.0, 130.0, 100.0, 10.0, or_range=10.0)
        self.assertTrue(ctx['structural_break'])
        self.assertEqual(ctx['break_direction'], "BULLISH")

    def test_no_break(self):
        """Verify no break on chop."""
        bars = [
            {'o': 100, 'h': 110, 'l': 90, 'c': 105, 'volume': 100},
            {'o': 105, 'h': 115, 'l': 100, 'c': 102, 'volume': 100}, # Down
            {'o': 102, 'h': 120, 'l': 105, 'c': 108, 'volume': 100}, # Up
            {'o': 108, 'h': 125, 'l': 110, 'c': 112, 'volume': 100}
        ]
        ctx = calculate_micro_context(bars, 112.0, 90.0, 130.0, 100.0, 10.0, or_range=10.0)
        self.assertFalse(ctx['structural_break'])

if __name__ == '__main__':
    unittest.main()
