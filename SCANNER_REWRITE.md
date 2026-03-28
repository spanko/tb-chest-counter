# TB Chest Counter — Scanner Rewrite Handoff

## Context

This is `spanko/tb-chest-counter`, a Total Battle clan automation tool that:
- Logs into totalbattle.com using a utility Playwright browser session
- Navigates to the Clan → Gifts tab
- Opens each pending chest gift and records its contents
- Stores results in PostgreSQL (Azure Container Apps Job in production)

The scanner was crashing at ~iteration 38 with `Target crashed` (OOM). Root cause: a state-machine loop accumulating screenshots, result objects, multi-frame buffers, and Playwright CDP state across iterations. This rewrite fixes that and simplifies the architecture significantly.

---

## What's Changing

### Remove entirely
- Multi-frame screenshot consensus (capture N screenshots, compare) — gone. Single screenshot per action, released immediately.
- `verify_with_stronger_model()` — gone. One Claude call per open-chest, confidence threshold handled inline.
- Scroll-based pagination — gone. The list shifts up under the cursor after each Open click.
- `capture_gift_screenshots()` in `browser.py` — gone.
- Chat bridge / Sendbird / Telegram code — gone (separate concern, not in scope).
- `thefuzz`, `flask`, `Pillow`, `apscheduler`, `httpx`, `asyncio-compat` from requirements — gone.

### Keep
- `TBBrowser` class structure in `browser.py` — keep login, `navigate_to_gifts()`, coordinate-based clicking.
- `storage_pg.py` — keep, just update the schema it writes to.
- `config.py` dual-mode loader (env vars for cloud, settings.json for local) — keep.
- ACA Job infrastructure, PostgreSQL, GitHub Actions deploy — untouched.

### Add / rewrite
- New scan loop in `main.py` — vision-native, stateless per iteration.
- Two focused Claude prompts replacing the old extraction prompt.
- `browser.execute_action()` — thin dispatcher for click actions.

---

## The New Scan Loop

The key insight: the TB gift list **shifts up under the cursor** after each Open click. So after finding the first Open button once, every subsequent click lands on the next gift automatically. No scroll, no coordinate re-detection.

```
1. Navigate to Gifts tab
2. Screenshot → ask Claude: "where is the first Open button?" → get (x, y)
3. Loop:
   a. Click (x, y)
   b. Screenshot immediately (no pause needed — the open animation is instant)
   c. Ask Claude: "what did this chest contain, and is the list empty now?"
   d. If done → break
   e. Store {player_name, chest_type, contents, opened_at}
4. Bulk insert to PostgreSQL
5. Exit
```

Memory profile: each iteration allocates `png_bytes` + `b64_string`, both explicitly `del`'d before the next click. Flat memory regardless of gift count.

---

## Code to Write

### `src/main.py` — new scan loop

```python
import asyncio
import base64
import logging
from datetime import datetime, timezone

log = logging.getLogger("tb-scanner")

OPEN_BUTTON_X = 995  # Fixed x coordinate — all Open buttons are in the same column
                     # Calibrated at 1280x720. Adjust if viewport changes.

async def run_chest_scan(config: dict):
    from browser import TBBrowser
    from vision import find_first_gift, read_opened_chest
    from storage_pg import Storage

    storage = Storage(config)
    run_id = storage.start_run()
    run_gifts = []

    try:
        async with TBBrowser(config, headless=config.get("_headless", True)) as browser:
            await browser.login()
            await browser.navigate_to_gifts()

            # Phase 1: find the first Open button (one-time)
            png = await browser.page.screenshot()
            b64 = base64.b64encode(png).decode(); del png
            first = await find_first_gift(b64, config); del b64

            if first.done:
                log.info("No gifts to claim.")
                storage.complete_run(run_id, 0)
                return

            click_x = OPEN_BUTTON_X
            click_y = first.open_button_y

            # Phase 2: click → read → repeat, cursor stays put
            max_gifts = config.get("chest_counter", {}).get("max_gifts", 200)
            for i in range(max_gifts):
                await browser.page.mouse.click(click_x, click_y)

                png = await browser.page.screenshot()
                b64 = base64.b64encode(png).decode(); del png
                result = await read_opened_chest(b64, config); del b64

                if result.done:
                    log.info(f"No more gifts after {i} opened.")
                    break

                run_gifts.append({
                    "player_name": result.player_name,
                    "chest_type": result.chest_type,
                    "contents": result.items,
                    "opened_at": datetime.now(timezone.utc).isoformat(),
                    "run_id": run_id,
                })
                log.info(f"[{i+1}] {result.player_name} — {result.chest_type}: {result.items}")

    except Exception as e:
        log.error(f"Scan failed: {e}", exc_info=True)
        storage.fail_run(run_id, str(e))
        raise

    storage.bulk_insert(run_gifts)
    storage.complete_run(run_id, len(run_gifts))
    log.info(f"Done. Stored {len(run_gifts)} gifts.")
```

### `src/vision.py` — two focused prompts

**`find_first_gift(b64, config)`** — called once at the start:

```python
FIND_FIRST_PROMPT = """
You are looking at the Total Battle Clan Gifts tab at 1280x720.

The gift list shows rows, each with a green "Open" button on the right side (~x=995).
Find the FIRST (topmost) gift row that has an Open button.

Return JSON only:
{
  "done": false,
  "player_name": "...",
  "chest_type": "...",
  "open_button_y": 350
}

Set done=true if there are no gift rows with Open buttons visible.
open_button_y should be the pixel y-coordinate of the center of the first Open button.
Return only valid JSON, no markdown.
"""
```

