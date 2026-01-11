import os
import sys
from openai import OpenAI

# 1. Print Env Vars
print("--- DEBUG INFO ---")
api_base = os.getenv("BRAIN_API_BASE", "NOT_SET")
model = os.getenv("BRAIN_MODEL_NAME", "NOT_SET")
print(f"BRAIN_API_BASE: {api_base}")
print(f"BRAIN_MODEL_NAME: {model}")

# 2. Network Check
print("\n--- RESOLUTION CHECK ---", flush=True)
try:
    import socket
    print("Socket module imported", flush=True)
    hostname = api_base.split("://")[1].split(":")[0]
    print(f"Resolving: {hostname}", flush=True)
    ip = socket.gethostbyname(hostname)
    print(f"Resolved {hostname} to {ip}", flush=True)
except Exception as e:
    print(f"DNS Resolution Failed: {e}", flush=True)

# 3. OpenAI Client Check
print("\n--- CLIENT CHECK ---", flush=True)
try:
    client = OpenAI(base_url=api_base, api_key="EMPTY", timeout=10.0)
    print(f"Client created with base_url={client.base_url}", flush=True)
    
    # Simple list models call
    print("Listing models...", flush=True)
    models = client.models.list()
    print(f"Models found: {[m.id for m in models]}", flush=True)

    # Chat Completion Call
    print("Attempting Chat Completion...", flush=True)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=10
    )
    print("SUCCESS: Chat Completion works!", flush=True)
    print(f"Response: {response.choices[0].message.content}", flush=True)

except Exception as e:
    print(f"FAILURE: {e}", flush=True)
