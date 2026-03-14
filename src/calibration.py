"""Vision-based UI calibration for Total Battle.

Instead of hardcoded pixel coordinates, we screenshot the current game state
and ask Claude Vision to locate UI elements. Results are cached to disk
and reused until the next calibration run.

Calibration flow:
    1. Take a screenshot of the current game state
    2. Send to Claude Vision with a prompt asking for element bounding boxes
    3. Parse response into a calibration profile
    4. Save to data/calibration.json
    5. browser.py reads calibration profile instead of using hardcoded coords

Recalibrate when:
    - First run on a new machine
    - Game UI updates
    - Viewport size changes
    - Clicks are missing their targets
"""

import asyncio
import base64
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import anthropic

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent


# ── Calibration Profile ─────────────────────────────────────────────────────

CALIBRATION_FILE = ROOT / "data" / "calibration.json"

# The screens we need to calibrate against and the elements we need on each.
# Each element has a description Claude Vision will use to locate it.
CALIBRATION_SCREENS = {
    "main_game": {
        "description": "Main game view after login with popups dismissed. Shows the city/base with bottom navigation bar.",
        "elements": {
            "bottom_nav_clan": {
                "description": (
                    "The CLAN button in the bottom navigation bar. It has a shield/banner icon "
                    "and the word 'CLAN' or a clan-related icon. It's typically the 5th or 6th "
                    "button from the left in the bottom nav bar. Return the CENTER of this button."
                ),
            },
        },
    },
    "clan_panel": {
        "description": "The 'My Clan' panel is open, showing clan info with a left sidebar containing navigation items.",
        "elements": {
            "sidebar_gifts": {
                "description": (
                    "The 'Gifts' menu item in the left sidebar of the clan panel. "
                    "It may have a red badge/number showing pending gift count. "
                    "Return the CENTER of this clickable menu item."
                ),
            },
            "sidebar_members": {
                "description": (
                    "The 'Members' menu item in the left sidebar of the clan panel. "
                    "It may show a member count. Return the CENTER of this clickable item."
                ),
            },
            "close_button": {
                "description": (
                    "The X (close) button in the top-right corner of the 'My Clan' panel. "
                    "Return the CENTER of this X button."
                ),
            },
        },
    },
    "gifts_view": {
        "description": "The Gifts tab is open inside the clan panel, showing a list of gift/chest entries.",
        "elements": {
            "gift_list_center": {
                "description": (
                    "The CENTER of the scrollable gift list area. This is where we position "
                    "the mouse for scrolling. Return the center point of the list content area, "
                    "NOT a header or button."
                ),
            },
            "gift_list_top": {
                "description": (
                    "The TOP of the visible gift list area (just below any headers/tabs). "
                    "Return the Y coordinate where the first gift entry starts."
                ),
            },
            "gift_list_bottom": {
                "description": (
                    "The BOTTOM of the visible gift list area (just above any footer buttons). "
                    "Return the Y coordinate where the last visible gift entry ends."
                ),
            },
            "triumphal_gifts_tab": {
                "description": (
                    "The 'Triumphal Gifts' tab header/button, if visible. This is a tab at the top "
                    "of the gifts view that switches between regular gifts and triumphal gifts. "
                    "Return the CENTER of this tab. Return null if not visible."
                ),
            },
        },
    },
    "members_view": {
        "description": "The Members tab is open inside the clan panel, showing a list of clan member names.",
        "elements": {
            "member_list_center": {
                "description": (
                    "The CENTER of the scrollable member list area. This is where we position "
                    "the mouse for scrolling through the member list."
                ),
            },
            "member_list_top": {
                "description": (
                    "The TOP Y coordinate where the first member entry starts in the list."
                ),
            },
            "member_list_bottom": {
                "description": (
                    "The BOTTOM Y coordinate where the last visible member entry ends."
                ),
            },
        },
    },
}


LOCATE_SYSTEM_PROMPT = """You are a precise UI element locator for the game Total Battle.
You are given a screenshot of the game UI and asked to find specific elements.

IMPORTANT RULES:
1. Return pixel coordinates as integers, relative to the top-left corner of the image.
2. For "CENTER" requests, estimate the center of the clickable area of the element.
3. If an element is NOT visible or does NOT exist in the screenshot, return null.
4. Be precise — off-by-20-pixels is fine, off-by-100 will miss the target.
5. The viewport is {width}x{height} pixels.
6. Pay close attention to the bottom navigation bar — it contains small icon buttons.
7. The clan panel has a brown/dark left sidebar with menu items stacked vertically.

Return ONLY valid JSON, no markdown fences, no explanation."""