**`read_opened_chest(b64, config)`** — called after every click:

```python
READ_CHEST_PROMPT = """
A chest in Total Battle was just clicked open. Analyze the screen.

Two possible states:
1. A chest opened showing its contents (items, resources, troops, gold, etc.)
2. The gift list is empty — no more gifts to open

Return JSON only:
{
  "done": false,
  "player_name": "...",
  "chest_type": "...",
  "items": [
    {"item": "Gold", "quantity": 500000},
    {"item": "Wood", "quantity": 200},
    {"item": "Swordsmen", "quantity": 50}
  ]
}

If no chest opened (empty list, nothing happened, error screen):
{"done": true, "player_name": "", "chest_type": "", "items": []}

Return only valid JSON, no markdown.
"""
```

Use `anthropic.Anthropic().messages.create()` with `model=config["vision"]["model"]` (default `claude-haiku-4-5-20251001`). Pass the b64 image as `{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}}`. Parse the response text as JSON directly — no stripping needed if prompt says "no markdown."

### `src/browser.py` — remove dead methods

Delete:
- `capture_gift_screenshots()` (multi-frame method)
- `scroll_gifts_down()`
- `inject_ws_interceptor()` / `poll_intercepted_messages()` (chat bridge)
- `_screenshot_counter` tracking

Keep:
- `TBBrowser.__init__`, `__aenter__`, `__aexit__`
- `login()`
- `navigate_to_gifts()`
- `page` property

### `requirements.txt` — trimmed

```
playwright>=1.49.0
anthropic>=0.39.0
psycopg2-binary>=2.9.9
pydantic>=2.0.0
```

That's it. Four packages.

---

## Docker Fix — Why Builds Are Slow

**The problem:** `az acr build` doesn't cache layers between runs. Every build re-runs `playwright install chromium --with-deps` which is ~3 minutes of apt installs + binary download every single time.

**Also:** `mcr.microsoft.com/playwright/python:v1.49.0-noble` already ships with Chromium. The `RUN playwright install chromium --with-deps` line is redundant — it reinstalls what's already there.

**The fix — `Dockerfile` should be:**

```dockerfile
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy
# jammy (22.04) over noble (24.04): smaller, more stable for headless Linux
# Chromium is already in this image — do NOT run playwright install

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# This is now the only slow layer (~30s), and it only reruns when requirements.txt changes

COPY src/ ./src/
COPY config/ ./config/
RUN mkdir -p /tmp/screenshots

CMD ["python", "src/main.py", "chests", "--cloud"]
```

**To get fast iteration builds**, set up the two-stage base/scanner split:

```bash
# Step 1: build the base image ONCE (30s — just pip install)
az acr build --registry tbdevacrb7jbhj \
  --image tb-scanner-base:v1 \
  --file Dockerfile.base "."

# Step 2: on every code change, build the scanner layer (~5s — just COPY src/)
az acr build --registry tbdevacrb7jbhj \
  --image tb-chest-scanner:candidate \
  --file Dockerfile.scanner "."
```

**`Dockerfile.base`:**
```dockerfile
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN mkdir -p /tmp/screenshots
```

**`Dockerfile.scanner`:**
```dockerfile
ARG ACR_SERVER=tbdevacrb7jbhj.azurecr.io
FROM ${ACR_SERVER}/tb-scanner-base:v1
WORKDIR /app
COPY src/ ./src/
COPY config/ ./config/
CMD ["python", "src/main.py", "chests", "--cloud"]
```

Rebuild `Dockerfile.base` only when `requirements.txt` changes (rare). Day-to-day iteration uses `Dockerfile.scanner` only (~5s builds).

---

## Validated Facts — Don't Re-Research

- TB login page is real HTML DOM (use selectors). Post-login UI is Canvas/WASM (use coordinates).
- Viewport: 1280x720. All coordinates calibrated to this.
- Playwright stealth patches work. TB does not detect headless Chromium.
- Store/offers popup appears after login — dismiss with Escape or click X at ~(1258, 68).
- Clan shield icon: ~(57, 345). Gifts tab within clan panel: ~(258, 257).
- Open button column x: ~995. Verify this in a `--visible` run if it's moved.
- After clicking Open, the list shifts up — the cursor stays in place for the next gift.
- The "Claim chests" button at the bottom marks end of list (use as a fallback termination signal in the list view, though the vision model's `done` detection should handle it).
- Claude Haiku 4.5 is the right model for extraction — matches Sonnet accuracy on this UI at 1/3 cost.
- ACA Job config: `tbdev-scan-for-main`, resource group `rg-tb-chest-counter-dev`, ACR `tbdevacrb7jbhj`.

---

## First Task After Rewrite

Run with `--visible` flag to verify:
1. Login works, popups dismissed, Gifts tab reached
2. `find_first_gift()` returns a plausible `open_button_y` value
3. First click opens a chest and `read_opened_chest()` extracts content correctly
4. Second click (cursor unmoved) opens the next chest
5. Loop terminates cleanly when gifts run out

Log `open_button_y` from the first call and confirm it's in the range 150-600 (the gift list area at 1280x720).
