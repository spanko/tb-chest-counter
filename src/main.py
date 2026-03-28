#!/usr/bin/env python3
"""TB Chest Counter — Scanner entrypoint (simplified rewrite).

The new scan loop is vision-native and stateless per iteration:
1. Navigate to Gifts tab
2. Screenshot → ask Claude: "where is the first Open button?" → get (x, y)
3. Loop: click (x, y) → screenshot → ask Claude: "what did this chest contain?"
4. Bulk insert to PostgreSQL
5. Exit

Memory profile: each iteration allocates png_bytes + b64_string, both explicitly
del'd before the next click. Flat memory regardless of gift count.

Usage:
    python main.py chests [--visible]       # Run chest opener
    python main.py chests --cloud           # Cloud mode (reads config from env vars)
"""

import argparse
import asyncio
import base64
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from config import load_config
from storage_azure import upload_screenshot

log = logging.getLogger("tb-scanner")

# Note: Open button coordinates are now detected by Vision on first find.
# All subsequent clicks use the same (x, y) since gifts stack in place.


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)-12s] %(levelname)-7s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# ── Chest Scanner (New Simplified Loop) ────────────────────────────────────


async def run_chest_scan(config: dict):
    """Execute a single chest scan cycle using batch Vision calls.

    Optimization: Get ALL visible gifts in one Vision call, click through them all,
    then take another screenshot. This reduces Vision calls by ~4x.
    """
    from browser import TBBrowser
    from vision import find_all_visible_gifts

    cloud_mode = config.get("_cloud_mode", False)
    headless = config.get("_headless", True)

    # Select storage backend
    if cloud_mode:
        from storage_pg import Storage
    else:
        from storage import Storage

    storage = Storage(config)
    run_id = storage.start_run("claude-haiku-4-5-20251001")
    run_gifts = []
    total_opened = 0

    try:
        async with TBBrowser(config, headless=headless) as browser:
            await browser.login()
            await browser.navigate_to_gifts()

            max_gifts = config.get("chest_counter", {}).get("max_gifts", 200)
            batch_num = 0

            while total_opened < max_gifts:
                batch_num += 1
                log.info(f"=== Batch {batch_num}: Taking screenshot and finding all visible gifts ===")

                # Screenshot and get ALL visible gifts
                png = await browser.page.screenshot()
                b64 = base64.b64encode(png).decode()

                # Save debug screenshot
                debug_path = Path("/tmp/screenshots") / f"batch_{batch_num}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                debug_path.parent.mkdir(parents=True, exist_ok=True)
                with open(debug_path, "wb") as f:
                    f.write(base64.b64decode(b64))
                upload_screenshot(str(debug_path), f"debug/batch_{batch_num}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")

                del png

                # Get all visible gifts in one Vision call
                result = await find_all_visible_gifts(b64, config)
                del b64

                if result.done or len(result.gifts) == 0:
                    log.info(f"No more gifts found. Total opened: {total_opened}")
                    break

                log.info(f"Found {len(result.gifts)} gifts in this batch")

                # Click through ALL visible gifts rapidly
                click_x = result.open_button_x
                for gift in result.gifts:
                    if total_opened >= max_gifts:
                        log.info(f"Reached max_gifts limit ({max_gifts})")
                        break

                    total_opened += 1
                    log.info(f"[{total_opened}] Opening {gift.chest_type} from {gift.player_name} at ({click_x}, {gift.open_button_y})...")

                    # Click the Open button
                    await browser.page.mouse.click(click_x, gift.open_button_y)

                    # Store immediately
                    gift_data = {
                        "player_name": gift.player_name,
                        "chest_type": gift.chest_type,
                        "contents": [],
                        "opened_at": datetime.now(timezone.utc).isoformat(),
                        "run_id": run_id,
                    }
                    storage.store_chest(run_id, gift_data)
                    run_gifts.append(gift_data)

                    log.info(f"[{total_opened}] Stored: {gift.player_name} — {gift.chest_type}")

                    # Brief pause between clicks
                    await asyncio.sleep(0.3)

                # After clicking all visible gifts, loop back to take new screenshot
                log.info(f"Batch {batch_num} complete. Opened {len(result.gifts)} gifts this batch.")

    except Exception as e:
        log.error(f"Scan failed: {e}", exc_info=True)
        storage.fail_run(run_id, str(e))
        raise

    # Chests are already stored immediately as they're opened
    # Just update the run stats
    storage.complete_run(run_id, 1, len(run_gifts), len(run_gifts))
    log.info(f"Done. Stored {len(run_gifts)} gifts.")
    storage.close()


