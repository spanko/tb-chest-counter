"""Claude Vision API — Structured chest extraction from screenshots.

Sends gift tab screenshots to Claude and gets back structured JSON
with player names, chest types, and confidence scores.
"""

import base64
import json
import logging
from pathlib import Path
from typing import Optional

import anthropic
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

# ── Structured Output Schemas ───────────────────────────────────────────────

class ChestGift(BaseModel):
    """A single gift/chest entry extracted from the screenshot."""
    player_name: Optional[str] = Field(default=None, description="Player name from the 'From:' field, exactly as displayed")
    chest_type: str = Field(description="Full chest type name in bold, e.g. 'Forgotten Chest', 'Elven Citadel Chest'")
    source: Optional[str] = Field(default=None, description="Source field, e.g. 'Level 10 Crypt', 'Level 15 Citadel'")
    time_left: Optional[str] = Field(default=None, description="Time remaining, e.g. '18h 12m', '17h 53m'")
    quantity: int = Field(default=1, description="Number of chests (usually 1)")
    confidence: float = Field(default=1.0, description="0.0-1.0 extraction confidence")


class GiftPageExtraction(BaseModel):
    """Result of extracting all gifts from one screenshot."""
    gifts: list[ChestGift] = Field(default_factory=list)
    total_gift_count: Optional[int] = Field(default=None, description="Number shown in the Gifts tab badge, e.g. 23")
    has_more: bool = Field(default=False, description="True if the list continues below visible area (no 'Claim chests' button visible)")
    extraction_notes: str = Field(default="", description="Any issues noticed during extraction")


# ── System Prompt ───────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a precise data extraction assistant for the game Total Battle.
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
- Bottom: "Delete expired chests" link and "Claim chests" button (only visible on the last page)

EXTRACTION RULES:
1. Extract EVERY visible gift entry. Do not skip any.
2. Be precise with player names from the "From:" field — they may contain spaces,
   numbers, or unusual capitalization. Do NOT correct unusual spellings.
3. Use the exact chest type name shown in bold.
4. Extract the source (e.g., "Level 10 Crypt", "Level 15 Citadel").
5. Extract the time remaining (e.g., "18h 12m").
6. If the red badge number is visible on the Gifts tab, include it as total_gift_count.
7. IMPORTANT: Set has_more=true if you CANNOT see "Claim chests" or "Delete expired chests" at the bottom.
   Set has_more=false ONLY when you can see these buttons (meaning this is the last page).
8. If text is partially obscured or unclear, lower the confidence score.

CONFIDENCE SCORING:
- 1.0 = clearly readable, no ambiguity
- 0.8-0.9 = mostly clear, minor uncertainty in one character
- 0.5-0.7 = partially obscured or ambiguous
- Below 0.5 = best guess, needs verification

IMPORTANT: If you do NOT see the Gifts tab or any gift entries (e.g., the screenshot shows
a different screen, or the gift list is empty), return an empty gifts array and describe
what you actually see in extraction_notes. This helps diagnose navigation issues."""

USER_PROMPT = """Extract all visible gift/chest entries from this Total Battle Gifts tab screenshot.

Return a JSON object with this EXACT structure:
{
  "gifts": [
    {
      "player_name": "PlayerName from 'From:' field",
      "chest_type": "Full chest name from bold text",
      "source": "Source text or null",
      "time_left": "Time remaining or null",
      "quantity": 1,
      "confidence": 1.0
    }
  ],
  "total_gift_count": null or number from badge,
  "has_more": true if there are more gifts below (no "Claim chests" button visible),
  "extraction_notes": ""
}

