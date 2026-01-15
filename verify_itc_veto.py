#!/usr/bin/env python3
import sys
import os

# Add current directory to path
sys.path.insert(0, os.getcwd())

from engine.enrichment import (
    calculate_micro_context,
    calculate_style_eligibility
)

def test_itc_failure_to_accept():
    print("\n🧪 Testing ITC Failure to Accept (Structural Veto)...")
    
    or_range = 100
    support = 25000
    resistance = 25500
    
    # 1. Create a "Bullish Impulse" (Large move + Expanding Volume)
    # Move must be >= 0.4 * OR = 40 pts
    # Directional ratio >= 0.65 (7/10 green)
    bars_impulse = [
        {'o': 25100, 'h': 25110, 'l': 25100, 'c': 25105, 'volume': 1000},
        {'o': 25105, 'h': 25115, 'l': 25105, 'c': 25112, 'volume': 1100},
        {'o': 25112, 'h': 25125, 'l': 25112, 'c': 25120, 'volume': 1200},
        {'o': 25120, 'h': 25135, 'l': 25120, 'c': 25130, 'volume': 1300},
        {'o': 25130, 'h': 25145, 'l': 25130, 'c': 25140, 'volume': 1400},
        {'o': 25140, 'h': 25155, 'l': 25140, 'c': 25150, 'volume': 1500},
        {'o': 25150, 'h': 25165, 'l': 25150, 'c': 25160, 'volume': 2000}, # Vol Expanding
        {'o': 25160, 'h': 25170, 'l': 25155, 'c': 25165, 'volume': 1800},
        {'o': 25165, 'h': 25175, 'l': 25160, 'c': 25172, 'volume': 1900},
        {'o': 25172, 'h': 25185, 'l': 25170, 'c': 25180, 'volume': 3000},
    ]
    # Impulse: Low 25100, High 25185, Move 85 pts (>= 40)
    
    # CASE A: GOOD Acceptance (Closes above 60% of impulse)
    # Acc Level = 25100 + 0.6 * 85 = 25151
    # We need to ensure total bars >= 50 for MA calculation
    prefix = []
    for i in range(60):
        v = 25000 + i
        if i == 20: v = 24950 # confirmed low
        if i == 40: v = 24980 # confirmed higher low
        prefix.append({'o': v-5, 'h': v+10, 'l': v-10, 'c': v, 'volume': 500})
    bars_full_impulse = prefix + bars_impulse
    
    bars_accept = bars_full_impulse + [
        {'o': 25180, 'h': 25190, 'l': 25175, 'c': 25185, 'volume': 3000},
        {'o': 25185, 'h': 25188, 'l': 25170, 'c': 25175, 'volume': 3000},
        {'o': 25175, 'h': 25180, 'l': 25165, 'c': 25170, 'volume': 10000},
    ]
    
    micro_ok = calculate_micro_context(bars_accept, 25170, support, resistance, 25250, 20, or_range)
    print(f"   Success Scenario - Impulse Detected: {micro_ok['impulse_detected']}, Failure: {micro_ok['failure_to_accept']}, Swing: {micro_ok['swing_context']}")
    
    plan = {"market_personality": "TRENDING", "boundary_levels": {}}
    em = {"or_range": or_range, "expected_move_high": 50}
    styles_ok = calculate_style_eligibility("11:00", micro_ok, plan, {}, 25170, em)
    assert styles_ok['INTRADAY_TREND_CONTINUATION'] == True, "❌ FAIL: ITC should be active when trend is accepted"
    print("   ✅ PASS: ITC active on accepted trend")

    # CASE B: FAILURE TO ACCEPT
    bars_fail = bars_full_impulse + [
        {'o': 25180, 'h': 25180, 'l': 25140, 'c': 25145, 'volume': 3000},
        {'o': 25145, 'h': 25150, 'l': 25130, 'c': 25135, 'volume': 3000},
        {'o': 25135, 'h': 25140, 'l': 25120, 'c': 25125, 'volume': 3000},
        {'o': 25125, 'h': 25130, 'l': 25110, 'c': 25115, 'volume': 3000},
        {'o': 25115, 'h': 25120, 'l': 25100, 'c': 25105, 'volume': 10000},
    ]
    
    micro_fail = calculate_micro_context(bars_fail, 25105, support, resistance, 25250, 20, or_range)
    print(f"   Failure Scenario - Impulse Detected: {micro_fail['impulse_detected']}, Failure: {micro_fail['failure_to_accept']}")
    assert micro_fail['failure_to_accept'] == True, "❌ FAIL: Should detect failure_to_accept"
    
    styles_fail = calculate_style_eligibility("11:00", micro_fail, plan, {}, 25105, em)
    assert styles_fail['INTRADAY_TREND_CONTINUATION'] == False, "❌ FAIL: ITC should be VETOED on failure to accept"
    print("   ✅ PASS: ITC vetoed on failure to accept")

if __name__ == "__main__":
    try:
        test_itc_failure_to_accept()
        print("\n🎉 FAILURE_TO_ACCEPT TESTS PASSED!")
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 ERROR: {e}")
        sys.exit(1)
