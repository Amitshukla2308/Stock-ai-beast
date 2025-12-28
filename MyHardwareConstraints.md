# My Hardware Constraints: Building "The Beast"
### Deploying vLLM on RTX 5090 Blackwell Architecture

## 1. Executive Summary
This case study documents the transformation of a high-end Windows 11 workstation into a **"Sovereign AI"** environment. The primary objective was to deploy the **vLLM** inference engine to utilize the **32GB GDDR7 VRAM** of the **NVIDIA RTX 5090 (Blackwell)** for local hosting of the **DeepSeek-R1-32B** model.

Through iterative troubleshooting, the project moved from a fragile Windows-native setup to a robust **WSL2-based hybrid architecture** that balances Windows usability with Linux-native performance.

## 2. Technical Profile: "The Beast"
* **GPU:** NVIDIA GeForce RTX 5090 (Blackwell Architecture, `sm_120`)
* **VRAM:** 32GB GDDR7 (34.19GB detected)
* **OS:** Windows 11 Pro (Host) + Ubuntu 24.04 (WSL2 Engine)
* **Primary AI Engine:** vLLM (Source-built with `cu128` support)
* **Storage Hub:** `D:\AI_HUB` (Secondary SSD for high-capacity model storage)

## 3. Key Challenges & Resolutions

### Problem 1: The "Roaming" Python Conflict
* **Symptoms:** Dependencies were installing to `AppData/Roaming` instead of the local Conda environment, causing version mismatches.
* **Resolution:** **Migration to WSL2.** By isolating the AI engine inside a Linux subsystem, we eliminated Windows pathing "pollution" and ensured that every dependency remained trapped within a dedicated virtual environment.

### Problem 2: Blackwell (sm_120) Compatibility
* **Symptoms:** Standard vLLM and PyTorch installations failed with `RuntimeError: no kernel image is available`.
* **Resolution:** **Compiling for the Sovereign Stack.** We utilized **CUDA 12.8 Nightly** builds and set the environment variable `TORCH_CUDA_ARCH_LIST="12.0"` to force the software to recognize the new Blackwell cores.

### Problem 3: The "Antigravity" Screen Flashing
* **Symptoms:** Windows Desktop Window Manager (DWM) conflicted with high-load AI tasks, causing screen flickering.
* **Resolution:** **MPO Registry Fix.** We disabled Multi-Plane Overlay (MPO) in the Windows registry, stabilizing the UI while the 5090 executed heavy tensor computations.

### Problem 4: System RAM Spillover (OOM)
* **Symptoms:** Models were defaulting to System RAM, resulting in <1 token/sec speeds.
* **Resolution:** **VRAM Residency Locking.** By implementing the `--gpu-memory-utilization 0.95` flag in vLLM and using **FP8 quantization**, we forced the weights to stay entirely within the 32GB GDDR7 cache.

## 4. The Sovereign Architecture (Final State)

### The Three-Zone Logic
#### 1. Windows 11 (The Control Center)
* **IDE:** VS Code + Antigravity.
* **Tools:** Docker Desktop (WSL2 Backend), NVIDIA Control Panel.

#### 2. WSL2 Ubuntu (The Engine Room)
* **Environment:** `beast_vllm` (Python 3.12).
* **Task:** Runs the high-performance vLLM server with direct GPU passthrough.

#### 3. D: Drive (The Vault)
* **Path:** `D:\AI_HUB`
* **Bridge:** Symlinked to `~/ai_hub` in Linux.
* **Benefit:** Zero-copy model loading. Weights are shared between Windows and Linux without duplication.

## 5. TESTED: Optimized Launch Protocol
To achieve maximum throughput on DeepSeek-R1, the following command was established:

```bash
vllm serve "neuralmagic/DeepSeek-R1-Distill-Qwen-32B-quantized.w8a8" \
    --quantization fp8 \
    --gpu-memory-utilization 0.92 \
    --max-model-len 16384 \
    --kv-cache-dtype fp8 \
    --enforce-eager

