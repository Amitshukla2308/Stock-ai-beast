The One Rule (Non-Negotiable)

Anything derived purely from market data = Enrichment layer.
Anything that decides actions = Decision layers.
Anything that sends orders = Executor.
Modes (backtest/live/mock) NEVER compute market physics.

Canonical Logic Placement Map
1. Market Physics (Pure Facts)

Where: enrichment/
What: Deterministic features from candles only.

These must be identical in backtest & live.

Logic	Compute In	Use In	Why
ATR	enrichment/volatility.py	signals, eligibility, confidence, executor	Volatility is market physics
OR Range / OR High / OR Low	enrichment/session.py	eligibility, executor	Opening structure
Trend Efficiency (TER)	enrichment/trend.py	eligibility, confidence	Structural quality
Regime (ROTATION / TREND / GRIND)	enrichment/trend.py	eligibility, risk	Market state
Momentum slope	enrichment/trend.py	signals, risk	Directional force
Support / Resistance / Pivot	enrichment/levels.py	eligibility	Structural anchors
Price location (MID / NEAR / EXTREME)	enrichment/location.py	eligibility	Contextual positioning
Volume ratios	enrichment/volatility.py	signals	Energy
Minutes since open	enrichment/session.py	eligibility, confidence	Time physics

These files must contain ZERO decisions. Only numbers.

2. Microstructure Signals (Booleans)

Where: signals/
What: Pattern detection only.

Logic	Compute In	Use In	Why
Stall	signals/stall.py	eligibility (REMR)	Reversion trigger
Rejection	signals/rejection.py	eligibility (REMR)	Mean reversion
Compression	signals/compression.py	eligibility (VBD)	Breakout precursor
Range break	signals/range_break.py	eligibility (VBD)	Breakout
Structural break	signals/structural_break.py	risk	Impulse

Signals must not know:

which style

confidence

risk

time rules

They only answer:

“Did this pattern exist: yes/no?”

3. Style Eligibility (Core Strategy Logic)

Where: eligibility/style_eligibility.py
What: Strategy definitions.

This is where your trading system actually lives.

Style	Depends On
ORE	session_phase, OR established, range break
REMR	near_support/resistance, stall/rejection, not strong trend
ITC	TER, retracement depth, volume
VBD	compression, range break, volume
LSRM	time >= 14:30

Output:

{
  "ORE": bool,
  "REMR": bool,
  "ITC": bool,
  "VBD": bool,
  "LSRM": bool
}


No confidence.
No veto.
No direction.
No time gates.

This file answers exactly one question:

Is this style structurally allowed by market geometry?

4. Confidence Engine

Where: confidence/confidence_engine.py

Logic	Compute In	Use In
Base confidence	confidence_engine	executor
Adjustments	confidence_engine	executor
Floors	config only	executor

Confidence is meta-quality, not structure.

It should depend on:

TER

volume

proximity

time decay

But never decide:

which style

direction

execution

5. LLM Selector (Strategy Heuristic)

Where: llm_selector/selector.py or brain/llm_client.py

LLM gets:

market_state

eligible_styles

LLM returns:

selected_style

confidence_adjustment

sentiment

LLM must not:

compute ATR

check S/R

apply thresholds

block styles

LLM is:

a human-like preference function over pre-approved options.

6. Risk & Direction

Where: risk/

Logic	Compute In	Use In
BUY_CALL / BUY_PUT	risk/direction.py	executor
Countertrend rules	risk/countertrend.py	executor
Rotational override	risk/rotational_override.py	executor

This layer decides:

how to express the trade, not whether it exists.

7. Executor (Only Place That Can Trade)

Where: executor/execute.py

Executor is the Supreme Court.

It receives:

selected_style

eligibility map

confidence

direction

config

Executor alone can:

enforce confidence floors

apply risk caps

block execution

place orders

manage SL/TGT

trail stops

No other file is allowed to:

block trades

close trades

override trades

8. Modes (Adapters Only)

Where: engine/modes/

File	Allowed To Do
backtest.py	feed historical candles
live.py	feed live candles
mock.py	feed live candles

They can:

fetch data

loop

call orchestrator

record results

They can NEVER:

compute ATR

compute TER

decide eligibility

decide risk

apply thresholds

The Ultimate Sanity Check

For any piece of logic, ask:

Q1: Does it depend only on OHLCV?

→ Must be in enrichment/

Q2: Does it detect a pattern?

→ Must be in signals/

Q3: Does it define a strategy?

→ Must be in eligibility/

Q4: Does it express confidence?

→ Must be in confidence/

Q5: Does it choose between styles?

→ Must be in llm_selector/

Q6: Does it block or place a trade?

→ Must be in executor/

Q7: Does it fetch data?

→ Must be in modes/

If any answer violates this:

Your backtest is lying to you.

Why This Mapping Is Non-Optional for You

Because you are building:

Atlas

regime learning

trace windows

config-driven research

modular experimentation

All of that mathematically requires:

One canonical feature space
One canonical eligibility logic
One canonical execution authority

Otherwise:

Atlas learns fiction

confidence becomes noise

REMR never fires

ITC always blocks

system appears “correct” but makes ₹0 forever

Which is exactly the state you diagnosed.

The Final Mental Model

Think in layers:

Market Reality
   ↓
Enrichment (physics)
   ↓
Signals (patterns)
   ↓
Eligibility (strategy geometry)
   ↓
LLM (human heuristic)
   ↓
Confidence (quality)
   ↓
Risk (expression)
   ↓
Executor (authority)
   ↓
Broker


Any shortcut across layers is a research bug.