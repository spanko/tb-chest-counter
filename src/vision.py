"""Claude Vision API — Simplified chest extraction for the new scan loop.

Two focused prompts:
1. find_first_gift() — called once at the start to locate the first Open button
2. read_opened_chest() — called after each click to extract chest contents
"""

import json
import logging
from dataclasses import dataclass

import anthropic

log = logging.getLogger(__name__)

# ── Response Models ────────────────────────────────────────────────────────


@dataclass
class FirstGiftResult:
    """Result from find_first_gift()."""
    done: bool  # True if no gifts to claim
    player_name: str
    chest_type: str
    open_button_x: int  # X coordinate of the first Open button
    open_button_y: int  # Y coordinate of the first Open button


@dataclass
class GiftInfo:
    """Info about a single gift in the list."""
    player_name: str
    chest_type: str
    open_button_y: int  # Y coordinate of the Open button


@dataclass
class AllGiftsResult:
    """Result from find_all_visible_gifts()."""
    done: bool  # True if no gifts visible
    open_button_x: int  # X coordinate (same for all buttons)
    gifts: list[GiftInfo]  # List of visible gifts, top to bottom


@dataclass
class ChestItem:
    """A single item from an opened chest."""
    item: str
    quantity: int


@dataclass
class OpenedChestResult:
    """Result from read_opened_chest()."""
    done: bool  # True if no more gifts
    player_name: str
    chest_type: str
    items: list[ChestItem]


# ── Prompts ────────────────────────────────────────────────────────────────

FIND_ALL_GIFTS_PROMPT = """You are looking at the Total Battle Clan Gifts tab at 1280x720.

The gift list shows rows of chests sent by clan members. Each row shows:
- A chest icon on the left
- Player name and chest type (e.g. "Forgotten Chest", "Sapphire Chest", "Barbarian Chest")
- An "Open" button on the right side

List ALL visible gift rows from TOP to BOTTOM. For each gift, provide:
- player_name: The player who sent it
- chest_type: The type of chest (e.g. "Orc Chest", "Sand Chest", "Elegant Chest")
- open_button_y: The Y pixel coordinate of that row's Open button

The Open buttons are all at the same X coordinate (around 770).

Return JSON only:
{
  "done": false,
  "open_button_x": 770,
  "gifts": [
    {"player_name": "Player1", "chest_type": "Orc Chest", "open_button_y": 195},
    {"player_name": "Player2", "chest_type": "Sand Chest", "open_button_y": 255},
    {"player_name": "Player3", "chest_type": "Elegant Chest", "open_button_y": 315},
    {"player_name": "Player4", "chest_type": "Forgotten Chest", "open_button_y": 375}
  ]
}

Set done=true ONLY if there are NO gift rows visible at all (empty list).
Return only valid JSON, no markdown."""

FIND_FIRST_PROMPT = """You are looking at the Total Battle Clan Gifts tab at 1280x720.

The gift list shows rows of chests sent by clan members. Each row shows:
- A chest icon on the left
- Player name and chest type (e.g. "Forgotten Chest", "Sapphire Chest", "Barbarian Chest")
- A button on the right side to claim/open the chest

Find the FIRST (topmost) gift row that has a claimable chest with a button.
Return the EXACT pixel coordinates of the center of that button.

Return JSON only:
{
  "done": false,
  "player_name": "PlayerName",
  "chest_type": "Forgotten Chest",
  "open_button_x": 770,
  "open_button_y": 230
}

Set done=true ONLY if there are NO gift rows visible at all (empty list).
If you see gift rows with chests, return done=false and provide BOTH x and y coordinates.

Return only valid JSON, no markdown."""

READ_CHEST_PROMPT = """A chest in Total Battle was just clicked. Analyze the screen at 1280x720.

Three possible states:
1. A chest OPENED showing its contents in a popup/dialog (items, resources, troops, gold)
2. The gift list is EMPTY — no more gifts to open (done=true)
3. The gift list is still showing with chests to open — the click missed (done=false, return empty items)

IMPORTANT: If you see the gift list with chest rows and "Open" buttons visible, the click did NOT work.
Return done=false with empty items so we can retry.

If a chest popup IS showing with contents:
{
  "done": false,
  "player_name": "PlayerName",
  "chest_type": "Forgotten Chest",
  "items": [
    {"item": "Gold", "quantity": 500000},
    {"item": "Wood", "quantity": 200}
  ]
}

If the gift list is still visible (click missed, need retry):
{"done": false, "player_name": "", "chest_type": "", "items": []}

If no gifts remain (empty list, "No gifts" message):
{"done": true, "player_name": "", "chest_type": "", "items": []}

Return only valid JSON, no markdown."""


