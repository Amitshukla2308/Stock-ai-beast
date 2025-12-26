def risk_gate(inference_json: dict, technical_state: dict, portfolio_state: dict) -> bool:
    """
    The Deterministic Layer.
    Verifies if the AI's decision is safe to execute based on hard rules.
    """
    ai_action = inference_json.get("action", "HOLD").upper()
    ai_confidence = inference_json.get("confidence", 0.0)
    
    print(f"🛡️ [Guardrails] Checking AI Action: {ai_action} (Conf: {ai_confidence})")

    # Rule 0: HOLD is always safe
    if ai_action == "HOLD":
        return True

    # Rule 1: Confidence Threshold
    # We require higher confidence for entry than exit
    if ai_confidence < 0.75:
        print(f"🛑 Blocked: Low Confidence ({ai_confidence} < 0.75)")
        return False
        
    # Rule 2: Trend Alignment
    # Don't buy if trend is strongly DOWN
    if ai_action == "BUY" and technical_state["trend"] == "DOWN":
        print("🛑 Blocked: Buying in a DOWN trend is forbidden by policy.")
        return False
        
    # Rule 3: Volatility limit
    # If volatility is extreme (> 3%), AI might be hallucinating stability
    if technical_state["volatility"] > 3.0: 
        print(f"🛑 Blocked: Market too volatile ({technical_state['volatility']:.2f}%).")
        return False
        
    print("✅ Gate Passed.")
    return True
