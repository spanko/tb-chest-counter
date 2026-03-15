# ============================================================================
# TB Chest Scanner — Dockerfile
# Playwright + Chromium headless for Azure Container Apps Jobs
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
COPY data/calibration.json ./data/calibration.json
RUN mkdir -p /app/data/screenshots /app/data/browser_data /tmp/screenshots
# Scanner entrypoint — reads clan config from env vars
CMD ["python", "src/main.py", "chests", "--cloud"]
