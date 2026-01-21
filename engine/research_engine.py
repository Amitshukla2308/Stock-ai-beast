"""
v2.8 Research Engine Orchestrator
The central pipeline that coordinates all modules to produce Trading Instructions.
Deterministic Execution Fabric.
"""
import logging
import json
from typing import Dict, Any

from config.config_loader import config
from enrichment.session import calculate_time_context
from enrichment.volatility import calculate_opening_range, calculate_expected_move_envelope, calculate_atr
from enrichment.trend import calculate_trend_efficiency, calculate_momentum_slope
from enrichment.levels import get_reference_levels
from enrichment.location import calculate_proximity, classify_location

from signals.rejection import detect_rejection_pattern
from signals.compression import detect_compression
from signals.range_break import detect_range_break
from signals.structural_break import detect_impulse, detect_structural_break
from signals.stall import detect_stall

from eligibility.style_eligibility import evaluate_eligibility
from confidence.confidence_engine import confidence_engine
from llm_selector.selector import StrategySelector
from risk.direction import decide_direction
from audit.trace_logger import trace_logger

logger = logging.getLogger(__name__)

class ResearchEngine:
    """
    Orchestrates the trading pipeline from raw data to final decision.
    """
    def __init__(self, llm_client):
        self.selector = StrategySelector(llm_client)
        
    def process_tick(self, context: Dict[str, Any], plan: Dict[str, Any], allow_llm: bool = True) -> Dict[str, Any]:
        """
        Executes the full modular pipeline.
        Returns: Decision Packet (Instructions)
        """
        # 0. Data Extraction
        current_time_str = context.get('time_str', 'N/A')
        close = context.get('close', 0.0)
        atr = calculate_atr(context.get('last_15min', []))
        if atr == 0: atr = 15.0 # Warmup default
        
        # [LOG] 0. TICK INPUT
        logger.info(f"[TICK] 🕒 {current_time_str} | Close: {close} | ATR: {atr}")

        today_5min = context.get('today_5min', [])
        last_15min = context.get('last_15min', [])
        daily_3 = context.get('daily_3', [])
        
        # 1. ENRICHMENT (Facts)
        time_ctx = calculate_time_context(current_time_str)
        
        or_data = calculate_opening_range(today_5min)
        or_range = or_data['or_range'] if or_data else 0.0
        
        prev_day = daily_3[0] if daily_3 else {}
        prior_day_range = (prev_day.get('h', 0) - prev_day.get('l', 0)) if prev_day else 0
        em_envelope = calculate_expected_move_envelope(or_range, prior_day_range)
        
        levels_dict = get_reference_levels(plan)
        
        # Safe extraction of trend efficiency
        ter_data = calculate_trend_efficiency(today_5min)
        ter, regime, regime_momentum = ter_data if isinstance(ter_data, tuple) else (0.0, "ROTATION", 0.0)

        # Safe extraction of momentum slope
        slope_data = calculate_momentum_slope(last_15min[-3:] if len(last_15min) >= 3 else [])
        m_slope, m_consistency = slope_data if isinstance(slope_data, tuple) else (0.0, 0.0)
        
        prox_data = calculate_proximity(close, levels_dict, or_range, atr)
        loc_data = classify_location(close, levels_dict, prox_data['proximity_limit'])
        
        # Consolidate Enrichment for downstream
        enrichment = {
            **time_ctx,
            **(or_data if or_data else {"or_high": None, "or_low": None, "or_range": 0.0}),
            **em_envelope,
            **levels_dict, # s1, s2, r1, r2, bc, tc, pivot
            "trend_efficiency": ter, "trend_regime": regime, "regime_momentum": regime_momentum,
            "momentum_slope": m_slope, "momentum_consistency": m_consistency,
            **prox_data, **loc_data,
            "or_established": or_data is not None,
            "atr": atr,
            "vix": context.get('vix', 15.0),
            "price": close,
            "symbol": context.get('symbol', 'Nifty'),
            "time": current_time_str
        }
        
        # [LOG] 1. ENRICHMENT
        logger.info(f"[ENRICH] 🌍 Regime: {regime} ({ter:.2f}) | Loc: {loc_data.get('location_class')} | Mom: {m_slope} | Range: {or_range:.0f}")
        
        # 2. SIGNALS (Patterns)
        last_bar_15 = last_15min[-1] if last_15min else {}
        rejection_pattern = detect_rejection_pattern(last_bar_15, last_15min[:-1])
        compression = detect_compression(last_bar_15.get('h', 0) - last_bar_15.get('l', 0), atr)
        range_break = detect_range_break(last_bar_15)
        impulse_detected, break_dir = detect_impulse(last_15min, atr)
        struct_break, struct_break_dir = detect_structural_break(close, enrichment['or_high'], enrichment['or_low'], atr)
        stall = detect_stall(last_bar_15, enrichment.get('near_htf', False)) # Simple stall
        
        signals = {
            "rejection": rejection_pattern != "NONE",
            "rejection_pattern": rejection_pattern,
            "compression": compression,
            "range_break": range_break,
            "impulse_detected": impulse_detected,
            "break_direction": break_dir,
            "structural_break": struct_break,
            "structural_break_direction": struct_break_dir,
            "stall": stall
        }
        
        # [LOG] 2. SIGNALS
        active_signals = [k for k, v in signals.items() if v and v != "NONE" and v is not False]
        logger.info(f"[SIGNAL] 📡 Detected: {active_signals if active_signals else 'None'}")

        # 3. ELIGIBILITY (Rules)
        eligible_styles_map = evaluate_eligibility(enrichment, signals)
        eligible_styles = [s for s, eligible in eligible_styles_map.items() if eligible]
        
        # [LOG] 3. ELIGIBILITY
        logger.info(f"[ELIG] 🚦 Allowed: {eligible_styles}")
        
        # 4. LLM GATE (Only skip if not tactical interval)
        if not allow_llm:
             return {
                "decision": {"action": "HOLD", "reason": "LLM Gated (Interval)"},
                "enrichment": enrichment, 
                "signals": signals, 
                "selected_style": "NONE", 
                "eligible_styles": eligible_styles
             }

        # 5. LLM TACTICAL CALL (Always at 15-min intervals - Non-Negotiable)
        market_state = {
            "price": round(close, 1),
            "trend_efficiency": ter,
            "regime": regime,
            "session_phase": time_ctx['session_phase'],
            "minutes_since_open": time_ctx['minutes_since_open'],
            "symbol": enrichment['symbol'],
            "time": enrichment['time'],
            "eligible_styles": eligible_styles
        }
        
        # LLM Selection
        selection = self.selector.select_style(eligible_styles if eligible_styles else ["HOLD"], market_state, plan)
        selected_style = selection.get('selected_style', 'NONE')
        
        # 6. CONFIDENCE (Always calculate if style selected)
        confidence = 0.0
        if selected_style not in ["NONE", "HOLD"]:
            confidence_map = confidence_engine.calculate_confidence([selected_style], enrichment)
            confidence = confidence_map.get(selected_style, 0.0)
            logger.info(f"[CONFID] 🧮 Score: {confidence} ({selected_style})")
        
        # 7. RISK (Direction & Expression)
        direction_data = {"action": "HOLD", "reason": "No Strategy Selected"}
        if selected_style not in ["NONE", "HOLD"]:
            direction_data = decide_direction(selected_style, enrichment, signals)
        elif selected_style == "HOLD":
            direction_data = {"action": "HOLD", "reason": selection.get('reason', 'LLM chose HOLD')}
            
        # 8. TRACEABILITY LOGGING (Always log tactical calls for EOD Audit)
        dummy_decision = {
            "action": direction_data['action'] if selected_style != "HOLD" else "HOLD", 
            "confidence": confidence, 
            "reason": selection.get('reason', 'Decision Processed')
        }
        trace_logger.log_decision_chain(
            tick={"timestamp": enrichment['time']},
            style=selected_style, 
            eligibility=eligible_styles_map,
            risk=direction_data,
            confidence={"score": confidence}, 
            decision=dummy_decision
        )
        
        # 9. Gating Returns: If no eligible styles OR LLM selected HOLD/NONE, exit gracefully
        if not eligible_styles or selected_style in ["NONE", "HOLD"]:
            logger.info(f"[LLM] 📝 Tactical Response: {selection.get('reason', 'No action')}")
            return {
                "decision": {"action": "HOLD", "reason": selection.get('reason', 'No eligible styles')},
                "enrichment": enrichment,
                "signals": signals,
                "selected_style": selected_style,
                "eligible_styles": eligible_styles
            }
            
        if direction_data['action'] == "HOLD":
             return {
                "decision": direction_data,
                "enrichment": enrichment,
                "signals": signals,
                "selected_style": selected_style,
                "eligible_styles": eligible_styles
             }
             
        # Merge Decision for Output
        decision = {
            # Base Decision
            "action": direction_data['action'],
            "selected_style": selected_style,
            "confidence": confidence,
            "reason": selection.get('reason', 'Signal Generated'),
            "engine_reason": direction_data.get('reason'), # Filter reason
            
            # Geometry (from LLM or Default)
            "entry_price": selection.get('entry_price', close),
            "sl": selection.get('sl'),
            "target": selection.get('target'),
            "expected_move_high": enrichment.get('expected_range_pts', 0),
            
            # Context used
            "ter": ter,
            "regime": regime
        }
        
        # Return full results for reporting/logging
        return {
            "decision": decision,
            "enrichment": enrichment,
            "signals": signals,
            "selected_style": selected_style,
            "eligible_styles": eligible_styles
        }