# ── Smoke Test ──────────────────────────────────────────────────────────────


async def run_smoke_test(config: dict):
    """Smoke test: login, navigate, find first gift — but don't open anything."""
    from browser import TBBrowser
    from vision import find_first_gift

    headless = config.get("_headless", True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    screenshot_dir = Path("/tmp/screenshots")
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    results = {
        "timestamp": timestamp,
        "steps": {},
        "passed": False,
    }

    try:
        async with TBBrowser(config, headless=headless) as browser:
            # Step 1: Login
            log.info("[smoke] Step 1: Login...")
            await browser.login()
            results["steps"]["login"] = "passed"

            login_shot = screenshot_dir / f"smoke_{timestamp}_01_login.png"
            await browser.page.screenshot(path=str(login_shot))
            log.info(f"[smoke] Screenshot: {login_shot}")

            # Step 2: Navigate to Gifts
            log.info("[smoke] Step 2: Navigate to Gifts...")
            await browser.navigate_to_gifts()
            results["steps"]["navigate"] = "passed"

            gifts_shot = screenshot_dir / f"smoke_{timestamp}_02_gifts.png"
            await browser.page.screenshot(path=str(gifts_shot))
            log.info(f"[smoke] Screenshot: {gifts_shot}")

            # Step 3: Find first Open button
            log.info("[smoke] Step 3: Find first Open button...")
            png = await browser.page.screenshot(timeout=60000)
            b64 = base64.b64encode(png).decode()
            del png

            first = await find_first_gift(b64, config)
            del b64

            results["steps"]["find_first"] = "passed"
            results["first_gift"] = {
                "done": first.done,
                "player_name": first.player_name,
                "chest_type": first.chest_type,
                "open_button_y": first.open_button_y,
            }

            if first.done:
                log.info("[smoke] No gifts found (empty list)")
            else:
                log.info(f"[smoke] First gift: {first.player_name} — {first.chest_type} at y={first.open_button_y}")

                # Verify y coordinate is in reasonable range
                if 150 <= first.open_button_y <= 600:
                    log.info(f"[smoke] Y coordinate {first.open_button_y} is in valid range (150-600)")
                else:
                    log.warning(f"[smoke] Y coordinate {first.open_button_y} is outside expected range (150-600)")

        results["passed"] = True
        log.info("[smoke] All steps passed.")

    except Exception as e:
        log.error(f"[smoke] Failed: {e}", exc_info=True)
        results["error"] = str(e)
        results["passed"] = False

    # Write results JSON
    results_path = screenshot_dir / f"smoke_{timestamp}_results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)
    log.info(f"[smoke] Results: {results_path}")

    if not results["passed"]:
        sys.exit(1)


# ── CLI ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="TB Chest Counter")
    parser.add_argument("command", choices=["chests", "smoke"],
                        help="chests: run scanner | smoke: smoke test")
    parser.add_argument("--cloud", action="store_true",
                        help="Cloud mode — read config from env vars")
    parser.add_argument("--visible", action="store_true",
                        help="Show browser window (local dev)")
    parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args()
    setup_logging(args.verbose)

    # Smoke mode can also be triggered by SCAN_MODE=smoke env var
    scan_mode = os.environ.get("SCAN_MODE", args.command)

    config = load_config(cloud=args.cloud)

    # Set headless based on --visible flag
    config["_headless"] = not args.visible

    if scan_mode == "chests":
        asyncio.run(run_chest_scan(config))
    elif scan_mode == "smoke":
        asyncio.run(run_smoke_test(config))


if __name__ == "__main__":
    main()