LOCATE_USER_PROMPT = """Look at this Total Battle screenshot and locate these UI elements.

Current screen context: {screen_description}

For each element below, return its pixel coordinates as {{"x": int, "y": int}} or null if not found.

Elements to locate:
{elements_json}

Return a JSON object mapping element names to coordinates:
{{
  "element_name": {{"x": 123, "y": 456}},
  "other_element": null
}}"""


# ── Calibration Functions ────────────────────────────────────────────────────

def _normalize_coords(raw) -> Optional[dict]:
    """Normalize coordinates from various Vision response formats.

    Handles:
        {"x": 123, "y": 456}                → {"x": 123, "y": 456}
        [123, 456]                           → {"x": 123, "y": 456}
        {"center_x": 123, "center_y": 456}  → {"x": 123, "y": 456}
        {"left": 100, "top": 200, ...}      → {"x": 100, "y": 200}
        null / None                          → None
        anything else                        → None
    """
    if raw is None:
        return None

    if isinstance(raw, list) and len(raw) >= 2:
        try:
            return {"x": int(raw[0]), "y": int(raw[1])}
        except (ValueError, TypeError):
            return None

    if isinstance(raw, dict):
        # Direct x/y keys
        if "x" in raw and "y" in raw:
            try:
                return {"x": int(raw["x"]), "y": int(raw["y"])}
            except (ValueError, TypeError):
                return None

        # Alternate key patterns
        x_keys = ["x", "center_x", "cx", "left", "pixel_x"]
        y_keys = ["y", "center_y", "cy", "top", "pixel_y"]

        x_val = None
        y_val = None
        for k in x_keys:
            if k in raw:
                x_val = raw[k]
                break
        for k in y_keys:
            if k in raw:
                y_val = raw[k]
                break

        if x_val is not None and y_val is not None:
            try:
                return {"x": int(x_val), "y": int(y_val)}
            except (ValueError, TypeError):
                return None

    log.debug(f"Could not normalize coords: {raw}")
    return None

def load_calibration() -> Optional[dict]:
    """Load cached calibration profile from disk."""
    if CALIBRATION_FILE.exists():
        try:
            with open(CALIBRATION_FILE) as f:
                data = json.load(f)
            log.debug(f"Loaded calibration from {CALIBRATION_FILE}")
            return data
        except (json.JSONDecodeError, KeyError) as e:
            log.warning(f"Invalid calibration file: {e}")
    return None


def save_calibration(profile: dict):
    """Save calibration profile to disk."""
    CALIBRATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    profile["calibrated_at"] = datetime.now(timezone.utc).isoformat()
    with open(CALIBRATION_FILE, "w") as f:
        json.dump(profile, f, indent=2)
    log.info(f"Calibration saved to {CALIBRATION_FILE}")


def get_element_coords(profile: dict, screen: str, element: str) -> Optional[dict]:
    """Get calibrated coordinates for an element.

    Returns:
        {"x": int, "y": int} or None if not calibrated/found.
    """
    if not profile:
        return None
    screens = profile.get("screens", {})
    elements = screens.get(screen, {}).get("elements", {})
    coords = elements.get(element)
    if coords and isinstance(coords, dict) and "x" in coords and "y" in coords:
        return coords
    return None


