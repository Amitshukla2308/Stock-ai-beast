import os

def update_prompts():
    path = os.path.join("brain", "prompts.py")
    content = """# brain/prompts.py

SYSTEM_PROMPT = \"\"\"You are 'Beast', NSE algo-trader. Goal: max PnL, min drawdown. Data-driven. Output: ONLY valid JSON.\"\"\"

MORNING_BRIEF_PROMPT = \"\"\"
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
\"\"\"

TACTICAL_UPDATE_PROMPT = \"\"\"
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
\"\"\"

EOD_JOURNAL_PROMPT = \"\"\"
# Post-Trade Auditor v2.0
DATA: Plan:{morning_plan}|Logs:{execution_logs}|Chart:{eod_chart}|Symbol:{symbol}

AUDIT TASKS:
1. Analyze WINNING trades: What market condition + decision led to profit?
2. Analyze LOSING trades: What market condition + decision led to loss?
3. Did bias alignment help or hurt?
4. Were SL/Target sizes appropriate?

OUTPUT:
{{"date":"{session_id}","pnl_final":{total_pnl},"bias_efficiency":<0-1>,
"what_went_well":[{{"trade":"<CALL/PUT at time>","market_condition":"<trend/range/breakout>","decision":"<entry timing/exit timing>","lesson":"<reusable insight>"}}],
"what_went_wrong":[{{"trade":"<CALL/PUT at time>","market_condition":"<condition>","mistake":"<wrong bias/early entry/late exit/wide SL>","lesson":"<avoid this pattern>"}}],
"root_cause_of_losses":"SL_HUNT|WRONG_BIAS|LATE_EXIT|NONE",
"optimal_strategy_retro":"<strategy that would have maximized PnL>",
"nugget_good":"In [condition], do [action] - it works",
"nugget_bad":"In [condition], avoid [action] - it fails"}}

\"\"\"
"""
    with open(path, "w") as f:
        f.write(content)
    print(f"Updated {path}")

