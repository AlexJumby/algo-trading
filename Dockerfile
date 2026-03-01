FROM python:3.11-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Python deps (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY src/ src/
COPY scripts/ scripts/
COPY config/settings.example.yaml config/settings.example.yaml

# Create dirs for runtime data
RUN mkdir -p data logs config

# Default: paper trading
ENV BYBIT_API_KEY=""
ENV BYBIT_API_SECRET=""

ENTRYPOINT ["python"]
CMD ["scripts/run_live.py", "--mode", "paper"]
