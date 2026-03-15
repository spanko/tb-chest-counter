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


async def cmd_chests(config: dict, visible: bool, mode: str = "open"):
    """Run a chest counter scan.

    Two modes:
        open   — Click "Open" on each gift, collecting rewards. Destructive
                 but 100% reliable (no scrolling needed). DEFAULT.
        scroll — Screenshot and scroll through the list without opening.
                 Non-destructive but scrolling can be unreliable.
    """
    from browser import TBBrowser
    from vision import extract_gifts_from_screenshot
    from storage import Storage

    storage = Storage(config)
    logging.info(f"Chest scan mode: {mode}")

    # Use DB roster if available
    roster = storage.get_active_roster()
    if not roster:
        roster = config["clan"].get("roster", [])
    if roster:
        logging.info(f"Using roster: {len(roster)} members")

    async with TBBrowser(config, headless=not visible) as browser:
        await browser.login()
        await browser.navigate_to_gifts()

        if mode == "open":
            total_new = await _scan_by_opening(browser, config, storage, roster)
        else:
            total_new = await _scan_by_scrolling(browser, config, storage, roster)

    # ── Results summary ──────────────────────────────────────────────
    _print_scan_summary(storage)


async def _scan_by_opening(browser, config, storage, roster) -> int:
    """Open each gift one by one from the top of the list.

    Each "Open" click removes that gift and the next slides up.
    No scrolling needed. Destructive (gifts are claimed).
    """
    from vision import extract_gifts_from_screenshot, validate_player_names

    total_new = 0
    gift_num = 0
    max_gifts = 500  # Safety limit
    consecutive_failures = 0
    max_failures = 5  # Stop if we fail to open 5 times in a row
    # Recalibrate the Open button every N gifts in case it drifts
    recalibrate_interval = 25

    while gift_num < max_gifts:
        # Screenshot to extract the current top gift's data
        screenshots = await browser.capture_gift_screenshots(count=1)
        if not screenshots:
            break

        extraction = extract_gifts_from_screenshot(screenshots[0], config)
        gifts = extraction.gifts

        if not gifts:
            if extraction.extraction_notes:
                logging.info(f"  Vision notes: {extraction.extraction_notes}")
            logging.info("No more gifts visible — done.")
            break

        # Record the top gift before opening it
        top_gift = gifts[0]
        logging.info(
            f"Gift {gift_num + 1}: {top_gift.chest_type} "
            f"from {top_gift.player_name} "
            f"(time_left={top_gift.time_left})"
        )

        # Validate and store
        to_store = [top_gift]
        if roster:
            to_store = validate_player_names(to_store, roster)
        new_count = storage.store_gifts(to_store)
        total_new += new_count

        # Click "Open" on the first gift
        opened = await browser.click_open_first_gift()
        if not opened:
            consecutive_failures += 1
            logging.warning(f"  Failed to click Open ({consecutive_failures}/{max_failures})")
            if consecutive_failures >= max_failures:
                logging.error("Too many Open failures — stopping.")
                break
            # Try recalibrating
            await browser.recalibrate_open_button()
            continue

        consecutive_failures = 0

        # Dismiss the reward popup
        await browser.dismiss_reward_popup()

        # Periodically recalibrate the Open button position
        if (gift_num + 1) % recalibrate_interval == 0:
            logging.debug(f"Recalibrating Open button (every {recalibrate_interval} gifts)...")
            await browser.recalibrate_open_button()

        gift_num += 1

    logging.info(f"Open scan complete: {gift_num} gifts opened, {total_new} new stored.")
    return total_new


async def _scan_by_scrolling(browser, config, storage, roster) -> int:
    """Scroll through the gift list without opening. Non-destructive."""
    from vision import extract_gifts_from_screenshot, validate_player_names

    total_new = 0
    page = 0
    max_pages = 200
    all_seen_keys = set()
    stall_count = 0
    max_stalls = 3

    while page < max_pages:
        screenshots = await browser.capture_gift_screenshots(count=1)
        if not screenshots:
            break

        extraction = extract_gifts_from_screenshot(screenshots[0], config)
        gifts = extraction.gifts

        logging.info(f"Page {page + 1}: {len(gifts)} gifts extracted")

        if not gifts:
            if extraction.extraction_notes:
                logging.warning(f"  Vision notes: {extraction.extraction_notes}")
            if page == 0:
                logging.warning("No gifts on first page — check data/screenshots/debug/")
            break

        new_on_page = 0
        for g in gifts:
            key = (
                g.player_name.strip().lower(),
                g.chest_type.strip().lower(),
                (g.time_left or "").strip(),
            )
            if key not in all_seen_keys:
                all_seen_keys.add(key)
                new_on_page += 1

        logging.info(f"  {new_on_page} new ({len(all_seen_keys)} total unique seen)")

        if new_on_page == 0:
            stall_count += 1
            if stall_count >= max_stalls:
                logging.info("Scroll stalled — reached end.")
                break
        else:
            stall_count = 0

        if roster:
            gifts = validate_player_names(gifts, roster)

        new_count = storage.store_gifts(gifts)
        total_new += new_count
        logging.info(f"  → {new_count} stored")

        await browser.scroll_gifts_down()
        page += 1

    logging.info(
        f"Scroll scan complete: {total_new} new stored, "
        f"{len(all_seen_keys)} unique seen across {page + 1} pages."
    )
    return total_new


def _print_scan_summary(storage):
    """Print a summary of what's in the database after a scan."""
    lb = storage.get_leaderboard()
    if not lb:
        print("\nNo chest data in database yet.")
        return

    total_chests = sum(r["chest_count"] for r in lb)
    total_points = sum(r["total_points"] for r in lb)

    print("\n" + "=" * 60)
    print("CHEST SCAN RESULTS")
    print("=" * 60)
    print(f"  Total chests in DB: {total_chests}")
    print(f"  Total points:       {total_points}")
    print(f"  Players:            {len(lb)}")
    print()
    print(f"  {'#':<4} {'Player':<25} {'Chests':>7} {'Points':>7}")
    print(f"  {'-'*4} {'-'*25} {'-'*7} {'-'*7}")
    for i, row in enumerate(lb[:20], 1):
        print(
            f"  {i:<4} {row['player_name']:<25} "
            f"{row['chest_count']:>7} {row['total_points']:>7}"
        )
    if len(lb) > 20:
        print(f"  ... and {len(lb) - 20} more players")
    print("=" * 60)
    print(f"\n  Dashboard: python main.py dashboard -> http://localhost:5000")
    print(f"  CSV export: python main.py export")


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
    parser.add_argument("--mode", choices=["open", "scroll"], default="open",
                        help="Chest scan mode: 'open' claims each gift (default), "
                             "'scroll' reads without opening")
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
        asyncio.run(cmd_chests(config, args.visible, args.mode))
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