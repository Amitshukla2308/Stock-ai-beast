import os
from openai import OpenAI
import json
from dotenv import load_dotenv

load_dotenv()

VLLM_API_BASE = os.getenv("VLLM_API_BASE", "http://localhost:8000/v1")
VLLM_API_KEY = os.getenv("VLLM_API_KEY", "EMPTY") 
MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B")

client = OpenAI(
    base_url=VLLM_API_BASE,
    api_key=VLLM_API_KEY,
)

def analyze_market_regime(technical_summary, news_summary):
    prompt = f"""
    You are a Senior Risk Manager for a quantitative trading fund.
    Analyze the following market data and determine the current market regime.
    
    Technical Summary:
    {technical_summary}
    
    News Summary:
    {news_summary}
    
    Output strictly in JSON format with the following keys:
    - "regime": One of ["BULLISH", "BEARISH", "VOLATILE", "SIDEWAYS"]
    - "risk_score": A number between 0 (Safe) and 10 (Extreme Danger)
    - "suggested_cash_buffer": Percentage of portfolio to keep in cash (0.0 to 1.0)
    - "reasoning": Brief explanation.
    """
    
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "You are a helpful AI assistant that outputs JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=500
        )
        content = response.choices[0].message.content
        clean_content = content.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_content)
        
    except Exception as e:
        print(f"Error calling AI: {e}")
        return {
            "regime": "UNKNOWN",
            "risk_score": 10,
            "suggested_cash_buffer": 1.0,
            "reasoning": "AI Service Unavailable"
        }
