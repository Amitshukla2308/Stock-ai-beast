Post-Implementation Verification Plan

(For the Modular Research Engine)

This is the plan Antigravity should literally follow as a checklist.

Phase A — Structural Integrity Checks (No Trading Logic)

Goal: Prove the architecture is real, not just renamed files.

A1. God File Elimination Test

Test:

Temporarily rename:

brain/llm_client.py → brain/llm_client_old.py


System must still:

start

run backtest

produce logs

produce decisions

Failure Means:
You did not truly extract the orchestrator.
Old brain is still secretly in control.

A2. Single Responsibility Test (Per Module)

For each module:

Module	Must Contain	Must NOT Contain
enrichment/*	calculations	decisions
signals/*	booleans	thresholds
eligibility/*	style allow	confidence
confidence/*	scoring	blocking
llm_selector/*	prompt + parse	gates
risk/*	direction	eligibility
executor/*	final block/open	calculations

Test:
Search each folder for keywords:

if
block
threshold
>=
<=


If found in wrong module → violation.

A3. Line Count Constraint

Hard rule:

No file > 300 lines


If violated → system will rot again.

This is not stylistic.
This is entropy control.

Phase B — Config Authority Verification

Goal: Prove no magic numbers exist in Python.

B1. Magic Number Scan

Search entire repo for:

0.4
0.5
0.55
15%
10%
14:30
38%


Every hit must be:

config_loader.get("...")


Not literal.

B2. Config Perturbation Test

Do this experiment:

In config:

"REMR": {
  "confidence_floor": 0.95
}


Run backtest.

Expected result:

REMR never executes.

Logs explicitly show:

REMR_survived_confidence=False


Then change to:

"confidence_floor": 0.10


Expected:

REMR fires aggressively.

If behavior does not change → config is fake.

Phase C — Trace Integrity (Most Important)

This is where most LLM-coded systems lie.

C1. Mandatory Trace Chain

For every style, every tick:

REMR_candidate
REMR_eligible
REMR_survived_risk
REMR_survived_confidence
REMR_executed


Each must be logged explicitly.

No “implicit” logic.

C2. Causal Consistency Test

Pick any HOLD tick.

You must be able to answer in 30 seconds:

“Why exactly did REMR not execute here?”

And point to one boolean.

Not a paragraph.
Not a vibe.
A single boolean.

Phase D — Determinism Tests

Goal: Prove system is not haunted.

D1. Replay Test

Run same backtest twice.

Expected:

Identical trades

Identical logs

Identical confidence values

If not → hidden state exists.

D2. Seed Isolation Test

Force:

LLM disabled
LLM always returns ORE


System must still:

respect eligibility

block invalid ORE

produce deterministic output

If system collapses → LLM has illegal authority.

Phase E — Behaviour Sanity Tests

These are not profit tests.
These are physics tests.

E1. Rotational Day Test

Pick known range day.

Expected:

At least 1 REMR or VBD

No ITC dominance

If zero trades → over-filtering still exists.

E2. Trend Day Test

Pick strong trend day.

Expected:

ITC dominates

REMR rarely fires

ORE early

If not → regime logic broken.

E3. Threshold Sweep Test

Automate:

REMR confidence floor: 0.2 → 0.8


Plot:

trade count

win rate

avg pnl

Must form smooth curve.
If jagged → hidden gates exist.

The Meta Question You Asked:
“What kind of mistakes do LLM coding agents make?”

This is critical. These are the real failure modes.

1. Illusion of Modularity

LLMs will:

create new files

move functions

but leave implicit coupling

Example:

eligibility.py imports confidence.py


This kills the entire architecture.

2. Semantic Duplication

LLMs will:

copy logic

paste it in two places

change variable names

You think it's modular.
It’s actually logic cloned twice.

This creates:

“Why did changing config not affect behaviour?”

Because one copy is still hardcoded.

3. Fake Config Extraction

LLMs love this pattern:

threshold = config["remr"]["threshold"]
if x > 0.45:   # ← still hardcoded


Looks config-driven.
Is actually lying.

4. Silent Defaulting (Most Dangerous)

LLMs often write:

value = config.get("remr_floor", 0.45)


If config breaks → silently reverts to old behavior.

This is catastrophic for research.

All defaults must crash.

5. Hidden Global State

LLMs accidentally introduce:

cached values

static variables

module-level state

Which makes:

backtests non-reproducible

logs inconsistent

tuning meaningless

6. Narrative Logging

LLMs love writing:

"REMR rejected due to insufficient structure"


This is useless.

You need:

REMR_eligible=False (near_support=False)


Only booleans matter.
Natural language is poison here.

The One Rule That Saves Everything

This is the rule Antigravity should tattoo on the wall:

If you cannot express a decision as a boolean trace, the system is lying.

Not unclear.
Not complex.
Lying.