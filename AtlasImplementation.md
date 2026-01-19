Phase-3 = Market Atlas & Verification Engine
Objective

Build an offline system that answers only one question:

“When NIFTY behaves like this, what has historically happened next?”

No trading.
No execution.
No signals.

Only intelligence.

STEP 1 — Data Canonicalization (5 Years)

Input:

NIFTY 5-min OHLCV

India VIX (aligned to 5-min)

Output:

One immutable, synchronized time-index.

Rules:

Forward-fill VIX.

Drop corrupt candles.

Enforce continuity.

Deliverable:
market_5min.parquet

STEP 2 — Deterministic Feature Engine

For every candle compute:

Price Geometry

Volatility Geometry

Volume Geometry

VIX Geometry

Time Geometry

(as per Phase-3 spec)

Deliverable:
state_vectors.parquet

Invariant:
Same formulas used offline and live.

STEP 3 — Trace & Forward Labeling

For each state:

Horizons: +3, +6, +12 bars
Compute:

MFE, MAE, Net Return

Drawdown Path

Time-to-failure

Break-even Probability

Deliverable:
labeled_states.parquet

STEP 4 — Market Behavior Atlas

Persist:

(State Vector, Context) → Outcome Distributions


Aggregate by similarity (not exact match):

Mean, Median, Tail Risk

Win Rate

Expectancy

Variance

Deliverable:
atlas_store

STEP 5 — Regime Discovery

Unsupervised clustering on:

State geometry

Volatility pressure

Transition velocity

Output per regime:

Expectancy Surface

Stability Score

DD Profile

VIX Sensitivity

Deliverable:
regimes.json

STEP 6 — Vector Index (RAG Layer)

Embed:

State Vector

Trace Window Summary

Build:

FAISS/Qdrant index over historical states.

Deliverable:
atlas_index

STEP 7 — Verification Engine (NO TRADING)

Runtime flow:

Historical Replay Candle by Candle:
  → Compute Stateₜ
  → Query Atlas
  → Record:
      Expected Return
      Predicted Risk
      Actual Outcome


Metrics:

Expectancy Error

Tail Risk Hit Rate

Regime Stability

Drawdown Prediction Accuracy

Deliverable:
verification_report