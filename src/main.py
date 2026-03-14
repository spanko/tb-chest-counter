#!/usr/bin/env python3
"""TB Toolkit — Chest Counter + Chat Bridge for Total Battle.

Usage:
    python main.py calibrate [--visible]   # Vision-calibrate UI element positions
    python main.py chests [--visible]      # Run chest counter once
    python main.py roster [--visible]      # Scan clan members list
    python main.py chat [--visible]        # Run chat bridge (continuous)
    python main.py all [--visible]         # Both: chat continuous + chests on schedule
    python main.py export                  # Export chest data to CSV
    python main.py dashboard              # Start web dashboard
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "settings.json"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        print(f"ERROR: Config not found at {CONFIG_PATH}")
        print(f"  Run: cp config/settings.example.json config/settings.json")
        print(f"  Then edit config/settings.json with your credentials.")
        sys.exit(1)
    with open(CONFIG_PATH) as f:
        return json.load(f)


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)-12s] %(levelname)-7s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# ── Commands ────────────────────────────────────────────────────────────────

async def cmd_calibrate(config: dict, visible: bool):
    """Run Vision-based UI calibration to locate all clickable elements."""
    from browser import TBBrowser
    from calibration import run_full_calibration

    if not visible:
        logging.warning("Calibration works best with --visible so you can verify clicks.")
        logging.warning("Running headless anyway...")

    async with TBBrowser(config, headless=not visible) as browser:
        await browser.login()
        profile = await run_full_calibration(browser, config)

        # Print summary
        print("\n" + "=" * 60)
        print("CALIBRATION RESULTS")
        print("=" * 60)
        for screen_name, screen_data in profile.get("screens", {}).items():
            elements = screen_data.get("elements", {})
            found = sum(1 for v in elements.values() if v)
            total = len(elements)
            status = "OK" if found == total else "WARNING"
            print(f"  {status} {screen_name}: {found}/{total} elements located")
            for elem_name, coords in elements.items():
                if coords:
                    print(f"      {elem_name}: ({coords['x']}, {coords['y']})")
                else:
                    print(f"      {elem_name}: NOT FOUND")
        print("=" * 60)


async def cmd_chests(config: dict, visible: bool):
    """Run a single chest counter scan."""
    from browser import TBBrowser
    from vision import extract_gifts_from_screenshot, consensus_merge, validate_player_names
    from storage import Storage

    storage = Storage(config)

    # Use DB roster if available, fall back to config
    roster = storage.get_active_roster()
    if roster:
        logging.info(f"Using DB roster: {len(roster)} active members")
    else:
        roster = config["clan"].get("roster", [])
        if roster:
            logging.info(f"Using config roster: {len(roster)} members")
        else:
            logging.info("No roster available — skipping name validation")

    async with TBBrowser(config, headless=not visible) as browser:
        await browser.login()
        await browser.navigate_to_gifts()

        page = 0
        max_pages = config["chest_counter"].get("max_pages", 10)
        total_new = 0

        while page < max_pages:
            screenshots = await browser.capture_gift_screenshots(
                count=config["chest_counter"].get("multi_frame_count", 2)
            )

            if not screenshots:
                logging.info("No screenshots captured — may have reached end of gifts.")
                break

            # Extract from each screenshot independently
            all_extractions = []
            for ss_path in screenshots:
                extraction = extract_gifts_from_screenshot(ss_path, config)
                all_extractions.append(extraction)
                logging.debug(f"  Extracted {len(extraction.gifts)} gifts from {ss_path}")

            # Consensus: keep gifts that appear in majority of frames
            confirmed = consensus_merge(all_extractions)
            logging.info(f"Page {page + 1}: {len(confirmed)} gifts confirmed by consensus")

            if not confirmed:
                logging.info("No gifts found on this page — stopping.")
                break

            # Validate against roster if available
            if roster:
                confirmed = validate_player_names(confirmed, roster)

            # Store with dedup
            new_count = storage.store_gifts(confirmed)
            total_new += new_count
            logging.info(
                f"  → {new_count} new gifts stored "
                f"({len(confirmed) - new_count} duplicates skipped)"
            )

            # Check if there are more pages
            has_more = any(e.has_more for e in all_extractions)
            if not has_more:
                logging.info("No more gift pages.")
                break

            await browser.scroll_gifts_down()
            page += 1

        logging.info(f"Chest scan complete: {total_new} new gifts across {page + 1} pages.")


async def cmd_roster(config: dict, visible: bool):
    """Scan clan member list and update roster in database."""
    from browser import TBBrowser
    from roster import scan_clan_roster
    from storage import Storage

    storage = Storage(config)

    async with TBBrowser(config, headless=not visible) as browser:
        await browser.login()
        members = await scan_clan_roster(browser, config)

        if not members:
            logging.error("No members found. Calibration may be needed.")
            return

        result = storage.update_roster(members)

        # Print summary
        print(f"\nRoster scan complete: {len(members)} members found")
        if result["new"]:
            print(f"  New members: {', '.join(result['new'])}")
        if result["returned"]:
            print(f"  Returned:    {', '.join(result['returned'])}")
        if result["left"]:
            print(f"  Left clan:   {', '.join(result['left'])}")
        print(f"  Unchanged:   {result['updated']}")


async def cmd_chat(config: dict, visible: bool):
    """Run chat bridge continuously."""
    from browser import TBBrowser
    from chat_bridge import ChatBridge

    bridge = ChatBridge(config)

    async with TBBrowser(config, headless=not visible) as browser:
        await browser.login()
        await browser.inject_ws_interceptor()

        logging.info("Chat bridge running. Press Ctrl+C to stop.")
        logging.info(
            f"Telegram forwarding: "
            f"{'ENABLED' if config['chat_bridge'].get('forward_to_telegram') else 'DISABLED'}"
        )

        try:
            while True:
                messages = await browser.poll_intercepted_messages()
                for msg in messages:
                    await bridge.handle_message(msg)
                await asyncio.sleep(1)
        finally:
            await bridge.close()


async def cmd_all(config: dict, visible: bool):
    """Run chat bridge continuously + chest scans on schedule."""
    from browser import TBBrowser
    from chat_bridge import ChatBridge
    from vision import extract_gifts_from_screenshot, consensus_merge, validate_player_names
    from storage import Storage
    import time

    storage = Storage(config)
    bridge = ChatBridge(config)

    # Use DB roster if available
    roster = storage.get_active_roster()
    if not roster:
        roster = config["clan"].get("roster", [])

    async with TBBrowser(config, headless=not visible) as browser:
        await browser.login()
        await browser.inject_ws_interceptor()

        scan_interval = config["chest_counter"].get("scan_interval_hours", 4) * 3600
        last_scan = 0

        logging.info(f"Combined mode: chat bridge + chest scan every {scan_interval // 3600}h")
        logging.info("Press Ctrl+C to stop.")

        try:
            while True:
                # Handle chat messages
                messages = await browser.poll_intercepted_messages()
                for msg in messages:
                    await bridge.handle_message(msg)

                # Periodic chest scan
                now = time.time()
                if now - last_scan >= scan_interval:
                    logging.info("Starting scheduled chest scan...")
                    try:
                        await browser.navigate_to_gifts()
                        screenshots = await browser.capture_gift_screenshots(count=2)
                        if screenshots:
                            all_ex = [
                                extract_gifts_from_screenshot(s, config)
                                for s in screenshots
                            ]
                            confirmed = consensus_merge(all_ex)
                            if roster:
                                confirmed = validate_player_names(confirmed, roster)
                            new = storage.store_gifts(confirmed)
                            logging.info(f"Chest scan: {new} new gifts stored.")
                        await browser.navigate_back_to_main()

                        # Re-inject WS interceptor since we navigated away
                        await browser.inject_ws_interceptor()
                    except Exception as e:
                        logging.error(f"Chest scan failed: {e}")
                    last_scan = now

                await asyncio.sleep(1)
        finally:
            await bridge.close()


def cmd_export(config: dict):
    """Export chest data to CSV."""
    from storage import Storage
    storage = Storage(config)
    path = storage.export_csv()
    logging.info(f"Exported to {path}")


def cmd_dashboard(config: dict):
    """Start Flask web dashboard."""
    from dashboard import create_app
    app = create_app(config)
    host = config["dashboard"].get("host", "127.0.0.1")
    port = config["dashboard"].get("port", 5000)
    logging.info(f"Dashboard at http://{host}:{port}")
    app.run(host=host, port=port, debug=True)


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="TB Toolkit — Chest Counter + Chat Bridge")
    parser.add_argument(
        "command",
        choices=["calibrate", "chests", "roster", "chat", "all", "export", "dashboard"],
        help="Which tool to run",
    )
    parser.add_argument("--visible", action="store_true",
                        help="Show browser window (for calibration/debugging)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Debug-level logging")
    args = parser.parse_args()

    setup_logging(args.verbose)
    config = load_config()

    # Ensure data directories exist
    for key in ["database", "chest_log", "chat_log", "export_dir", "screenshot_dir"]:
        p = ROOT / config["storage"][key]
        if key.endswith("_dir"):
            p.mkdir(parents=True, exist_ok=True)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)

    # Dispatch
    if args.command == "calibrate":
        asyncio.run(cmd_calibrate(config, args.visible))
    elif args.command == "chests":
        asyncio.run(cmd_chests(config, args.visible))
    elif args.command == "roster":
        asyncio.run(cmd_roster(config, args.visible))
    elif args.command == "chat":
        asyncio.run(cmd_chat(config, args.visible))
    elif args.command == "all":
        asyncio.run(cmd_all(config, args.visible))
    elif args.command == "export":
        cmd_export(config)
    elif args.command == "dashboard":
        cmd_dashboard(config)


if __name__ == "__main__":
    main()