async def locate_elements_in_screenshot(
    screenshot_path: str,
    screen_name: str,
    config: dict,
) -> dict:
    """Send a screenshot to Claude Vision and ask it to locate UI elements.

    Args:
        screenshot_path: Path to PNG screenshot
        screen_name: Key into CALIBRATION_SCREENS
        config: App config (needs vision.anthropic_api_key)

    Returns:
        Dict mapping element names to {"x": int, "y": int} or None
    """
    screen_def = CALIBRATION_SCREENS.get(screen_name)
    if not screen_def:
        raise ValueError(f"Unknown calibration screen: {screen_name}")

    api_key = config["vision"]["anthropic_api_key"]
    # Use the stronger model for calibration — accuracy matters more than cost
    model = config["vision"].get("model_verify", "claude-sonnet-4-5-20250929")

    viewport = config["game"].get("viewport", {"width": 1280, "height": 720})

    # Build element descriptions for the prompt
    elements_for_prompt = {}
    for elem_name, elem_def in screen_def["elements"].items():
        elements_for_prompt[elem_name] = elem_def["description"]

    # Read and encode image
    with open(screenshot_path, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")

    client = anthropic.Anthropic(api_key=api_key)

    system_prompt = LOCATE_SYSTEM_PROMPT.format(
        width=viewport["width"], height=viewport["height"]
    )
    user_prompt = LOCATE_USER_PROMPT.format(
        screen_description=screen_def["description"],
        elements_json=json.dumps(elements_for_prompt, indent=2),
    )

    log.info(f"Calibrating screen '{screen_name}' — locating {len(elements_for_prompt)} elements...")

    try:
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_data,
                            },
                        },
                        {"type": "text", "text": user_prompt},
                    ],
                }
            ],
        )

        text = response.content[0].text.strip()
        # Strip markdown fences if present
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        result = json.loads(text)

        # Normalize coordinates — Vision may return various formats:
        #   {"x": 123, "y": 456}           ← expected
        #   [123, 456]                      ← list form
        #   {"center_x": 123, "center_y": 456}  ← alternate keys
        #   {"x": 123, "y": 456, "width": ...}  ← with extras (fine)
        #   123                             ← just a number (broken)
        normalized = {}
        for name, coords in result.items():
            normalized[name] = _normalize_coords(coords)

        log.info(f"  Calibration results for '{screen_name}':")
        for name, coords in normalized.items():
            if coords:
                log.info(f"    {name}: ({coords['x']}, {coords['y']})")
            else:
                log.info(f"    {name}: NOT FOUND")

        return normalized

    except json.JSONDecodeError as e:
        log.error(f"Failed to parse calibration response: {e}")
        log.debug(f"Raw: {text[:500]}")
        return {}
    except anthropic.APIError as e:
        log.error(f"Claude API error during calibration: {e}")
        return {}


