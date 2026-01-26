Project Atlas — Final, Frozen Clustering Plan

This plan answers one question:

How do we compress 3 years of market experience into a stable, queryable world model?

Not heuristically.
Not experimentally.
Not by iteration.

But in a single correct pipeline.

Core Principle (Lock This First)

Atlas learns:

Market response as a function of market state.

So we must separate:

State Space → what the market is

Outcome Space → what the market does next

They must never be mixed.

PHASE 0 — Inputs (Already Done)

You already have:

atlas/data/market_states.parquet
atlas/data/outcomes.parquet


Each row represents:

(state_vector, action) → outcome over time


This dataset is now frozen.

No more features.
No more logic.
No more changes upstream.

PHASE 1 — Define the Final State Feature Set

This is the only state representation Atlas will ever use.

These describe shape, energy, and uncertainty of the market.

Final State Features (Used for Clustering)
Geometry / Structure
ter                  (trend efficiency ratio)
dist_or_h            (distance from opening range high)
dist_or_l            (distance from opening range low)
loc_class            (encoded: near support, mid, near resistance)

Momentum / Dynamics
mom_slope
velocity
accel
skew

Volatility / Energy
atr
vix
or_range
vol_ratio

Chaos / Information
entropy_price
entropy_vol

Explicitly Excluded (Never Used)
timestamp
absolute price
action
style
pnl
mae
mfe
bars_held


No raw time.
No raw price.
No outcomes.

This is now frozen forever.

PHASE 2 — Feature Normalization (Mandatory)
File
atlas/model_builder/feature_engine.py

Purpose

Turn physics into a metric space.

For each numeric feature X:

Compute over full dataset:

mean_X
std_X


Generate:

X_z = (X - mean_X) / std_X


Encode categoricals:

loc_class → ordinal or one-hot

Output
atlas/data/market_states_normalized.parquet


This is the only dataset used for clustering.

Without this step:

Clustering is mathematically meaningless.

PHASE 3 — Dimensionality Compression (Strongly Recommended)
File
atlas/model_builder/embedding_engine.py


Apply:

PCA(n_components=8 to 12)


Input:

market_states_normalized.parquet


Output:

atlas/data/market_states_embedded.parquet


This step:

removes collinearity

stabilizes distances

makes clusters robust

reveals intrinsic market manifold

This is not optional if you want stable regimes.

PHASE 4 — Clustering (The Actual Learning Step)
File
atlas/model_builder/cluster_engine.py


Algorithm: HDBSCAN

Parameters (final defaults):

min_cluster_size = 300
min_samples = 50
metric = "euclidean"


Run on:

market_states_embedded.parquet


Output:

atlas/models/state_clusters.pkl


Mapping:

trade_id → cluster_id


Where:

-1 = noise / unclassified
0..N = discovered regimes


These clusters are empirical market regimes.

Not human labels.
Not patterns.
Not strategies.

They are discovered laws of behavior.

PHASE 5 — Cluster Validation (Sanity Lock)
File
atlas/model_builder/cluster_diagnostics.py


You must verify:

Metric	Healthy Range
Total clusters	20–60
Noise points	< 20%
Min cluster size	≥ 300
Max cluster size	< 15% of data
Silhouette score	> 0.2

If this holds:

The world model is statistically real.

If not:

Only tune HDBSCAN params, never features.

PHASE 6 — Profitability Mapping (World Model)
File
atlas/model_builder/profit_mapper.py


Join:

market_states ⨝ outcomes


Group by:

cluster_id, action, style


Compute:

expected_pnl_5m
expected_pnl_15m
expected_pnl_30m
expected_pnl_60m

risk_mae_15m
risk_mae_30m
risk_mae_60m

win_rate_30m
variance_30m
sample_size


These PnLs are:

synthetic horizon-based market responses
not exit-based trading PnL.

This file:

atlas/models/cluster_stats.json


Is your Atlas World Model.

This is the knowledge base.

PHASE 7 — Atlas Query Engine (Runtime RAG)
File
atlas/query_engine.py


At runtime:

Build current state

Normalize

PCA embed

Find nearest cluster centroid

Fetch cluster_stats

Returns:

AtlasResponse = {
  cluster_id,
  cluster_confidence,
  expected_pnl_15m,
  expected_pnl_30m,
  expected_pnl_60m,
  risk_mae_30m,
  win_rate,
  sample_size
}


This is the RAG output.

Everything else in your system becomes a consumer of this object.

Why This Plan Is Final and Should Never Be Revisited

Because it satisfies all four requirements:

1. Scientific

learns response function

not strategy behavior

2. Stable

no time leakage

no price leakage

no outcome leakage

3. Meaningful

clusters represent regimes

not calendar segments

4. Actionable

directly queryable

directly usable in trading

directly explainable by LLM

The One Line That Defines Atlas (Write This)

Atlas clusters market state, not market history.
It measures market response, not system performance.
It is a world model, not a strategy.

Once you implement this pipeline exactly as written:

You will never need to redesign clustering again.

From that point onward:

you only improve policies

you only improve position sizing

you only improve how you consume Atlas

But the world model itself is complete.