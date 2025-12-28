import os
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
        """Generic wrapper for LLM call with JSON enforcement"""
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
            print(f"\n--- 🧠 BRAIN OUTPUT ---\n{content}\n-----------------------")
            lat = (time.time() - start)
            print(f"      ⚡ Brain Latency: {lat:.1f}s")
            return data
        except Exception as e:
            print(f"❌ Brain Freeze: {e}")
            return None

    def get_morning_brief(self, context_data, current_tick=None, symbol="BANKNIFTY"):
        """
        Generate the Morning Brief with the new VIX-aware schema.
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
        
        if prev_close and current_price:
            gap_points = round(current_price - prev_close, 2)
        else:
            gap_points = "N/A"
            prev_close = "N/A"
        
        prompt = MORNING_BRIEF_PROMPT.format(
            symbol=symbol,
            market_data=market_data_str,
            vix_value=vix_value,
            gap_points=gap_points,
            prev_close=prev_close
        )
        
        print(f"\n--- 🧠 BRAIN INPUT (MORNING) ---\n{prompt}\n--------------------------------")
        data = self._query_brain(SYSTEM_PROMPT, prompt)
        
        if data:
            personality = data.get('market_personality', 'N/A')
            vix_regime = data.get('vix_regime', 'N/A')
            bias = data.get('primary_bias', 'N/A')
            print(f"      🌅 {personality} | VIX:{vix_regime} | Bias:{bias}")
            
        return data

    def get_tactical_update(self, tick, context, plan, current_pnl, open_position, day_pnl=0.0, symbol="BANKNIFTY"):
        """
        Generate Tactical Update with the new VIX-aware schema.
        PRUNED: 15-min candles removed to reduce latency.
        OFFLOADED: ATR and Range provided as static technicals.
        """
        current_ohlc = f"{tick['open']:.1f} / {tick['high']:.1f} / {tick['low']:.1f} / {tick['close']:.1f}"
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
        if not open_position:
            active_pos_details = "FLAT"
        else:
            active_pos_details = f"{open_position['side']} @ {open_position.get('entry_price', 'N/A')}"
        
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
        
        print(f"\n--- 🧠 BRAIN INPUT (TACTICAL) ---\n{prompt}\n--------------------------------")
        data = self._query_brain(SYSTEM_PROMPT, prompt)
        
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
        Generate EOD Audit with the new schema.
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
        data = self._query_brain(SYSTEM_PROMPT, prompt)
        if not data:
            return "Could not generate audit."
            
        nugget = data.get('dataset_nugget', 'N/A')
        audit_summary = f"PnL:{total_pnl:.1f} | {data.get('bias_efficiency', 'N/A')} | Nugget:{nugget}"
        print(f"      📊 EOD: {audit_summary}")
        
        return audit_summary
