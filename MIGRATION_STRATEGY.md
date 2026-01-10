# 🚜 Migration Strategy: The "Unbundling" Refactor

**Objective**: Decouple the Monolithic "Stock AI Beast" into a Service-Oriented Architecture (SOA).
**Why**: To allow the GPU-heavy AI Core (`vLLM`) to persist as a shared utility while we restart/refactor the Trading Engine or run other apps (n8n).

---

## 1. Directory Structure Plan

We are moving from a single folder to a `projects` workspace.

```text
/home/beast/projects/
├── ai-core/                 # [NEW] The Shared GPU Stack
│   ├── docker-compose.yml   # vLLM, Ollama, Open WebUI
│   └── models/ -> D:\AI_HUB # Symlink to weights
│
├── stock-ai-beast/          # [EXISTING] The Trading System
│   ├── engine/              # Logic
│   ├── docker-compose.yml   # REDUCED (Stripped of AI)
│   └── trigger.py           # Control
│
└── n8n-flow/                # [NEW] Orchestration
    └── docker-compose.yml   # n8n, Postgres
```

---

## 2. Phase 1: Setup "AI Core" (The Server)

**Action**: Create `/home/beast/projects/ai-core/docker-compose.yml`.

### The Config
This service will own port `8000` (vLLM) and `11434` (Ollama).

```yaml
version: '3.8'
services:
  vllm:
    image: vllm/vllm-openai:latest
    container_name: ai_core_vllm
    runtime: nvidia
    environment:
      - TORCH_CUDA_ARCH_LIST=12.0
    volumes:
      - /mnt/d/AI_HUB/models/huggingface:/root/.cache/huggingface
    ports:
      - "8000:8000"  # EXPOSED TO HOST
    command: >
      --model /root/.cache/huggingface/hub/Qwen3-30B-A3B-Instruct-AWQ 
      --quantization awq --gpu-memory-utilization 0.95 --enforce-eager
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

  ollama:
    image: ollama/ollama:latest
    container_name: ai_core_ollama
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

volumes:
  ollama_data:
```

---

## 3. Phase 2: Refactor "Stock AI Beast" (The Client)

**Action**: Lobotomize `stock-ai-beast/docker-compose.llm.yml`.

### Requirements
1.  **DELETE** the `vllm` and `ollama` services.
2.  **UPDATE** `beast-engine` environment variables to point to the **Host Gateway**.

### The Config Change
```yaml
  beast-engine:
    environment:
      # OLD: http://beast_brain:8000/v1
      # NEW: Point to the Host Machine's Port 8000
      - BRAIN_API_BASE=http://host.docker.internal:8000/v1
      - WORKER_API_BASE=http://host.docker.internal:8000/v1
    extra_hosts:
      - "host.docker.internal:host-gateway"  # MAGIC SAUCE
```
*   `host.docker.internal` allows the container to talk to `localhost:8000` on your Windows/WSL machine, where `ai_core_vllm` is listening.

---

## 4. Phase 3: Setup "n8n" (The Orchestrator)

**Action**: Create `/home/beast/projects/n8n-flow/docker-compose.yml`.

### The Repo Structure
We will organize workflows by logical use-case to keep the repo clean.
```text
n8n-flow/
├── docker-compose.yml
├── .env
├── stock-ai-beast/      # [FOLDER] Trading Workflows
│   ├── control_plane.json
│   └── alerting.json
├── home-automation/     # [FOLDER] Future Use Case
└── personal-finance/    # [FOLDER] Future Use Case
```

### The Config
```yaml
version: '3.8'
services:
  n8n:
    image: n8nio/n8n:latest
    ports:
      - "5678:5678"
    environment:
      - N8N_HOST=n8n.local
      - WEBHOOK_URL=http://localhost:5678/
    extra_hosts:
      - "host.docker.internal:host-gateway" # Needs to talk to AI + Beast API
```

---

## 5. Repository Status
*   **AI Core**: `https://github.com/Amitshukla2308/ai-core` (Created)
*   **n8n Workflows**: `https://github.com/Amitshukla2308/n8n-workflows` (Created)
*   **Stock Beast**: `https://github.com/Amitshukla2308/Stock-ai-beast` (Existing)

## 6. Migration Checklist (For Next Session)

1.  **Stop Everything**:
    ```bash
    cd ~/projects/stock-ai-beast
    docker-compose -f docker-compose.llm.yml down
    ```
2.  **Move Up**:
    ```bash
    cd ..
    mkdir ai-core n8n-flow
    ```
3.  **Deploy AI Core** (Wait for model load):
    ```bash
    cd ai-core
    # Create docker-compose.yml
    docker-compose up -d
    # Test curl http://localhost:8000/v1/models
    ```
4.  **Deploy Beast** (Lite Version):
    ```bash
    cd ../stock-ai-beast
    # Edit docker-compose.llm.yml
    docker-compose -f docker-compose.llm.yml up -d
    ```
    
**Note**: You will not lose any data (DuckDB/Redis persistence remains in `stock-ai-beast/data`).
