from brain.llm_client import LLMClient
import sys

def test():
    print("Initializing Client...")
    try:
        client = LLMClient()
    except Exception as e:
        print(f"❌ Client Init Failed: {e}")
        return

    print("\n-------------------------------------------------")
    print("🧠 Testing Brain Connection (Single Model)...")
    try:
        # Test 1: Simple JSON check
        response = client._query_model(
            "You are a system check tool. Output only JSON.", 
            "Respond with JSON: {'status': 'online', 'role': 'single_model'}"
        )
        if response:
            print(f"✅ Brain Response: {response}")
        else:
            print("❌ Brain Response Failed (None)")
            
    except Exception as e:
        print(f"❌ Brain Exception: {e}")

if __name__ == "__main__":
    test()
