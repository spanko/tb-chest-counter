# TB Chest Counter — Next Steps (for new Claude conversation)

## Context

Adam is building a multi-clan Total Battle chest counter deployed to Azure.
The repo is `spanko/tb-chest-counter` (GitHub, master branch). This is a
continuation of work done across multiple conversations and Claude Code sessions.

## Current Blocker: Cloud Login Failure

The scanner container starts, connects to PostgreSQL, loads calibration, launches
Chromium, and calls the Claude Vision API — but **cannot authenticate with Total Battle
in the cloud environment**. It gets stuck on the login/registration page.

### What Vision sees in the cloud

```
"Welcome back! Enter your data to login"
```

The scanner is screenshotting the login page, not the gifts tab. 0 gifts extracted.

### What works locally

Locally with `--visible`, the scanner logs in, navigates to Gifts, extracts 8+ chests
with 100% accuracy. The persistent browser context at `data/browser_data/` caches
session cookies so subsequent runs skip the login flow.

### Root cause candidates (from Claude Code investigation)

1. **No persistent session in cloud** — each container run starts with empty
   `data/browser_data/`. No cached cookies. Login must work from scratch every time.
2. **Email input not found** — after clicking "Log in", the email/password fields
   aren't being located. This could be timing (form not rendered yet) or different
   DOM structure in headless mode.
3. **IP/geo restrictions** — Azure datacenter IPs may be blocked or redirected to
   a different login flow by Total Battle.
4. **Bot detection** — TB may detect the headless browser despite stealth patches
   and serve a different page (CAPTCHA, challenge, or altered DOM).
5. **Browser fingerprinting** — headless Chromium in a container has a different
   fingerprint than a real Windows Chrome session.

### What Claude Code attempted

1. Added screenshot upload to Azure Blob Storage for debugging visibility
2. Modified `browser.py`, `main.py`, and `requirements.txt` to support uploads
3. Added `azure-storage-blob>=12.19.0` to requirements
4. **Problem**: The package wasn't properly installed due to Docker layer caching
5. **Problem**: Even with code changes, no screenshots reached blob storage
6. Built and deployed multiple image iterations — login still fails

### What's needed to unblock

**Option A: Fix the headless login** (ideal but may be hard)
- Take debug screenshots at every step of the login flow
- Check if the DOM is different in headless vs headed mode
- Add explicit waits after clicking "Log in" before looking for email field
- Try different selectors, longer timeouts
- Test locally in headless mode: `python src/main.py smoke` (no --visible)

**Option B: Pre-bake session cookies** (pragmatic workaround)
- Log in once locally with `--visible`
- Export the `data/browser_data/` directory (contains session cookies)
- Bake it into the Docker image via `COPY data/browser_data/ ./data/browser_data/`
- Session cookies may persist for days/weeks, reducing login frequency
- Will need periodic re-login when cookies expire

**Option C: Use a different authentication approach**
- TB may have an API-based login that bypasses the web form
- Check if the Sendbird/game server endpoints accept direct auth
- This was explored earlier and deemed impractical (binary MessagePack protocol)

### Key code locations for login debugging

- `src/browser.py` lines ~160-280: The `login()` method
- Email input selectors tried: `get_by_placeholder("Email")`, `input[type='email']`,
  `input[name='email']`, `input[placeholder*='mail' i]`
- Password: `get_by_placeholder("Password")`
- Submit: `get_by_role("button", name="LOGIN")`

### Screenshot upload infrastructure (partially built by Claude Code)

- `azure-storage-blob` added to requirements.txt
- `browser.py` `_debug_screenshot()` modified to upload to blob when in cloud mode
- `main.py` passes blob connection string and run_id via config
- `aca-scanner-job.bicep` has `azure-storage-connection-string` secret configured
- **Not yet working** — needs a `--no-cache` rebuild to ensure package is installed

## What's fully deployed and working

### Azure Infrastructure
- Resource Group: `rg-tb-chest-counter-dev`
- ACA Environment: `tbdev-env-b7jbhj` (Consumption tier)
- ACA Job (scanner): `tbdev-scan-for-main` (cron: every 4 hours)
- ACA Job (smoke test): `tb-smoke-test` (manual trigger)
- PostgreSQL Flex: `tbdev-pg-b7jbhj.postgres.database.azure.com` / `tbchests` (B1ms)
- Container Registry: `tbdevacrb7jbhj.azurecr.io`
- Key Vault: `tbdev-kv-b7jbhj` (secrets seeded)
- Static Web App: `witty-hill-0bd97521e.6.azurestaticapps.net` (dashboard, not built yet)
- All Bicep in `infra/` — modular, parameterized, working
- GitHub Actions CI/CD in `.github/workflows/deploy.yml` (needs OIDC setup)
- Log Analytics workspace ID: `84afec13-9a92-4daf-af9f-620e7cd84767`

