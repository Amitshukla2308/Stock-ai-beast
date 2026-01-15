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
        logger.info(f"🧠 Brain Connecting to: {self.brain_model} at {self.brain_api_base}")
        self.brain_client = OpenAI(base_url=self.brain_api_base, api_key=self.brain_api_key, timeout=300.0)

    def wait_for_model_ready(self):
        """Blocks until the model responds effectively (handles lazy loading)"""
        logger.info(f"⏳ Verification: Waiting for {self.brain_model} to load...")
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
            logger.info(f"\n--- {role_icon} {role_name} SYSTEM ---\n{system_msg}\n---")
            
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
            logger.info(f"\n--- {role_icon} {role_name} OUTPUT ({lat:.2f}s) ---\n{content[:5000]}\n-----------------------")
            
            # Try to parse JSON with error recovery
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
                    logger.error(f"      ❌ JSON recovery failed, returning None")
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
        
        # Calculate industry-standard pivot points
        daily_data = context_data.get('daily_3', []) # Now actually contains 6 days due to database.py change
        pivot, support, resistance = 0, 0, 0
        d_candles = {}
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
        
        logger.info(f"\n--- 🧠 BRAIN INPUT (MORNING) ---\n{prompt}\n--------------------------------")
        
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
            # Inject pre-calculated levels into response (script-calculated, not LLM)
            if 'boundary_levels' not in data:
                data['boundary_levels'] = {}
            data['boundary_levels']['pivot_point'] = pivot
            data['boundary_levels']['support_zone'] = support
            data['boundary_levels']['resistance_zone'] = resistance

            # Authoritative Overrides (Rule Mapping)
            data['primary_bias'] = authoritative_context.get('primary_bias', data.get('primary_bias'))
            data['bias_strength'] = authoritative_context.get('bias_strength', data.get('bias_strength'))
            data['market_personality'] = authoritative_context.get('market_personality', data.get('market_personality'))
            data['vix_regime'] = authoritative_context.get('vix_regime', data.get('vix_regime'))
            data['expected_range_pts'] = authoritative_context.get('expected_range_pts', data.get('expected_range_pts', 150))
            data['invalidation_level'] = authoritative_context.get('invalidation_level', data.get('invalidation_level'))
            data['max_expected_move'] = authoritative_context.get('max_expected_move', data.get('max_expected_move', 150))

            logger.info(f"      📐 Pivot Levels: S={support:.1f} | P={pivot:.1f} | R={resistance:.1f}")
            logger.info(f"      ⚖️ Authoritative Bias: {data['primary_bias']} ({data['bias_strength']})")
            
            personality = data.get('market_personality', 'N/A')
            vix_regime = data.get('vix_regime', 'N/A')
            bias = data.get('primary_bias', 'N/A')
            logger.info(f"      🌅 {personality} | VIX:{vix_regime} | Bias:{bias}")
            
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
        
        # Boundary Levels
        boundaries = plan.get('boundary_levels', {}) if plan else {}
        support = boundaries.get('support_zone', 'N/A')
        resistance = boundaries.get('resistance_zone', 'N/A')
        pivot = boundaries.get('pivot_point', 'N/A')
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
            calculate_location_context, STYLE_ECONOMICS
        )
        
        # 1. Opening Range (OR)
        or_data = calculate_opening_range(today_5min)
        or_range = or_data['or_range'] if or_data else None
        
        # 2. Expected Move (EM) Envelope
        # prior_day_range comes from database.py but we need it from plan/context
        # context['daily_3'][0] is yesterday
        prev_day = context.get('daily_3', [{}])[0]
        prior_day_range = (prev_day.get('h', 0) - prev_day.get('l', 0)) if prev_day else 0
        em_envelope = calculate_expected_move_envelope(or_range, prior_day_range)
        
        # 3. Micro Context (Structural facts)
        micro_context = calculate_micro_context(
            bars_15min=last_15min,
            current_price=close,
            support=plan.get('boundary_levels', {}).get('support_zone', 0),
            resistance=plan.get('boundary_levels', {}).get('resistance_zone', 0),
            pivot=plan.get('boundary_levels', {}).get('pivot_point', 0),
            atr_14=atr,
            or_range=em_envelope.get('or_range', 0)
        )
        
        # 4. Time Context (Canonical Section 1)
        time_context = calculate_time_context(current_time_str)
        
        # 5. Location Context (Canonical Section 3)
        location_context = calculate_location_context(
            current_price=close,
            support=plan.get('boundary_levels', {}).get('support_zone', 0),
            pivot=plan.get('boundary_levels', {}).get('pivot_point', 0),
            resistance=plan.get('boundary_levels', {}).get('resistance_zone', 0),
            or_range=em_envelope.get('or_range', 0)
        )
        
        # 6. Style Eligibility (PHASE-2.5: Authoritative Filters)
        eligible_styles = calculate_style_eligibility(
            current_time_str=current_time_str,
            micro_context=micro_context,
            morning_plan=plan,
            or_data=or_data,
            current_price=close,
            expected_move=em_envelope
        )
        
        # Log eligibility matrix for observability
        logger.info(f"   📋 Style Eligibility Matrix: {json.dumps(eligible_styles, indent=2)}")
        
        # 7. Economic Context (Dynamic Target based on EM High)
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
            market_personality=plan.get('market_personality', 'CHOPPY'),
            primary_bias=plan.get('primary_bias', 'NEUTRAL'),
            bias_strength=plan.get('bias_strength', 'FRAGILE'),
            support=round(plan.get('boundary_levels', {}).get('support_zone', 0), 1),
            pivot=round(plan.get('boundary_levels', {}).get('pivot_point', 0), 1),
            resistance=round(plan.get('boundary_levels', {}).get('resistance_zone', 0), 1),
            invalidation_level=plan.get('invalidation_level', 'N/A'),
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
            consecutive_sl=0 # Placeholder
        )
        
        logger.info(f"\n--- 👷 WORKER INPUT (TACTICAL) ---\n{prompt}\n--------------------------------")
        
        # ROUTING: BRAIN with purpose-specific system prompt (Was WORKER)
        data = self._query_model(SYSTEM_PROMPT_TACTICAL, prompt)
        
        if data:
            # --- NORMALIZATION (MANDATORY UPGRADE) ---
            
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

            # --- PHASE-2.5: STRATEGIC REMR GUARD (Physical Enforcement) ---
            selected_style = data.get('selected_style', 'NONE')
            if selected_style == 'REMR' and action in ['BUY_CALL', 'BUY_PUT']:
                location = location_context.get('location', 'MID_RANGE')
                
                # Rule: Resistance -> BUY_PUT
                if location in ['NEAR_RESISTANCE', 'OPTIMAL_TOP'] and action == 'BUY_CALL':
                    logger.warning(f"      🛡️ REMR Guard: Flipped BUY_CALL to BUY_PUT at {location}")
                    data['action'] = "BUY_PUT"
                    data['reason'] = f"(Guard Flipped) {data['reason']}"
                
                # Rule: Support -> BUY_CALL
                elif location in ['NEAR_SUPPORT', 'OPTIMAL_BOTTOM'] and action == 'BUY_PUT':
                    logger.warning(f"      🛡️ REMR Guard: Flipped BUY_PUT to BUY_CALL at {location}")
                    data['action'] = "BUY_CALL"
                    data['reason'] = f"(Guard Flipped) {data['reason']}"
            
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
            
            # Log AFTER all normalizations are applied
            reason_short = reason[:40] + '...' if len(reason) > 40 else reason
            logger.info(f"      🔸 {action} | Mode:{data['mode']} | Entry:{entry:.1f} | SL:{data['sl']} (-{sl_points:.1f}) | TGT:{data['target']} (+{tgt_points:.1f}) | {reason_short}")
        
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
