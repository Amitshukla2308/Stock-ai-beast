
# D2 Model Calibration Report
- **Model**: Logistic Regression (L2, C=0.1)
- **Target**: Regime 11/9 in next 3 steps
- **Test Size**: 65597 samples

## Performance Metrics
- **ROC AUC**: 0.8466
- **Brier Score**: 0.0577 (Lower is better)
- **Precision @ 40% Prob**: 0.8703

## Feature Importance (Coefficients)
| Feature     |       Coef |
|:------------|-----------:|
| prior_to_9  |  7.04037   |
| prior_to_11 |  6.81069   |
| R_t-1       |  0.064555  |
| R_t         |  0.0310634 |
| R_t-2       | -0.0229164 |