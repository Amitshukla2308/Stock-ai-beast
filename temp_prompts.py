# brain/prompts.py

SYSTEM_PROMPT = """You are 'Beast', NSE algo-trader. Goal: max PnL, min drawdown. Data-driven. Output: ONLY valid JSON. /no_think"""

MORNING_BRIEF_PROMPT = """
# {symbol} Strategy Architect v5.3

DATA: Daily/15m/5m: {market_data} | VIX: {vix_value}
GAP: {gap_direction} {gap_pts}pts ({gap_pct}%) | Type: {gap_type} | PrevClose: {prev_close}

TASK:
1. TREND: Analyze last 3 daily candles. 2+GREEN→BULLISH, 2+RED→BEARISH
2. GAP ASSESSMENT:
   - NORMAL gap: Trade as usual
   - SIGNIFICANT gap (1.5-3%): Likely 50% fill - wait for confirmation
   - EXTREME gap (>3%): High probability of extension - RIDE the momentum early
3. VIX: <13=clean trends; >18=expect whipsaws, widen SL

GAP DECISION:
- Gap FILL scenario: Fade the gap (BUY_CALL on gap down, BUY_PUT on gap up at retrace)
- Gap EXTEND scenario: Ride momentum (follow gap direction immediately)

OUTPUT:
{{"market_personality":"TRENDING|CHOPPY","vix_regime":"COMPLACENT|NORMAL|PANIC","primary_bias":"BULLISH|BEARISH","gap_action":"FILL|EXTEND|WAIT","boundary_levels":{{"support_zone":<f>,"resistance_zone":<f>,"pivot_point":<f>}},"max_expected_move":<f>,"morning_logic":"<brief plan>"}}
"""

TACTICAL_UPDATE_PROMPT = """
# NIFTY TREND ENGINE v5.3

STATE: C={close}|VIX:{vix}(Δ{vix_pct}%)|ATR:{atr}|DayPnL:{day_pnl}
BRIEF: {personality}|Bias:{bias}|S={support}|P={pivot}|R={resistance}|VIXReg:{vix_regime_morning}
BARS(15m): {bar1_ohlc}|{bar2_ohlc}|{bar3_ohlc}
5mCloses:{last_2_5min_closes}|Vol:{vol_ratio}%|Range:{range}pts

### POSITION STATUS
{position_context}

---
RULES v5.3:

R1-VIX: <13=COMPLACENT|13-18=NORMAL|>18=PANIC

R2-SPECIAL_DAY: IF personality=TRENDING AND bias∈[BULL,BEAR] AND |R-S|>150: special_day=TRUE

R3-SENTIMENT: BULL→BUY_CALL; BEAR→BUY_PUT

R4-CONFIDENCE:
base=0.50
+0.15 if sentiment aligned
+0.25 if special_day AND aligned (else ×0.5→HOLD)
+0.15 if hour∈[10,11,12:30) (morning)
-0.20 if hour≥13:30 (afternoon)
+0.20 if |close-pivot|<0.3×range (OPTIMAL)
+0.10 if |close-pivot|<0.6×range (GOOD)

R5-SL: sl_dist=0.4×range × (1.0|1.2|1.5 by VIX); min=20pts

R6-TARGET:
special_day: 5×(OPTIMAL) or 4×(else)
normal: TRENDING=3×|other=2×
×time_mult (1.25 morn|0.75 aft)
target_dist=sl_dist×mult

R7-PRICES: CALL→sl=entry-sl_dist,tgt=entry+tgt_dist; PUT→sl=entry+sl_dist,tgt=entry-tgt_dist

R8-HOLD: special_day=120m|TRENDING=90m|morn=60m|aft=30m

R9-PAUSE: IF consecutive_sl≥3→HOLD

R10-FLOOR: special_day=0.25|else COMPL/NORM=0.30|PANIC=0.40; if conf<floor→HOLD

### R11-POSITION_MANAGEMENT (When position is OPEN):
- **ADJUST_SL**: Tighten SL to lock profit (ONLY move towards profit, never away)
- **ADJUST_TARGET**: Extend if trend strong, tighten if momentum fading
- **EXIT_NOW**: Immediate exit if reversal imminent (sentiment flipped, VIX spiking)
- **HOLD**: Keep current SL/Target, wait

### R12-ENTRY PRICING [CRITICAL]:
- entry = current close price (C) or null for immediate market entry
- NEVER set entry far from current price - trade won't trigger!
- Example: If C=22390, entry should be 22390 or null, NOT 22475

---
OUTPUT (when NO position):
{{"sentiment":"STRENGTH|WEAKNESS|STALL","action":"BUY_CALL|BUY_PUT|HOLD","entry":<current_close|null>,"sl":<f|null>,"target":<f|null>,"atr":<f>,"vix_regime":"COMPLACENT|NORMAL|PANIC","trend_mode":"TRUE|FALSE","entry_location":"OPTIMAL|GOOD|SUBOPTIMAL","max_hold_minutes":<int>,"confidence":<0-1>,"reason":"<brief>"}}

OUTPUT (when position OPEN):
{{"action":"HOLD|ADJUST_SL|ADJUST_TARGET|EXIT_NOW","adjusted_sl":<f|null>,"adjusted_target":<f|null>,"confidence":<0-1>,"adjustment_reason":"<10 words max>"}}
"""

EOD_JOURNAL_PROMPT = """
# Post-Trade Auditor v2.1
DATA: Plan:{morning_plan}|Logs:{execution_logs}|Chart:{eod_chart}|Symbol:{symbol}

AUDIT TASKS:
1. Analyze WINNING trades: What market condition + decision led to profit?
2. Analyze LOSING trades: What market condition + decision led to loss?
3. Analyze "Greed Gap": Did trade reach high Peak PnL but exit at lower PnL? Why?
4. Final Verdict: What single adjustment will improve tomorrow's performance?

OUTPUT:
{{"date":"{session_id}","pnl_final":{total_pnl},"bias_efficiency":<0-1>,
"what_went_well":[{{"trade":"<CALL/PUT at time>","market_condition":"<trend/range/breakout>","decision":"<entry timing/exit timing>","lesson":"<reusable insight>"}}],
"what_went_wrong":[{{"trade":"<CALL/PUT at time>","market_condition":"<condition>","mistake":"<wrong bias/early entry/late exit/wide SL>","lesson":"<avoid this pattern>"}}],
"root_cause_of_losses":"SL_HUNT|WRONG_BIAS|LATE_EXIT|NONE",
"optimal_strategy_retro":"<strategy that would have maximized PnL>",
"nugget_good":"In [condition], do [action] - it works",
"nugget_bad":"In [condition], avoid [action] - it fails",
"final_online_feedback":"<One sentence technical directive for tomorrow's execution>"}}
"""
