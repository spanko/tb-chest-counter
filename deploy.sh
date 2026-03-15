#!/usr/bin/env bash
# ============================================================================
# TB Chest Counter — Deploy Infrastructure
# Usage:
#   ./deploy.sh dev                    # Deploy dev environment
#   ./deploy.sh prod                   # Deploy prod environment
#   ./deploy.sh dev --seed-secrets     # Deploy + populate Key Vault secrets
#   ./deploy.sh dev --schema           # Deploy + run DB schema migration
# ============================================================================

set -euo pipefail

ENV="${1:-dev}"
SHIFT_ARGS=1
SEED_SECRETS=false
RUN_SCHEMA=false

for arg in "${@:2}"; do
    case "$arg" in
        --seed-secrets) SEED_SECRETS=true ;;
        --schema)      RUN_SCHEMA=true ;;
        *)             echo "Unknown flag: $arg"; exit 1 ;;
    esac
done

RG_NAME="rg-tb-chest-counter-${ENV}"
LOCATION="westus2"
PARAM_FILE="infra/environments/${ENV}.bicepparam"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  TB Chest Counter — Deploying [$ENV]"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── Ensure resource group exists ────────────────────────────────────────────
echo "→ Ensuring resource group: $RG_NAME"
az group create \
    --name "$RG_NAME" \
    --location "$LOCATION" \
    --tags project=tb-chest-counter environment="$ENV" \
    --output none

# ── Deploy Bicep ────────────────────────────────────────────────────────────
echo "→ Deploying Bicep templates..."
DEPLOY_OUTPUT=$(az deployment group create \
    --resource-group "$RG_NAME" \
    --template-file infra/main.bicep \
    --parameters "$PARAM_FILE" \
    --query 'properties.outputs' \
    --output json)

echo "$DEPLOY_OUTPUT" | jq .

# Extract outputs
ACR_SERVER=$(echo "$DEPLOY_OUTPUT" | jq -r '.ACR_LOGIN_SERVER.value')
KV_NAME=$(echo "$DEPLOY_OUTPUT" | jq -r '.KEY_VAULT_NAME.value')
PG_FQDN=$(echo "$DEPLOY_OUTPUT" | jq -r '.POSTGRES_FQDN.value')
DASH_URL=$(echo "$DEPLOY_OUTPUT" | jq -r '.DASHBOARD_URL.value')

echo ""
echo "  ACR:        $ACR_SERVER"
echo "  Key Vault:  $KV_NAME"
echo "  PostgreSQL: $PG_FQDN"
echo "  Dashboard:  https://$DASH_URL"

# ── Seed Key Vault secrets (interactive) ────────────────────────────────────
if [ "$SEED_SECRETS" = true ]; then
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Seeding Key Vault secrets"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    # Anthropic API key (shared across all clans)
    echo -n "Anthropic API Key: "
    read -rs ANTHROPIC_KEY
    echo ""
    az keyvault secret set --vault-name "$KV_NAME" \
        --name "anthropic-api-key" --value "$ANTHROPIC_KEY" --output none
    echo "  ✓ anthropic-api-key"

    # PostgreSQL password
    echo -n "PostgreSQL admin password: "
    read -rs PG_PASS
    echo ""
    az keyvault secret set --vault-name "$KV_NAME" \
        --name "pg-password" --value "$PG_PASS" --output none
    echo "  ✓ pg-password"

    # Per-clan TB utility account credentials
    CLANS=$(echo "$DEPLOY_OUTPUT" | jq -r '.CLAN_JOBS.value[].clanId')
    for CLAN_ID in $CLANS; do
        echo ""
        echo "  Clan: $CLAN_ID"
        echo -n "    TB username: "
        read -r TB_USER
        echo -n "    TB password: "
        read -rs TB_PASS
        echo ""

        az keyvault secret set --vault-name "$KV_NAME" \
            --name "tb-${CLAN_ID}-username" --value "$TB_USER" --output none
        az keyvault secret set --vault-name "$KV_NAME" \
            --name "tb-${CLAN_ID}-password" --value "$TB_PASS" --output none
        echo "    ✓ tb-${CLAN_ID}-username"
        echo "    ✓ tb-${CLAN_ID}-password"
    done
fi

# ── Run database schema ────────────────────────────────────────────────────
if [ "$RUN_SCHEMA" = true ]; then
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Running database schema migration"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    echo -n "PostgreSQL admin password (or press enter to read from KV): "
    read -rs SCHEMA_PG_PASS
    echo ""

    if [ -z "$SCHEMA_PG_PASS" ]; then
        SCHEMA_PG_PASS=$(az keyvault secret show --vault-name "$KV_NAME" \
            --name "pg-password" --query "value" -o tsv)
    fi

    PGPASSWORD="$SCHEMA_PG_PASS" psql \
        -h "$PG_FQDN" \
        -U tbadmin \
        -d tbchests \
        -f infra/schema.sql

    echo "  ✓ Schema applied"

    # Seed clan records from param file
    echo "→ Seeding clan records..."
    for CLAN_ID in $(echo "$DEPLOY_OUTPUT" | jq -r '.CLAN_JOBS.value[].clanId'); do
        PGPASSWORD="$SCHEMA_PG_PASS" psql \
            -h "$PG_FQDN" -U tbadmin -d tbchests -c \
            "INSERT INTO clans (clan_id, clan_name, kingdom)
             VALUES ('$CLAN_ID', '$CLAN_ID', 225)
             ON CONFLICT (clan_id) DO NOTHING;"
    done
    echo "  ✓ Clan records seeded"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Deployment complete!"
echo ""
echo "  Next steps:"
echo "    1. Build & push scanner image:"
echo "       az acr build --registry ${ACR_SERVER%%.*} -t tb-chest-scanner:latest ./src"
echo "    2. Seed secrets (if not done):"
echo "       ./deploy.sh $ENV --seed-secrets"
echo "    3. Run schema (if not done):"
echo "       ./deploy.sh $ENV --schema"
echo "    4. Dashboard: https://$DASH_URL"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
