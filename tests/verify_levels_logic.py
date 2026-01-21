import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.append(os.getcwd())

# Mock Config before importing modules that use it
with patch('config.config_loader.config') as mock_config:
    # Setup Mock Config Defaults
    mock_config.get_itc_config.return_value = {'min_TER': 0.5, 'confidence_floor': 0.6}
    mock_config.get_remr_config.return_value = {'max_fade_slope_atr_ratio': 0.5, 'confidence_floor': 0.6, 'near_threshold': {'or_pct': 0.1, 'atr_pct': 0.2, 'min_points': 5}}
    mock_config.get_proximity_threshold.return_value = 10.0
    mock_config.get_global_switch.return_value = True

    # Import modules under test
    from enrichment.morning import calculate_pivots, calculate_cpr
    from enrichment.levels import get_reference_levels
    from enrichment.location import calculate_proximity, classify_location
    from eligibility.style_eligibility import evaluate_eligibility
    from confidence.confidence_engine import confidence_engine

class TestAdvancedLevels(unittest.TestCase):

    def setUp(self):
        # Sample Daily Data (Previous Day)
        # H=200, L=100, C=150
        # Pivot = (200+100+150)/3 = 150
        # BC = (200+100)/2 = 150
        # TC = (150-150) + 150 = 150 (Flat CPR)
        
        # Let's try separate values for CPR width
        # H=105, L=95, C=100
        # Pivot = 300/3 = 100
        # BC = 200/2 = 100
        # TC = (100-100)+100 = 100
        
        self.daily_data = [{
            'h': 105.0, 'l': 95.0, 'c': 100.0, 'o': 100.0
        }]
        
        # Scenario 2: Wide CPR
        # H=110, L=90, C=100
        # Pivot = 300/3 = 100
        # BC = (110+90)/2 = 100
        # TC = 100
        
        # Scenario 3: Trending Day for levels
        # Prev: H=20000, L=19800, C=19900
        # P = 59700/3 = 19900
        # BC = 19900
        # TC = 19900
        pass

    def test_cpr_calculation(self):
        """Verify BC, TC, Pivot math"""
        # Data: H=200, L=100, C=180
        # P = 480/3 = 160
        # BC = 300/2 = 150
        # TC = (160 - 150) + 160 = 170
        data = [{'h': 200, 'l': 100, 'c': 180}]
        cpr = calculate_cpr(data)
        
        self.assertEqual(cpr['pivot'], 160.0)
        self.assertEqual(cpr['bc'], 150.0)
        self.assertEqual(cpr['tc'], 170.0)
        print("\n✅ CPR Calculation Verified: P=160, BC=150, TC=170")

    def test_pivots_s2_r2(self):
        """Verify S1, S2, R1, R2"""
        # Data: H=200, L=100, C=180 (P=160)
        # R1 = 2*P - L = 320 - 100 = 220
        # S1 = 2*P - H = 320 - 200 = 120
        # R2 = P + (H-L) = 160 + 100 = 260
        # S2 = P - (H-L) = 160 - 100 = 60
        data = [{'h': 200, 'l': 100, 'c': 180}]
        pivots = calculate_pivots(data)
        
        self.assertEqual(pivots['r1'], 220.0)
        self.assertEqual(pivots['s1'], 120.0)
        self.assertEqual(pivots['r2'], 260.0)
        self.assertEqual(pivots['s2'], 60.0)
        print("✅ Pivots (S2-R2) Verified")

    def test_location_classification_nearest(self):
        """Verify we snap to the nearest level (new logic)"""
        levels = {
            'pivot': 100, 'bc': 95, 'tc': 105,
            'r1': 110, 'r2': 120,
            's1': 90, 's2': 80
        }
        
        # Price 109 -> Nearest R1 (110)
        prox = calculate_proximity(109, levels, 20, 10)
        loc = classify_location(109, levels, prox['proximity_limit'])
        
        self.assertEqual(loc['nearest_structural_level'], 'R1')
        print("✅ Location matches Nearest Level (R1)")
        
        # Price 96 -> Nearest BC (95) vs Pivot(100)? 
        # Distance to BC=1, Pivot=4. Should choose BC.
        prox = calculate_proximity(96, levels, 20, 10)
        loc = classify_location(96, levels, prox['proximity_limit'])
        self.assertIn(loc['nearest_structural_level'], ['BC'])
        print("✅ Location matches Nearest CPR Component")

    def test_itc_cpr_gating(self):
        """Verify ITC is allowed/boosted outside CPR, maybe restricted inside"""
        # Mock dependencies for ITC check
        # CPR: 100-110
        enrichment = {
            'trend_efficiency': 0.8,
            'trend_regime': 'TREND',
            'bc': 100, 'tc': 110,
            'price': 120, # Outside CPR (Bullish)
            'atr': 10,
            'or_range': 20
        }
        
        with patch('config.config_loader.config.get_itc_config') as mock_itc:
            mock_itc.return_value = {'min_TER': 0.5}
            
            # Case 1: Outside CPR
            elig = evaluate_eligibility(enrichment, {})
            self.assertTrue(elig.get('ITC'), "ITC should be Eligible outside CPR with Trend")
            print("✅ ITC Eligible Outside CPR")
            
            # Case 2: Inside CPR
            enrichment['price'] = 105 # Inside
            elig = evaluate_eligibility(enrichment, {})
            # Depending on strictness, it might still be allowed but confidence penalized
            # But the 'style_eligibility' logic I wrote had `if outside_cpr:` as a boost or gate?
            # Let's check the code expectation:
            # "if outside_cpr: ... elig=True" -> implies if INSIDE, might NOT be eligible unless other conditions met?
            # Actually my code was:
            # if outside_cpr: if trend: elig=True
            # It did NOT have an 'else' block for inside CPR in the snippet I wrote. 
            # So expected is False if strict gate.
            
            self.assertFalse(elig.get('ITC', False), "ITC should be restricted inside CPR (Churn zone)")
            print("✅ ITC Restricted Inside CPR")

    def test_confidence_structural_boost(self):
        """Verify confidence gets a boost from structure"""
        enrichment = {
            'trend_efficiency': 0.6,
            'trend_regime': 'TREND',
            'bc': 100, 'tc': 110,
            'price': 120, # Outside
            'near_htf': True,
            'near_tc': True, 
            'vix': 15
        }
        
        # ITC Score
        scores = confidence_engine.calculate_confidence(['ITC', 'REMR'], enrichment)
        
        # ITC Base 0.5 + Trend Boost (0.6*0.5=0.3) + CPR Boost (0.1) = 0.9 (approx)
        itc_score = scores['ITC']
        self.assertGreater(itc_score, 0.7, f"ITC Score {itc_score} should reflect boosts")
        print(f"✅ ITC Confidence Boosted: {itc_score}")
        
        # REMR Score
        # Base 0.5 - Trend Penalty (0.3) + CPR Boundary Boost (0.1) = 0.3
        remr_score = scores['REMR']
        self.assertLess(remr_score, 0.5, "REMR should be penalized in strong trend")
        print(f"✅ REMR Confidence Penalized: {remr_score}")


if __name__ == '__main__':
    unittest.main()
