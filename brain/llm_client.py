import os
import json
import time
import logging
import math
from openai import OpenAI
from data.database import get_connection
from dotenv import load_dotenv
from brain.prompts import (
    SYSTEM_PROMPT_MORNING, USER_PROMPT_MORNING,
    SYSTEM_PROMPT_TACTICAL, USER_PROMPT_TACTICAL,
    SYSTEM_PROMPT_EOD, USER_PROMPT_EOD
)

load_dotenv()

# Initialize Logger
logger = logging.getLogger(__name__)

class LLMClient:
    def __init__(self):
        # --- BRAIN CONFIG (Strategic / Qwen 14B) ---
        self.brain_api_base = os.getenv("BRAIN_API_BASE", "http://localhost:8000/v1")
        self.brain_api_key = os.getenv("BRAIN_API_KEY", "EMPTY")
        self.brain_model = os.getenv("BRAIN_MODEL_NAME", "Qwen/Qwen2.5-14B-Instruct-Q8")
        
        # Initialize Client
        logger.debug(f"🧠 Brain Connecting to: {self.brain_model} at {self.brain_api_base}")
        self.brain_client = OpenAI(base_url=self.brain_api_base, api_key=self.brain_api_key, timeout=300.0)
        
        # Persistent State (latched until reversed)
        self.structural_break_state = None  # None, 'BULLISH', or 'BEARISH'
        self.structural_break_entry_done = False  # Track if we already entered on this break
        self.intraday_open = None  # Persistent baseline for the day

    def wait_for_model_ready(self):
        """Blocks until the model responds effectively (handles lazy loading)"""
        logger.debug(f"⏳ Verification: Waiting for {self.brain_model} to load...")
        max_retries = 20 # 20 * 5s = 100s (plus client timeout)
        
        for i in range(max_retries):
            try:
                # Simple ping
                self.brain_client.chat.completions.create(
                    model=self.brain_model,
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=1
                )
                logger.info("✅ Brain is ONLINE and READY.")
                return True
            except Exception as e:
                logger.info(f"   💤 Waking up Brain... ({i+1}/{max_retries}) - {str(e)[:50]}...")
                time.sleep(5)
        
        logger.error("❌ Brain Init Failed: Model did not load in time.")
        return False

    def _query_model(self, system_msg, user_msg):
        """Generic wrapper"""
        import traceback
        start = time.time()
        
        client = self.brain_client
        model = self.brain_model
        role_icon = "🧠"
        role_name = "BRAIN"

        try:
            # Log System Prompt for visibility
            logger.debug(f"\n--- {role_icon} {role_name} SYSTEM ---\n{system_msg}\n---")
            
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg}
                ],
                temperature=0.1, # Forced deterministic
                top_p=0.9,
                max_tokens=1500 
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
            # Log full content (up to 5000 chars) for debugging visibility
            logger.debug(f"\n--- {role_icon} {role_name} OUTPUT ({lat:.2f}s) ---\n{content[:5000]}\n-----------------------")
            
            # Try to parse JSON with error recovery
            logger.info(f"      [BRAIN] RAW RESPONSE: {content}")
            try:
                data = json.loads(content)
            except json.JSONDecodeError as e:
                # If we are already in a retry (Validation/Fix mode), don't recurse infinitely
                if "FIX THE FOLLOWING MALFORMED JSON" in user_msg or "RETRY WARNING" in user_msg:
                    return None

                # Try to find the position and truncate
                logger.warning(f"      ⚠️ JSON parse error at position {e.pos}, attempting recovery...")
                
                # RECOVERY STRATEGY:
                # 1. Try to find the last '}' and hope for valid JSON before it
                last_brace_idx = content.rfind('}')
                if last_brace_idx != -1:
                    try:
                        potential = content[:last_brace_idx+1]
                        data = json.loads(potential)
                        logger.info(f"      ✅ JSON recovery successful (found last brace)")
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
                    logger.info(f"      ✅ JSON recovery successful (heuristic truncation)")
                except:
                    # LAST RESORT: Regex extraction for critical keys
                    logger.warning(f"      ⚠️ JSON recovery failed, attempting regex extraction...")
                    data = {}
                    
                    # Extract notes/plan
                    logic_match = re.search(r'"(?:notes|morning_logic|market_logic)":\s*"([^"]*)"', content)
                    if logic_match: data['notes'] = logic_match.group(1)
                    
                    # Extract levels
                    for level in ['support', 'pivot', 'resistance']:
                        lvl_match = re.search(rf'"{level}":\s*([0-9.]+)', content)
                        if lvl_match:
                            if 'reference_levels' not in data: data['reference_levels'] = {}
                            data['reference_levels'][level] = float(lvl_match.group(1))
                    
                    if not data:
                        logger.error(f"      ❌ JSON recovery failed completely")
                        return None
            
            return data
        except Exception as e:
            traceback.print_exc()
            logger.error(f"❌ {role_icon} {role_name} FAILURE: {e}")
            return None

    def get_morning_brief(self, context_data, current_tick=None, symbol="BANKNIFTY"):
        """
        Generate the Morning Brief (PHASE-2 Precision)
        """
        vix_value = context_data.get('vix_spot', 'N/A')
        today_open = current_tick.get('open') if current_tick else None
        self.intraday_open = today_open  # Latch the day's open
        
        # Calculate industry-standard pivot points
        daily_data = context_data.get('daily_3', []) # Now actually contains 6 days due to database.py change
        pivot, support, resistance = 0, 0, 0
        d_candles = {'d1_open':0,'d1_high':0,'d1_low':0,'d1_close':0,'d2_open':0,'d2_high':0,'d2_low':0,'d2_close':0,'d3_open':0,'d3_high':0,'d3_low':0,'d3_close':0}
        prior_close = 0
        prior_range = 0
        
        if daily_data and len(daily_data) >= 1:
            # daily_data is DESC (index 0 is yesterday)
            prev_day = daily_data[0]
            h = float(prev_day.get('h', prev_day.get('high', 0)))
            l = float(prev_day.get('l', prev_day.get('low', 0)))
            c = float(prev_day.get('c', prev_day.get('close', 0)))
            prior_close = c
            prior_range = h - l
            
            if h and l and c:
                pivot = round((h + l + c) / 3, 1)
                support = round(2 * pivot - h, 1)
                resistance = round(2 * pivot - l, 1)
                logger.debug(f"      📐 PIVOT CALC: PriorDay H={h:.1f} L={l:.1f} C={c:.1f} → S={support:.1f} P={pivot:.1f} R={resistance:.1f}")
            
            # Populate d1, d2, d3 (chronological for prompt: d3 is yesterday)
            # daily_data[0] = yesterday (D-1)
            # daily_data[1] = D-2
            # daily_data[2] = D-3
            for i, idx in enumerate([2, 1, 0]):
                if len(daily_data) > idx:
                    d = daily_data[idx]
                    d_candles[f'd{i+1}_open'] = d.get('o', d.get('open', 0))
                    d_candles[f'd{i+1}_high'] = d.get('h', d.get('high', 0))
                    d_candles[f'd{i+1}_low'] = d.get('l', d.get('low', 0))
                    d_candles[f'd{i+1}_close'] = d.get('c', d.get('close', 0))
                else:
                    d_candles[f'd{i+1}_open'] = d_candles[f'd{i+1}_high'] = d_candles[f'd{i+1}_low'] = d_candles[f'd{i+1}_close'] = 0

        # Gap
        gap_points = round(today_open - prior_close, 2) if (prior_close and today_open) else 0.0
        gap_direction = "UP" if gap_points >= 0 else "DOWN"
        gap_pct = round((gap_points / prior_close) * 100, 2) if prior_close else 0.0
        
        # Authoritative Morning Context
        from engine.enrichment import calculate_morning_context
        auth_context = calculate_morning_context(
            daily_hist=daily_data,
            current_price=today_open,
            support=support,
            resistance=resistance,
            pivot=pivot,
            vix=vix_value if isinstance(vix_value, (int, float)) else 15.0,
            atr_14=context_data.get('atr_14')
        )

        # Extract trade date from current_tick (timestamp)
        trade_date = "N/A"
        if current_tick and 'timestamp' in current_tick:
            ts = current_tick['timestamp']
            if hasattr(ts, 'strftime'):
                trade_date = ts.strftime('%Y-%m-%d')
            else:
                trade_date = str(ts)[:10]

        prompt = USER_PROMPT_MORNING.format(
            symbol=symbol,
            trade_date=trade_date,
            **d_candles,
            prior_close=prior_close,
            prior_day_range_pts=round(prior_range, 1),
            prior_trend_strength="N/A", # Optional refinement later
            vix_value=vix_value,
            gap_direction=gap_direction,
            gap_points=gap_points,
            gap_percent=gap_pct,
            support_zone=support,
            pivot_point=pivot,
            resistance_zone=resistance,
            atr_14=context_data.get('atr_14', 'N/A'),
            expected_range_pts=auth_context.get('expected_range_pts', 150)
        )
        
        logger.debug(f"\n--- 🧠 BRAIN INPUT (MORNING) ---\n{prompt}\n--------------------------------")
        
        # ROUTING: BRAIN with purpose-specific system prompt
        data = self._query_model(SYSTEM_PROMPT_MORNING, prompt)
        
        # --- ENFORCE AUTHORITATIVE RULES (Deterministic Overrides) ---
        from engine.enrichment import calculate_morning_context
        authoritative_context = calculate_morning_context(
            daily_hist=daily_data,
            current_price=today_open if isinstance(today_open, (int, float)) else pivot,
            support=support,
            resistance=resistance,
            pivot=pivot,
            vix=vix_value if isinstance(vix_value, (int, float)) else 15.0,
            atr_14=context_data.get('atr_14')
        )

        if data:
            # 1. Inject pre-calculated IMMUTABLE LEVELS
            if 'reference_levels' not in data:
                data['reference_levels'] = {}
            
            data['reference_levels']['pivot'] = pivot
            data['reference_levels']['support'] = support
            data['reference_levels']['resistance'] = resistance
            
            # 2. Inject Authoritative Risk/Volatility Overrides
            if 'risk_regime' not in data:
                data['risk_regime'] = {}
                
            # Use authoritative VIX regime/range if available
            auth_vix = authoritative_context.get('vix_regime')
            auth_range = authoritative_context.get('expected_range_pts')
            
            if auth_vix: data['risk_regime']['vix_state'] = auth_vix
            if auth_range: data['risk_regime']['expected_move_pts'] = int(auth_range)

            # 3. Log the Policy Configuration
            logger.debug(f"      📐 Anchors: S={support} | P={pivot} | R={resistance}")
            logger.debug(f"      🛡️ Risk Regime: {data['risk_regime']['vix_state']} (Exp: {data['risk_regime']['expected_move_pts']} pts)")
            logger.debug(f"      📜 Tactical Permissions: {json.dumps(data.get('tactical_permissions', {}))}")

            # Legacy Compatibility (Optional - can be removed if Tactical prompt updated)
            # data['market_personality'] = data['risk_regime'].get('vix_state', 'NORMAL')
            # data['primary_bias'] = "NEUTRAL (State Machine)" 
            
            return data
            
        return None
            
        return data

    def get_tactical_update(self, tick, context, plan, current_pnl, open_position, day_pnl=0.0, symbol="BANKNIFTY"):
        """
        Generate Tactical Update (TACTICAL -> WORKER)
        """
        from engine.enrichment import calculate_micro_context, calculate_economic_context
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
        
        # Boundary Levels (stored in reference_levels by get_morning_brief)
        levels = plan.get('reference_levels', {}) if plan else {}
        support = levels.get('support', 'N/A')
        resistance = levels.get('resistance', 'N/A')
        pivot = levels.get('pivot', 'N/A')
        vix_regime_morning = plan.get('vix_regime', 'NORMAL') if plan else 'NORMAL'
        
        last_15min = context.get('last_15min', [])
        recent_15min = last_15min[-14:] if len(last_15min) >= 14 else last_15min
        
        # Format bars as compact OHLC list
        bars_lines = []
        for i, bar in enumerate(recent_15min):
            bars_lines.append(f"  {i+1}. O={bar['o']:.1f} H={bar['h']:.1f} L={bar['l']:.1f} C={bar['c']:.1f}")
        bars_15m = "\n".join(bars_lines) if bars_lines else "No data"
        
        # Last 5-min closes
        today_5min = context.get('today_5min', [])
        recent_5min = today_5min[-5:] if today_5min else []
        last_5m_closes = ",".join([f"{bar['c']:.1f}" for bar in recent_5min]) if recent_5min else "N/A"
        
        # Day Stats
        day_high = context.get('day_high', close)
        day_low = context.get('day_low', close)
        day_range_pts = day_high - day_low
        
        # Position Context
        if open_position:
            side = open_position['side']
            entry = open_position.get('entry_price', 'N/A')
            sl = open_position.get('sl', 'N/A')
            tgt = open_position.get('target', 'N/A')
            position_state = f"OPEN: {side} @ {entry} (SL:{sl}, TGT:{tgt})"
        else:
            position_state = "FLAT (No Position)"
        
        # Time Extraction
        ts = tick.get('ts', tick.get('timestamp'))
        current_time_str = "N/A"
        if ts:
            if hasattr(ts, 'strftime'):
                current_time_str = ts.strftime('%H:%M')
            else:
                try:
                    current_time_str = str(ts)[11:16]
                except:
                    current_time_str = "N/A"

        # --- CONTENT ENRICHMENT (PHASE-2.5: CANONICAL COMPLIANCE) ---
        from engine.enrichment import (
            calculate_micro_context, calculate_economic_context, 
            calculate_opening_range, calculate_expected_move_envelope,
            calculate_style_eligibility, calculate_time_context,
            calculate_location_context, calculate_intraday_state, STYLE_ECONOMICS
        )
        
        # 1. Opening Range (OR)
        or_data = calculate_opening_range(today_5min)
        or_range = or_data['or_range'] if or_data else None
        
        # Determine OR High/Low Reference
        day_high = context.get('day_high', close)
        day_low = context.get('day_low', close)
        or_h_ref = or_data.get('or_high') if or_data else plan.get('reference_levels', {}).get('or_estimate_high', day_high)
        or_l_ref = or_data.get('or_low') if or_data else plan.get('reference_levels', {}).get('or_estimate_low', day_low)

        # 2. Expected Move (EM) Envelope
        daily_3 = context.get('daily_3', [])
        prev_day = daily_3[0] if daily_3 else {}
        prior_day_range = (prev_day.get('h', 0) - prev_day.get('l', 0)) if prev_day else 0
        em_envelope = calculate_expected_move_envelope(or_range, prior_day_range)
        
        # Absolute EM Levels for V-reversal detection
        em_low_price = or_l_ref - em_envelope.get('expected_move_low', 0) if or_l_ref else close - 100
        em_high_price = or_h_ref + em_envelope.get('expected_move_high', 0) if or_h_ref else close + 100
        
        # 3. Micro Context (Structural facts)
        micro_context = calculate_micro_context(
            bars_15min=last_15min,
            current_price=close,
            support=plan.get('reference_levels', {}).get('support', 0),
            resistance=plan.get('reference_levels', {}).get('resistance', 0),
            pivot=plan.get('reference_levels', {}).get('pivot', 0),
            atr_14=atr,
            or_range=em_envelope.get('or_range', 0),
            em_low=em_low_price,
            em_high=em_high_price
        )
        
        # 4. Time Context (Canonical Section 1)
        time_context = calculate_time_context(current_time_str)
        
        # 5. Location Context (Canonical Section 3)
        location_context = calculate_location_context(
            current_price=close,
            support=plan.get('reference_levels', {}).get('support', 0), # New Key
            pivot=plan.get('reference_levels', {}).get('pivot', 0),
            resistance=plan.get('reference_levels', {}).get('resistance', 0),
            or_range=em_envelope.get('or_range', 0)
        )
        
        # 6. Intraday State Machine (Rule Dispatcher)
        # Determine OR High/Low (already calculated above)
        intraday_state, state_reason = calculate_intraday_state(
             current_price=close,
             or_high=or_h_ref,
             or_low=or_l_ref,
             bars_15min=last_15min,
             atr=atr
        )
        # Log State
        logger.debug(f"      🚦 Intraday State: {intraday_state} ({state_reason})")
        
        today_5min = context.get('today_5min', [])
        eligible_styles = calculate_style_eligibility(
            current_time_str=current_time_str,
            micro_context=micro_context,
            morning_plan=plan,
            or_data=or_data,
            current_price=close,
            expected_move=em_envelope,
            today_5min=today_5min,
            intraday_state=intraday_state
        )
        
        # Log eligibility matrix for observability
        logger.debug(f"   📋 Style Eligibility Matrix: {json.dumps(eligible_styles, indent=2)}")
        
        # 8. Economic Context
        target_pts = em_envelope.get('expected_move_high', 40)
        economic_context = calculate_economic_context(
            current_price=close,
            target_pts=target_pts
        )

        # Helper for safe float conversion
        def safe_f(val, baseline=0.0):
            try:
                f = float(val)
                return baseline if (math.isnan(f) or math.isinf(f)) else f
            except:
                return baseline

        prompt = USER_PROMPT_TACTICAL.format(
            current_time=current_time_str,
            time_context=json.dumps(time_context, indent=2),
            location_context=json.dumps(location_context, indent=2),
            eligible_styles=json.dumps(eligible_styles, indent=2),
            style_economics=json.dumps(STYLE_ECONOMICS, indent=2),
            volatility_of_day=em_envelope.get('volatility_of_day', 'NORMAL'),
            em_low=em_envelope.get('expected_move_low', 0),
            em_high=em_envelope.get('expected_move_high', 0),
            symbol=symbol,
            close=round(close, 1),
            day_high=round(day_high, 1),
            day_low=round(day_low, 1),
            day_range_pts=round(day_range_pts, 1),
            vix=round(safe_f(vix), 1),
            atr=round(safe_f(atr), 1),
            intraday_state=intraday_state,
            state_reason=state_reason,
            risk_regime=plan.get('risk_regime', {}).get('regime', 'NORMAL'),
            support=round(plan.get('reference_levels', {}).get('support', 0), 1),
            pivot=round(plan.get('reference_levels', {}).get('pivot', 0), 1),
            resistance=round(plan.get('reference_levels', {}).get('resistance', 0), 1),
            bars_15m=bars_15m,
            last_5m_closes=last_5m_closes,
            swing_context=micro_context.get('swing_context', 'UNKNOWN'),
            retracement_depth=micro_context.get('retracement_depth', 'UNKNOWN'),
            price_behavior=micro_context.get('price_behavior', 'UNKNOWN'),
            volume_behavior=micro_context.get('volume_behavior', 'UNKNOWN'),
            micro_bias=micro_context.get('micro_bias', 'UNKNOWN'),
            micro_confidence=micro_context.get('confidence', 0.0),
            expected_move_pts=economic_context.get('expected_move_pts', 0),
            estimated_option_pnl_inr=economic_context.get('estimated_option_pnl_inr', 0),
            net_expected_pnl_inr=economic_context.get('net_expected_pnl_inr', 0),
            economic_significance=economic_context.get('economic_significance', 'UNKNOWN'),
            position_state=position_state,
            unrealized_pnl=round(current_pnl, 1),
            day_pnl=round(day_pnl, 1),
            consecutive_sl=0 if intraday_state in ["TREND_UP", "TREND_DOWN"] else context.get('consecutive_sl', 0) # Guard: Skip cooling if Trending
        )
        
        # Post-processing for eligible_styles (as per instruction)
        # STYLE 3: INTRADAY_TREND_CONTINUATION (ITC)
        # Allowed if State Machine detects TREND or if we have STABLE break or V-Reversal
        v_rev = micro_context.get('v_reversal', False)
        has_break = micro_context.get('structural_break', False)
        if intraday_state in ["TREND_UP", "TREND_DOWN"] or v_rev or has_break:
            eligible_styles["INTRADAY_TREND_CONTINUATION"] = True

        logger.debug(f"\n--- 👷 WORKER INPUT (TACTICAL) ---\n{prompt}\n--------------------------------")
        
        # ROUTING: BRAIN with purpose-specific system prompt
        data = self._query_model(SYSTEM_PROMPT_TACTICAL, prompt)
        
        if data:
            # --- NORMALIZATION (MANDATORY UPGRADE) ---
            
            # [Existing Time/Mode Normalization Logic - omitted for brevity if unchanged, but keeping context]
            # ... (Assume surrounding code handles this via careful chunk replacement if I were rewriting whole file, but here I am targeting specific block).
            # Wait, sticking to contiguous block replacement, I must include the whole block if I want to edit effectively.
            
            # Let's perform the prompt update first. The Guards logic (Opportunity Recovery) is further down.
            pass

            
            # 1. Deterministic Mode and Late Session Gate
            try:
                # Extract time from tick or current_time_str
                if current_time_str != "N/A":
                    tm = time.strptime(current_time_str, "%H:%M")
                    hr_min = tm.tm_hour * 100 + tm.tm_min 
                    
                    if 915 <= hr_min <= 1000:
                        data['mode'] = "OPENING_RANGE"
                    elif hr_min > 1000:
                        data['mode'] = "STRUCTURE"
                        if hr_min <= 1030:
                            data['action'] = "HOLD"
                            data['reason'] = "Market cooling period (10:00-10:30)"
                    else:
                        data['mode'] = "UNKNOWN"

                    # --- PHASE-2 LATE SESSION GATE ---
                    if hr_min >= 1500:
                        is_directional = micro_context.get('micro_bias') != 'NEUTRAL'
                        is_not_range = micro_context.get('price_behavior') != 'IN_RANGE'
                        is_meaningful = economic_context.get('economic_significance') == 'MEANINGFUL'
                        
                        if not (is_directional and is_not_range and is_meaningful):
                            if data.get('action') in ['BUY_CALL', 'BUY_PUT']:
                                data['action'] = "HOLD"
                                data['reason'] = "Late session safety: Setup lacks required micro/economic strength."
                                logger.info("      🛡️ Late Session Gate: Forcing HOLD (Phase-2 Safety)")
                else:
                    data['mode'] = "UNKNOWN"
            except Exception as e:
                logger.error(f"Error in mode normalization: {e}")
                data['mode'] = "UNKNOWN"

            # 2. Confidence Normalization
            try:
                conf_val = data.get('confidence', 0)
                # If LLM failed to provide a valid confidence, use the micro_context pre-computed one as fallback
                if conf_val is None or not isinstance(conf_val, (int, float)):
                    conf_val = micro_context.get('confidence', 0.0)
                
                f_conf = float(conf_val)
                if math.isnan(f_conf) or math.isinf(f_conf):
                    f_conf = 0.0
                data['confidence'] = max(0.0, min(1.0, f_conf))
            except:
                data['confidence'] = 0.0

            # 3. Action Normalization
            action = data.get('decision', data.get('action', 'HOLD'))
            data['action'] = action
            
            # 4. Reason Normalization (HOLD must have a reason)
            reason = data.get('reason', data.get('adjustment_reason', ''))
            if action == 'HOLD' and not reason:
                reason = "Market not in optimal zone for entry"
            data['technical_reason'] = reason
            data['reason'] = reason # Ensure both are set for compatibility

            # --- PHASE-2.5: PHYSICAL REASONABILITY GATING ---
            
            # Safe ATR access
            raw_atr = context.get('atr_14', context.get('atr', 15))
            try:
                atr = float(raw_atr)
            except:
                atr = 15.0
            
            # SL Gating
            sl = data.get('sl_points', 0)
            if sl and isinstance(sl, (int, float)) and sl > 4 * atr:
                old_sl = sl
                data['sl_points'] = round(1.5 * atr)
                logger.warning(f"      🚨 LLM Hallucinated Massive SL: {old_sl} | Capped to {data['sl_points']} (1.5x ATR)")
                data['reason'] = f"(SL Capped) {data.get('reason', '')}"

            # Target Gating
            tgt = data.get('target_points', 0)
            if tgt and isinstance(tgt, (int, float)) and tgt > 15 * atr: # Target can be larger, but not infinite
                old_tgt = tgt
                data['target_points'] = round(3 * atr)
                logger.warning(f"      🚨 LLM Hallucinated Massive Target: {old_tgt} | Capped to {data['target_points']} (3x ATR)")
                data['reason'] = f"(Target Capped) {data.get('reason', '')}"

            # --- PHASE-2.5: INJECT MICRO-CONTEXT FOR GUARDS & LOGIC ---
            data['micro_context'] = {
                'impulse_detected': micro_context.get('impulse_detected', False),
                'failure_to_accept': micro_context.get('failure_to_accept', False),
                'impulse_move_pts': micro_context.get('impulse_move_pts', 0.0),
                'velocity_increasing': micro_context.get('velocity_increasing', False),
                'last_body_ratio': micro_context.get('last_body_ratio', 0.0),
                'net_progress_3': micro_context.get('net_progress_3', 0.0),
                'absorption': micro_context.get('absorption', False),
                'stall_at_level': micro_context.get('stall_at_level', False),
                'failure_to_extend': micro_context.get('failure_to_extend', False),
                'weak_follow_through': micro_context.get('weak_follow_through', False),
                'rejection': micro_context.get('rejection', False),
                'structural_break': micro_context.get('structural_break', False),
                'break_direction': micro_context.get('break_direction', 'NEUTRAL')
            }

            # --- PHASE-2.5: STRATEGIC REMR GUARD (Physical Enforcement) ---
            selected_style = data.get('selected_style', 'NONE')
            if selected_style == 'REMR' and action in ['BUY_CALL', 'BUY_PUT']:
                location = location_context.get('location', 'MID_RANGE')
                
                # Retrieve advanced micro-context metrics
                # FIX: Use local micro_context variable instead of data.get (Silent Bug Fix)
                velocity_increasing = micro_context.get('velocity_increasing', False)
                last_body_ratio = micro_context.get('last_body_ratio', 0.0)
                absorption = micro_context.get('absorption', False)
                
                stall = micro_context.get('stall_at_level', False)
                failure = micro_context.get('failure_to_extend', False) # Failure to Extend
                rejection = micro_context.get('rejection', False)
                weak_ft = micro_context.get('weak_follow_through', False)
                
                # Check Flip Conditions
                flip_candidate = False
                target_side = None
                
                if location in ['NEAR_RESISTANCE', 'OPTIMAL_TOP'] and action == 'BUY_CALL':
                    flip_candidate = True
                    target_side = "BUY_PUT"
                elif location in ['NEAR_SUPPORT', 'OPTIMAL_BOTTOM'] and action == 'BUY_PUT':
                    flip_candidate = True
                    target_side = "BUY_CALL"
                
                if flip_candidate:
                    # 1. CONTINUATION RISK CHECK (Do NOT Flip If...)
                    continuation_risk = False
                    
                    # Risk A: Velocity increasing in direction of break
                    # If we are BUY_CALL (original), we are betting ON continuation. 
                    # If we flip to BUY_PUT, we are betting AGAINST it.
                    # Risk exists if the CURRENT move (which we are flipping against) is strong.
                    if velocity_increasing: continuation_risk = True # Momentum expanding into level
                    
                    # Risk B: Strong Candle Body Ratio (>0.6)
                    if last_body_ratio > 0.6: continuation_risk = True # Marubozu-like close into level
                    
                    # Risk C: Net Progress is strong (no stall)
                    # Implicit in velocity/body, but can use net_progress_N if needed.
                    
                    # 2. REJECTION CONFIRMATION (Only Flip If...)
                    # We need at least 3 confirmation signals
                    signals = [stall, failure, rejection, weak_ft, absorption]
                    rejection_score = sum(1 for s in signals if s)
                    
                    if not continuation_risk and rejection_score >= 3:
                        logger.warning(f"      🛡️ REMR Guard: Flipped {action} to {target_side} at {location} (Score: {rejection_score}/5)")
                        data['action'] = target_side
                        data['reason'] = f"(Guard Flipped) {data['reason']}"
                    
                    else:
                        # FLIP REJECTED: Determine if we should HOLD or keep original (rare)
                        # Usually if we are at resistance and model said BUY_CALL, but we don't flip to PUT,
                        # we should probably HOLD rather than buying the breakout blindly unless it's a breakout style?
                        # selected_style is REMR, so we are NOT trading breakouts.
                        # So if we can't flip to Mean Reversion, we must HOLD (skip the breakout).
                        logger.warning(f"      🛡️ REMR Guard: FLIP BLOCKED (Continuation Risk or Low Score {rejection_score}/5). Enforcing HOLD.")
                        data['action'] = "HOLD"
                        data['reason'] = f"REMR Flip Blocked: High Continuation Risk / Low Rejection Signal ({rejection_score}/5)"
            
            # --- PHASE-2.5: SINGLE POSITION GUARD (Anti-Pyramiding) ---
            # If we are already in a position, BLOCKED any new Entry signals.
            # This prevents LLM hallucinations from confusing the user or logs.
            if open_position and data['action'] in ['BUY_CALL', 'BUY_PUT']:
                logger.warning(f"      [ENGINE] 🛡️ Position Guard: Blocked {data['action']} because position is already OPEN.")
                data['action'] = "HOLD"
                data['reason'] = f"(System Fixed) Invalid Entry Signal while Position Open."

            # --- PHASE-2.5: INJECT AUTHORITATIVE HOLD TIME ---
            # Ensure Executor gets the correct Style-based time limit
            sel_style = data.get('selected_style', 'NONE')
            if sel_style in STYLE_ECONOMICS:
                 data['max_hold_minutes'] = STYLE_ECONOMICS[sel_style]['max_hold_min']
            
            # --- CALCULATION (EXISTING LOGIC) ---
            
            # Entry Price
            close_price = close # From local var
            if isinstance(close_price, str): close_price = 0.0
            
            entry = float(data.get('entry') or 0)
            if entry == 0: entry = float(close_price)
            data['entry'] = entry

            # SL/Target Calculation (Points -> Price)
            # Support both 'sl_points' (new) and 'sl' (legacy/hallucination) keys
            def get_safe_pt(key_primary, key_secondary):
                val = data.get(key_primary, data.get(key_secondary, 0))
                if val is None: val = 0
                try:
                    f = float(val)
                    return 0.0 if (math.isnan(f) or math.isinf(f)) else f
                except:
                    return 0.0

            sl_raw = get_safe_pt('sl_points', 'sl')
            tgt_raw = get_safe_pt('target_points', 'target')
            
            # Heuristic: If value > 1000, model likely outputted PRICE instead of POINTS.
            # Convert to points (distance)
            sl_points = sl_raw
            if sl_raw > 1000:
                 sl_points = abs(entry - sl_raw)
            
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
            data['sl_points'] = sl_points
            data['target_points'] = tgt_points
            
            # --- SMART PHASE-2 UPDATES (Trend Day Performance Fixes) ---
            
            # 1. BIAS DECAY (Original)
            morning_bias = plan.get('primary_bias', 'NEUTRAL')
            bias_weight = time_context.get('bias_weight', 1.0)
            effective_bias = morning_bias
            if bias_weight < 0.3:
                 effective_bias = "NEUTRAL (Decayed)"
            
            # 2. STRUCTURAL BREAK OVERRIDE (Trend Guard + Directional Alignment)
            # This is a LATCHED STATE - only log when state CHANGES
            current_break = data.get('micro_context', {}).get('structural_break', False)
            break_dir = data.get('micro_context', {}).get('break_direction', 'NEUTRAL')
            net_progress = data.get('micro_context', {}).get('net_progress_3', 0)
            v_reversal = data.get('micro_context', {}).get('v_reversal', False)
            
            # --- GLOBAL TIME CONTEXT ---
            # current_time_str is already calculated at the top of the function
            current_hour = current_time_str.split(':')[0] if current_time_str != 'N/A' else '00'
            try: hour_int = int(current_hour)
            except: hour_int = 0
            
            # Update latched state
            structural_break = False
            if current_break and break_dir != 'NEUTRAL':
                 # Check if state changed
                 if self.structural_break_state != break_dir:
                      # NEW BREAK or DIRECTION REVERSAL
                      self.structural_break_state = break_dir
                      self.structural_break_entry_done = False
                      logger.warning(f"      [ENGINE] 🔓 STRUCTURAL BREAK DETECTED ({break_dir}) @ {close} -> Enforcing Trend Alignment")
                 structural_break = True
            elif not current_break and self.structural_break_state:
                 # Break condition ended
                 logger.warning(f"      [ENGINE] 🔒 STRUCTURAL BREAK ENDED (was {self.structural_break_state})")
                 self.structural_break_state = None
                 self.structural_break_entry_done = False
            
            # --- SYNERGY: DYNAMIC CONFIDENCE BOOST ---
            # 1. Aligned Daily Progress (+0.10)
            p_baseline = self.intraday_open if self.intraday_open else tick.get('open', close)
            p_since_open = close - p_baseline
            aligned_momentum = (p_since_open > 0 and action == 'BUY_CALL') or (p_since_open < 0 and action == 'BUY_PUT')
            
            # 2. Aligned Structural Break (+0.10)
            break_aligned = (self.structural_break_state == 'BULLISH' and action == 'BUY_CALL') or \
                            (self.structural_break_state == 'BEARISH' and action == 'BUY_PUT')
            
            # 3. Aligned with Day Open (is_aligned)
            is_aligned = (break_aligned and p_since_open > 0) if action == 'BUY_CALL' else \
                         (break_aligned and p_since_open < 0)
            # Simpler check for alignment
            is_aligned = (action == 'BUY_CALL' and p_since_open > 0) or (action == 'BUY_PUT' and p_since_open < 0)
            
            old_conf = data.get('confidence', 0)
            boost = 0
            if aligned_momentum: boost += 0.10
            if break_aligned: boost += 0.10
            if v_reversal and action == "BUY_CALL": boost += 0.10
            
            if boost > 0:
                data['confidence'] = min(0.95, old_conf + boost)
                logger.info(f"      [ENGINE] 🚀 SYNERGY BOOST: Confidence {old_conf:.2f} -> {data['confidence']:.2f} (+{boost:.2f})")

            # 3. V-REVERSAL OVERRIDE (Phase-2.6 Synergy)
            # Allows counter-trend reversal if extreme exhaustion + fast recovery detected
            if v_reversal and action == "BUY_CALL" and self.structural_break_state == "BEARISH":
                logger.warning(f"      [ENGINE] 💥 V-REVERSAL OVERRIDE: Allowing Long during Bearish Break.")
                structural_break = False # Temporarily reset to allow the LLM signal
            
            # Use latched state for logic
            if self.structural_break_state and structural_break:
                  break_dir = self.structural_break_state
                  
                  # Progress since Open for Directional Alignment
                  today_open = tick.get('open', close) # Open of the First bar
                  progress_since_open = close - today_open
                  
                  # One-Way Hierarchy: Disable REMR completely when in Trend
                  is_counter_trend = False
                  if break_dir == 'BULLISH' and action == 'BUY_PUT': is_counter_trend = True
                  if break_dir == 'BEARISH' and action == 'BUY_CALL': is_counter_trend = True
                  
                  if is_counter_trend:
                       logger.warning(f"      [ENGINE] 🛑 BLOCKED COUNTER-TREND SIGNAL: {action} during {break_dir} Break.")
                       data['action'] = "HOLD"
                       data['reason'] = f"Counter-Trend Signal Blocked (Attempted {action} during {break_dir} Break)"
                       data['engine_decision'] = "BLOCKED"
                  else:
                       # Force ITC style if REMR was selected
                       if data.get('selected_style') in ['RANGE_EXTREME_MEAN_REVERSION', 'REMR']:
                            data['selected_style'] = 'INTRADAY_TREND_CONTINUATION'
                            data['engine_reason'] = f"Style Corrected to ITC (Aligned with {break_dir} Break)"
                  
                  effective_bias = f"{break_dir}_TREND (Structural Break)"

            # 3. PHASE 2.5: BEHAVIORAL GATING & MOMENTUM CONFLICTS
            rejection_pattern = micro_context.get('rejection_pattern', 'NONE')
            m_slope = micro_context.get('momentum_slope', 0)
            
            # A. REMR Behavioral Gate (Section 3.A of Plan)
            if data.get('selected_style') in ['RANGE_EXTREME_MEAN_REVERSION', 'REMR']:
                # Rule: REMR must have a behavioral rejection signature
                if rejection_pattern == 'NONE':
                     # If early (<10:00), it's a hard block. Mid-day is a warning or reduction.
                     hr_int = int(current_time_str.split(':')[0]) if current_time_str != 'N/A' else 9
                     if hr_int < 10:
                         logger.warning(f"      [ENGINE] 🛑 REMR BLOCKED (No Rejection): Candle lacks behavioral rejection signature at open.")
                         data['action'] = "HOLD"
                         data['reason'] = "REMR Blocked: No behavioral rejection candle detected in Opening Range."
                         data['engine_decision'] = "BLOCKED"
                
                # B. Momentum-Location Conflict Filter (Section 3.D of Plan)
                # BLOCK short if price > Pivot AND Momentum is upward
                is_short = data['action'] == 'BUY_PUT'
                is_long = data['action'] == 'BUY_CALL'
                
                if is_short and m_slope > 0 and close > pivot:
                     logger.warning(f"      [ENGINE] 🛑 MOMENTUM CONFLICT: REMR Put blocked vs positive slope ({m_slope}) + price > pivot.")
                     data['action'] = "HOLD"
                     data['reason'] = "REMR Short Blocked: Momentum currently positive above pivot."
                     data['engine_decision'] = "BLOCKED"
                elif is_long and m_slope < 0 and close < pivot:
                     logger.warning(f"      [ENGINE] 🛑 MOMENTUM CONFLICT: REMR Call blocked vs negative slope ({m_slope}) + price < pivot.")
                     data['action'] = "HOLD"
                     data['reason'] = "REMR Long Blocked: Momentum currently negative below pivot."
                     data['engine_decision'] = "BLOCKED"

            # C. Flip Intelligence (Section 3.E of Plan)
            # Prevent oscillating bias unless rejection is present
            if open_position and data['action'] != 'HOLD':
                current_side = open_position['side']
                new_action = data['action']
                is_flip = (current_side == 'BUY_CALL' and new_action == 'BUY_PUT') or \
                          (current_side == 'BUY_PUT' and new_action == 'BUY_CALL')
                
                if is_flip and rejection_pattern == 'NONE':
                     logger.warning(f"      [ENGINE] 🛡️ FLIP BLOCKED: Bias flip attempted without rejection pattern.")
                     data['action'] = "HOLD" # Or keep original? Usually HOLD is safer to exit first.
                     data['reason'] = "Flip Intelligence: Bias flip blocked (no rejection pattern confirmed)."
                     data['engine_decision'] = "BLOCKED"

            # 4. TWO-STAGE TREND CONFIRMATION (Replaces impulsive overrides)
            # Stage 1: Break Detected (already done above)
            # Stage 2: Acceptance Confirmed (pullback failed to retrace >40% OR 2 closes beyond break)
            
            trend_acceptance_confirmed = False
            failure_to_accept = micro_context.get('failure_to_accept', False)
            impulse_detected = micro_context.get('impulse_detected', False)
            retracement_depth = micro_context.get('retracement_depth', 'UNCERTAIN')
            vol_behavior = micro_context.get('volume_behavior', 'NORMAL')
            is_expanding_vol = 'EXPANDING' in vol_behavior
            
            if structural_break and not failure_to_accept:
                 # CRITICAL FIX: Trend Acceptance requires ENERGY, not just location
                 # Impulse = directional commitment, ExpandVol = participation urgency
                 # Pullback is a TIMING filter, not a confirmation signal
                 
                 has_energy = impulse_detected or is_expanding_vol
                 acceptable_pullback = retracement_depth in ['SHALLOW', 'NORMAL', 'UNCERTAIN']
                 
                 # SYNERGY TUNING: Restore strictness for reliability
                 if v_reversal:
                      high_conf_floor = 0.45 
                 elif is_aligned:
                      high_conf_floor = 0.55
                 else:
                      high_conf_floor = 0.70

                 high_conf_aligned = data.get('confidence', 0) >= high_conf_floor
                 
                 if has_energy:
                      # Energy detected - true acceptance
                      trend_acceptance_confirmed = True
                      logger.warning(f"      [ENGINE] ✅ TREND ACCEPTANCE (ENERGY): Impulse={impulse_detected}, ExpandVol={is_expanding_vol}, Pullback={retracement_depth}")
                 elif acceptable_pullback and high_conf_aligned:
                      # Steady grind - accept if confidence crosses the (now lower) floor
                      trend_acceptance_confirmed = True
                      logger.warning(f"      [ENGINE] ✅ TREND ACCEPTANCE (GRIND): Conf={data.get('confidence', 0):.2f}, Pullback={retracement_depth}, Aligned={is_aligned}")
                 elif acceptable_pullback:
                      # Pullback ok but NO energy or high confidence - this is drift, not commitment
                      logger.warning(f"      [ENGINE] ⏳ PENDING ACCEPTANCE: Pullback={retracement_depth} but NO ENERGY (Need Energy or Conf >= {high_conf_floor})")
                 else:
                      logger.warning(f"      [ENGINE] ⏳ BREAK PENDING ACCEPTANCE: Retracement={retracement_depth}, Impulse={impulse_detected}, ExpandVol={is_expanding_vol}")

            # --- FINAL GATE: MOMENTUM ALIGNMENT ---
            # Section 3.D/Synergy fix: Even if structure is accepted, block if momentum is sharks-opposite
            # This prevents entering a gap-up that is actively dropping (01-12 scenario)
            m_slope = micro_context.get('momentum_slope', 0)
            if action == 'BUY_CALL' and m_slope < -2 and not v_reversal:
                 logger.warning(f"      [ENGINE] 🛑 MOMENTUM GATE: CALL blocked vs negative slope ({m_slope}).")
                 trend_acceptance_confirmed = False
                 if not open_position: # Only block new entry, don't exit if already in
                      data['action'] = "HOLD"
            elif action == 'BUY_PUT' and m_slope > 2:
                 logger.warning(f"      [ENGINE] 🛑 MOMENTUM GATE: PUT blocked vs positive slope ({m_slope}).")
                 trend_acceptance_confirmed = False
                 if not open_position:
                      data['action'] = "HOLD"

            # 4. DIRECTIONAL CONSISTENCY CHECK
            # Override only if sign(ProgressSinceOpen) == sign(BreakDirection)
            directional_consistent = False
            today_open_baseline = self.intraday_open if self.intraday_open else tick.get('open', close)
            p_since_open = close - today_open_baseline
            if break_dir == 'BULLISH' and p_since_open >= 0: directional_consistent = True
            if break_dir == 'BEARISH' and p_since_open <= 0: directional_consistent = True
            
            if structural_break and not directional_consistent:
                 # SYNERGY: If confidence is high (>0.75) OR V-Reversal OR Late-Day
                 # trust the break over the open-baseline.
                 is_late = hour_int >= 11 # 11:00 AM onwards, trust the new trend
                 if data.get('confidence', 0) >= 0.75 or v_reversal or is_late:
                      directional_consistent = True
                      reason = "Late Day" if is_late else ("V-Reversal" if v_reversal else "High Conf")
                      logger.warning(f"      [ENGINE] 🔓 TRUSTING BREAK ({reason}) despite Directional Mismatch (Conf={data.get('confidence', 0):.2f})")
                 else:
                      logger.warning(f"      ⚠️ DIRECTIONAL MISMATCH: Break={break_dir} but NetProgress={p_since_open:.1f} -> Skipping override")

            # 5. OPPORTUNITY RECOVERY GATE (Force Entry ONLY if confirmed)
            is_opportunity_recovery = False
            
            if hour_int >= 11 and day_pnl == 0 and open_position is None:
                 day_high = data.get('day_high', 0)
                 day_low = data.get('day_low', 0)
                 realized_range = day_high - day_low
                 em_high = em_envelope.get('expected_move_high', 100)
                 
                 if realized_range > 0.7 * em_high:
                      is_opportunity_recovery = True
                      logger.warning(f"      🔓 OPPORTUNITY RECOVERY ACTIVE: Range={realized_range:.0f} > 0.7*EM")
                      # Boost confidence for recovery attempts
                      data['confidence'] = max(data.get('confidence', 0), 0.85)

            # 6. CONDITIONAL COOLING (Expansion Override)
            is_cooling = False
            if "10:00" <= current_time_str <= "10:30":
                 velocity_inc = data.get('micro_context', {}).get('velocity_increasing', False)
                 day_range = data.get('day_high', 0) - data.get('day_low', 0)
                 or_range_val = em_envelope.get('or_range', 50)
                 range_expanding = day_range > 1.2 * or_range_val
                 
                 if velocity_inc or (structural_break and trend_acceptance_confirmed) or range_expanding:
                      logger.warning(f"      🔥 COOLING SKIPPED (Expansion): VelInc={velocity_inc}, TrendAccept={trend_acceptance_confirmed}")
                      is_cooling = False
                 else:
                      is_cooling = True
                      
            if is_cooling:
                 data['engine_decision'] = "BLOCKED"
                 data['engine_reason'] = "Market Cooling Period (10:00-10:30)"
            
            # --- DISCIPLINED TREND ENTRY (Replaces blind overrides) ---
            # ONLY enter if ALL conditions are met:
            # 1. structural_break = True
            # 2. trend_acceptance_confirmed = True
            # 3. directional_consistent = True
            # 4. action == HOLD (LLM is conservative)
            # 5. Not already in position
            
            required_conf = 0.70
            selected_style = data.get('selected_style', '')
            atr_val = data.get('atr', 50)
            
            # Qualified Trend Entry
            qualified_trend_entry = (
                 structural_break and 
                 trend_acceptance_confirmed and 
                 directional_consistent and 
                 data['action'] == 'HOLD' and 
                 open_position is None
            )
            
            if qualified_trend_entry:
                 current_conf = float(data.get('confidence', 0))
                 
                 # Lowered threshold for confirmed trends
                 if current_conf >= 0.25 or is_opportunity_recovery:
                      # HARD GEOMETRY SWITCH: Use ITC geometry, NOT REMR
                      data['selected_style'] = 'INTRADAY_TREND_CONTINUATION'
                      data['confidence'] = 0.75
                      
                      # ITC Geometry: 50pt SL, 90pt TGT (R:R = 1.8 to pass guard)
                      if break_dir == 'BULLISH':
                           data['action'] = 'BUY_CALL'
                           data['sl'] = round(close - 50, 2)
                           data['target'] = round(close + 90, 2)
                      elif break_dir == 'BEARISH':
                           data['action'] = 'BUY_PUT'
                           data['sl'] = round(close + 50, 2)
                           data['target'] = round(close - 90, 2)
                      
                      data['reason'] = f"(Confirmed Trend: {break_dir}, Acceptance ✓) {data['reason']}"
                      logger.warning(f"      [ENGINE] 💥 DISCIPLINED TREND ENTRY: {data['action']} @ {close} (ITC Geometry: SL={data['sl']}, TGT={data['target']})")
            
            # If Opportunity Recovery but NO qualified trend, just boost confidence for LLM's signal
            elif is_opportunity_recovery and data['action'] != 'HOLD':
                 current_conf = float(data.get('confidence', 0))
                 if current_conf >= 0.40 and current_conf < 0.8:
                      data['confidence'] = 0.85
                      data['reason'] = f"(Opp. Recovery Boost) {data['reason']}"
                      logger.warning(f"      [ENGINE] 🚀 CONFIDENCE BOOSTED for Opportunity Recovery: {current_conf} -> 0.85")

            
            # RE-EVALUATE STYLE ELIGIBILITY WITH NEW BIAS
            # (No re-calc needed, just applied in prompt or enforced below)
            
            # Update Payload for Prompt
            data['primary_bias'] = effective_bias
            data['is_opportunity_recovery'] = is_opportunity_recovery
            data['expected_move_high'] = em_envelope.get('expected_move_high', 0)

            # Log AFTER all normalizations are applied (Use data[] for post-guard values)
            final_reason = data.get('reason', reason)
            reason_short = final_reason[:40] + '...' if len(final_reason) > 40 else final_reason
            logger.info(f"      [LLM] 🔸 {data['action']} | Mode:{data['mode']} | Entry:{entry:.1f} | SL:{data['sl']} (-{sl_points:.1f}) | TGT:{data['target']} (+{tgt_points:.1f}) | {reason_short}")
            
            # 7. TREND EXHAUSTION GATE (Phase 2.5)
            # Disable ITC if move already covered > 1.2 * EM and volume is contracting
            if data.get('selected_style') == 'INTRADAY_TREND_CONTINUATION' and data['action'] != 'HOLD':
                em_high = em_envelope.get('expected_move_high', 100)
                # Proxy displacement move since break
                day_high = context.get('day_high', close)
                day_low = context.get('day_low', close)
                realized_move = day_high - day_low
                # 2. Volume expansion check (Canonical Primitive)
                # Use local micro_context (Authoritative)
                vol_behavior = micro_context.get('volume_behavior', 'NORMAL')
                
                if realized_move > 1.2 * em_high and 'CONTRACTING' in vol_behavior:
                    logger.warning(f"      [ENGINE] 🛑 TREND EXHAUSTED: Move={realized_move:.0f} > 1.2*EM ({em_high:.0f}) + Vol Contraction.")
                    data['action'] = "HOLD"
                    data['reason'] = f"Trend Exhaustion Gate: Realized move ({realized_move:.0f}) exceeded 1.2*EM and volume is contracting."
                    data['engine_decision'] = "BLOCKED"
        
        return data

    def get_eod_journal(self, trades, morning_plan, session_id, eod_data, symbol="BANKNIFTY"):
        """
        Generate EOD Audit (AUDIT -> BRAIN) - PHASE-2 STRUCTURAL AUDITOR
        """
        total_pnl = sum([t.get('pnl', 0) for t in trades if t.get('pnl') is not None])
        
        # Format Authoritative Morning Plan
        plan_details = {
            "bias": f"{morning_plan.get('primary_bias')} ({morning_plan.get('bias_strength')})",
            "personality": morning_plan.get('market_personality'),
            "invalidation": morning_plan.get('invalidation_level'),
            "expected_range": morning_plan.get('expected_range_pts')
        }
        morning_plan_str = json.dumps(plan_details, indent=2)
        
        # 1. Chronological Execution Logs
        compact_logs = []
        for t in trades:
            if t.get('pnl') is not None:
                entry_time = str(t.get('entry_time', ''))[11:16]
                exit_time = str(t.get('exit_time', ''))[11:16]
                reason_map = {'SL Hit': 'SL', 'Target Hit': 'TGT', 'AI Logic Exit': 'AI', 'EOD Square-off': 'EOD'}
                reason = reason_map.get(t.get('reason', ''), t.get('reason', ''))[:3]
                pnl = t.get('pnl', 0)
                pnl_str = f"+{pnl:.1f}" if pnl >= 0 else f"{pnl:.1f}"
                compact_logs.append(f"{t['side']} {t['entry_price']:.1f}@{entry_time}→{t['exit_price']:.1f}@{exit_time} {reason} {pnl_str}")
        
        execution_logs_str = "\n".join(compact_logs) if compact_logs else "No trades executed."

        # 2. System Actions (Skipped/Blocked)
        # Fetch from DB for this session
        conn = get_connection()
        skipped_summary = "No significant trades were blocked/skipped today."
        try:
            skipped_rows = conn.execute("""
                SELECT timestamp, content FROM simulation_logs 
                WHERE session_id = ? AND event_type = 'TACTICAL'
            """, (session_id,)).fetchall()
            
            blocks = []
            for row in skipped_rows:
                ts_str = str(row[0])[11:16]
                content = json.loads(row[1])
                if content.get('engine_decision') == 'BLOCKED' or content.get('action') == 'HOLD':
                    reason = content.get('engine_reason') or content.get('reason') or "Standard Filter"
                    blocks.append(f"[{ts_str}] HOLD/BLOCKED: {reason}")
            
            if blocks:
                # Keep only unique types or last 10
                skipped_summary = "\n".join(blocks[-10:])
        except:
            pass
        finally:
            conn.close()
        
        eod_chart_str = json.dumps(eod_data, default=str)
        
        prompt = USER_PROMPT_EOD.format(
            symbol=symbol,
            session_id=session_id,
            total_pnl=f"{total_pnl:.2f}",
            morning_plan=morning_plan_str,
            execution_logs=execution_logs_str,
            skipped_trades_summary=skipped_summary,
            eod_chart=eod_chart_str
        )
        
        logger.info(f"\n--- 🧠 BRAIN INPUT (EOD AUDIT v2) ---\n{prompt}\n--------------------------------")
        
        # ROUTING: BRAIN with purpose-specific system prompt
        data = self._query_model(SYSTEM_PROMPT_EOD, prompt)
        
        if not data:
            logger.info("      🔄 Attempting SELF-CORRECTION for EOD Audit...")
            data = self._query_model(SYSTEM_PROMPT_EOD + "\n\nCRITICAL: You must output ONLY valid JSON.", prompt + "\n\nRETRY: Last output was invalid. Fix formatting.")

        if not data:
            return {
                "audit_summary": f"PnL:{total_pnl:.1f} | Audit Failed",
                "bias_fitness": 0,
                "primary_edge_source": "NONE",
                "system_lesson": "EOD audit failed to generate."
            }
            
        # Standard summary for logs
        fitness = data.get('bias_fitness', 0)
        edge = data.get('primary_edge_source', 'NONE')
        audit_summary = f"PnL:{total_pnl:.1f} | Fitness:{fitness} | Edge:{edge}"
        logger.info(f"      📊 EOD AUDIT: {audit_summary}")
        
        data['audit_summary'] = audit_summary
        return data