def update_llm_client():
    path = os.path.join("brain", "llm_client.py")
    content = """import os
import json
import time
from openai import OpenAI
from dotenv import load_dotenv
from brain.prompts import SYSTEM_PROMPT, MORNING_BRIEF_PROMPT, TACTICAL_UPDATE_PROMPT, EOD_JOURNAL_PROMPT

load_dotenv()

class LLMClient:
    def __init__(self):
        self.api_base = os.getenv("VLLM_API_BASE", "http://localhost:8000/v1")
        self.api_key = os.getenv("VLLM_API_KEY", "EMPTY")
        self.model = os.getenv("MODEL_NAME", "Qwen/Qwen2.5-32B-Instruct-AWQ")
        
        # Initialize Client
        self.client = OpenAI(base_url=self.api_base, api_key=self.api_key, timeout=60.0)
        print(f"🧠 Brain Connected: {self.model} at {self.api_base}")

    def _query_brain(self, system_msg, user_msg):
        \"\"\"Generic wrapper for LLM call with JSON enforcement\"\"\"
        start = time.time()
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg}
                ],
                temperature=0.1, # Forced deterministic
                top_p=0.9,
                max_tokens=600
            )
            content = response.choices[0].message.content
            content = content.replace("```json", "").replace("```", "").strip()
            
            data = json.loads(content)
            # Full output for monitoring
            print(f"\\n--- 🧠 BRAIN OUTPUT ---\\n{content}\\n-----------------------")
            lat = (time.time() - start)
            print(f"      ⚡ Brain Latency: {lat:.1f}s")
            return data
        except Exception as e:
            print(f"❌ Brain Freeze: {e}")
            return None

    def get_morning_brief(self, context_data, current_tick=None, symbol="BANKNIFTY"):
        \"\"\"
        Generate the Morning Brief with the v5.3 Gap-aware schema.
        \"\"\"
        market_data = {
            "daily_3": context_data.get('daily_3', []),
            "last_15min": context_data.get('last_15min', []),
            "today_5min": context_data.get('today_5min', [])
        }
        market_data_str = json.dumps(market_data, default=str)
        vix_value = context_data.get('vix_spot', 'N/A')
        prev_close = current_tick.get('prev_close') if current_tick else None
        current_price = current_tick['close'] if current_tick else None
        
        # Extract gap info from context (set by backtest.py)
        gap_info = context_data.get('gap_info', {})
        gap_direction = gap_info.get('direction', 'N/A')
        gap_pts = gap_info.get('pts', 0)
        gap_pct = gap_info.get('pct', 0)
        gap_type = gap_info.get('type', 'NORMAL')
        
        # Fallback gap calculation if no gap_info
        if not gap_info and prev_close and current_price:
            gap_pts = round(current_price - prev_close, 2)
            gap_pct = (gap_pts / prev_close) * 100 if prev_close else 0
            gap_direction = 'UP' if gap_pts > 0 else 'DOWN'
            if abs(gap_pct) >= 3.0:
                gap_type = 'EXTREME'
            elif abs(gap_pct) >= 1.5:
                gap_type = 'SIGNIFICANT'
            else:
                gap_type = 'NORMAL'
        
        prompt = MORNING_BRIEF_PROMPT.format(
            symbol=symbol,
            market_data=market_data_str,
            vix_value=vix_value,
            gap_direction=gap_direction,
            gap_pts=f"{abs(gap_pts):.0f}" if isinstance(gap_pts, (int, float)) else gap_pts,
            gap_pct=f"{abs(gap_pct):.1f}" if isinstance(gap_pct, (int, float)) else gap_pct,
            gap_type=gap_type,
            prev_close=prev_close if prev_close else "N/A"
        )
        
        print(f"\\n--- 🧠 BRAIN INPUT (MORNING) ---\\n{prompt}\\n--------------------------------")
        data = self._query_brain(SYSTEM_PROMPT, prompt)
        
        if data:
            personality = data.get('market_personality', 'N/A')
            vix_regime = data.get('vix_regime', 'N/A')
            bias = data.get('primary_bias', 'N/A')
            print(f"      🌅 {personality} | VIX:{vix_regime} | Bias:{bias}")
            
        return data

    def get_tactical_update(self, tick, context, plan, current_pnl, open_position, day_pnl=0.0, symbol="BANKNIFTY"):
        \"\"\"
        Generate Tactical Update with the v4.0 Backtested schema.
        \"\"\"
        vix_value = context.get('vix_spot', 'N/A')
        vix_pct = context.get('vix_pct', 0.0)
        atr_val = context.get('atr_14', 'N/A')
        vol_ratio = context.get('vol_ratio', 100.0)
        
        # Position Details
        active_pos_details = "FLAT" if not open_position else f"{open_position['side']} @ {open_position.get('entry_price', 'N/A')}"
        
        # Position Context for LLM (when position is open)
        if open_position:
            entry_price = open_position.get('entry_price', 0)
            current_close = tick['close']
            side = open_position['side']
            
            # Calculate unrealized PnL
            if side == 'CALL':
                unrealized_pnl = current_close - entry_price
            else:
                unrealized_pnl = entry_price - current_close
            # Handle None values for display
            sl_val = open_position.get('sl')
            target_val = open_position.get('target')
            peak_val = open_position.get('peak_price') or entry_price
            
            sl_str = f"{sl_val:.1f}" if sl_val else "N/A"
            target_str = f"{target_val:.1f}" if target_val else "N/A"
            
            position_context = f\"\"\"OPEN {side} POSITION:
- Entry: {entry_price:.1f} | Current: {current_close:.1f}
- SL: {sl_str} | Target: {target_str}
- Peak: {peak_val:.1f}
- Unrealized P&L: {unrealized_pnl:+.1f} pts
- ACTION OPTIONS: HOLD | ADJUST_SL | ADJUST_TARGET | EXIT_NOW\"\"\"
        else:
            position_context = "NO POSITION - Looking for entry signals"
        
        # Format 15-min Candles (Last 3)
        today_15min = context.get('today_15min', [])
        recent_15min = today_15min[-3:] if today_15min else []
        bars_ohlc = ["No data", "No data", "No data"]
        for i, bar in enumerate(recent_15min):
            bars_ohlc[i] = f"  {bar['ts']}: O={bar['o']:.1f} H={bar['h']:.1f} L={bar['l']:.1f} C={bar['c']:.1f}"
        
        # Boundaries
        boundaries = plan.get('boundary_levels', {}) if plan else {}
        support = boundaries.get('support_zone', 'N/A')
        resistance = boundaries.get('resistance_zone', 'N/A')
        pivot = boundaries.get('pivot_point', 'N/A')

        # Get last 2 5min closes for breakout confirmation
        last_2_closes = context.get('last_2_5min_closes', [])
        last_2_closes_str = f"[{last_2_closes[0]:.2f}, {last_2_closes[1]:.2f}]" if len(last_2_closes) >= 2 else "N/A"

        prompt = TACTICAL_UPDATE_PROMPT.format(
            symbol=symbol,
            close=tick['close'],
            vix=vix_value,
            vix_pct=f"{vix_pct:+.2f}",
            atr=atr_val,
            day_pnl=f"{day_pnl:.1f}",
            personality=plan.get('market_personality', 'UNKNOWN') if plan else 'UNKNOWN',
            bias=plan.get('primary_bias', 'NEUTRAL') if plan else 'NEUTRAL',
            support=support,
            pivot=pivot,
            resistance=resistance,
            vix_regime_morning=plan.get('vix_regime', 'NORMAL') if plan else 'NORMAL',
            bar1_ohlc=bars_ohlc[0],
            bar2_ohlc=bars_ohlc[1],
            bar3_ohlc=bars_ohlc[2],
            last_2_5min_closes=last_2_closes_str,
            vol_ratio=vol_ratio,
            range=context.get('current_range', 'N/A'),
            position_context=position_context
        )
        
        print(f"\\n--- 🧠 BRAIN INPUT (TACTICAL v4.0) ---\\n{prompt}\\n--------------------------------")
        data = self._query_brain(SYSTEM_PROMPT, prompt)
        
        if data:
            # PHASE 4: Alignment with Executor
            data['action'] = data.get('action', 'HOLD')
            data['entry_price'] = data.get('entry')
            data['sl'] = data.get('sl')
            data['target'] = data.get('target')
            data['confidence'] = data.get('confidence', 0.5) # Default to 0.5 if missing
            data['technical_reason'] = data.get('reason', data.get('adjustment_reason', ''))
            
            # Context for Executor logic
            data['atr'] = atr_val
            data['vix'] = vix_value
            data['morning_bias'] = plan.get('primary_bias', 'NEUTRAL') if plan else 'NEUTRAL'
            data['max_hold_minutes'] = data.get('max_hold_minutes', 30)

            action = data['action']
            reason = data['technical_reason']
            reason_short = reason[:50] + '...' if len(reason) > 50 else reason
            print(f"      🔸 {action} | {reason_short}")
            
        return data

    def get_eod_journal(self, trades, morning_plan, session_id, eod_data, symbol="BANKNIFTY"):
        \"\"\"
        Generate EOD Audit with the new schema.
        \"\"\"
        total_pnl = sum([t.get('pnl', 0) for t in trades if t.get('pnl') is not None])
        morning_plan_str = json.dumps(morning_plan, default=str)
        
        compact_logs = []
        for t in trades:
            if t.get('pnl') is not None:
                entry_time = str(t.get('entry_time', ''))[-14:-9]
                exit_time = str(t.get('exit_time', ''))[-14:-9]
                reason_map = {'SL Hit': 'SL', 'Target Hit': 'TGT', 'AI Logic Exit': 'AI', 'EOD Square-off': 'EOD'}
                reason = reason_map.get(t.get('reason', ''), t.get('reason', ''))[:3]
                pnl = t.get('pnl', 0)
                pnl_str = f"+{pnl:.1f}" if pnl >= 0 else f"{pnl:.1f}"
                compact_logs.append(f"{t['side']} {t['entry_price']:.1f}@{entry_time}→{t['exit_price']:.1f}@{exit_time} {reason} {pnl_str}")
        
        execution_logs_str = " | ".join(compact_logs) if compact_logs else "No trades"
        eod_chart_str = json.dumps(eod_data, default=str)
        
        prompt = EOD_JOURNAL_PROMPT.format(
            symbol=symbol,
            morning_plan=morning_plan_str,
            execution_logs=execution_logs_str,
            eod_chart=eod_chart_str,
            session_id=session_id,
            total_pnl=f"{total_pnl:.2f}"
        )
        
        print(f"\\n--- 🧠 BRAIN INPUT (EOD) ---\\n{prompt}\\n--------------------------------")
        data = self._query_brain(SYSTEM_PROMPT, prompt)
        if not data:
            return "Could not generate audit."
            
        nugget_good = data.get('nugget_good', 'N/A')
        nugget_bad = data.get('nugget_bad', 'N/A')
        audit_summary = f"PnL:{total_pnl:.1f} | Eff:{data.get('bias_efficiency', 'N/A')} | ✓:{nugget_good} | ✗:{nugget_bad}"
        print(f"      📊 EOD: {audit_summary}")
        
        return audit_summary
"""


    with open(path, "w") as f:
        f.write(content)
    print(f"Updated {path}")

