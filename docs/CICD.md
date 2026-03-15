# CI/CD Setup — GitHub Actions → Azure

## How the Pipeline Works

```
Push to main (src/, Dockerfile, requirements.txt changes)
    │
    ▼
┌─ BUILD ──────────────────────────────────────┐
│  Docker build → push to ACR                  │
│  Tags: sha-abc1234, candidate                │
└──────────────────────────────────────────────┘
    │
    ▼
┌─ SMOKE TEST ─────────────────────────────────┐
│  Trigger ACA Job: tb-smoke-test              │
│  Image: :candidate                           │
│  Mode: smoke (login → navigate → screenshot  │
│         → vision extract → NO chest writes)  │
│  Artifacts: screenshots uploaded to GH       │
└──────────────────────────────────────────────┘
    │ pass?
    ▼
┌─ PROMOTE ────────────────────────────────────┐
│  Retag: sha-abc1234 → :production            │
│  Update all ACA scanner jobs to new SHA tag  │
│  Next scheduled run uses the new image       │
└──────────────────────────────────────────────┘
```

**In-flight safety:** ACA Jobs that are already running continue on their
existing container. The image update only affects *future* executions.
There is no disruption to running scans.

## GitHub Repository Secrets

Set these in Settings → Secrets and variables → Actions:

| Secret | Value | Where to Get |
|--------|-------|-------------|
| `AZURE_CLIENT_ID` | App registration client ID | `az ad app show --id <app> --query appId` |
| `AZURE_TENANT_ID` | Azure AD tenant ID | `az account show --query tenantId` |
| `AZURE_SUBSCRIPTION_ID` | Azure subscription ID | `az account show --query id` |
| `ACR_LOGIN_SERVER` | e.g., `tbdevacr123456.azurecr.io` | Bicep output `ACR_LOGIN_SERVER` |
| `ACR_NAME` | e.g., `tbdevacr123456` | Registry name (no `.azurecr.io`) |
| `AZURE_RESOURCE_GROUP` | e.g., `rg-tb-chest-counter-dev` | Your resource group |
| `ACA_ENVIRONMENT_NAME` | e.g., `tbdev-env-abc123` | Bicep output `ACA_ENVIRONMENT_NAME` |
| `STORAGE_ACCOUNT` | Storage account name (for smoke screenshots) | Optional |

## Setting Up Azure OIDC for GitHub Actions

This avoids storing service principal secrets. GitHub authenticates directly
with Azure AD using OpenID Connect.

```bash
# 1. Create app registration
az ad app create --display-name "tb-chest-counter-cicd"
APP_ID=$(az ad app list --display-name "tb-chest-counter-cicd" --query "[0].appId" -o tsv)

# 2. Create service principal
az ad sp create --id $APP_ID
SP_OBJECT_ID=$(az ad sp show --id $APP_ID --query id -o tsv)

# 3. Grant Contributor on resource group
az role assignment create \
    --assignee $SP_OBJECT_ID \
    --role Contributor \
    --scope /subscriptions/<sub-id>/resourceGroups/rg-tb-chest-counter-dev

# 4. Add federated credential for GitHub Actions
az ad app federated-credential create --id $APP_ID --parameters '{
    "name": "github-main",
    "issuer": "https://token.actions.githubusercontent.com",
    "subject": "repo:spanko/tb-chest-counter:ref:refs/heads/main",
    "audiences": ["api://AzureADTokenExchange"]
}'

# 5. Also add credential for pull requests (if you want PR smoke tests)
az ad app federated-credential create --id $APP_ID --parameters '{
    "name": "github-pr",
    "issuer": "https://token.actions.githubusercontent.com",
    "subject": "repo:spanko/tb-chest-counter:pull_request",
    "audiences": ["api://AzureADTokenExchange"]
}'
```

## Manual Workflow Triggers

From the GitHub Actions tab, you can manually trigger the workflow:

- **Skip smoke test** (emergency deploy): Check "Skip smoke test"
- **Smoke test only** (validate without deploying): Check "Run smoke test only"

## Smoke Test Details

The smoke test runs against the first clan in your config (FOR main).
It exercises the full pipeline:

1. **Login** — Playwright opens TB, authenticates with utility account
2. **Navigate** — Clicks through to Clan → Gifts tab
3. **Screenshot** — Captures the gifts page
4. **Vision extract** — Sends to Claude Haiku, parses structured response
5. **Scroll** — Scrolls down if more gifts exist

It does NOT:
- Write to the `chests` table
- Trigger deduplication
- Count toward scan statistics
- Affect leaderboards

Screenshots are uploaded as GitHub Actions artifacts (retained 7 days)
so you can visually verify what the scanner saw.

## Image Tag Strategy

| Tag | Purpose | Who Updates |
|-----|---------|-------------|
| `sha-abc1234` | Immutable, pinned to commit | Build step |
| `candidate` | Latest build, pre-promotion | Build step |
| `production` | Current promoted build | Promote step |
| `latest` | Alias for production | Promote step |

Scanner ACA Jobs are always pinned to a specific `sha-*` tag, never
`:latest` or `:production`. This guarantees reproducibility — you can
always tell exactly which code a scan ran on.
