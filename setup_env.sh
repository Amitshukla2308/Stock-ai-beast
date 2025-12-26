#!/bin/bash
set -e

echo "🚀 Starting The Beast Trading Environment Setup..."

# 1. Install uv if not present
if ! command -v uv &> /dev/null; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
else
    echo "✅ uv is already installed."
fi

# 2. Create Virtual Environment
echo "Creating virtual environment..."
uv venv .venv
source .venv/bin/activate

# 3. Install Dependencies
echo "Installing dependencies..."
# Core: vectorbt (backtesting), fyers-apiv3 (broker), duckdb (storage)
# AI: openai (standard client for vLLM)
# Utils: pandas, python-dotenv, numpy
uv pip install vectorbt fyers-apiv3 duckdb pandas numpy python-dotenv openai ta-lib

echo "✅ Environment Setup Complete!"
echo "To activate: source .venv/bin/activate"