# ── Vision Functions ───────────────────────────────────────────────────────


def _call_claude(b64_image: str, prompt: str, config: dict) -> dict:
    """Send image to Claude and parse JSON response."""
    api_key = config["vision"]["anthropic_api_key"]
    model = config["vision"].get("model_routine", "claude-haiku-4-5-20251001")

    client = anthropic.Anthropic(api_key=api_key)

    response = client.messages.create(
        model=model,
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": b64_image,
                        },
                    },
                    {
                        "type": "text",
                        "text": prompt,
                    },
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

    return json.loads(text)


async def find_all_visible_gifts(b64_image: str, config: dict) -> AllGiftsResult:
    """Find ALL visible gifts in the gift list.

    Returns all visible gifts so we can click through them in batch
    before taking another screenshot.

    Args:
        b64_image: Base64-encoded PNG screenshot
        config: Config dict with vision settings

    Returns:
        AllGiftsResult with list of all visible gifts
    """
    try:
        data = _call_claude(b64_image, FIND_ALL_GIFTS_PROMPT, config)

        gifts = []
        for gift_data in data.get("gifts", []):
            gifts.append(GiftInfo(
                player_name=gift_data.get("player_name", ""),
                chest_type=gift_data.get("chest_type", ""),
                open_button_y=gift_data.get("open_button_y", 0),
            ))

        result = AllGiftsResult(
            done=data.get("done", False),
            open_button_x=data.get("open_button_x", 770),
            gifts=gifts,
        )

        if result.done:
            log.info("find_all_visible_gifts: No gifts to claim")
        else:
            log.info(f"find_all_visible_gifts: Found {len(result.gifts)} gifts")
            for g in result.gifts:
                log.info(f"  - {g.player_name}: {g.chest_type} at y={g.open_button_y}")

        return result

    except (json.JSONDecodeError, KeyError) as e:
        log.error(f"find_all_visible_gifts: Failed to parse response: {e}")
        return AllGiftsResult(done=True, open_button_x=770, gifts=[])


async def find_first_gift(b64_image: str, config: dict) -> FirstGiftResult:
    """Find the first Open button in the gift list.

    Called once at the start of a scan to locate the initial click target.

    Args:
        b64_image: Base64-encoded PNG screenshot
        config: Config dict with vision settings

    Returns:
        FirstGiftResult with done=True if no gifts, or open_button_y coordinate
    """
    try:
        data = _call_claude(b64_image, FIND_FIRST_PROMPT, config)

        result = FirstGiftResult(
            done=data.get("done", False),
            player_name=data.get("player_name", ""),
            chest_type=data.get("chest_type", ""),
            open_button_x=data.get("open_button_x", 770),  # Default fallback
            open_button_y=data.get("open_button_y", 0),
        )

        if result.done:
            log.info("find_first_gift: No gifts to claim")
        else:
            log.info(f"find_first_gift: Found '{result.chest_type}' from {result.player_name} at ({result.open_button_x}, {result.open_button_y})")

        return result

    except (json.JSONDecodeError, KeyError) as e:
        log.error(f"find_first_gift: Failed to parse response: {e}")
        return FirstGiftResult(done=True, player_name="", chest_type="", open_button_x=770, open_button_y=0)


@dataclass
class PopupDetectionResult:
    """Result from detect_popup_blocker()."""
    has_blocker: bool  # True if something is blocking the Gifts tab
    description: str  # What the blocker is
    close_method: str  # "x_button", "click_outside", "escape", or "none"
    x: int  # X coordinate if close_method is "x_button"
    y: int  # Y coordinate if close_method is "x_button"


