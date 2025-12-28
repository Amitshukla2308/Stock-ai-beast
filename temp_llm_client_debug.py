import os
import json
import time
from openai import OpenAI
from dotenv import load_dotenv
from brain.prompts import SYSTEM_PROMPT, MORNING_BRIEF_PROMPT, TACTICAL_UPDATE_PROMPT, EOD_JOURNAL_PROMPT

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
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg}
                ],
                temperature=0.1, # Forced deterministic
                top_p=0.9,
                max_tokens=1000 if not use_worker else 400 
            )
            content = response.choices[0].message.content
            # Strip markdown code blocks if present
            content = content.replace("```json", "").replace("```", "").strip()
            
            data = json.loads(content)
            
            # Monitoring Log
            lat = (time.time() - start)
            print(f"\n--- {role_icon} {role_name} OUTPUT ({lat:.2f}s) ---\n{content}\n-----------------------")
            
            return data
        except json.JSONDecodeError as e:
            print(f"❌ {role_icon} {role_name} JSON PARSE FAILURE: {e}")
            print(f"RAW CONTENT: {content}")
            return None
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
        current_price = current_tick['close'] if current_tick else None
        
        gap_points = round(current_price - prev_close, 2) if (prev_close and current_price) else 0.0
        if gap_points == 0.0 and (not prev_close or not current_price): 
            prev_close = "N/A"
            gap_points = 0.0
        
        # Calculate additional gap variables
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
        
        prompt = MORNING_BRIEF_PROMPT.format(
            symbol=symbol,
            market_data=market_data_str,
            vix_value=vix_value,
            gap_direction=gap_direction,
            gap_pts=gap_points,
            gap_pct=gap_pct,
            gap_type=gap_type,
            prev_close=prev_close
        )
        
        print(f"\n--- 🧠 BRAIN INPUT (MORNING) ---\n{prompt}\n--------------------------------")
        
        # ROUTING: BRAIN
        data = self._query_model(SYSTEM_PROMPT, prompt, use_worker=False)
        
        if data:
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
        o = tick.get('open', tick.get('o', 0))
        h = tick.get('high', tick.get('h', 0))
        l = tick.get('low', tick.get('l', 0))
        c = tick.get('close', tick.get('c', 0))
        current_ohlc = f"{o:.1f} / {h:.1f} / {l:.1f} / {c:.1f}"
        vix_value = context.get('vix_spot', 'N/A')
        
        # Morning Context
        morning_personality = plan.get('market_personality', 'UNKNOWN') if plan else 'UNKNOWN'
        morning_bias = plan.get('primary_bias', 'NEUTRAL') if plan else 'NEUTRAL'
        
        # Boundary Levels
        boundaries = plan.get('boundary_levels', {}) if plan else {}
        support_zone = boundaries.get('support_zone', 'N/A')
        resistance_zone = boundaries.get('resistance_zone', 'N/A')
        pivot_point = boundaries.get('pivot_point', 'N/A')
        
        # Position Details
        active_pos_details = "FLAT" if not open_position else f"{open_position['side']} @ {open_position.get('entry_price', 'N/A')}"
        
        # Format 5-min Candles (Last 3)
        today_5min = context.get('today_5min', [])
        recent_5min = today_5min[-3:] if today_5min else []
        last_5min_lines = []
        for bar in recent_5min:
            last_5min_lines.append(f"  {bar['ts']}: O={bar['o']:.1f} H={bar['h']:.1f} L={bar['l']:.1f} C={bar['c']:.1f}")
        last_5min_candles = "\n".join(last_5min_lines) if last_5min_lines else "No data"
        
        prompt = TACTICAL_UPDATE_PROMPT.format(
            symbol=symbol,
            atr_val=context.get('atr_14', 'N/A'),
            vol_regime=context.get('vol_regime', 'NORMAL'),
            current_range=context.get('current_range', 'N/A'),
            current_ohlc=current_ohlc,
            vix_value=vix_value,
            morning_personality=morning_personality,
            morning_bias=morning_bias,
            support_zone=support_zone,
            resistance_zone=resistance_zone,
            pivot_point=pivot_point,
            last_5min_candles=last_5min_candles,
            active_pos_details=active_pos_details,
            position_pnl=f"{current_pnl:.1f}",
            day_pnl=f"{day_pnl:.1f}"
        )
        
        print(f"\n--- 👷 WORKER INPUT (TACTICAL) ---\n{prompt}\n--------------------------------")
        
        # ROUTING: WORKER
        data = self._query_model(SYSTEM_PROMPT, prompt, use_worker=True)
        
        if data:
            # Output Normalization
            data['action'] = data.get('decision', 'HOLD')
            data['entry_price'] = data.get('entry')
            data['sl'] = data.get('sl')
            data['target'] = data.get('target')
            data['confidence'] = data.get('confidence')
            data['technical_reason'] = data.get('reason', '')
            
            action = data['action']
            reason = data['technical_reason']
            reason_short = reason[:40] + '...' if len(reason) > 40 else reason
            print(f"      🔸 {action} | {reason_short}")
            
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
        
        prompt = EOD_JOURNAL_PROMPT.format(
            symbol=symbol,
            morning_plan=morning_plan_str,
            execution_logs=execution_logs_str,
            eod_chart=eod_chart_str,
            session_id=session_id,
            total_pnl=f"{total_pnl:.2f}"
        )
        
        print(f"\n--- 🧠 BRAIN INPUT (EOD) ---\n{prompt}\n--------------------------------")
        
        # ROUTING: BRAIN
        data = self._query_model(SYSTEM_PROMPT, prompt, use_worker=False)
        if not data:
            return "Could not generate audit."
            
        nugget = data.get('dataset_nugget', 'N/A')
        audit_summary = f"PnL:{total_pnl:.1f} | {data.get('bias_efficiency', 'N/A')} | Nugget:{nugget}"
        print(f"      📊 EOD: {audit_summary}")
        
        return audit_summary
