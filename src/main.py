#!/usr/bin/env python3
"""TB Chest Counter — Scanner entrypoint.

Local:
    python main.py chests [--visible]       # Run chest counter once
    python main.py smoke  [--visible]       # Smoke test (no writes to chests table)
    python main.py export                   # Export chest data to CSV

Cloud (ACA Job):
    python main.py chests --cloud           # Reads config from env vars
    python main.py smoke  --cloud           # Smoke test in cloud (CI/CD)
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from config import load_config

log = logging.getLogger("tb-scanner")


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)-12s] %(levelname)-7s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# ── Chest Scanner ───────────────────────────────────────────────────────────

async def run_chest_scan(config: dict):
    """Execute a single chest scan cycle."""
    from browser import TBBrowser
    from vision import extract_gifts_from_screenshot, verify_with_stronger_model

    cloud_mode = config.get("_cloud_mode", False)
    clan_id = config.get("_clan_id", "local")
    vision_cfg = config.get("vision", {})
    scan_cfg = config.get("chest_counter", {})

    # Select storage backend
    if cloud_mode:
        from storage_pg import Storage
    else:
        from storage import Storage

    storage = Storage(config)
    run_id = storage.start_run(vision_cfg.get("model_routine", "claude-haiku-4-5-20251001"))

    total_found = 0
    total_new = 0
    total_pages = 0
    total_cost = 0.0
    headless = config.get("_headless", True)

    try:
        async with TBBrowser(config, headless=headless) as browser:
            await browser.login()
            await browser.navigate_to_gifts()

            roster = storage.get_roster()

            page = 0
            max_pages = scan_cfg.get("max_pages", 10)
            multi_frame = scan_cfg.get("multi_frame_count", 2)

            while page < max_pages:
                screenshots = await browser.capture_gift_screenshots(count=multi_frame)

                if not screenshots:
                    log.info("No screenshots captured — end of gifts or navigation issue.")
                    break

                primary_screenshot = screenshots[0]
                result = extract_gifts_from_screenshot(primary_screenshot, config)

                if not result.gifts:
                    log.info(f"Page {page + 1}: No gifts found — end of list.")
                    break

                log.info(f"Page {page + 1}: Extracted {len(result.gifts)} gifts")

                for gift in result.gifts:
                    gift_dict = gift.model_dump() if hasattr(gift, 'model_dump') else gift.dict()
                    total_found += 1

                    # Verify low-confidence extractions with Sonnet
                    threshold = float(vision_cfg.get("verify_threshold", 0.85))
                    if gift.confidence < threshold:
                        log.info(
                            f"Low confidence ({gift.confidence:.0%}) for "
                            f"{gift.player_name}/{gift.chest_type} — verifying"
                        )
                        verified_result = verify_with_stronger_model(
                            primary_screenshot, config
                        )
                        for vgift in verified_result.gifts:
                            if vgift.player_name == gift.player_name:
                                gift_dict = vgift.model_dump() if hasattr(vgift, 'model_dump') else vgift.dict()
                                gift_dict["verified"] = True
                                break

                    # Fuzzy match player name against roster
                    if roster:
                        gift_dict["player_name_raw"] = gift_dict["player_name"]
                        matched = _fuzzy_match(gift_dict["player_name"], roster)
                        if matched:
                            gift_dict["player_name"] = matched

                    gift_dict["screenshot_ref"] = str(primary_screenshot)

                    is_new = storage.store_chest(run_id, gift_dict)
                    if is_new:
                        total_new += 1

                total_pages += 1

                if not result.has_more:
                    log.info("No more gifts indicated — scan complete.")
                    break

                await browser.scroll_gifts_down()
                page += 1

        storage.complete_run(run_id, total_pages, total_found, total_new, total_cost)
        log.info(
            f"Scan complete: {total_pages} pages, {total_found} gifts found, "
            f"{total_new} new (clan: {clan_id})"
        )

    except Exception as e:
        log.error(f"Scan failed: {e}", exc_info=True)
        storage.fail_run(run_id, str(e))
        raise
    finally:
        storage.close()


def _fuzzy_match(name: str, roster: list[str], threshold: int = 80) -> str | None:
    """Fuzzy match a player name against the clan roster."""
    try:
        from thefuzz import fuzz
    except ImportError:
        return None

    best_score = 0
    best_match = None
    for candidate in roster:
        score = fuzz.ratio(name.lower(), candidate.lower())
        if score > best_score:
            best_score = score
            best_match = candidate

    if best_score >= threshold:
        if best_match != name:
            log.debug(f"Fuzzy matched '{name}' → '{best_match}' ({best_score}%)")
        return best_match
    return None


# ── Smoke Test ──────────────────────────────────────────────────────────────

async def run_smoke_test(config: dict):
    """Smoke test: login, navigate, screenshot, extract — but don't store chests."""
    from browser import TBBrowser
    from vision import extract_gifts_from_screenshot

    cloud_mode = config.get("_cloud_mode", False)
    clan_id = config.get("_clan_id", "local")
    vision_cfg = config.get("vision", {})
    headless = config.get("_headless", True)

    screenshot_dir = Path(config.get("storage", {}).get("screenshot_dir", "/tmp/smoke-screenshots"))
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    results = {
        "clan_id": clan_id,
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

            # Step 3: Capture + Vision extraction (page 1 only)
            log.info("[smoke] Step 3: Vision extraction...")
            screenshots = await browser.capture_gift_screenshots(count=1)

            if not screenshots:
                results["steps"]["capture"] = "failed — no screenshots"
                raise RuntimeError("Screenshot capture returned empty")

            results["steps"]["capture"] = "passed"
            result = extract_gifts_from_screenshot(screenshots[0], config)

            results["steps"]["vision"] = "passed"
            results["gifts_extracted"] = len(result.gifts)
            results["has_more"] = result.has_more
            results["extraction_notes"] = result.extraction_notes

            for gift in result.gifts:
                log.info(f"[smoke]   {gift.player_name} / {gift.chest_type} (conf: {gift.confidence})")

            # Step 4: Scroll test
            if result.has_more:
                log.info("[smoke] Step 4: Scroll test...")
                await browser.scroll_gifts_down()
                scroll_shot = screenshot_dir / f"smoke_{timestamp}_03_scrolled.png"
                await browser.page.screenshot(path=str(scroll_shot))
                results["steps"]["scroll"] = "passed"
                log.info(f"[smoke] Screenshot: {scroll_shot}")
            else:
                results["steps"]["scroll"] = "skipped — no more gifts"

        results["passed"] = True
        log.info(f"[smoke] All steps passed. {results.get('gifts_extracted', 0)} gifts extracted.")

    except Exception as e:
        log.error(f"[smoke] Failed: {e}", exc_info=True)
        results["error"] = str(e)
        results["passed"] = False

    # Write results JSON
    results_path = screenshot_dir / f"smoke_{timestamp}_results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)
    log.info(f"[smoke] Results: {results_path}")

    # Record in database if cloud mode
    if cloud_mode:
        try:
            from storage_pg import Storage
            storage = Storage(config)
            run_id = storage.start_run(f"smoke:{vision_cfg.get('model_routine', 'unknown')}")
            if results["passed"]:
                storage.complete_run(run_id, 1, results.get("gifts_extracted", 0), 0)
            else:
                storage.fail_run(run_id, results.get("error", "unknown"))
            storage.close()
        except Exception as e:
            log.warning(f"[smoke] Could not record to DB (non-fatal): {e}")

    # Upload screenshots to blob storage if configured
    blob_conn = os.environ.get("SMOKE_BLOB_CONNECTION")
    if blob_conn:
        _upload_smoke_screenshots(screenshot_dir, timestamp, blob_conn)

    if not results["passed"]:
        sys.exit(1)


def _upload_smoke_screenshots(screenshot_dir: Path, timestamp: str, conn_string: str):
    """Upload smoke screenshots to Azure Blob Storage."""
    try:
        from azure.storage.blob import BlobServiceClient
        client = BlobServiceClient.from_connection_string(conn_string)
        container = client.get_container_client("smoke-screenshots")
        for f in screenshot_dir.glob(f"smoke_{timestamp}*"):
            with open(f, "rb") as data:
                container.upload_blob(f.name, data, overwrite=True)
            log.info(f"[smoke] Uploaded {f.name} to blob storage")
    except ImportError:
        log.warning("[smoke] azure-storage-blob not installed — skipping upload")
    except Exception as e:
        log.warning(f"[smoke] Blob upload failed (non-fatal): {e}")


# ── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="TB Chest Counter")
    parser.add_argument("command", choices=["chests", "smoke", "export"],
                        help="chests: run scanner | smoke: smoke test | export: dump CSV")
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

    elif args.command == "export":
        if config.get("_cloud_mode"):
            log.error("Export is for local mode only. Use the dashboard in cloud mode.")
            sys.exit(1)
        from storage import Storage
        storage = Storage(config)
        storage.export_csv()
        storage.close()


if __name__ == "__main__":
    main()