POPUP_DETECTION_PROMPT = """You are looking at a Total Battle game screenshot at 1280x720.

Look for any POPUP or OVERLAY blocking the main game view. A popup is:
- A rectangular panel/dialog floating IN FRONT of the game
- Usually centered or prominent on screen
- Has an X (close) button in its upper-right corner
- May have a darker/dimmed background behind it

Common popup types that MUST be closed:
- Store/shop panels (Bonus Sales, Special Offers, item shops with prices)
- Info panels ("Great Archaeologist", tutorials, help screens)
- Proposal/offer dialogs ("A proposal from...")
- Payment dialogs with USD prices
- Achievement/reward notifications
- Event banners or announcements

CRITICAL: The X button is ALWAYS in the upper-right corner OF THE POPUP PANEL ITSELF.
This is NOT the screen edge - look 20-40 pixels inside from the panel's top-right corner.
The X is usually a small icon or button within the popup's border.

What is NOT a popup (do NOT report as blocker):
- The Clan panel on the left side with Gifts/Members tabs
- The gift list showing player names and "Open" buttons
- Bottom navigation bar
- Top resource bar
- Normal game UI elements

If you find a popup:
1. Identify the X button in its upper-right corner
2. Return the EXACT pixel coordinates of the X button center

Return JSON only (no markdown):
{
  "has_blocker": true,
  "description": "Great Archaeologist info panel",
  "close_method": "x_button",
  "x": 875,
  "y": 95
}

If no X visible, click outside the popup:
{
  "has_blocker": true,
  "description": "Payment dialog without clear X",
  "close_method": "click_outside",
  "x": 50,
  "y": 400
}

If no popup found:
{
  "has_blocker": false,
  "description": "Clan Gifts tab visible with chest rows",
  "close_method": "none",
  "x": 0,
  "y": 0
}

Return only valid JSON."""


async def detect_popup_blocker(b64_image: str, config: dict) -> PopupDetectionResult:
    """Detect if anything is blocking access to the Gifts tab.

    Uses Vision to identify popups/overlays and determine how to close them.

    Args:
        b64_image: Base64-encoded PNG screenshot
        config: Config dict with vision settings

    Returns:
        PopupDetectionResult with blocker info and close instructions
    """
    try:
        data = _call_claude(b64_image, POPUP_DETECTION_PROMPT, config)

        result = PopupDetectionResult(
            has_blocker=data.get("has_blocker", False),
            description=data.get("description", ""),
            close_method=data.get("close_method", "none"),
            x=data.get("x", 0),
            y=data.get("y", 0),
        )

        if result.has_blocker:
            log.info(f"detect_popup_blocker: Found '{result.description}' — close via {result.close_method} at ({result.x}, {result.y})")
        else:
            log.info(f"detect_popup_blocker: No blocker — {result.description}")

        return result

    except (json.JSONDecodeError, KeyError) as e:
        log.error(f"detect_popup_blocker: Failed to parse response: {e}")
        return PopupDetectionResult(
            has_blocker=False,
            description=f"parse error: {e}",
            close_method="none",
            x=0,
            y=0
        )


async def read_opened_chest(b64_image: str, config: dict) -> OpenedChestResult:
    """Read the contents of a just-opened chest.

    Called after each Open button click to extract chest contents.

    Args:
        b64_image: Base64-encoded PNG screenshot
        config: Config dict with vision settings

    Returns:
        OpenedChestResult with chest contents or done=True if list is empty
    """
    try:
        data = _call_claude(b64_image, READ_CHEST_PROMPT, config)

        items = []
        for item_data in data.get("items", []):
            items.append(ChestItem(
                item=item_data.get("item", ""),
                quantity=item_data.get("quantity", 0),
            ))

        result = OpenedChestResult(
            done=data.get("done", False),
            player_name=data.get("player_name", ""),
            chest_type=data.get("chest_type", ""),
            items=items,
        )

        if result.done:
            log.info("read_opened_chest: No more gifts")
        else:
            items_str = ", ".join(f"{i.item}x{i.quantity}" for i in result.items[:3])
            log.info(f"read_opened_chest: {result.player_name} — {result.chest_type}: {items_str}")

        return result

    except (json.JSONDecodeError, KeyError) as e:
        log.error(f"read_opened_chest: Failed to parse response: {e}")
        return OpenedChestResult(done=True, player_name="", chest_type="", items=[])
