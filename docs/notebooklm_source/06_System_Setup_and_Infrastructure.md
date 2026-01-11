# 6. System Setup & Infrastructure

## Hardware Architecture: "The Beast" Rig
The system is designed to run on a high-end consumer workstation with specific focus on GPU VRAM for local LLM inference.

### Specifications
*   **GPU**: NVIDIA GeForce RTX 5090 (Blackwell Architecture)
    *   **VRAM**: 32GB GDDR7 (Critical for hosting Qwen 30B models locally)
    *   **Driver**: CUDA 12.8 Nightly (required for `sm_120` support)
*   **Storage**: Dedicated NVMe SSD (`D:\AI_HUB`) for model weights (Symlinked to WSL2).
*   **OS**: Windows 11 Pro (Host) + Ubuntu 24.04 (WSL2 Subsystem).

---

## Software Ecosystem

### 1. Operating Environment (Hybrid)
*   **Host**: Windows 11 (VS Code, Docker Desktop).
*   **Execution**: WSL2 Ubuntu 24.04 (All compute happens here).
*   **Virtualization**: Docker Containers (GPU Passthrough enabled).

### 2. Container Orchestration (`docker-compose.llm.yml`)
The system runs as a cluster of 4 coupled services attached to a custom bridge network `beast_net`.

| Service | Container Name | Technology | Role |
| :--- | :--- | :--- | :--- |
| **Brain** | `beast_brain` | **vLLM** (OpenAI API) | Hosts Qwen3-30B locally. Exposes API at `http://localhost:8000`. |
| **Engine** | `beast_engine` | Python 3.12 | Runs the Strategy, Risk Manager, and Auditor. |
| **Producer** | `beast_producer` | Python 3.12 | Fetches data (Fyers API) and pushes to Redis. |
| **Bus** | `beast_redis` | Redis 7 | Pub/Sub messaging for ticks. Data persistence for state. |

### 3. Key Software Libraries
*   **Inference**: `vLLM` (v0.6.x+) with `--quantization awq` and FP8 KV-Cache.
*   **Database**: `DuckDB` (OLAP for 5-year history) + `Redis` (Real-time).
*   **Language**: Python 3.12.
*   **Broker Connectivity**: `fyers-apiv3` (NSE Data & Execution).

---

## Configuration & Secrets

### Environment Variables (`.env`)
The system requires a `.env` file in the root directory:
```bash
# Broker Credentials
FYERS_CLIENT_ID=your_client_id
FYERS_SECRET_ID=your_secret_id

# AI Credentials
HF_TOKEN=your_huggingface_token (for model download)
BRAIN_API_BASE=http://beast_brain:8000/v1
```

### Model Storage
*   Models are stored in `D:\AI_HUB` on Windows.
*   Mapped to `/root/.cache/huggingface` inside the `beast_brain` container via Docker volumes.
*   **Current Model**: `Qwen/Qwen2.5-14B-Instruct-Q8` (or similar 30B variant).

---

## Networking Flow
1.  **Fyers API** sends ticks via WebSocket -> **Producer**.
2.  **Producer** publishes to **Redis** Channel `TICKS:NIFTY`.
3.  **Engine** subscribes to `TICKS:NIFTY`.
4.  **Engine** constructs prompt -> sends HTTP POST to **Brain** (`http://beast_brain:8000`).
5.  **Brain** infers on RTX 5090 -> returns JSON decision.
6.  **Engine** validates -> sends Order to **Fyers API**.