def update_prompt_manager():
    path = os.path.join("brain", "prompt_manager.py")
    content = """def construct_prompt(technical_state, news_summary=""):
    \"\"\"
    Legacy prompt generator used by main_cxo.py.
    Updated to align with the new institutional-grade logic.
    \"\"\"
    atr = technical_state.get('atr', 'N/A')
    
    prompt = f\"\"\"
# Role: Intraday Scalper (The Beast)
Your goal: Maximize PnL by generating precise entry/exit signals.

# Current Market State
- Price: {technical_state.get('current_price', 'N/A')}
- Trend: {technical_state.get('trend', 'UNKNOWN')}
- RSI: {technical_state.get('rsi', 50):.2f}
- ATR: {atr}
- Volatility: {technical_state.get('volatility', 0):.2f}%

# Macro Context
{news_summary if news_summary else "No major news updates."}

# Logic Guards
1. BUY_CALL is INVALID if SL > (Entry - (0.5 * {atr if atr != 'N/A' else 50})).
2. STALL FILTER: If Action is HOLD for 3 consecutive intervals, force Action: EXIT if PnL is flat.

# Output (JSON Only)
{{
    "action": "BUY_CALL" | "BUY_PUT" | "EXIT" | "HOLD",
    "entry": <float>,
    "sl": <float>,
    "target": <float>,
    "confidence": <0.0-1.0>,
    "reasoning": "Short technical justification."
}}
\"\"\"
    return prompt
"""
    with open(path, "w") as f:
        f.write(content)
    print(f"Updated {path}")

if __name__ == "__main__":
    update_prompts()
    update_llm_client()
    update_prompt_manager()
