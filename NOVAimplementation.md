SUPER NOVA v1 — EXECUTABLE ENGINEERING PLAN

(Delta on existing codebase)

GLOBAL CONSTRAINTS (MUST BE ENFORCED)

These are invariants. Violating any of these breaks the system.

LLM MUST NOT:

decide trades

generate prose for learning

output free text for clustering

override deterministic logic

LLM MUST:

output fixed structured schema

numeric / categorical only

bounded values

same fields every tick

Regimes MUST be learned from:

LLM latent vectors

physics metrics

NOT from text

PHASE 0 — Freeze Trading Logic

No changes allowed in:

entry logic

exit logic

sizing logic

policy table

signals

Only data & atlas layers are touched.

PHASE 1 — Add LLM Latent Encoder (core)
File: llm_client.py

Add new method:

def get_market_latent_state(context: dict) -> dict:
    """
    Returns fixed schema latent state.
    No prose. No trading advice.
    """

Hardcode output schema:
LATENT_SCHEMA = {
    "trend_strength": float,          # 0.0 - 1.0
    "trend_direction": int,           # -1, 0, +1
    "mean_reversion": float,          # 0.0 - 1.0
    "volatility_regime": int,         # 0=low,1=mid,2=high
    "momentum_quality": float,        # 0.0 - 1.0
    "structure_type": int,            # 0..N enum
    "edge_call": float,               # 0.0 - 1.0
    "edge_put": float,                # 0.0 - 1.0
    "edge_hold": float,               # 0.0 - 1.0
    "edge_horizon": int,              # minutes
    "risk_state": int                 # 0=bad,1=neutral,2=good
}


LLM prompt must:

instruct model to output only JSON

validate numeric bounds

reject prose

PHASE 2 — Persist Latent State
File: database.py

Add new table:

market_latent_states (
    timestamp,
    symbol,
    trend_strength,
    trend_direction,
    mean_reversion,
    volatility_regime,
    momentum_quality,
    structure_type,
    edge_call,
    edge_put,
    edge_hold,
    edge_horizon,
    risk_state
)

PHASE 3 — Oracle Ghost Ground Truth
File: training_engine.py (inherits BacktestMode)

At every 15-min tick:

Spawn 3 ghost trades:

CALL

PUT

HOLD

Track for fixed horizon (e.g. 30 bars):

call_mfe

call_mae

put_mfe

put_mae

hold_pnl

edge_survival_5

edge_survival_10

Store into:

oracle_outcomes (
    timestamp,
    symbol,
    call_mfe,
    call_mae,
    put_mfe,
    put_mae,
    hold_pnl,
    edge_survival_5,
    edge_survival_10
)


No learning yet. Only data.

PHASE 4 — Build Atlas v2 Dataset
New file: atlas_v2/dataset_builder.py

Join:

market_latent_states
+ oracle_outcomes
+ existing physics features


Output:

atlas_v2_states.parquet


Each row = one tick.

PHASE 5 — Learn Regimes (Atlas v2)
File: atlas_v2/cluster_engine.py

Cluster on:

[
  trend_strength,
  trend_direction,
  mean_reversion,
  volatility_regime,
  momentum_quality,
  structure_type,
  edge_call,
  edge_put,
  edge_hold,
  risk_state
]


Use:

KMeans (start K=12)

or HDBSCAN later

Produce:

atlas_v2_model.pkl

atlas_v2_cluster_stats.json

Stats per cluster:

mean call_mfe

mean put_mfe

mean hold_pnl

edge_survival rates

PHASE 6 — Wire Atlas v2 Into Engine
File: atlas/atlas_engine.py

Add mode:

mode = "LATENT"


Replace old:

price → handcrafted features → cluster


With:

price → LLM latent → atlas_v2_model → regime_id


Engine now gets:

real semantic regime, not UNKNOWN.

PHASE 7 — Only Then Touch Policy

After at least 50k ticks:

Policy table updated using:

cluster_stats.json


Based on:

empirical MFE

MAE

survival

Not beliefs.

THE ONLY ACCEPTANCE TESTS

Your coding agent is done only if:

Test 1 — Schema purity

No LLM output contains text.
All outputs conform to schema.

Test 2 — Regime observability

After 1 month backtest:

<10% ticks are UNKNOWN

Test 3 — Ground truth exists

Every latent state row has:

oracle outcome row

Test 4 — Clusters are empirical

Every cluster has:

real MFE / MAE stats