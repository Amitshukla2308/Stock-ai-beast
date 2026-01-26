import pandas as pd
from engine import PolicyGate

def run_validation():
    print("🛡️ Policies Gate Validation...")
    gate = PolicyGate()
    
    # Test Cases
    cases = [
        # Alpha Regimes
        {"r": 11, "t": "IGNORE", "exp_risk": 1.5, "exp_mode": "AGGRESSIVE"},
        {"r": 9,  "t": "WATCH",  "exp_risk": 1.25, "exp_mode": "AGGRESSIVE"},
        
        # Traps
        {"r": 7, "t": "IGNORE", "exp_risk": 0.0, "exp_mode": "HARD_BLOCK"},
        {"r": 2, "t": "PREPARE","exp_risk": 0.0, "exp_mode": "HARD_BLOCK"}, # Precursor logic only applies if override exists
        
        # Precursors
        {"r": 3, "t": "IGNORE", "exp_risk": 0.0, "exp_mode": "HARD_BLOCK"},
        {"r": 3, "t": "WATCH",  "exp_risk": 0.0, "exp_mode": "OBSERVE_ONLY"},
        {"r": 3, "t": "PREPARE","exp_risk": 0.5, "exp_mode": "PRE_POSITION"},
        
        # Neutral Defaults
        {"r": 0, "t": "IGNORE", "exp_risk": 0.5, "exp_mode": "NEUTRAL"},
    ]
    
    results = []
    failed = 0
    
    for c in cases:
        policy = gate.get_policy(c['r'], c['t'])
        
        # Assertions
        risk_match = policy['max_risk_multiplier'] == c['exp_risk']
        mode_match = policy['positioning_mode'] == c['exp_mode']
        passed = risk_match and mode_match
        
        if not passed:
            failed += 1
            status = "❌ FAIL"
        else:
            status = "✅ PASS"
            
        results.append({
            "Input": f"R{c['r']} | {c['t']}",
            "Output": f"{policy['positioning_mode']} ({policy['max_risk_multiplier']}x)",
            "Expected": f"{c['exp_mode']} ({c['exp_risk']}x)",
            "Status": status
        })
        
    # Report
    print(pd.DataFrame(results).to_string(index=False))
    
    if failed == 0:
        print("\n✅ POLICY ENGINE VERIFIED: All test cases passed.")
    else:
        print(f"\n❌ POLICY ENGINE FAILURE: {failed} cases failed.")

if __name__ == "__main__":
    run_validation()
