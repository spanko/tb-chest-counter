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
    open_button_y: int  # Y coordinate of the first Open button


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

FIND_FIRST_PROMPT = """You are looking at the Total Battle Clan Gifts tab at 1280x720.

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
Return only valid JSON, no markdown."""

READ_CHEST_PROMPT = """A chest in Total Battle was just clicked open. Analyze the screen.

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
            open_button_y=data.get("open_button_y", 0),
        )

        if result.done:
            log.info("find_first_gift: No gifts to claim")
        else:
            log.info(f"find_first_gift: Found '{result.chest_type}' from {result.player_name} at y={result.open_button_y}")

        return result

    except (json.JSONDecodeError, KeyError) as e:
        log.error(f"find_first_gift: Failed to parse response: {e}")
        return FirstGiftResult(done=True, player_name="", chest_type="", open_button_y=0)


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
