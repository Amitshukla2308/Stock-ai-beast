FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Kolkata

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir redis apscheduler pytz fyers-apiv3 openai setuptools

# Copy Codebase
COPY . .

# Set Python path
ENV PYTHONPATH=/app

# Default command (can be overridden)
CMD ["python", "-m", "engine.live_engine"]
