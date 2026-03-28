# ============================================================================
# TB Chest Scanner — MONOLITHIC Dockerfile (fallback / first-time setup)
#
# Use this if you don't have the base image in ACR yet, or for CI builds
# that need a single self-contained Dockerfile.
#
# For fast iteration, switch to the two-stage approach:
#   1. Build base once:  az acr build --registry <ACR> --image tb-scanner-base:v1 --file Dockerfile.base .
#   2. Build scanner:    az acr build --registry <ACR> --image tb-chest-scanner:candidate --file Dockerfile.scanner .
#
# The base image caches Playwright+Chromium+deps (~2-3 min).
# Scanner builds on top add only src/config/data (~10 sec).
# ============================================================================

FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (Chromium only, saves ~400MB)
RUN playwright install chromium --with-deps

# Copy scanner source
COPY src/ ./src/
COPY config/ ./config/

# Copy calibration profile (pre-calibrated at 1280x720)
COPY data/calibration.json ./data/calibration.json

# Copy browser data with pre-baked session cookies to bypass login
COPY data/browser_data/ ./data/browser_data/

# Ensure data directories exist
RUN mkdir -p /app/data/screenshots /app/data/browser_data /tmp/screenshots

# Scanner entrypoint — reads clan config from env vars
CMD ["python", "src/main.py", "chests", "--cloud"]
