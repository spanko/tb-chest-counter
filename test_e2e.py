#!/usr/bin/env python3
"""End-to-end test — Login → Navigate → Screenshot → Extract → Display.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python test_e2e.py --visible             # Watch it work
    python test_e2e.py                       # Headless
    python test_e2e.py --visible --pause     # Pause between steps for debugging
"""

import argparse
import asyncio
import base64
import json
import logging
import os
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)-12s] %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("e2e_test")


async def main():
    parser = argparse.ArgumentParser(description="TB Toolkit End-to-End Test")
    parser.add_argument("--visible", action="store_true", help="Show browser")
    parser.add_argument("--pause", action="store_true", help="Pause between steps")
    parser.add_argument("--model", default="claude-haiku-4-5-20251001")
    parser.add_argument("--skip-login", action="store_true",
                        help="Skip login (if session cookies are saved)")
    args = parser.parse_args()

    # Load config
    config_path = Path(__file__).parent / "config" / "settings.json"
    if not config_path.exists():
        log.error(f"Config not found: {config_path}")
        log.error("Copy config/settings.example.json → config/settings.json and fill in credentials")
        return
    with open(config_path) as f:
        config = json.load(f)

    api_key = (
        config.get("vision", {}).get("anthropic_api_key")
        or os.environ.get("ANTHROPIC_API_KEY")
    )
    if not api_key:
        log.error("Set ANTHROPIC_API_KEY env var or add vision.anthropic_api_key to config/settings.json")
        return

    # Ensure dirs
    out_dir = Path(__file__).parent / "data" / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)

    def pause(msg: str):
        if args.pause:
            input(f"\n  ⏸️  {msg}\n     Press Enter to continue...\n")

    # ── Launch Browser ──────────────────────────────────────────────────
    from browser import TBBrowser

    log.info("=" * 60)
    log.info("TB Toolkit — End-to-End Test")
    log.info("=" * 60)

    async with TBBrowser(config, headless=not args.visible) as browser:
        # ── Step 1: Login ───────────────────────────────────────────────
        if not args.skip_login:
            log.info("\n[Step 1] Logging in...")
            await browser.login()
            pause("Login complete. Game should be loaded.")

            # Take post-login screenshot
            ss = out_dir / "e2e_01_post_login.png"
            await browser.page.screenshot(path=str(ss))
            log.info(f"  Screenshot: {ss}")
        else:
            log.info("\n[Step 1] Skipping login (--skip-login)")
            await browser.page.goto(config["game"]["url"], wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(15)

        # ── Step 2: Navigate to Gifts ───────────────────────────────────
        log.info("\n[Step 2] Navigating to Clan → Gifts...")
        await browser.navigate_to_gifts()
        pause("Should be on Gifts tab now.")

        ss = out_dir / "e2e_02_gifts_tab.png"
        await browser.page.screenshot(path=str(ss))
        log.info(f"  Screenshot: {ss}")

        # ── Step 3: Capture & Extract ───────────────────────────────────
        log.info("\n[Step 3] Capturing screenshots for extraction...")
        screenshots = await browser.capture_gift_screenshots(count=2)
        log.info(f"  Captured {len(screenshots)} screenshots")

        # Extract using Claude Vision
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        all_gifts = []
        page_num = 0

        while True:
            page_num += 1
            log.info(f"\n[Page {page_num}] Extracting gifts...")

            # Use first screenshot of current page
            image_path = screenshots[0]
            with open(image_path, "rb") as f:
                image_data = base64.standard_b64encode(f.read()).decode("utf-8")

            t0 = time.time()
            response = client.messages.create(
                model=args.model,
                max_tokens=4096,
                system=VISION_SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_data}},
                        {"type": "text", "text": "Extract all visible gift/chest entries from this Total Battle Gifts tab screenshot."},
                    ],
                }],
            )
            elapsed = time.time() - t0

            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]

            result = json.loads(text.strip())
            gifts = result.get("gifts", [])
            has_more = result.get("has_more", False)
            total_badge = result.get("total_gift_count")

            log.info(f"  Extracted {len(gifts)} gifts in {elapsed:.1f}s")
            log.info(f"  Tokens: {response.usage.input_tokens} in / {response.usage.output_tokens} out")
            if total_badge:
                log.info(f"  Total badge: {total_badge}")

            for i, g in enumerate(gifts, 1):
                log.info(f"    {i}. {g['chest_type']} — {g['player_name']} — {g.get('source', '?')}")
                all_gifts.append(g)

            if not has_more:
                log.info(f"  Last page (has_more=false)")
                break

            if page_num >= config.get("chest_counter", {}).get("max_pages", 10):
                log.info(f"  Reached max pages ({page_num})")
                break

            # Scroll and capture next page
            log.info(f"  Scrolling to next page...")
            await browser.scroll_gifts_down()
            pause(f"Scrolled to page {page_num + 1}.")

            screenshots = await browser.capture_gift_screenshots(count=1)

        # ── Summary ─────────────────────────────────────────────────────
        log.info("\n" + "=" * 60)
        log.info(f"EXTRACTION COMPLETE")
        log.info(f"  Total gifts: {len(all_gifts)}")
        log.info(f"  Pages scanned: {page_num}")

        # Group by player
        by_player = {}
        for g in all_gifts:
            name = g["player_name"]
            if name not in by_player:
                by_player[name] = []
            by_player[name].append(g["chest_type"])

        log.info(f"\n  By player:")
        for name, chests in sorted(by_player.items()):
            log.info(f"    {name}: {len(chests)} chests — {', '.join(chests)}")

        # Save full results
        results_path = out_dir / "e2e_extraction_results.json"
        with open(results_path, "w") as f:
            json.dump({"gifts": all_gifts, "pages": page_num}, f, indent=2)
        log.info(f"\n  Results saved: {results_path}")
        log.info("=" * 60)

        pause("Test complete. Review results above.")

        # ── Step 4: Navigate back ───────────────────────────────────────
        await browser.navigate_back_to_main()


