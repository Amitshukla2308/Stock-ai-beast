ATLAS — End-to-End Project Plan
0. Strategic Positioning

Atlas is a detached Market Intelligence Service which will be used by stock-ai-beast.

┌──────────────┐
│Stock-ai-beast│  (Live Trading)
└──────┬───────┘
       │ Query
       ▼
┌──────────────────┐
│      ATLAS       │  (Market Memory)
└──────────────────┘


Atlas:

Never trades.

Never enforces rules.

Only answers:
“Historically, what happened next when the market looked like this?”

Loaction to build: \\wsl.localhost\Ubuntu-24.04\home\beast\projects\Atlas
A. Data Canonicalization Service

(Foundation of Market Memory)

Folder:

/home/beast/projects/Atlas/


This step answers only one question:

“Do I have a single, clean, immutable market timeline?”

No intelligence yet.
Only correctness.

1. Objective

Create a continuous, corruption-free, time-aligned 5-minute market tape for:

NIFTY OHLCV

India VIX

This becomes the only raw input for all future Atlas layers.

2. Inputs
Source	Granularity	Notes
NIFTY OHLCV	5-min	Exchange timestamps
India VIX	Irregular / 1-min	Must be aligned to 5-min
3. Output

Single file:

Atlas/data/market_5min.parquet


Schema:

Column	Type
ts	datetime (IST)
open	float
high	float
low	float
close	float
volume	float
vix	float

Invariant:
One row = one 5-min candle, no gaps, no duplicates.

4. Canonicalization Rules
A. Time Alignment

Convert everything to IST.

Create a strict 5-min grid from 09:15 to 15:30.

Drop any candle outside market hours.

B. Continuity

Missing candle?

Drop the entire 5-min slot.

Duplicate timestamp?

Keep the first valid OHLCV.

C. VIX Sync

Forward-fill VIX to nearest 5-min candle.

Never backward-fill.

D. Corruption Guards

Drop candle if:

high < max(open, close)

low > min(open, close)

volume ≤ 0

range = 0 for 3 consecutive candles

5. Folder Structure (Step-1)
Atlas/
 ├── data/
 │    └── raw/
 │         ├── nifty.csv
 │         └── vix.csv
 ├── scripts/
 │    └── canonicalize.py
 └── data/
      └── market_5min.parquet

6. Script Responsibility

canonicalize.py must:

Load raw CSVs.

Normalize timestamps.

Build 5-min index.

Apply validation rules.

Forward-fill VIX.

Persist Parquet.

7. Validation Metrics (Must Log)

Total candles ingested.

Candles dropped (and reason).

Missing slots.

Final row count per year.

This is critical for data trust.

8. Dockerization (Atlas-Ingest)

Later, this becomes:

atlas-ingest:latest


But for now, implement as a clean Python module.

9. Success Criteria

You should be able to answer:

“How many valid 5-min candles exist per year?”

“Is there any day with missing structure?”

“Is VIX aligned for every candle?”

Only after this is correct do we move to intelligence.

B. Feature / State Vector Engine

Container: atlas-features

1. Objective

Transform each 5-min candle into a State Vector that fully describes:

Price behavior

Volatility behavior

Volume behavior

Risk pressure (VIX)

Time context

No trading logic. No gates. No styles. Only physics.

2. Input
Atlas/data/market_5min.parquet

3. Output
Atlas/data/state_vectors.parquet


Each row:

(ts, F1, F2, F3, ... Fn)


Where Fi are deterministic, numeric features.

4. Feature Groups (Directly Mapped From Your Audit)

Everything you listed becomes features.

A. Time Geometry
Feature	Meaning
minutes_since_open	
bias_weight	
session_phase (one-hot or int)	
B. Candle Geometry
Feature
body_size
range_size
upper_wick_ratio
lower_wick_ratio
body_ratio
relative_range
relative_volume
C. Volatility Geometry
Feature
atr_14
effective_atr
or_range
vol_of_day
expected_move_low (0.6x OR)
expected_move_high (1.2x OR)
D. Location Geometry
Feature
dist_to_support
dist_to_pivot
dist_to_resistance
loc_zone_id
E. Energy & Momentum
Feature
momentum_slope
momentum_consistency
ter
regime_momentum
or_regime_id
F. Behavior Signals (Binary or Int)
Feature
rejection_flag
stall_flag
failure_to_extend_flag
weak_follow_through_flag
absorption_flag
v_reversal_flag
vwap_dist
G. Risk Pressure
Feature
vix_level
vix_slope
vix_zscore
5. Invariants

