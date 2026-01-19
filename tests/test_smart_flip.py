
import unittest
from engine.enrichment import calculate_micro_context

class TestSmartFlip(unittest.TestCase):
    def test_continuation_risk_detection(self):
        """Test that strong trend metrics flag continuation risk"""
        # Scenario: 3 bullish candles with increasing range (Velocity Increasing)
        # O-H-L-C-Vol
        bars = [
            {'o': 100, 'h': 110, 'l': 95, 'c': 108, 'volume': 1000}, # Range 15
            {'o': 108, 'h': 125, 'l': 105, 'c': 124, 'volume': 1200}, # Range 20 
            {'o': 124, 'h': 150, 'l': 122, 'c': 148, 'volume': 1500}, # Range 28 (Aggressive expansion)
        ]
        or_range = 100
        
        ctx = calculate_micro_context(bars, 148, 100, 200, 150, 10, or_range)
        
        self.assertTrue(ctx['velocity_increasing'], "Should detect increasing velocity")
        self.assertTrue(ctx['last_body_ratio'] > 0.6, f"Body ratio {ctx['last_body_ratio']} should be high")

    def test_absorption_detection(self):
        """Test that high volume with low progress flags absorption"""
        # Scenario: High volume doji at highs
        bars = [
            {'o': 100, 'h': 110, 'l': 95, 'c': 108, 'volume': 1000},
            {'o': 108, 'h': 112, 'l': 106, 'c': 110, 'volume': 1000},
            {'o': 110, 'h': 115, 'l': 105, 'c': 111, 'volume': 3000}, # Huge Vol, tiny progress
        ]
        # Previous avg vol (dummy based on calculation window) -> needs 4 bars total for avg calc
        bars = [
            {'o': 100, 'h': 110, 'l': 95, 'c': 108, 'volume': 1000},
            {'o': 100, 'h': 110, 'l': 95, 'c': 108, 'volume': 1000},
            {'o': 100, 'h': 110, 'l': 95, 'c': 108, 'volume': 1000}, # Avg 1000
            {'o': 110, 'h': 115, 'l': 105, 'c': 111, 'volume': 3000}, # 3x Avg
        ]
        or_range = 100
        
        ctx = calculate_micro_context(bars, 111, 100, 200, 150, 10, or_range)
        
        self.assertTrue(ctx['absorption'], "Should detect absorption")

if __name__ == '__main__':
    unittest.main()
