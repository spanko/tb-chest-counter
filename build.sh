#!/usr/bin/env bash
# ============================================================================
# build.sh — Build & push Docker images for TB Chest Scanner
#
# Usage:
#   ./build.sh base              # Build base image (Playwright+deps) — run once or when requirements.txt changes
#   ./build.sh scanner           # Build scanner image (code only) — run on every code change
#   ./build.sh scanner --local   # Build locally with Docker Desktop and push (fastest)
#   ./build.sh all               # Build both base + scanner
#   ./build.sh scanner --promote # Retag candidate → latest after smoke test passes
# ============================================================================

set -euo pipefail

# --- Configuration (override with env vars) ---
ACR_NAME="${ACR_NAME:-tbdevacrb7jbhj}"
ACR_SERVER="${ACR_NAME}.azurecr.io"
BASE_IMAGE="tb-scanner-base"
BASE_TAG="${BASE_TAG:-v1}"
SCANNER_IMAGE="tb-chest-scanner"
RESOURCE_GROUP="${RESOURCE_GROUP:-rg-tb-chest-counter-dev}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${CYAN}[build]${NC} $1"; }
ok()   { echo -e "${GREEN}[build]${NC} $1"; }
warn() { echo -e "${YELLOW}[build]${NC} $1"; }
err()  { echo -e "${RED}[build]${NC} $1" >&2; }

usage() {
    echo "Usage: ./build.sh <command> [flags]"
    echo ""
    echo "Commands:"
    echo "  base                Build base image (Playwright+Chromium+deps)"
    echo "  scanner             Build scanner image (code layer only)"
    echo "  all                 Build base + scanner"
    echo ""
    echo "Flags:"
    echo "  --local             Build locally with Docker Desktop and push to ACR"
    echo "  --promote           Retag candidate → latest (after smoke test passes)"
    echo "  --base-tag TAG      Base image tag (default: v1)"
    echo ""
    echo "Environment variables:"
    echo "  ACR_NAME            ACR registry name (default: tbdevacrb7jbhj)"
    echo "  BASE_TAG            Base image tag (default: v1)"
    echo "  RESOURCE_GROUP      Azure resource group (default: rg-tb-chest-counter-dev)"
    exit 1
}

build_base_remote() {
    log "Building base image in ACR (Playwright + Chromium + deps)..."
    log "This takes 2-3 minutes. Only needed when requirements.txt changes."
    echo ""

    az acr build \
        --registry "$ACR_NAME" \
        --image "${BASE_IMAGE}:${BASE_TAG}" \
        --file Dockerfile.base \
        "."

    ok "Base image pushed: ${ACR_SERVER}/${BASE_IMAGE}:${BASE_TAG}"
}

build_base_local() {
    log "Building base image locally..."

    docker build \
        -f Dockerfile.base \
        -t "${ACR_SERVER}/${BASE_IMAGE}:${BASE_TAG}" \
        .

    log "Pushing base image to ACR..."
    az acr login --name "$ACR_NAME"
    docker push "${ACR_SERVER}/${BASE_IMAGE}:${BASE_TAG}"

    ok "Base image pushed: ${ACR_SERVER}/${BASE_IMAGE}:${BASE_TAG}"
}

build_scanner_remote() {
    log "Building scanner image in ACR (code layer only)..."

    # Get git SHA for tagging
    local SHA
    SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

    az acr build \
        --registry "$ACR_NAME" \
        --image "${SCANNER_IMAGE}:candidate" \
        --image "${SCANNER_IMAGE}:sha-${SHA}" \
        --file Dockerfile.scanner \
        --build-arg "ACR_SERVER=${ACR_SERVER}" \
        --build-arg "BASE_TAG=${BASE_TAG}" \
        "."

    ok "Scanner image pushed: ${ACR_SERVER}/${SCANNER_IMAGE}:candidate (sha-${SHA})"
    echo ""
    log "Next: run smoke test, then './build.sh scanner --promote' to go live"
}

build_scanner_local() {
    log "Building scanner image locally with Docker Desktop..."

    local SHA
    SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

    docker build \
        -f Dockerfile.scanner \
        --build-arg "ACR_SERVER=${ACR_SERVER}" \
        --build-arg "BASE_TAG=${BASE_TAG}" \
        -t "${ACR_SERVER}/${SCANNER_IMAGE}:candidate" \
        -t "${ACR_SERVER}/${SCANNER_IMAGE}:sha-${SHA}" \
        .

    log "Pushing to ACR..."
    az acr login --name "$ACR_NAME"
    docker push "${ACR_SERVER}/${SCANNER_IMAGE}:candidate"
    docker push "${ACR_SERVER}/${SCANNER_IMAGE}:sha-${SHA}"

    ok "Scanner image pushed: ${ACR_SERVER}/${SCANNER_IMAGE}:candidate (sha-${SHA})"
    ok "Local build + push completed — much faster than remote az acr build!"
    echo ""
    log "Next: run smoke test, then './build.sh scanner --promote' to go live"
}

promote() {
    log "Promoting candidate → latest..."

    # Import candidate as latest (ACR-side retag, no download needed)
    az acr import \
        --name "$ACR_NAME" \
        --source "${ACR_SERVER}/${SCANNER_IMAGE}:candidate" \
        --image "${SCANNER_IMAGE}:latest" \
        --force

    ok "Promoted: ${SCANNER_IMAGE}:candidate → ${SCANNER_IMAGE}:latest"
    echo ""
    log "ACA Jobs referencing :latest will pick this up on next trigger."
    log "To force immediate update:"
    echo "  az containerapp job update --name tbdev-scan-for-main --resource-group $RESOURCE_GROUP --image ${ACR_SERVER}/${SCANNER_IMAGE}:latest"
}

# --- Parse arguments ---
COMMAND="${1:-}"
shift || true

LOCAL=false
PROMOTE=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --local)    LOCAL=true; shift ;;
        --promote)  PROMOTE=true; shift ;;
        --base-tag) BASE_TAG="$2"; shift 2 ;;
        *)          err "Unknown flag: $1"; usage ;;
    esac
done

# --- Dispatch ---
case "$COMMAND" in
    base)
        if $LOCAL; then
            build_base_local
        else
            build_base_remote
        fi
        ;;
    scanner)
        if $PROMOTE; then
            promote
        elif $LOCAL; then
            build_scanner_local
        else
            build_scanner_remote
        fi
        ;;
    all)
        if $LOCAL; then
            build_base_local
            build_scanner_local
        else
            build_base_remote
            build_scanner_remote
        fi
        ;;
    *)
        usage
        ;;
esac
