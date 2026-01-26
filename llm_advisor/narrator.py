import logging
import json
from .schemas import PolicyContext, NarrativeOutput
from .prompts import SYSTEM_PROMPT_NARRATOR, USER_PROMPT_CONTEXT
# from brain.llm_client import LLMClient # Removed to break cycle

logger = logging.getLogger(__name__)

class PolicyNarrator:
    def __init__(self, llm_client):
        # We use the injected LLMClient to avoid circular imports and recursion
        self.llm_client = llm_client
        
    def explain_policy(self, context: PolicyContext) -> NarrativeOutput:
        """
        Generates a narrative justification for the policy decision.
        Returns a structured dictionary (NarrativeOutput).
        """
        # 1. Format the User Prompt with runtime context
        user_msg = USER_PROMPT_CONTEXT.format(
            regime_id=context['regime_id'],
            transition_mode=context['transition_mode'],
            transition_probability=context['transition_probability'],
            positioning_mode=context['positioning_mode'],
            allowed_actions=context['allowed_actions'],
            max_risk_multiplier=context['max_risk_multiplier'],
            policy_notes=context['policy_notes']
        )
        
        # 2. Query the Model (Deterministic Temp=0.1 via LLMClient default)
        # Using _query_model to leverage existing JSON cleaning/recovery logic
        try:
            response_data = self.llm_client._query_model(SYSTEM_PROMPT_NARRATOR, user_msg)
            
            if not response_data:
                return self._fallback_narrative(context, "LLM failed to respond.")
                
            # 3. Validate / Normalize Output
            return {
                "selected_policy": str(response_data.get('selected_policy', context['positioning_mode'])),
                "rationale": str(response_data.get('rationale', "Use standard operating procedures based on policy rules.")),
                "confidence": str(response_data.get('confidence', "STRUCTURAL"))
            }
            
        except Exception as e:
            logger.error(f"❌ PolicyNarrator Error: {e}")
            return self._fallback_narrative(context, str(e))

    def _fallback_narrative(self, context: PolicyContext, reason: str) -> NarrativeOutput:
        """Safe fallback if LLM is offline or errors."""
        return {
            "selected_policy": context['positioning_mode'],
            "rationale": f"Automated Policy Enforcement ({context['policy_notes']}). Narrative unavailable: {reason}",
            "confidence": "STRUCTURAL"
        }

if __name__ == "__main__":
    # Mock Test
    import time
    narrator = PolicyNarrator()
    
    # Mock Context: Regime 3 -> PREPARE for Alpha
    ctx: PolicyContext = {
        "regime_id": 3,
        "transition_mode": "PREPARE",
        "transition_probability": 0.173,
        "allowed_actions": ["PRE_POSITION"],
        "max_risk_multiplier": 0.5,
        "positioning_mode": "PRE_POSITION",
        "policy_notes": "Accumulate spot inventory for breakout."
    }
    
    print("⏳ Asking LLM to explain Regime 3 PREPARE policy...")
    # We need to wait for model ready in a real env, assuming LLMClient handles it or we manually poke
    # For this script run, we try once.
    
    result = narrator.explain_policy(ctx)
    print("\n--- LLM ADVISOR OUTPUT ---")
    print(json.dumps(result, indent=2))