### Database (schema applied, working)
- Tables: clans, clan_members, chests, chest_types, scan_runs
- Views: v_leaderboard_7d, v_clan_summary, v_player_breakdown
- Chest types seeded with point values
- PostgreSQL firewall open (0.0.0.0-255.255.255.255 for dev — lock down later)

### Scanner code (working locally, login fails in cloud)
- `config.py` — returns dict from env vars (cloud) or settings.json (local)
- `storage_pg.py` — PostgreSQL storage with dedup, point lookup, roster matching
- `main.py` — CLI with `chests`, `smoke`, `export` commands + `--cloud` flag
- `browser.py` — Playwright with stealth, calibration-based navigation
- `vision.py` — Claude Vision extraction (100% accuracy with Haiku)
- `calibration.py` — Vision-based coordinate detection (calibration.json baked into Docker)
- Dockerfile builds and runs in ACA

### Smoke test results (latest cloud run)
- Container starts: ✅
- Config from env vars: ✅
- PostgreSQL connects: ✅ (scan run 6 recorded)
- Calibration loads: ✅
- Playwright launches: ✅
- TB page loads: ✅
- "Log in" link clicked: ✅
- Email field found: ❌ **BLOCKER**
- Login completes: ❌
- Navigation to Gifts: ❌ (clicks calibrated coords but on login screen)
- Vision extraction: ✅ (ran, correctly reported 0 gifts on login screen)
- Screenshot upload to blob: ❌ (package not installed properly)

## After login is fixed

1. **Run a real chest scan**: trigger `tbdev-scan-for-main` and verify
   chests appear in PostgreSQL
2. **Set up GitHub OIDC**: follow `docs/CICD.md` — create app registration,
   federated credentials, populate GitHub secrets
3. **Build the dashboard**: Static Web App with Functions API backend
   querying PostgreSQL
4. **Add more clans**: edit `infra/environments/dev.bicepparam`, seed KV secrets, redeploy
5. **Lock down PostgreSQL firewall**: remove 0.0.0.0 rule
6. **Prod deployment**: separate resource group with `enablePublicAccess = false`

## Key commands reference

```powershell
# Rebuild and push Docker image (remote, no layer cache, 2-3 min)
az acr build --registry tbdevacrb7jbhj --image "tb-chest-scanner:latest" --image "tb-chest-scanner:candidate" --file Dockerfile "."

# For faster iteration: build locally + push (requires Docker Desktop)
az acr login --name tbdevacrb7jbhj
docker build -t tbdevacrb7jbhj.azurecr.io/tb-chest-scanner:candidate .
docker push tbdevacrb7jbhj.azurecr.io/tb-chest-scanner:candidate

# Force no-cache rebuild (when package changes aren't taking effect)
docker build --no-cache -t tbdevacrb7jbhj.azurecr.io/tb-chest-scanner:candidate .

# Trigger smoke test
az containerapp job start --name tb-smoke-test --resource-group rg-tb-chest-counter-dev

# Trigger real scan
az containerapp job start --name tbdev-scan-for-main --resource-group rg-tb-chest-counter-dev

# Check recent logs (last 5 minutes)
az monitor log-analytics query --workspace 84afec13-9a92-4daf-af9f-620e7cd84767 --analytics-query "ContainerAppConsoleLogs_CL | where TimeGenerated > ago(5m) | order by TimeGenerated desc | take 30" --output table

# Check job execution status
az containerapp job execution list --name tb-smoke-test --resource-group rg-tb-chest-counter-dev --output table

# Query PostgreSQL via Docker
docker run --rm -it postgres:16 psql "host=tbdev-pg-b7jbhj.postgres.database.azure.com port=5432 dbname=tbchests user=tbadmin password=PASSWORD sslmode=require"

# Redeploy Bicep
az deployment group create --resource-group rg-tb-chest-counter-dev --template-file infra/main.bicep --parameters infra/environments/dev.bicepparam --parameters pgAdminPassword="PASSWORD" --query "properties.outputs" --output json
```

## Architecture decisions made

- No chat bridge (removed to save cost)
- Claude Vision with Haiku for routine scans, Sonnet for verification
- PostgreSQL Flex B1ms over Cosmos DB (SQL better for leaderboard queries)
- Static Web App free tier for dashboard
- ACA Jobs (timer-triggered, scale to zero) for scanner
- Image tags pinned to SHA, promoted via CI/CD
- ACR builds don't cache layers — for fast iteration, build locally with Docker Desktop and push. Remote `az acr build` takes 2-3 min each time. Future optimization: pre-built base image with Playwright+deps.
- Single PostgreSQL database, multi-tenant by clan_id column
- Calibration profile baked into Docker image (1280x720)
- Estimated cost: ~$21-29/mo for 5 clans, currently ~$18/mo for 1 clan

## Clan scope

- Currently deployed: FOR main only (kingdom 225)
- Planned: FOR + FOR Academy + 3-5 allied clans (5-10 total)
- Each clan needs a utility TB account, Key Vault secrets, and an ACA Job entry
