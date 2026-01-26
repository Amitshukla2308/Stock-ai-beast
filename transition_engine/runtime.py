import pandas as pd
import os

class RegimeTransitionMonitor:
    def __init__(self, model_dir="atlas/models", version="v1"):
        self.model_dir = model_dir
        self.version = version
        self.matrix = None
        self.precursors = None
        self.precursors_2step = None
        
        self.load_artifacts()
        
    def load_artifacts(self):
        # Load Transition Matrix
        matrix_path = os.path.join(self.model_dir, f"regime_transition_matrix_{self.version}.parquet")
        if os.path.exists(matrix_path):
            self.matrix = pd.read_parquet(matrix_path)
            # Create quick lookup dict: (from, to) -> prob
            self.prob_lookup = self.matrix.set_index(['from_regime', 'to_regime'])['probability'].to_dict()
        else:
            print(f"⚠️ Warning: Transition Matrix not found at {matrix_path}")
            
        # Load Precursors (1-Step)
        p1_path = os.path.join(self.model_dir, f"regime_precursors_{self.version}.parquet")
        if os.path.exists(p1_path):
            self.precursors = pd.read_parquet(p1_path)
        
        # Load Precursors (2-Step) - Optional for now but good to have
        p2_path = os.path.join(self.model_dir, f"regime_precursors_2step_{self.version}.parquet")
        if os.path.exists(p2_path):
            self.precursors_2step = pd.read_parquet(p2_path)
            
    def get_transition_context(self, current_regime_id):
        """
        Returns advisory context for the current regime.
        Does NOT return trade decisions.
        """
        if self.precursors is None:
            return {"mode": "off", "error": "artifacts_missing"}
            
        # 1. Check for Alpha Precursor Status
        # Filter precursors where current_regime matches
        relevant = self.precursors[self.precursors['current_regime'] == current_regime_id].sort_values('p_transition', ascending=False)
        
        if relevant.empty:
            return {
                "current_regime": int(current_regime_id),
                "mode": "IGNORE",
                "alpha_target": None,
                "probability": 0.0
            }
            
        # Get best alpha target
        best_match = relevant.iloc[0]
        prob = best_match['p_transition']
        target = int(best_match['target_regime'])
        
        # 2. Logic Thresholds (Locked spec)
        # P < 2%      -> IGNORE
        # 2% <= P < 8% -> WATCH
        # P >= 8%     -> PREPARE
        
        mode = "IGNORE"
        if prob >= 0.08:
            mode = "PREPARE"
        elif prob >= 0.02:
            mode = "WATCH"
            
        return {
            "current_regime": int(current_regime_id),
            "mode": mode,
            "alpha_target": target,
            "probability": round(prob, 4),
            "rank": int(best_match['rank'])
        }

if __name__ == "__main__":
    # Quick Test
    monitor = RegimeTransitionMonitor()
    # Test a few regimes
    for r in [3, 7, 0]:
        ctx = monitor.get_transition_context(r)
        print(f"Regime {r}: {ctx}")
