Research Session Report v2.8 (Single Source of Truth)
Objective (Non-Negotiable)

Transform the current trade/reporter.py output from a bot-style summary into a research-grade diagnostic instrument that can answer:

“Why did the system make or lose money?”
in under 30 seconds of reading logs.

This report becomes the primary research artifact of Stock-AI-Beast.

Core Design Principles

No derived metrics in backtest.py or executor

All analytics live in trade/reporter.py

Backtest and live only push raw events

All metrics must come from Trade Engine

trade/models.py

trade/ledger.py

trade/store.py

trade/exit_engine.py

trade/eod.py

Reporter is read-only

It never influences execution

It only aggregates and explains what happened

Target File Ownership
Module	Responsibility
trade/models.py	Trade, ExitEvent, DailySummary
trade/ledger.py	MFE / MAE / hold time
trade/store.py	SQLite persistence
trade/exit_engine.py	Exit reason
trade/eod.py	Daily forced close
trade/reporter.py	ALL analytics + reporting

Only trade/reporter.py changes.

Phase 1 — Expand Trade Data Model
File: trade/models.py

Ensure Trade contains:

class Trade:
    id
    symbol
    style
    direction
    entry_time
    entry_price
    exit_time
    exit_price
    exit_reason  # SL / TGT / EOD / MANUAL
    pnl_points
    mfe_points
    mae_points
    hold_candles


This is mandatory for research reporting.

Phase 2 — Ledger Must Track MFE / MAE
File: trade/ledger.py

Every open trade must update:

trade.mfe_points = max(trade.mfe_points, current_price - entry_price)
trade.mae_points = min(trade.mae_points, current_price - entry_price)
trade.hold_candles += 1


This must happen every candle in backtest and live.

No MFE/MAE → report is meaningless.

Phase 3 — Reporter Aggregation Engine
File: trade/reporter.py

Create a single function:

def generate_session_report(trades: List[Trade], daily_summaries: List[DailySummary])


This function must compute:

Executive Metrics
total_trades
wins
losses
win_rate
net_pnl_points
net_pnl_rupees
avg_pnl_per_trade
profit_factor
expectancy
max_drawdown
max_runup
equity_efficiency

Phase 4 — Trade Distribution Section

Computed in reporter:

by_style = groupby(trades, style)
by_direction = groupby(trades, direction)
by_exit_reason = groupby(trades, exit_reason)

Phase 5 — Exit Quality Analytics (Most Important)

Computed only from ledger data:

avg_mfe = mean(trade.mfe_points)
avg_mae = mean(trade.mae_points)
avg_realized_win
avg_realized_loss
profit_giveback_ratio = 1 - (avg_realized_win / avg_mfe)
exit_efficiency_score = avg_realized_win / avg_mfe


This is where real money leaks are detected.

Phase 6 — Style Diagnostics

Per style:

trades
win_rate
net_pnl
avg_mfe
avg_mae
avg_hold_time
target_hit_rate
stop_hit_rate


Plus auto-generated textual conclusion:

if avg_mfe > abs(avg_mae) and pnl < 0:
    conclusion = "Edge exists in entry, lost in exit logic."


This must be machine generated, not LLM.

Phase 7 — Daily Performance Map

From trade/eod.py summaries:

date
trades_count
daily_pnl
daily_max_dd
notes


This answers: Which days are killing you?

Phase 8 — Opportunity Cost (Critical for v2.8)

Reporter must receive:

From enrichment layer:

trend_efficiency per day

OR established per day

Compute:

days_with_edge
days_traded
days_missed
missed_edge_cost
participation_rate


This is the single most important metric for research.

Phase 9 — System Verdict Generator

Reporter must output:

status = POSITIVE_EDGE | NEGATIVE_EDGE | INCONCLUSIVE
primary_issue
secondary_issue
risk_profile
action_plan


Generated deterministically from metrics.

No LLM involvement.

Final Output Format (Canonical)

The report must be printed exactly in this structure:

Header

Executive Summary

Trade Distribution

Exit Quality

Style Diagnostics

Daily Breakdown

Opportunity Cost

System Verdict

This is the only valid session report format going forward.

Absolute Verification Criteria

Antigravity implementation is considered successful only if:

Structural

trade/reporter.py is the only analytics file

No analytics logic in backtest.py or executor.py

Data

MFE / MAE visible per trade

Hold time visible per trade

Research

From a single report you can answer:

Why did we lose money?
Where is edge leaking?
Are entries or exits broken?
Are we missing market moves?

in under 30 seconds without reading code.

Why This Plan Is Correct for Beast

Because it aligns with your real system architecture:

Entries → eligibility + LLM

Risk → executor

Exits → exit_engine

Memory → ledger

Knowledge → reporter

And turns Stock-AI-Beast into:

A market research system, not a trading bot.

This is the point where your system becomes scientifically improvable.