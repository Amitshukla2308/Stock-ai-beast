import pickle
import pandas as pd
import numpy as np
import os

# Kill Switch (As requested)
EARLY_WARNING_ENABLED = True

class EarlyWarningPredictor:
    def __init__(self, model_dir="atlas/models", version="v1"):
        self.model_dir = model_dir
        self.version = version
        self.model = None
        
        self.load_artifacts()
        
    def load_artifacts(self):
        path = os.path.join(self.model_dir, f"early_warning_{self.version}.pkl")
        if os.path.exists(path):
            with open(path, 'rb') as f:
                self.model = pickle.load(f)
        else:
            print(f"⚠️ Warning: Early Warning Model not found at {path}")
            
    def get_alpha_probability(self, context) -> float:
        """
        Returns P(Regime 11 or 9 in next K steps).
        Context must contain:
        - R_t (current regime)
        - R_t-1 (previous regime)
        - R_t-2 (2 steps ago)
        - prior_to_11 (from transition matrix)
        - prior_to_9 (from transition matrix)
        """
        if not EARLY_WARNING_ENABLED or self.model is None:
            return 0.0
            
        try:
            # Construct Feature Vector strictly matching training
            features = pd.DataFrame([{
                'R_t': context.get('R_t'),
                'R_t-1': context.get('R_t-1'),
                'R_t-2': context.get('R_t-2'),
                'prior_to_11': context.get('prior_to_11'),
                'prior_to_9': context.get('prior_to_9')
            }])
            
            # Predict Proba (Class 1)
            prob = self.model.predict_proba(features)[0, 1]
            return float(prob)
            
        except Exception as e:
            print(f"❌ Prediction Error: {e}")
            return 0.0

if __name__ == "__main__":
    # Quick Test
    predictor = EarlyWarningPredictor()
    
    # Mock Context (Regime 3 -> usually precedes 11)
    mock_ctx = {
        'R_t': 3,
        'R_t-1': 3,
        'R_t-2': 2,
        'prior_to_11': 0.173, # From matrix
        'prior_to_9': 0.0
    }
    
    p = predictor.get_alpha_probability(mock_ctx)
    print(f"🔮 P(Alpha | Regime 3): {p:.4f}")
    
    if p > 0.2:
        print("🚀 Signal: ELEVATED PROBABILITY")
    else:
        print("💤 Signal: BASELINE")
