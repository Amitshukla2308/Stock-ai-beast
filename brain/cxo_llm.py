import os
import json
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

VLLM_API_BASE = os.getenv("VLLM_API_BASE", "http://localhost:8000/v1")
VLLM_API_KEY = os.getenv("VLLM_API_KEY", "EMPTY") 
MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B")

client = OpenAI(
    base_url=VLLM_API_BASE,
    api_key=VLLM_API_KEY,
)

def get_cxo_decision(prompt: str) -> dict:
    """
    Sends the prompt to the LLM and parses the response.
    """
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "You are a JSON-only trading bot. Output valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3, # Lower temperature for more deterministic/logic-based output
            max_tokens=300
        )
        
        content = response.choices[0].message.content
        
        # Strip markdown code blocks if present
        clean_content = content.replace("```json", "").replace("```", "").strip()
        
        decision = json.loads(clean_content)
        return decision
        
    except json.JSONDecodeError:
        print(f"❌ CXO Parse Error. Raw output: {content[:50]}...")
        return {"action": "HOLD", "confidence": 0.0, "reasoning": "Parse Error"}
        
    except Exception as e:
        print(f"❌ CXO Connection Error: {e}")
        return {"action": "HOLD", "confidence": 0.0, "reasoning": "Connection Error"}
