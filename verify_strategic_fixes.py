import sys
import os
from datetime import time

# Add project root to path
sys.path.append(os.getcwd())

from hot_path.executor import HotPathExecutor
from engine.enrichment import calculate_location_context

def test_remr_confidence_gate():
    print("Testing REMR Confidence Gate...")
    executor = HotPathExecutor()
    
    # CASE 1: REMR with 0.46 confidence should be EXECUTED
    instructions_remr = {
        "selected_style": "REMR",
        "action": "BUY_PUT",
        "confidence": 0.46,
        "mode": "STRUCTURE",
        "tick_time": time(11, 0)
    }
    executor.update_instructions(instructions_remr)
    decision = instructions_remr.get('engine_decision')
    print(f"REMR (0.46) Decision: {decision}")
    assert decision == "EXECUTED", f"Expected EXECUTED for REMR 0.46, got {decision}"

    # CASE 2: ITC with 0.46 confidence should be BLOCKED (threshold 0.65)
    instructions_itc = {
        "selected_style": "ITC",
        "action": "BUY_CALL",
        "confidence": 0.46,
        "mode": "STRUCTURE",
        "tick_time": time(11, 0)
    }
    executor.update_instructions(instructions_itc)
    decision = instructions_itc.get('engine_decision')
    print(f"ITC (0.46) Decision: {decision}")
    assert decision == "BLOCKED", f"Expected BLOCKED for ITC 0.46, got {decision}"
    print("✅ Confidence gate test passed.")

def test_optimal_location():
    print("\nTesting OPTIMAL Location Classification...")
    # or_range = 100
    # support = 25600, resistance = 25700
    support = 25600
    resistance = 25700
    pivot = 25650
    or_range = 100
    
    # CASE 1: Distance = 1.6 from Resistance ( < 5) should be OPTIMAL_TOP
    ctx = calculate_location_context(25701.6, support, pivot, resistance, or_range)
    print(f"Price 25701.6 (Dist 1.6 from R) Location: {ctx['location']}")
    assert ctx['location'] == "OPTIMAL_TOP", f"Expected OPTIMAL_TOP, got {ctx['location']}"
    
    # CASE 2: Distance = 3 from Support ( < 5) should be OPTIMAL_BOTTOM
    ctx = calculate_location_context(25597.0, support, pivot, resistance, or_range)
    print(f"Price 25597.0 (Dist 3 from S) Location: {ctx['location']}")
    assert ctx['location'] == "OPTIMAL_BOTTOM", f"Expected OPTIMAL_BOTTOM, got {ctx['location']}"
    
    # CASE 3: Distance = 10 from Resistance ( > 5 but within 0.15*or_range=15) should be NEAR_RESISTANCE
    ctx = calculate_location_context(25710.0, support, pivot, resistance, or_range)
    print(f"Price 25710.0 (Dist 10 from R) Location: {ctx['location']}")
    assert ctx['location'] == "NEAR_RESISTANCE", f"Expected NEAR_RESISTANCE, got {ctx['location']}"
    
    print("✅ Location classification test passed.")

if __name__ == "__main__":
    try:
        test_remr_confidence_gate()
        test_optimal_location()
        print("\nALL STRATEGIC FIX TESTS PASSED.")
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
