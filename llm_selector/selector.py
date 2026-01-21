"""
v2.8 LLM Selector: Strategy Picker
Filters and presents allowed styles to the LLM.
Uses eligibility/style_eligibility.py to enforce rules BEFORE prompting.
"""
import logging
import json
from typing import List, Dict, Any

from brain.prompts import USER_PROMPT_TACTICAL, SYSTEM_PROMPT_TACTICAL
from eligibility.style_eligibility import evaluate_eligibility

logger = logging.getLogger(__name__)

class StrategySelector:
    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    def get_allowed_strategies(self, enrichment_data: Dict, signals: Dict) -> List[str]:
        """
        Get list of eligible strategies for this tick.
        """
        # 1. Run Quantitative Eligibility
        eligibility_map = evaluate_eligibility(enrichment_data, signals)
        
        # 2. Filter True keys
        allowed = [style for style, is_eligible in eligibility_map.items() if is_eligible]
        
        return allowed

    def select_style(self, eligible_styles: List[str], market_state: Dict, plan: Dict) -> Dict[str, Any]:
        """
        Query LLM to select the best style from eligible list.
        """
        if not self.llm_client:
            logger.error("LLM Client not initialized in Selector")
            return {"selected_style": "NONE", "reason": "Internal Error"}

        # 1. Construct Prompt
        # Format Market State
        state_str = json.dumps(market_state, indent=2)
        allowed_str = ", ".join(eligible_styles) if eligible_styles else "NONE (Defensive Mode)"
        
        # Plan Context
        bias = plan.get('primary_bias', 'NEUTRAL')
        levels = plan.get('reference_levels', {})
        
        # Construct Full Context Payload
        full_payload = {
            "symbol": market_state.get('symbol', 'Nifty'),
            "time": market_state.get('time', 'N/A'),
            "price": market_state.get('price', 0),
            "bias": bias,
            "reference_levels": levels,
            "market_state": market_state,
            "allowed_strategies": eligible_styles
        }
        
        json_payload_str = json.dumps(full_payload, indent=2)
        
        prompt = USER_PROMPT_TACTICAL.format(json_payload=json_payload_str)
        
        # 2. Query LLM
        response = self.llm_client._query_model(SYSTEM_PROMPT_TACTICAL, prompt)
        
        if not response:
             return {"selected_style": "NONE", "reason": "LLM No Response"}

        # 3. Parse Decision
        # Expected format: { "action": "BUY_CALL", "selected_style": "REMR", "confidence": 0.8, ... }
        return response

    def construct_style_prompt_segment(self, allowed_styles: List[str]) -> str:
        """
        Generate the prompt string limiting LLM choices.
        """
        if not allowed_styles:
            return "NO TRADING STRATEGIES AVAILABLE. MODE: DEFENSIVE."
            
        return f"ALLOWED STRATEGIES: {', '.join(allowed_styles)}"

# Global Instance (will need injection)
selector = StrategySelector()