# Same prompt as vision.py
VISION_SYSTEM_PROMPT = """You are a precise data extraction assistant for the game Total Battle.
You are looking at screenshots of the Clan Gifts tab, which shows chest gifts
that clan members have earned from crypts, citadels, and other activities.

GIFT ENTRY LAYOUT (each entry is a row with):
- A chest icon on the left with a "Clan" badge
- **Chest type name** in bold (e.g., "Forgotten Chest", "Sand Chest", "Elven Citadel Chest")
- "From: PlayerName" — the clan member who earned it
- "Source: Level X Crypt" or "Source: Level X Citadel" — where it came from
- "Time left: Xh Ym" on the right — countdown until expiry
- A green "Open" button on the far right

PAGE STRUCTURE:
- Top: "Gifts" tab with a red badge showing total count (e.g., "23")
- Middle: List of gift entries (typically 4 visible at once)
- Bottom: "Delete expired chests" link and "Claim chests" button (if visible, this is the last page)

EXTRACTION RULES:
1. Extract EVERY visible gift entry. Do not skip any.
2. Be precise with player names from the "From:" field — they may contain spaces,
   numbers, or unusual capitalization. Do NOT correct unusual spellings.
3. Use the exact chest type name shown in bold.
4. Extract the source (e.g., "Level 10 Crypt", "Level 15 Citadel").
5. Extract the time remaining (e.g., "18h 12m").
6. If the red badge number is visible on the Gifts tab, include it as total_gift_count.
7. Set has_more=false if you can see "Claim chests" or "Delete expired chests" at the bottom.
8. If text is partially obscured or unclear, lower the confidence score.

RESPOND WITH ONLY valid JSON matching this schema (no markdown, no backticks):
{
  "gifts": [
    {
      "player_name": "string",
      "chest_type": "string",
      "source": "string or null",
      "time_left": "string or null",
      "quantity": 1,
      "confidence": 1.0
    }
  ],
  "total_gift_count": null,
  "has_more": false,
  "extraction_notes": ""
}"""


if __name__ == "__main__":
    asyncio.run(main())
