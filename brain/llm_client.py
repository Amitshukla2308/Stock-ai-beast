import os
import json
import time
import logging
import math
import random
from openai import OpenAI
from data.database import get_connection
from dotenv import load_dotenv
from brain.prompts import (
    SYSTEM_PROMPT_MORNING, USER_PROMPT_MORNING,
    SYSTEM_PROMPT_TACTICAL, USER_PROMPT_TACTICAL,
    SYSTEM_PROMPT_EOD, USER_PROMPT_EOD
)
from engine.research_engine import ResearchEngine
from config.config_loader import config

load_dotenv()

# Initialize Logger
logger = logging.getLogger(__name__)

# v2.8 ROTATIONAL EXECUTION SWITCH
# Allows non-trend styles (REMR, VBD, ORE) to execute in ROTATION/RANGE regimes
# without requiring directional alignment (which is only for ITC)
ALLOW_ROTATIONAL_EXECUTION = True

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
        # v2.8 Modular Orchestrator
        self.research_engine = ResearchEngine(self)
        
        self.structural_break_state = "NEUTRAL"
        self.structural_break_entry_done = False  # Track if we already entered on this break
        self.intraday_open = None  # Persistent baseline for the day
        
        # New Regime Hysteresis State
        self.regime_state = {
            'current': 'ROTATION',
            'candidate': 'ROTATION',
            'age': 0,
            'candidate_age': 0
        }
        
        # New Regime Hysteresis State
        self.regime_state = {
            'current': 'ROTATION',
            'candidate': 'ROTATION',
            'age': 0,
            'candidate_age': 0
        }

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

    def _safe_round(self, value, digits=2, default=0.0):
        """Helper to safe round values that might be None or strings"""
        try:
            if value is None or value == 'N/A': return default
            val = float(value)
            return round(val, digits)
        except:
            return default
            
    def _safe_f(self, value, default=0.0):
        """Helper to safe float cast"""
        try:
            if value is None or value == 'N/A': return default
            return float(value)
        except:
            return default

    def get_morning_brief(self, context_data, current_tick=None, symbol="BANKNIFTY"):
        """
        Generate the Morning Brief (PHASE-2 Precision)
        Delegates calculation to enrichment.morning
        """
        from enrichment.morning import calculate_pivots, calculate_cpr, analyze_gap, get_prior_candles
        from enrichment.session import calculate_morning_context

        vix_value = context_data.get('vix_spot', 'N/A')
        today_open = current_tick.get('open') if current_tick else None
        self.intraday_open = today_open  # Latch the day's open
        
        daily_data = context_data.get('daily_3', [])
        
        # 1. Calculate Expanded Pivots and CPR (Delegated)
        pivots = calculate_pivots(daily_data)
        cpr = calculate_cpr(daily_data)
        
        pivot = pivots['pivot']
        s1, s2 = pivots['s1'], pivots['s2']
        r1, r2 = pivots['r1'], pivots['r2']
        bc, tc = cpr['bc'], cpr['tc']
        
        # 2. Format 3-Day Candles (Delegated)
        d_candles = get_prior_candles(daily_data)
        
        # Helper for prior close
        prior_close = 0
        prior_range = 0
        if daily_data:
            prior_close = float(daily_data[0].get('c', daily_data[0].get('close', 0)))
            h = float(daily_data[0].get('h', daily_data[0].get('high', 0)))
            l = float(daily_data[0].get('l', daily_data[0].get('low', 0)))
            prior_range = h - l

        # 3. Analyze Gap (Delegated)
        gap_info = analyze_gap(today_open, prior_close)
        gap_points = gap_info['points']
        gap_pct = gap_info['percent']
        gap_direction = gap_info['direction']

        # 4. Authoritative Morning Context
        auth_context = calculate_morning_context(
            daily_hist=daily_data,
            current_price=today_open,
            support=s1,
            resistance=r1,
            pivot=pivot,
            vix=vix_value if isinstance(vix_value, (int, float)) else 15.0,
            atr_14=context_data.get('atr_14')
        )

        # Extract trade date
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
            prior_close=self._safe_round(prior_close, 2),
            prior_day_range_pts=self._safe_round(prior_range, 1),
            prior_trend_strength="N/A", # Optional refinement later
            vix_value=self._safe_round(vix_value, 2, 15.0),
            gap_direction=gap_direction,
            gap_points=gap_points,
            gap_percent=gap_pct,
            pivot_point=self._safe_round(pivot, 1),
            cpr_bc=self._safe_round(bc, 1),
            cpr_tc=self._safe_round(tc, 1),
            r1_zone=self._safe_round(r1, 1),
            r2_zone=self._safe_round(r2, 1),
            s1_zone=self._safe_round(s1, 1),
            s2_zone=self._safe_round(s2, 1),
            atr_14=self._safe_round(context_data.get('atr_14'), 2, 50.0),
            expected_range_pts=self._safe_round(auth_context.get('expected_range_pts'), 0, 150)
        )
        
        logger.debug(f"\n--- 🧠 BRAIN INPUT (MORNING) ---\n{prompt}\n--------------------------------")
        
        # ROUTING: BRAIN with purpose-specific system prompt
        data = self._query_model(SYSTEM_PROMPT_MORNING, prompt)
        
        if data:
            # 1. Inject pre-calculated IMMUTABLE LEVELS
            if 'reference_levels' not in data:
                data['reference_levels'] = {}
            
            data['reference_levels']['pivot'] = pivot
            data['reference_levels']['bc'] = bc
            data['reference_levels']['tc'] = tc
            data['reference_levels']['s1'] = s1
            data['reference_levels']['s2'] = s2
            data['reference_levels']['r1'] = r1
            data['reference_levels']['r2'] = r2
            
            # 2. Inject Authoritative Risk/Volatility Overrides
            if 'risk_regime' not in data:
                data['risk_regime'] = {}
                
            # Use authoritative VIX regime/range if available
            auth_vix = auth_context.get('vix_regime')
            auth_range = auth_context.get('expected_range_pts')
            
            if auth_vix: data['risk_regime']['vix_state'] = auth_vix
            if auth_range: data['risk_regime']['expected_move_pts'] = int(auth_range)

            # 3. Log the Policy Configuration
            logger.debug(f"      📐 Anchors: S={s1} | P={pivot} | R={r1}")
            logger.debug(f"      🛡️ Risk Regime: {data['risk_regime']['vix_state']} (Exp: {data['risk_regime']['expected_move_pts']} pts)")
            logger.debug(f"      📜 Tactical Permissions: {json.dumps(data.get('tactical_permissions', {}))}")

            return data
            
        return None
            
        return data

    def get_tactical_update(self, tick, context, plan, current_pnl, open_position, day_pnl=0.0, symbol="BANKNIFTY"):
        """
        Generate Tactical Update (TACTICAL -> WORKER)
        """
        # === v2.8 MODULAR RESEARCH ENGINE PIPELINE ===
        # Replaces thousands of lines of monolithic logic with deterministic modules
        try:
            data = self.research_engine.process_tick(context, plan)
            return data
        except Exception as e:
            logger.error(f"❌ Modular Pipeline Error: {e}", exc_info=True)
            return {"action": "HOLD", "reason": f"System Error in Modular Pipeline: {e}"}

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
        
        # PHASE 7: END-OF-DAY MISS DETECTION
        # if (trend_efficiency > 0.3 OR or_established) AND trades == 0: verdict = "MISS"
        trade_count = sum(1 for t in trades if t.get('pnl') is not None)
        ter = eod_data.get('trend_efficiency', 0.0)
        or_established = morning_plan.get('reference_levels', {}).get('or_estimate_high') is not None
        
        if trade_count == 0 and (ter > 0.3 or or_established):
             inject_miss_msg = "\n### CRITICAL SYSTEM ADVISORY:\nThis was a MISS day (Over-Filtering Detected). Zero trades executed despite clear Trend Efficiency > 0.3 OR OR Establishment.\n"
             prompt += inject_miss_msg
             logger.warning(f"      ⚠️ MISS VERDICT: Zero trades despite TrendEfficiency={ter:.2f}")

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
