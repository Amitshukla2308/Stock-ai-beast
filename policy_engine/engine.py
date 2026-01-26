import yaml
import os

class PolicyGate:
    def __init__(self, config_path="policy_engine/policy_table_v1.yaml"):
        self.config_path = config_path
        self.policy_map = self._load_policy_table()
        
    def _load_policy_table(self):
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"Policy table not found at {self.config_path}")
            
        with open(self.config_path, 'r') as f:
            return yaml.safe_load(f)
            
    def get_policy(self, regime_id: int, transition_mode: str = "IGNORE") -> dict:
        """
        Pure function: (Regime, TransitionContext) -> PolicyDescriptor
        """
        # 1. Inspect Regime Entry
        regime_key = int(regime_id)
        if regime_key not in self.policy_map['regimes']:
            # Fallback for undefined regimes (Safety Net)
            return {
                "allowed_actions": ["SCALP"],
                "max_risk_multiplier": 0.25,
                "positioning_mode": "DEFENSIVE_FALLBACK",
                "notes": f"Regime {regime_id} undefined in policy table. Defaulting to defensive."
            }
            
        regime_rules = self.policy_map['regimes'][regime_key]
        
        # 2. Check for Overrides (Transition Mode)
        # e.g., if regime=3 and mode=PREPARE
        if 'overrides' in regime_rules and transition_mode in regime_rules['overrides']:
            policy = regime_rules['overrides'][transition_mode]
            policy['source'] = f"Override: {transition_mode}"
            return policy
            
        # 3. Return Default
        policy = regime_rules['default']
        policy['source'] = "Default"
        return policy

if __name__ == "__main__":
    # Quick sanity check
    gate = PolicyGate()
    print("Regime 11 Policy:", gate.get_policy(11))
    print("Regime 3 (PREPARE):", gate.get_policy(3, "PREPARE"))