async def run_full_calibration(browser, config: dict) -> dict:
    """Run the full calibration sequence across all game screens.

    This navigates through the game UI, takes screenshots at each state,
    and uses Vision to locate all the elements we need.

    Args:
        browser: TBBrowser instance (already logged in)
        config: App config

    Returns:
        Complete calibration profile dict
    """
    profile = {
        "viewport": config["game"].get("viewport", {"width": 1280, "height": 720}),
        "screens": {},
    }

    ss_dir = ROOT / config["storage"]["screenshot_dir"] / "calibration"
    ss_dir.mkdir(parents=True, exist_ok=True)

    # ── Screen 1: Main game view ────────────────────────────────────────
    log.info("=" * 60)
    log.info("CALIBRATION STEP 1: Main game view")
    log.info("=" * 60)

    # Dismiss any popups first
    for _ in range(5):
        await browser.page.keyboard.press("Escape")
        await asyncio.sleep(0.3)
    await asyncio.sleep(2)

    ss_path = str(ss_dir / "cal_01_main_game.png")
    await browser.page.screenshot(path=ss_path, full_page=False)
    log.info(f"Screenshot: {ss_path}")

    main_elements = await locate_elements_in_screenshot(ss_path, "main_game", config)
    profile["screens"]["main_game"] = {
        "elements": main_elements,
        "screenshot": ss_path,
    }

    # ── Screen 2: Open clan panel ───────────────────────────────────────
    clan_btn = main_elements.get("bottom_nav_clan")
    if not clan_btn:
        log.error("CALIBRATION FAILED: Could not locate CLAN button on main screen.")
        log.error("Make sure the game is fully loaded with the bottom nav visible.")
        save_calibration(profile)
        return profile

    log.info("=" * 60)
    log.info("CALIBRATION STEP 2: Clan panel")
    log.info("=" * 60)

    await browser.page.mouse.click(clan_btn["x"], clan_btn["y"])
    log.info(f"Clicked CLAN button at ({clan_btn['x']}, {clan_btn['y']})")
    await asyncio.sleep(4)

    ss_path = str(ss_dir / "cal_02_clan_panel.png")
    await browser.page.screenshot(path=ss_path, full_page=False)
    log.info(f"Screenshot: {ss_path}")

    clan_elements = await locate_elements_in_screenshot(ss_path, "clan_panel", config)
    profile["screens"]["clan_panel"] = {
        "elements": clan_elements,
        "screenshot": ss_path,
    }

    # ── Screen 3: Open Gifts view ───────────────────────────────────────
    gifts_btn = clan_elements.get("sidebar_gifts")
    if not gifts_btn:
        log.error("CALIBRATION FAILED: Could not locate Gifts in clan sidebar.")
        save_calibration(profile)
        return profile

    log.info("=" * 60)
    log.info("CALIBRATION STEP 3: Gifts view")
    log.info("=" * 60)

    await browser.page.mouse.click(gifts_btn["x"], gifts_btn["y"])
    log.info(f"Clicked Gifts at ({gifts_btn['x']}, {gifts_btn['y']})")
    await asyncio.sleep(3)

    ss_path = str(ss_dir / "cal_03_gifts_view.png")
    await browser.page.screenshot(path=ss_path, full_page=False)
    log.info(f"Screenshot: {ss_path}")

    gifts_elements = await locate_elements_in_screenshot(ss_path, "gifts_view", config)
    profile["screens"]["gifts_view"] = {
        "elements": gifts_elements,
        "screenshot": ss_path,
    }

    # ── Screen 4: Open Members view ─────────────────────────────────────
    # Go back to clan panel sidebar first
    members_btn = clan_elements.get("sidebar_members")
    if not members_btn:
        log.warning("Could not locate Members in clan sidebar — skipping members calibration.")
        log.warning("Will re-attempt from clan panel on next calibration.")
    else:
        log.info("=" * 60)
        log.info("CALIBRATION STEP 4: Members view")
        log.info("=" * 60)

        # Need to navigate back to sidebar. Click Gifts → Members might work,
        # or we close and reopen. Safest: the sidebar should still be visible.
        await browser.page.mouse.click(members_btn["x"], members_btn["y"])
        log.info(f"Clicked Members at ({members_btn['x']}, {members_btn['y']})")
        await asyncio.sleep(3)

        ss_path = str(ss_dir / "cal_04_members_view.png")
        await browser.page.screenshot(path=ss_path, full_page=False)
        log.info(f"Screenshot: {ss_path}")

        members_elements = await locate_elements_in_screenshot(
            ss_path, "members_view", config
        )
        profile["screens"]["members_view"] = {
            "elements": members_elements,
            "screenshot": ss_path,
        }

    # ── Close clan panel and finish ─────────────────────────────────────
    close_btn = clan_elements.get("close_button")
    if close_btn:
        await browser.page.mouse.click(close_btn["x"], close_btn["y"])
        await asyncio.sleep(1)
    await browser.page.keyboard.press("Escape")
    await asyncio.sleep(1)

    save_calibration(profile)

    # Summary
    log.info("=" * 60)
    log.info("CALIBRATION COMPLETE")
    log.info("=" * 60)
    total = sum(
        sum(1 for v in s.get("elements", {}).values() if v)
        for s in profile["screens"].values()
    )
    missing = sum(
        sum(1 for v in s.get("elements", {}).values() if not v)
        for s in profile["screens"].values()
    )
    log.info(f"  Located: {total} elements")
    if missing:
        log.warning(f"  Missing: {missing} elements — some features may not work")
    log.info(f"  Saved to: {CALIBRATION_FILE}")

    return profile


# ── Single-element recalibration ─────────────────────────────────────────────

async def recalibrate_element(
    browser, config: dict, screen_name: str, element_name: str
) -> Optional[dict]:
    """Re-locate a single element by taking a fresh screenshot.

    Useful when the UI state has shifted (e.g., after a popup) and a cached
    coordinate is stale. Updates the calibration file in place.

    Returns:
        {"x": int, "y": int} or None
    """
    ss_dir = ROOT / config["storage"]["screenshot_dir"] / "calibration"
    ss_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    ss_path = str(ss_dir / f"recal_{screen_name}_{ts}.png")
    await browser.page.screenshot(path=ss_path, full_page=False)

    elements = await locate_elements_in_screenshot(ss_path, screen_name, config)
    coords = elements.get(element_name)

    if coords:
        # Update cached profile
        profile = load_calibration() or {"screens": {}, "viewport": {}}
        if screen_name not in profile["screens"]:
            profile["screens"][screen_name] = {"elements": {}}
        profile["screens"][screen_name]["elements"][element_name] = coords
        save_calibration(profile)
        log.info(f"Recalibrated {screen_name}.{element_name} → ({coords['x']}, {coords['y']})")

    return coords