Same formulas as Beast enrichment.

No conditional logic.

No thresholds for decisions.

Pure measurement.

Atlas ≠ Strategy.
Atlas = Instrument.

6. Folder Structure
Atlas/
 ├── features/
 │    └── build_state_vectors.py
 └── data/
      ├── market_5min.parquet
      └── state_vectors.parquet

7. Validation

After build:

Check NaN %

Distribution sanity (min/mean/max)

Temporal continuity

This layer must be stable across years.

8. Performance Expectation

~100k rows × ~50–70 features
→ <30 seconds compute.

9. Success Criteria

You should be able to open state_vectors.parquet and see:

Every candle described in terms of behavior, not price.

This is the “language” Atlas will reason in.

Mental Model

Price → Geometry → Behavior → State.

This is the vocabulary of the market.

Schema = superset of your enrichment.py outputs.

C. Forward Outcome Labeler

Container: atlas-labeler

(Teaching Atlas What Happened Next)

This is where Atlas becomes a memory, not just a recorder.

1. Objective

For every State Vector, compute what the market actually did after this moment.

This creates the empirical truth Atlas will learn from.

2. Input
Atlas/data/state_vectors.parquet


Also uses:

Atlas/data/market_5min.parquet


(for future price paths)

3. Horizons

We care about intraday behavior, so:

Horizon	Meaning
+3 bars	15 minutes
+6 bars	30 minutes
+12 bars	60 minutes
4. Labels To Compute (Per Horizon)

For each state at time t:

Metric	Definition
MFE	max(high[t+1:t+H]) − close[t]
MAE	close[t] − min(low[t+1:t+H])
NET_RET	close[t+H] − close[t]
DD_PATH	worst drawdown from local max
TIME_TO_FAIL	bars until price crosses −X pts
BE_PROB	% of path above entry after initial adverse

(Use X = 0 for BE, or 0.3*ATR for failure.)

5. Output
Atlas/data/labeled_states.parquet


Schema:

[ state_features..., 
  MFE_3, MAE_3, RET_3,
  MFE_6, MAE_6, RET_6,
  MFE_12, MAE_12, RET_12,
  DD_PATH, TIME_TO_FAIL, BE_PROB ]

6. Implementation Notes

Vectorized rolling windows (no loops if possible).

Skip last H rows of each session.

Do not cross session boundaries.

7. Validation

Check distribution of MFE vs MAE.

Ensure no look-ahead leakage.

Plot few random paths to visually verify.

8. Why This Matters

This is the step that converts:

“This is what the market looks like.”

into:

“This is what usually happens after it looks like this.”

Everything after this is just compression and retrieval.


This is where “memory” is created.



D. Behavior Aggregator (Atlas Core)

Container: atlas-core

(From Experience to Memory)

This step compresses millions of individual observations into usable market knowledge.

1. Objective

Transform:

(labeled_state₁, labeled_state₂, ..., labeled_stateₙ)


into:

(State Pattern) → Outcome Distribution


So that similar market conditions share a statistical memory.

2. Input
Atlas/data/labeled_states.parquet

3. Similarity Space

We cluster on state geometry only, not outcomes:

Use normalized vectors of:

TER

Effective ATR

Relative Range

Momentum Slope

Volume Ratio

VIX Pressure

Session Phase

Location Distances

(10–15 most informative dimensions, not all.)

4. Aggregation

For each cluster:

Compute:

Metric	Meaning
WinRate_H	P(RET_H > 0)
Mean_RET_H	
Median_RET_H	
Tail90_RET_H	
Mean_MAE_H	
Variance_H	
Regime_Stability	
VIX_Sensitivity	

(H = 3,6,12)

5. Output
Atlas/atlas_store/
   ├── clusters.parquet
   ├── stats_3.parquet
   ├── stats_6.parquet
   └── stats_12.parquet


