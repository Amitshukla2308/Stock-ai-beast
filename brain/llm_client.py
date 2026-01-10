import os
import json
import time
from openai import OpenAI
from dotenv import load_dotenv
from brain.prompts import (
    SYSTEM_PROMPT_MORNING, USER_PROMPT_MORNING,
    SYSTEM_PROMPT_TACTICAL, USER_PROMPT_TACTICAL,
    SYSTEM_PROMPT_EOD, USER_PROMPT_EOD
)

load_dotenv()

class LLMClient:
    def __init__(self):
        # --- BRAIN CONFIG (Strategic / Qwen 14B) ---
        self.brain_api_base = os.getenv("BRAIN_API_BASE", "http://localhost:8000/v1")
        self.brain_api_key = os.getenv("BRAIN_API_KEY", "EMPTY")
        self.brain_model = os.getenv("BRAIN_MODEL_NAME", "Qwen/Qwen2.5-14B-Instruct-Q8")
        
        # --- WORKER CONFIG (Tactical / Qwen 1.5B) ---
        self.worker_api_base = os.getenv("WORKER_API_BASE", "http://localhost:8001/v1")
        self.worker_api_key = os.getenv("WORKER_API_KEY", "EMPTY")
        self.worker_model = os.getenv("WORKER_MODEL_NAME", "Qwen/Qwen2.5-1.5B-Instruct")

        # Initialize Clients
        print(f"🧠 Brain Connecting to: {self.brain_model} at {self.brain_api_base}")
        self.brain_client = OpenAI(base_url=self.brain_api_base, api_key=self.brain_api_key, timeout=90.0)
        
        print(f"👷 Worker Connecting to: {self.worker_model} at {self.worker_api_base}")
        self.worker_client = OpenAI(base_url=self.worker_api_base, api_key=self.worker_api_key, timeout=10.0)

    def _query_model(self, system_msg, user_msg, use_worker=False):
        """Generic wrapper with routing logic"""
        start = time.time()
        
        if use_worker:
            client = self.worker_client
            model = self.worker_model
            role_icon = "👷"
            role_name = "WORKER"
        else:
            client = self.brain_client
            model = self.brain_model
            role_icon = "🧠"
            role_name = "BRAIN"

        try:
            # Log System Prompt for visibility
            print(f"\n--- {role_icon} {role_name} SYSTEM ---\n{system_msg}\n---")
            
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg}
                ],
                temperature=0.1, # Forced deterministic
                top_p=0.9,
                max_tokens=1500 if not use_worker else 400 
            )
            content = response.choices[0].message.content
            # Strip <think> tags
            import re
            content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL)
            
            # Strip markdown code blocks if present
            content = content.replace("```json", "").replace("```", "").strip()
            
            # Extract JSON object using regex (handles trailing text after JSON)
            json_match = re.search(r'\{.*\}', content, flags=re.DOTALL)
            if json_match:
                content = json_match.group(0)
            else:
                # If no full match, try to find the first '{' and use everything from there
                # This helps if the closing '}' is missing (truncated)
                first_brace = content.find('{')
                if first_brace != -1:
                    content = content[first_brace:]
            
            # Fix common LLM JSON mistakes
            content = content.replace('}},', '},')  # Fix double braces
            content = content.replace('"},{', '"},{"')  # Fix missing quotes
            content = content.replace('},"', '}",')  # Fix misplaced quotes
            
            # Specialized "Beast" Hallucination Fixes based on session crashes:
            # 1. Missing array key: "confirmed"},{""trade" -> "confirmed"},"what_went_well":[{"trade"
            content = re.sub(r'}\s*,\s*{\s*""trade"', '},"what_went_well":[{"trade"', content)
            
            # 2. Extra quote after closing brace: "follow-through"}",what_went_wrong -> "follow-through"},"what_went_wrong
            content = re.sub(r'}"\s*,', '},', content)
            
            # 3. Double-double quotes: ""trade"" -> "trade"
            content = content.replace('""', '"')

            # 4. Missing array brackets: Inject closing bracket if another key follows and bracket is unclosed
            if '"what_went_well": [' in content and '],"what_went_wrong"' not in content:
                 content = content.replace(',"what_went_wrong"', '],"what_went_wrong"')
            if '"what_went_wrong": [' in content and '],"root_cause' not in content:
                 content = content.replace(',"root_cause', '],"root_cause')
            
            content = re.sub(r',\s*}', '}', content)  # Remove trailing commas
            content = re.sub(r',\s*]', ']', content)  # Remove trailing commas in arrays
            
            # Monitoring Log
            lat = (time.time() - start)
            print(f"\n--- {role_icon} {role_name} OUTPUT ({lat:.2f}s) ---\n{content[:500]}...\n-----------------------")
            
            # Try to parse JSON with error recovery
            try:
                data = json.loads(content)
            except json.JSONDecodeError as e:
                # If we are already in a retry (Validation/Fix mode), don't recurse infinitely
                if "FIX THE FOLLOWING MALFORMED JSON" in user_msg or "RETRY WARNING" in user_msg:
                    return None

                # Try to find the position and truncate
                print(f"      ⚠️ JSON parse error at position {e.pos}, attempting recovery...")
                
                # RECOVERY STRATEGY:
                # 1. Try to find the last '}' and hope for valid JSON before it
                last_brace_idx = content.rfind('}')
                if last_brace_idx != -1:
                    try:
                        potential = content[:last_brace_idx+1]
                        data = json.loads(potential)
                        print(f"      ✅ JSON recovery successful (found last brace)")
                        return data
                    except:
                        pass

                # 2. Heuristic Truncation: 
                # If it's a truncation error, try closing open structures
                truncated = content[:e.pos]
                
                # Close any unclosed quotes
                if truncated.count('"') % 2 != 0:
                    truncated += '"'
                    
                # Count braces to balance
                open_braces = truncated.count('{') - truncated.count('}')
                if open_braces > 0:
                    truncated += '}' * open_braces
                
                try:
                    data = json.loads(truncated)
                    print(f"      ✅ JSON recovery successful (heuristic truncation)")
                except:
                    print(f"      ❌ JSON recovery failed, returning None")
                    return None
            
            return data
        except Exception as e:
            print(f"❌ {role_icon} {role_name} FAILURE: {e}")
            return None

    def get_morning_brief(self, context_data, current_tick=None, symbol="BANKNIFTY"):
        """
        Generate the Morning Brief (STRATEGIC -> BRAIN)
        """
        market_data = {
            "daily_3": context_data.get('daily_3', []),
            "last_15min": context_data.get('last_15min', []),
            "today_5min": context_data.get('today_5min', [])
        }
        market_data_str = json.dumps(market_data, default=str)
        vix_value = context_data.get('vix_spot', 'N/A')
        prev_close = current_tick.get('prev_close') if current_tick else None
        today_open = current_tick.get('open') if current_tick else None
        
        # Gap = Today's Open - Previous Close
        gap_points = round(today_open - prev_close, 2) if (prev_close and today_open) else 0.0
        if gap_points == 0.0 and (not prev_close or not today_open): 
            prev_close = "N/A"
            gap_points = 0.0
        
        # Calculate gap direction and percentage
        gap_direction = "UP" if gap_points >= 0 else "DOWN"
        gap_pct = round((gap_points / prev_close) * 100, 2) if prev_close and prev_close != "N/A" else 0.0
        
        # Classify gap type
        abs_pct = abs(gap_pct)
        if abs_pct < 1.5:
            gap_type = "NORMAL"
        elif abs_pct < 3.0:
            gap_type = "SIGNIFICANT"
        else:
            gap_type = "EXTREME"
        
        # Calculate industry-standard pivot points BEFORE LLM call
        # Classic Pivot: P = (H + L + C) / 3, S1 = 2*P - H, R1 = 2*P - L
        daily_data = context_data.get('daily_3', [])
        pivot, support, resistance = 0, 0, 0
        if daily_data and len(daily_data) >= 1:
            prev_day = daily_data[-1]
            h = float(prev_day.get('h', prev_day.get('high', 0)))
            l = float(prev_day.get('l', prev_day.get('low', 0)))
            c = float(prev_day.get('c', prev_day.get('close', 0)))
            if h and l and c:
                pivot = round((h + l + c) / 3, 1)
                support = round(2 * pivot - h, 1)
                resistance = round(2 * pivot - l, 1)
        
        prompt = USER_PROMPT_MORNING.format(
            symbol=symbol,
            market_data=market_data_str,
            vix_value=vix_value,
            gap_direction=gap_direction,
            gap_pts=gap_points,
            gap_pct=gap_pct,
            gap_type=gap_type,
            prev_close=prev_close,
            support=support,
            pivot=pivot,
            resistance=resistance
        )
        
        print(f"\n--- 🧠 BRAIN INPUT (MORNING) ---\n{prompt}\n--------------------------------")
        
        # ROUTING: BRAIN with purpose-specific system prompt
        data = self._query_model(SYSTEM_PROMPT_MORNING, prompt, use_worker=False)
        
        if data:
            # Inject pre-calculated levels into response (script-calculated, not LLM)
            if 'boundary_levels' not in data:
                data['boundary_levels'] = {}
            data['boundary_levels']['pivot_point'] = pivot
            data['boundary_levels']['support_zone'] = support
            data['boundary_levels']['resistance_zone'] = resistance
            print(f"      📐 Pivot Levels: S={support:.1f} | P={pivot:.1f} | R={resistance:.1f}")
            
            personality = data.get('market_personality', 'N/A')
            vix_regime = data.get('vix_regime', 'N/A')
            bias = data.get('primary_bias', 'N/A')
            print(f"      🌅 {personality} | VIX:{vix_regime} | Bias:{bias}")
            
        return data

    def get_tactical_update(self, tick, context, plan, current_pnl, open_position, day_pnl=0.0, symbol="BANKNIFTY"):
        """
        Generate Tactical Update (TACTICAL -> WORKER)
        """
        # Safe OHLC access with fallbacks
        close = tick.get('close', tick.get('c', 0))
        
        # VIX handling
        vix = context.get('vix_spot', context.get('vix', 'N/A'))
        # Calculate VIX change percentage (if available in context)
        vix_pct = 0.0  # Default, ideally compare with yesterday's VIX
        
        # ATR
        atr = context.get('atr_14', 'N/A')
        
        # Morning Brief Data
        personality = plan.get('market_personality', 'UNKNOWN') if plan else 'UNKNOWN'
        bias = plan.get('primary_bias', 'NEUTRAL') if plan else 'NEUTRAL'
        
        # Boundary Levels
        boundaries = plan.get('boundary_levels', {}) if plan else {}
        support = boundaries.get('support_zone', 'N/A')
        resistance = boundaries.get('resistance_zone', 'N/A')
        pivot = boundaries.get('pivot_point', 'N/A')
        vix_regime_morning = plan.get('vix_regime', 'NORMAL') if plan else 'NORMAL'
        
        # Last 14 15-min bars (for pattern recognition)
        last_15min = context.get('last_15min', [])
        recent_15min = last_15min[-14:] if len(last_15min) >= 14 else last_15min
        
        # Format bars as compact OHLC list
        bars_lines = []
        for i, bar in enumerate(recent_15min):
            bars_lines.append(f"  {i+1}. O={bar['o']:.1f} H={bar['h']:.1f} L={bar['l']:.1f} C={bar['c']:.1f}")
        bars_data = "\n".join(bars_lines) if bars_lines else "No data"
        
        # Last 2 5-min closes
        today_5min = context.get('today_5min', [])
        recent_5min = today_5min[-2:] if today_5min else []
        last_2_5min_closes = ",".join([f"{bar['c']:.1f}" for bar in recent_5min]) if recent_5min else "N/A"
        
        # Range
        range_val = context.get('current_range', 'N/A')
        
        # Position Context + Unrealized PnL
        unrealized_pnl = 0.0
        if open_position:
            side = open_position['side']
            entry = open_position.get('entry_price', 'N/A')
            sl = open_position.get('sl', 'N/A')
            target = open_position.get('target', 'N/A')
            unrealized_pnl = current_pnl
            position_context = f"OPEN: {side} @ {entry} | SL={sl} | TGT={target} | PnL={current_pnl:+.1f}pts"
        else:
            position_context = "FLAT (No Position)"
        
        # Time Extraction
        ts = tick.get('ts', tick.get('timestamp'))
        current_time = "N/A"
        if ts:
            if hasattr(ts, 'strftime'):
                current_time = ts.strftime('%H:%M')
            else:
                # Fallback for string timestamps
                try:
                    # Check format. If '2024-01-01 09:15:00', slicing works.
                    current_time = str(ts)[11:16]
                except:
                    current_time = "N/A"

        # Helper to safely format floats
        def fmt(val, decimals=1):
            try:
                return f"{float(val):.{decimals}f}"
            except:
                return str(val)

        # Calculate REAL-TIME VIX regime (not stale morning value)
        try:
            vix_float = float(vix)
            if vix_float < 13:
                vix_regime_current = "COMPLACENT"
            elif vix_float <= 18:
                vix_regime_current = "NORMAL"
            else:
                vix_regime_current = "PANIC"
        except:
            vix_regime_current = "UNKNOWN"

        # TODO: consecutive_sl should be passed from executor - placeholder for now
        consecutive_sl = 0

        prompt = USER_PROMPT_TACTICAL.format(
            close=fmt(close, 1),
            vix=fmt(vix, 1),
            atr=fmt(atr, 1),
            day_pnl=f"{day_pnl:.1f}",
            time=current_time,
            personality=personality,
            bias=bias,
            support=fmt(support, 1),
            pivot=fmt(pivot, 1),
            resistance=fmt(resistance, 1),
            bars_data=bars_data,
            last_2_5min_closes=last_2_5min_closes,
            range=fmt(range_val, 1),
            position_context=position_context,
            consecutive_sl=consecutive_sl,
            unrealized_pnl=f"{unrealized_pnl:.1f}"
        )
        
        print(f"\n--- 👷 WORKER INPUT (TACTICAL) ---\n{prompt}\n--------------------------------")
        
        # ROUTING: WORKER with purpose-specific system prompt
        data = self._query_model(SYSTEM_PROMPT_TACTICAL, prompt, use_worker=True)
        
        if data:
            # Output Normalization & Calculation
            action = data.get('decision', data.get('action', 'HOLD'))
            data['action'] = action
            
            # Entry Price
            close_price = close # From local var
            if isinstance(close_price, str): close_price = 0.0
            
            entry = float(data.get('entry') or 0)
            if entry == 0: entry = float(close_price)
            data['entry'] = entry

            # SL/Target Calculation (Points -> Price)
            # Support both 'sl_points' (new) and 'sl' (legacy/hallucination) keys
            sl_raw = float(data.get('sl_points', data.get('sl', 0)) or 0)
            tgt_raw = float(data.get('target_points', data.get('target', 0)) or 0)
            
            # Heuristic: If value > 1000, model likely outputted PRICE instead of POINTS.
            # Convert to points (distance)
            sl_points = sl_raw
            if sl_raw > 1000:
                 sl_points = abs(entry - sl_raw)
                 # print(f"⚠️ CALC: Converted SL Price {sl_raw} -> Dist {sl_points}")
            
            tgt_points = tgt_raw
            if tgt_raw > 1000:
                 tgt_points = abs(entry - tgt_raw)

            # Apply Geometry based on Action
            sl_price = 0.0
            tgt_price = 0.0
            
            if 'BUY_CALL' in action:
                sl_price = entry - sl_points if sl_points > 0 else 0
                tgt_price = entry + tgt_points if tgt_points > 0 else 0
            elif 'BUY_PUT' in action:
                sl_price = entry + sl_points if sl_points > 0 else 0
                tgt_price = entry - tgt_points if tgt_points > 0 else 0
            
            # Store Final Prices
            data['sl'] = round(sl_price, 2)
            data['target'] = round(tgt_price, 2)
            data['confidence'] = data.get('confidence')
            
            reason = data.get('reason', data.get('adjustment_reason', ''))
            data['technical_reason'] = reason
            
            # Log
            reason_short = reason[:40] + '...' if len(reason) > 40 else reason
            print(f"      🔸 {action} | Entry:{entry:.1f} | SL:{data['sl']} (-{sl_points:.1f}) | TGT:{data['target']} (+{tgt_points:.1f}) | {reason_short}")
            
        return data

    def get_eod_journal(self, trades, morning_plan, session_id, eod_data, symbol="BANKNIFTY"):
        """
        Generate EOD Audit (AUDIT -> BRAIN)
        """
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
        
        prompt = USER_PROMPT_EOD.format(
            symbol=symbol,
            morning_plan=morning_plan_str,
            execution_logs=execution_logs_str,
            eod_chart=eod_chart_str,
            session_id=session_id,
            total_pnl=f"{total_pnl:.2f}"
        )
        
        print(f"\n--- 🧠 BRAIN INPUT (EOD) ---\n{prompt}\n--------------------------------")
        
        # ROUTING: BRAIN with purpose-specific system prompt
        data = self._query_model(SYSTEM_PROMPT_EOD, prompt, use_worker=False)
        
        # OPTION 3: VALIDATION & SELF-CORRECTION STEP
        if not data:
            print("      🔄 Attempting SELF-CORRECTION for EOD Audit...")
            # Get the raw response if possible (we need to bypass slightly to get bad content)
            # Since we can't easily get raw from _query_model if it failed, we'll trigger a 'Clean-up' call
            # using a more aggressive 'Fixer' instructions
            data = self._query_model(SYSTEM_PROMPT_EOD + "\n\nCRITICAL: You must output ONLY valid JSON. Double-check all brackets and quotes.", prompt + "\n\nRETRY WARNING: The last output was malformed. Fix it now.", use_worker=False)

        if not data:
            return {
                "audit_summary": f"PnL:{total_pnl:.1f} | Audit Failed after Retry",
                "nugget_good": "N/A",
                "nugget_bad": "N/A",
                "bias_efficiency": 0
            }
            
        nugget = data.get('dataset_nugget', data.get('nugget_good', 'N/A'))
        audit_summary = f"PnL:{total_pnl:.1f} | {data.get('bias_efficiency', 'N/A')} | Nugget:{nugget}"
        print(f"      📊 EOD: {audit_summary}")
        
        # Inject summary into data for the caller
        data['audit_summary'] = audit_summary
        return data