IMPORTANT:
- Use field name "player_name" NOT "from_player" or other variations.
- Set has_more=true when the list continues below and you CANNOT see the "Claim chests" button.
- Set has_more=false ONLY when you can see the "Claim chests" or "Delete expired chests" buttons."""

# ── Extraction Functions ────────────────────────────────────────────────────

def extract_gifts_from_screenshot(image_path: str, config: dict) -> GiftPageExtraction:
    """Send a screenshot to Claude Vision and get structured gift data back.
    
    Args:
        image_path: Path to the PNG screenshot
        config: Full config dict (needs vision.anthropic_api_key and vision.model_routine)
        
    Returns:
        GiftPageExtraction with list of gifts
    """
    api_key = config["vision"]["anthropic_api_key"]
    model = config["vision"].get("model_routine", "claude-haiku-4-5-20251001")

    # Read and encode image
    with open(image_path, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")

    client = anthropic.Anthropic(api_key=api_key)

    log.debug(f"Sending {image_path} to {model}...")

    try:
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
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
                        {
                            "type": "text",
                            "text": USER_PROMPT,
                        },
                    ],
                }
            ],
        )

        # Parse the response — Claude should return JSON matching our schema
        text = response.content[0].text
        log.debug(f"Raw Claude response: {text[:1000]}")

        # Try to parse as JSON (Claude usually wraps in ```json blocks or returns raw)
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        # Handle case where Claude adds explanatory text after JSON
        # Find the first complete JSON object
        if text.startswith("{"):
            brace_count = 0
            json_end = 0
            for i, char in enumerate(text):
                if char == "{":
                    brace_count += 1
                elif char == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        json_end = i + 1
                        break
            if json_end > 0:
                text = text[:json_end]

        data = json.loads(text)
        # Ensure has_more is a boolean, default to False if None
        if "has_more" not in data or data["has_more"] is None:
            data["has_more"] = False

        # Filter out gifts without player_name (invalid extractions)
        if "gifts" in data:
            original_count = len(data["gifts"])
            data["gifts"] = [g for g in data["gifts"] if g.get("player_name")]
            filtered_count = original_count - len(data["gifts"])
            if filtered_count > 0:
                log.warning(f"Filtered out {filtered_count} gifts without player names")

        result = GiftPageExtraction(**data)
        log.info(f"Extracted {len(result.gifts)} gifts from {Path(image_path).name}")
        if not result.gifts and result.extraction_notes:
            log.warning(f"No gifts found. Vision notes: {result.extraction_notes}")
        return result

    except json.JSONDecodeError as e:
        log.error(f"Failed to parse Claude response as JSON: {e}")
        log.debug(f"Raw response: {text[:500]}")
        return GiftPageExtraction(extraction_notes=f"JSON parse error: {e}")

    except anthropic.APIError as e:
        log.error(f"Claude API error: {e}")
        return GiftPageExtraction(extraction_notes=f"API error: {e}")


def verify_with_stronger_model(image_path: str, config: dict) -> GiftPageExtraction:
    """Re-extract using the verification model (Sonnet) for higher accuracy."""
    api_key = config["vision"]["anthropic_api_key"]
    model = config["vision"].get("model_verify", "claude-sonnet-4-5-20250929")

    # Same extraction, different model
    original_model = config["vision"].get("model_routine")
    config["vision"]["model_routine"] = model
    result = extract_gifts_from_screenshot(image_path, config)
    config["vision"]["model_routine"] = original_model

    return result


# ── Consensus & Validation ──────────────────────────────────────────────────

def consensus_merge(extractions: list[GiftPageExtraction]) -> list[ChestGift]:
    """Merge multiple extractions of the same page, keeping consensus results.
    
    A gift is confirmed if it appears in the majority of extractions.
    This catches transient rendering glitches and LLM hallucinations.
    """
    if not extractions:
        return []

    if len(extractions) == 1:
        return extractions[0].gifts

    threshold = len(extractions) / 2  # Strict majority: must appear in MORE than half

    # Group gifts by normalized (player_name, chest_type)
    groups: dict[tuple, list[ChestGift]] = {}
    for extraction in extractions:
        for gift in extraction.gifts:
            key = (gift.player_name.strip().lower(), gift.chest_type.strip().lower())
            if key not in groups:
                groups[key] = []
            groups[key].append(gift)

    # Keep gifts that appear in majority of frames
    confirmed = []
    for key, gifts in groups.items():
        if len(gifts) > threshold:
            # Use the version with highest confidence
            best = max(gifts, key=lambda g: g.confidence)
            best.confidence = len(gifts) / len(extractions)
            confirmed.append(best)
        else:
            log.debug(f"Dropping low-consensus gift: {key} ({len(gifts)}/{len(extractions)})")

    return confirmed


def validate_player_names(gifts: list[ChestGift], roster: list[str]) -> list[ChestGift]:
    """Validate extracted player names against known clan roster.
    
    Uses fuzzy matching to correct minor OCR/vision errors.
    """
    if not roster:
        return gifts

    from thefuzz import process

    for gift in gifts:
        match, score = process.extractOne(gift.player_name, roster)
        if score >= 90:
            if match != gift.player_name:
                log.debug(f"Corrected player name: '{gift.player_name}' → '{match}' (score={score})")
            gift.player_name = match
        elif score >= 70:
            log.warning(f"Low-confidence name match: '{gift.player_name}' ≈ '{match}' (score={score})")
            gift.confidence *= (score / 100)
        else:
            log.warning(f"Unknown player: '{gift.player_name}' (best match: '{match}' at {score})")
            gift.confidence *= 0.5

    return gifts
