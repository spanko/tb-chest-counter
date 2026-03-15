# Headless Login Fix — Claude Code Handoff

## Problem

The TB chest scanner runs in Azure Container Apps as a headless Playwright container.
The full pipeline works — config loads from env vars, PostgreSQL connects, calibration
loads, Chromium launches, and Vision API calls succeed. But **login fails in headless mode**.

## What the logs show (from the cloud smoke test)

```
Looking for 'Log In' link...
Clicked 'Log in' link
Could not find email input.
Headless mode — run with --visible for first-time setup
```

After failing login, the browser is still on the login screen. It then tries to
navigate to Gifts using calibrated coordinates, but Vision correctly reports
"this is the login screen, not the gifts tab."

## Why it works locally but not in the container

Locally, `browser.py` uses a **persistent browser context** at `data/browser_data/`.
After the first manual login, the session cookies persist and subsequent runs skip
the login flow entirely (the `canvas` check at the top of `login()` detects the
game is already loaded).

In the container, `data/browser_data/` starts empty every run. There are no cached
cookies. The login flow must work from scratch every time.

## Root cause candidates (investigate in order)

1. **Timing**: After clicking "Log in", the email/password form may take longer to
   render in headless mode. The current code looks for `get_by_placeholder("Email")`
   immediately. Add explicit waits.

2. **Different DOM structure**: TB may serve a different login page to headless
   Chromium (user-agent detection, bot detection). The stealth patches in
   `__aenter__` may not be sufficient. Check if the login page DOM differs
   between headed and headless.

3. **Popup/overlay blocking the form**: TB sometimes shows cookie consent or
   promotional overlays that cover the login form. The `_dismiss_popups` call
   happens after login, not before.

4. **The "Log in" click didn't actually open the form**: The click succeeded
   according to the logs, but the email field wasn't found. The form may require
   a different click target or the page may not have finished loading.

## How to debug

```bash
# Run the smoke test locally in visible mode to see exactly what happens
python src/main.py smoke --visible

# Run headless locally to reproduce the container behavior
python src/main.py smoke
```

Compare what you see in visible vs headless. The key is figuring out what the
DOM looks like after clicking "Log in" — is the email field there but with a
different selector, or is it genuinely not rendered?

## Key code locations

- `src/browser.py` lines ~160-280: The `login()` method
- The email input search tries these selectors in order:
  1. `get_by_placeholder("Email")`
  2. `input[type='email']`
  3. `input[name='email']`
  4. `input[placeholder*='mail' i]`
- After filling email, it looks for `get_by_placeholder("Password")`
- Submit is via `get_by_role("button", name="LOGIN")`

## Likely fix

The most common fix for headless login issues is adding explicit waits after
clicking "Log in" and before searching for the email field:

```python
# After clicking "Log in" link
await asyncio.sleep(3)  # Current sleep

# Add: wait for the email input to actually appear
try:
    await self.page.wait_for_selector(
        "input[type='email'], input[placeholder*='mail' i], input[name='email']",
        timeout=10000
    )
except:
    # Take a debug screenshot to see what's actually on screen
    await self._debug_screenshot("login_form_missing")
```

Also consider:
- Taking a debug screenshot right after the "Log in" click to see the actual state
- Checking if TB is showing a CAPTCHA or bot detection challenge
- Adding `--disable-blink-features=AutomationControlled` to the Chromium args
  (already present, but verify it's working)

## What's already working (don't break these)

- Config loads from env vars via `config.py` (returns dict, not dataclass)
- PostgreSQL connects and writes to `scan_runs` table
- Calibration profile loads from `data/calibration.json`
- Claude Vision API calls work (Haiku extraction + screen verification)
- The smoke test flow in `main.py` correctly records results to PG
- All navigation after login uses calibrated coordinates

## Azure infrastructure reference

- ACA Job: `tb-smoke-test` (manual trigger for testing)
- ACA Job: `tbdev-scan-for-main` (cron scheduled, every 4 hours)
- PostgreSQL: `tbdev-pg-b7jbhj.postgres.database.azure.com` / `tbchests`
- ACR: `tbdevacrb7jbhj.azurecr.io`
- Key Vault: `tbdev-kv-b7jbhj`
- Resource Group: `rg-tb-chest-counter-dev`

## Test cycle

1. Fix `browser.py` login flow
2. Test locally: `python src/main.py smoke` (headless, no --visible)
3. If it passes headless locally, push and rebuild:
   ```
   git push
   az acr build --registry tbdevacrb7jbhj --image "tb-chest-scanner:latest" --image "tb-chest-scanner:candidate" --file Dockerfile "."
   az containerapp job start --name tb-smoke-test --resource-group rg-tb-chest-counter-dev
   ```
4. Check logs after 2-3 min:
   ```
   az monitor log-analytics query --workspace 84afec13-9a92-4daf-af9f-620e7cd84767 --analytics-query "ContainerAppConsoleLogs_CL | where TimeGenerated > ago(5m) | order by TimeGenerated desc | take 30" --output table
   ```
