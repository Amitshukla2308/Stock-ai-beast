
import unittest
from datetime import datetime
from hot_path.executor import HotPathExecutor, Action

class TestTransitionLogic(unittest.TestCase):
    def test_dynamic_reentry(self):
        """Verify REMR->ITC re-entry calculates dynamic targets."""
        exe = HotPathExecutor()
        
        # Setup REMR Continuation Monitor
        # Original Entry: 100. EM: 50.
        # Dynamic Target = 100 + 2*50 = 200.
        exe.remr_continuation_monitor = {
            'side': 'CALL',
            'trigger_price': 150,
            'expiry': datetime.now().replace(year=2099),
            'original_entry': 100.0,
            'em_high': 50.0
        }
        
        # Trigger Condition: Price 150 (Trigger hit)
        tick = {'close': 150.0, 'timestamp': datetime.now()}
        exe.process_tick(tick)
        
        # Check open_position (active_instructions is cleared after entry)
        # SL should be Price - 50 = 100
        # Target should be 200 (Dynamic)
        pos = exe.open_position
        self.assertAlmostEqual(pos['sl'], 100.0)
        self.assertAlmostEqual(pos['target'], 200.0)
        self.assertEqual(pos['style'], 'INTRADAY_TREND_CONTINUATION')

    def test_exhausted_target_projection(self):
        """Verify re-entry projects FRESH target if original is exhausted."""
        exe = HotPathExecutor()
        
        # Original Entry: 100. EM: 50. Dyn Target = 200.
        # Current Price: 190. (Only 10pts away -> Exhausted)
        exe.remr_continuation_monitor = {
            'side': 'CALL',
            'trigger_price': 190,
            'expiry': datetime.now().replace(year=2099),
            'original_entry': 100.0,
            'em_high': 50.0
        }
        
        tick = {'close': 190.0, 'timestamp': datetime.now()}
        exe.process_tick(tick)
        
        # Check open_position
        # Should project FRESH leg: Price + 1.0*EM = 190 + 50 = 240
        pos = exe.open_position
        self.assertAlmostEqual(pos['target'], 240.0)
        # SL: Price - 50 = 140
        self.assertAlmostEqual(pos['sl'], 140.0)

if __name__ == '__main__':
    unittest.main()