This is the memory of the market.

6. Implementation Notes

Use unsupervised clustering (KMeans / HDBSCAN).

Ensure clusters have minimum support (e.g., ≥200 samples).

Merge rare clusters into “OTHER.”

7. Validation

Check expectancy dispersion between clusters.

Identify convex vs flat regimes.

Confirm stability across years.

8. Meaning For Beast

At runtime, Beast no longer sees:

“TER = 0.62”

It sees:

“You are in Cluster 187, where historically mean 30-min return = +42 pts.”

E. Vector Intelligence (RAG Layer)

Container: atlas-rag
This layer answers:

“What kind of market is this, and how stable is it?”

1. Objective

Discover natural, data-driven regimes from behavior, not labels.

2. Input
Atlas/atlas_store/clusters.parquet


and

Atlas/data/labeled_states.parquet

3. Clustering Dimensions

Use slow-changing, structural features:

TER

Effective ATR

Relative Range

VIX Pressure

Momentum Consistency

Overlap Ratio

Session Phase

4. Outputs
Atlas/atlas_store/regimes.json


Each regime:

Field	Meaning
Regime_ID	
Expectancy_Surface (H=3,6,12)	
Stability_Score	
Drawdown_Profile	
Transition_Probabilities	
VIX_Sensitivity	
5. Validation

Regime persistence (avg duration).

Transition smoothness.

Expectancy separation.

6. Runtime Meaning

Beast will later ask Atlas:

“In this regime, how dangerous / profitable is continuation vs mean-reversion?”

This replaces heuristic regime rules with empirical ones.

F. Atlas Query API

Container: atlas-api
This is the bridge between offline intelligence and live decisioning.

1. Objective

Enable:

“Given the current market state, retrieve the most similar historical situations and their outcomes.”

2. Input
Atlas/data/state_vectors.parquet
Atlas/data/labeled_states.parquet

3. Embedding Strategy

Create embedding for:

Current State Vector

Recent Trace Window (last 3–5 states)

Regime Context

These are concatenated into one semantic vector.

4. Index

Use:

FAISS (local) or Qdrant (service)

Store:

Embedding → Cluster_ID → Outcome Stats

5. Output
Atlas/atlas_index/

6. Query API Contract
POST /query_state
{
  "state_vector": {...},
  "trace": [...]
}


Response:

{
  "expected_return_15m": ...,
  "expected_return_30m": ...,
  "tail_90": ...,
  "risk": ...,
  "regime": ...
}

7. Performance Target

Query latency < 20 ms.

Top-K similarity = 50–100.

8. Validation

Nearest-neighbor stability.

Consistency across days.

No leakage of future information.

G. Verification Engine (Shadow Mode)

Container: atlas-verify
This is your model governance layer.

Before Atlas influences money, it must prove it understands reality.

1. Objective

Replay history and verify:

“When Atlas said X, did the market actually do X?”

2. Input

state_vectors.parquet

labeled_states.parquet

atlas_index

atlas_store

3. Process

For each historical candle:

Compute Stateₜ

Query Atlas (as if live)

Record:

Predicted Expectancy

Predicted Risk

Compare with actual outcomes.

4. Metrics To Track
Metric	Meaning
Expectancy Error	
Tail Hit Rate	% times tail event occurred
Regime Stability	Prediction consistency
DD Prediction Accuracy	Risk forecast vs reality
5. Output
Atlas/reports/verification_report.html

6. Acceptance Criteria

Stable error distribution.

No regime drift.

Convex tails correctly identified.

Only after this passes do we integrate with Beast.

H. Stitching Into Beast (2.9+)

Modify LLM context:

Micro_Context
+ ATLAS_Context:
   - Expected_Return
   - Risk_Profile
   - Tail_Potential
   - Regime_Stability


Gates become:

Catastrophic only.

Geometry and time remain.

Binary “confidence” becomes gradient targeting.

Atlas does NOT override execution.


I. Why This Works With Your Existing Math

Everything you listed in your audit becomes:

Features, not rules.

Instead of:

“Block if TER < X”

You will now know:

“When TER ≈ X in history, expectancy was Y.”

This is the shift from engineered trading → empirical trading.