# SPEC-002-Aggressive Exit Optimization & ETD

## Background

The Antigravity Intelligence Stack has conclusively demonstrated **entry and timing edge** through Atlas (K=12), Transition Physics, and D2 Radar. Backtests confirm high MFE, controlled MAE, and strong participation — but also reveal **profit giveback and tail drawdowns caused primarily by late exits**.

This specification formalizes a single, aggressive exit optimization plan focused on **maximizing alpha regime extraction** while introducing **ETD (Exit Timing Deviation)** as a first-class metric. The goal is not to predict tops, but to **exit precisely when edge decays**, enabling right-skewed returns without increasing capital risk.

---

## Requirements

### Must Have
- Aggressive exits for Alpha Regimes (R9, R11)
- Deterministic, table-driven exit rules (no AI execution authority)
- Continuous collection of MFE, MAE, and ETD
- ETD computed without hindsight bias
- Zero changes to entry logic, sizing, or D2 training

### Should Have
- Regime-specific exit profiles
- D2-aware tightening (not hard exits)
- Time-decay based edge invalidation

### Won’t Have
- Price prediction exits
- Indicator-heavy trailing logic
- Partial position management (deferred)

---

## Method

### 1. Exit Philosophy (Locked)

> Let winners run indefinitely **until the edge dies**, then exit immediately.

Edge is defined by **state validity**, not price action.

---

### 2. Alpha Regime Exit Rules (R9, R11)

#### A1. No Fixed Profit Target
- Disable static TGT for Alpha Regimes
- Exit only via edge invalidation or decay

#### A2. MFE-Based Giveback Guard (Aggressive)

| MFE Achieved | Max Allowed Giveback |
|-------------|----------------------|
| ≥ 40 pts    | 35% of MFE           |
| ≥ 70 pts    | 25% of MFE           |

Exit condition:
```
if (MFE - CurrentPnL) > AllowedGiveback → EXIT
```

This preserves fat tails while preventing full reversals.

---

### 3. Regime Invalidation (Hard Kill)

Immediate exit if:
```
current_regime ∉ {entry_regime, known_precursors}
AND bars_in_trade > 2
```

Rationale: Alpha regimes are state-dependent; once invalidated, the thesis is dead.

---

### 4. D2-Aware Tightening (Not Exit)

D2 is a **leading indicator**.

```
If D2_probability drops > 50% from peak:
  → Switch to TIGHTEN mode
  → Reduce allowed giveback by 50%
```

No immediate exit — preparation only.

---

### 5. Time-Based Alpha Decay

Alpha regimes have finite lifetimes.

```
If bars_in_trade > expected_alpha_life (12–18 bars)
AND CurrentPnL < 0.6 * MFE
→ EXIT
```

This removes late-stage stagnation and capital traps.

---

## ETD (Exit Timing Deviation)

### Definition

```
ETD = PnL_at_edge_death − PnL_at_exit
```

- ETD = 0 → perfect exit
- ETD > 0 → exited late (gave back edge)
- ETD < 0 → exited early (acceptable)

---

### Edge Alive State

At each bar, compute:
```
EDGE_ALIVE = (
  regime_valid
  AND d2_not_collapsed
  AND volatility_supportive
  AND CurrentPnL ≥ dynamic_threshold
)
```

---

### Edge Death Event

- First bar where `EDGE_ALIVE` flips False
- Record:
  - timestamp
  - PnL_at_edge_death

---

### ETD Storage Schema

Per trade:
```
trade_id
entry_time
exit_time
MFE
MAE
PnL_exit
PnL_edge_death
ETD
```

Optional per-bar (for learning):
```
trade_id | bar_time | edge_alive | pnl | mfe | d2_prob
```

---

## Architecture Integration

```
ENTRY (unchanged)
│
├─ UNREALIZED_PNL (5m telemetry)
│
├─ EDGE STATE ENGINE (new)
│    ├─ regime validity
│    ├─ D2 collapse detection
│    ├─ time decay
│
├─ IN-TRADE TACTICAL (advisory)
│    └─ classifies: RUNNING / EXHAUSTING / DEAD
│
└─ EXIT ENGINE (deterministic)
     └─ executes rules above
```

LLM **never exits trades** — it only labels edge state.

---

## Implementation

1. Add EDGE_STATE computation to in-trade loop
2. Track and update MFE / MAE continuously (already present)
3. Detect and timestamp first EDGE_DEAD event
4. Persist `PnL_edge_death`
5. Compute ETD at trade close
6. Apply exit rules in priority order:
   1. Regime invalidation
   2. Time decay
   3. MFE giveback

---

## Milestones

- M1: EDGE_STATE engine live
- M2: Alpha regime exit rules enabled
- M3: ETD persisted per trade
- M4: Backtest comparison (ETD distribution)

---

## Gathering Results

Success criteria:
- Avg ETD → 0
- Reduced profit giveback
- Lower Max Drawdown
- Higher average win (same trade count)

Primary diagnostic:
```
Mean ETD
ETD Std Dev
ETD / MFE ratio
```

---

## Need Professional Help in Developing Your Architecture?

Please contact me at [sammuti.com](https://sammuti.com) :)

