
import unittest
from engine.risk_guard import RiskGuard
from datetime import datetime

class TestRehabGeometry(unittest.TestCase):
    def setUp(self):
        self.risk_guard = RiskGuard(wr_floor=0.55)

    def test_tier3_rehab_geometry(self):
        """Verify that Tier 3 regimes use MFE/MAE as dynamic TGT/SL offsets."""
        alpha_state = {
            "bias": "LONG",
            "win_rate": 0.50,
            "confluence_id": "T3_31_57",
            "tier": 3,
            "avg_mfe": 35.5,
            "avg_mae": 42.1,
            "is_fallback": False
        }
        current_price = 26000.0
        current_time = datetime(2026, 1, 30, 10, 0, 0)
        
        decision = self.risk_guard.validate_alpha(
            alpha_state, current_price, current_time=current_time,
            daily_trade_count=0, consecutive_losses=0
        )
        
        # Verify Action and Sizing
        self.assertEqual(decision['action'], "BUY_CALL")
        self.assertEqual(decision['size_factor'], 1.0)
        self.assertIn("[REHAB_GEOMETRY]", decision['reason'])
        
        # Verify Dynamic Geometry
        # Target = price + 35.5
        # SL = price - 42.1
        self.assertEqual(decision['target'], 26000.0 + 35.5)
        self.assertEqual(decision['sl'], 26000.0 - 42.1)
        self.assertIn("[DYNA_TGT:35.5|SL:42.1]", decision['reason'])

    def test_tier3_rehab_safety_squashing(self):
        """Verify that extreme MFE/MAE values are squashed for safety."""
        alpha_state = {
            "bias": "SHORT",
            "win_rate": 0.50,
            "confluence_id": "T3_6_48",
            "tier": 3,
            "avg_mfe": 5.0, # Too small -> 15.0
            "avg_mae": 150.0, # Too large -> 65.0
            "is_fallback": False
        }
        current_price = 26000.0
        
        decision = self.risk_guard.validate_alpha(alpha_state, current_price)
        
        # Target Offset (SHORT) Target = 26000 - 15.0
        # SL Offset (SHORT) SL = 26000 + 65.0
        self.assertEqual(decision['target'], 26000.0 - 15.0)
        self.assertEqual(decision['sl'], 26000.0 + 65.0)
        self.assertIn("[DYNA_TGT:15.0|SL:65.0]", decision['reason'])

if __name__ == "__main__":
    unittest.main()
