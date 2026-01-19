import duckdb
import pandas as pd
import json
from datetime import datetime, time, timedelta
import pytz
from engine.enrichment import calculate_micro_context, calculate_style_eligibility
from data.database import fetch_context_data

# Constants
SESSION_ID = 'BACKTEST_20260117_232147' # Jan 12 run
DATE_STR = '2026-01-12'
SYMBOL = 'NIFTY'

print(f"--- DIAGNOSING SESSION {SESSION_ID} ({DATE_STR}) ---")

conn = duckdb.connect('data/trading.db', read_only=True)

# 1. Fetch Morning Plan
plan_row = conn.execute(f"SELECT content FROM simulation_logs WHERE session_id='{SESSION_ID}' AND event_type='MORNING'").fetchone()
if not plan_row:
    print("❌ Critical: No Morning Plan found in logs! Using fallback.")
    morning_plan = {'market_personality': 'CHOPPY', 'primary_bias': 'NEUTRAL', 'boundary_levels': {'support_zone': 0, 'resistance_zone': 0, 'pivot_point': 0}}
else:
    morning_plan = json.loads(plan_row[0])
    print(f"✅ Morning Plan: {morning_plan.get('market_personality')} | {morning_plan.get('primary_bias')}")

conn.close() # Close to avoid lock during loop calls


# 2. Iterate Timesteps (09:45 to 15:00)
# We need to simulate the loop. logic: fetch_context_data wants a naive UTC timestamp (that represents IST).
# BacktestMode: "ts = current_tick['timestamp']" -> IST aware.
# fetch_context_data converts IST to UTC.

ist = pytz.timezone('Asia/Kolkata')
start_dt = ist.localize(datetime.strptime(f"{DATE_STR} 09:45:00", "%Y-%m-%d %H:%M:%S"))
end_dt = ist.localize(datetime.strptime(f"{DATE_STR} 15:00:00", "%Y-%m-%d %H:%M:%S"))

current_dt = start_dt
while current_dt <= end_dt:
    time_str = current_dt.strftime("%H:%M")
    
    # FETCH CONTEXT
    # Note: fetch_context_data expects naive UTC or timezone-aware.
    context = fetch_context_data(current_dt, symbol=SYMBOL, resolution="5")
    bars_15m = context.get('bars_15m', [])
    
    # RUN MICRO
    current_price = bars_15m[-1]['c'] if bars_15m else 0
    micro = calculate_micro_context(
        bars_15min=bars_15m,
        current_price=current_price,
        support=morning_plan.get('boundary_levels', {}).get('support_zone', 0),
        resistance=morning_plan.get('boundary_levels', {}).get('resistance_zone', 0),
        pivot=morning_plan.get('boundary_levels', {}).get('pivot_point', 0),
        atr_14=context.get('atr_14', 10),
        or_range=100 # Mock OR Range if needed, or fetch from context if available
    )
    
    # RUN ELIGIBILITY
    # Need OR Data for ORE style
    or_data = {} # Simplified
    
    eligible = calculate_style_eligibility(
        current_time_str=time_str,
        micro_context=micro,
        morning_plan=morning_plan,
        or_data=or_data,
        current_price=current_price,
        expected_move={}
    )
    
    # Check if ANY style is true
    any_true = any(eligible.values())
    if any_true:
        print(f"[{time_str}] ✅ ELIGIBLE: {[k for k,v in eligible.items() if v]}")
    else:
        # If blocked, print WHY specific styles failed? 
        # The function returns boolean dict. We can't see 'reason' unless we modify function or infer.
        # But we can look at micro_context to guess.
        if current_dt.minute == 0: # Print hourly sample only to reduce spam
             print(f"[{time_str}] ❌ ALL BLOCKED. Micro: {micro.get('price_behavior')} | Vol: {micro.get('volume_behavior')} | Bias: {micro.get('micro_bias')}")

    current_dt += timedelta(minutes=15)

conn.close()
