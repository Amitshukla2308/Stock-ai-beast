import pandas as pd
import numpy as np
import pickle
import os
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import brier_score_loss, roc_auc_score, precision_score
from .feature_builder import FeatureBuilder

def train_model(model_dir="atlas/models"):
    print("🧠 Training Early-Warning Model (D2)...")
    
    # 1. Build Data
    fb = FeatureBuilder(model_dir=model_dir)
    X, y = fb.build_dataset()
    
    # 2. Split (Temporal)
    # 70% Train, 30% Test (Strict time series split)
    split_idx = int(len(X) * 0.70)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]
    
    # 3. Train Logistic Regression
    # We want calibrated probabilities.
    print("⚙️ Fitting Logistic Regression...")
    clf = LogisticRegression(
        random_state=42, 
        solver='liblinear', 
        class_weight='balanced',
        C=0.1 # Strong regularization to prevent overfitting on rare events
    )
    clf.fit(X_train, y_train)
    
    # 4. Evaluate
    probs = clf.predict_proba(X_test)[:, 1]
    auc = roc_auc_score(y_test, probs)
    brier = brier_score_loss(y_test, probs)
    
    # Threshold Analysis
    y_pred_aggressive = (probs > 0.4).astype(int)
    precision = precision_score(y_test, y_pred_aggressive)
    
    results = f"""
# D2 Model Calibration Report
- **Model**: Logistic Regression (L2, C=0.1)
- **Target**: Regime 11/9 in next 3 steps
- **Test Size**: {len(y_test)} samples

## Performance Metrics
- **ROC AUC**: {auc:.4f}
- **Brier Score**: {brier:.4f} (Lower is better)
- **Precision @ 40% Prob**: {precision:.4f}

## Feature Importance (Coefficients)
"""
    coefs = pd.DataFrame({
        'Feature': X.columns,
        'Coef': clf.coef_[0]
    }).sort_values('Coef', ascending=False)
    
    results += coefs.to_markdown(index=False)
    
    print(results)
    
    # 5. Save Artifacts
    if not os.path.exists(model_dir):
        os.makedirs(model_dir)
        
    model_path = os.path.join(model_dir, "early_warning_v1.pkl")
    with open(model_path, 'wb') as f:
        pickle.dump(clf, f)
        
    report_path = os.path.join(model_dir, "early_warning_calibration.md")
    with open(report_path, "w") as f:
        f.write(results)
        
    print(f"✅ Model saved to {model_path}")
    print(f"📄 Report saved to {report_path}")

if __name__ == "__main__":
    train_model()
