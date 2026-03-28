"""Clan roster management — scrape members from game UI via Vision.

Screenshots the Members tab in the clan panel, uses Claude Vision to
extract player names, and tracks membership changes over time in SQLite.
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


# ── Vision Prompts ───────────────────────────────────────────────────────────

ROSTER_SYSTEM_PROMPT = """You are a precise data extraction assistant for the game Total Battle.
You are looking at a screenshot of the Clan Members list, which shows all members
of a clan with their names, roles, and other information.

EXTRACTION RULES:
1. Extract EVERY visible player name in the member list.
2. Be precise with player names — they may contain spaces, numbers, special characters,
   or unusual capitalization. Do NOT correct or normalize names.
3. If a role/rank is visible next to the name (e.g., "Leader", "Officer", "Elder", "Member"),
   extract it too.
4. If power/might numbers are visible, extract them.
5. Set has_more=true if the list appears to continue below the visible area
   (i.e., you can see partial entries at the bottom, or there's no clear end-of-list indicator).
6. If text is partially obscured, lower the confidence and include your best guess.

CONFIDENCE SCORING:
- 1.0 = clearly readable
- 0.8-0.9 = mostly clear, minor uncertainty
- 0.5-0.7 = partially obscured
- Below 0.5 = best guess"""

ROSTER_USER_PROMPT = """Extract all visible clan member names from this Total Battle Members tab screenshot.

Return a JSON object with this EXACT structure:
{
  "members": [
    {
      "player_name": "ExactPlayerName",
      "role": "Leader" or "Officer" or "Elder" or "Member" or null,
      "might": null or integer,
      "confidence": 1.0
    }
  ],
  "total_member_count": null or number if shown (e.g., "45/50 members"),
  "has_more": true/false,
  "extraction_notes": ""
}

IMPORTANT: Extract every visible name. Do not skip any."""


# ── Extraction ───────────────────────────────────────────────────────────────

class RosterMember:
    """A single clan member extracted from a screenshot."""

    def __init__(self, player_name: str, role: Optional[str] = None,
                 might: Optional[int] = None, confidence: float = 1.0):
        self.player_name = player_name
        self.role = role
        self.might = might
        self.confidence = confidence

    def to_dict(self) -> dict:
        return {
            "player_name": self.player_name,
            "role": self.role,
            "might": self.might,
            "confidence": self.confidence,
        }


class RosterPageExtraction:
    """Result of extracting members from one screenshot."""

    def __init__(self, members: list[RosterMember] = None,
                 total_member_count: Optional[int] = None,
                 has_more: bool = False, extraction_notes: str = ""):
        self.members = members or []
        self.total_member_count = total_member_count
        self.has_more = has_more
        self.extraction_notes = extraction_notes


def extract_members_from_screenshot(
    image_path: str, config: dict
) -> RosterPageExtraction:
    """Send a Members tab screenshot to Claude Vision and extract names.

    Uses the stronger verification model since roster accuracy is important
    and this runs infrequently.
    """
    api_key = config["vision"]["anthropic_api_key"]
    # Use Sonnet for roster — runs rarely, accuracy matters
    model = config["vision"].get("model_verify", "claude-sonnet-4-5-20250929")

    with open(image_path, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")

    client = anthropic.Anthropic(api_key=api_key)
    log.debug(f"Sending {image_path} to {model} for roster extraction...")

    try:
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=ROSTER_SYSTEM_PROMPT,
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
                        {"type": "text", "text": ROSTER_USER_PROMPT},
                    ],
                }
            ],
        )

        text = response.content[0].text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        # Extract first complete JSON object
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

        members = []
        for m in data.get("members", []):
            if m.get("player_name"):
                members.append(RosterMember(
                    player_name=m["player_name"],
                    role=m.get("role"),
                    might=m.get("might"),
                    confidence=m.get("confidence", 1.0),
                ))

        result = RosterPageExtraction(
            members=members,
            total_member_count=data.get("total_member_count"),
            has_more=data.get("has_more", False),
            extraction_notes=data.get("extraction_notes", ""),
        )
        log.info(f"Extracted {len(result.members)} members from {Path(image_path).name}")
        return result

    except json.JSONDecodeError as e:
        log.error(f"Failed to parse roster response: {e}")
        return RosterPageExtraction(extraction_notes=f"JSON parse error: {e}")
    except anthropic.APIError as e:
        log.error(f"Claude API error during roster extraction: {e}")
        return RosterPageExtraction(extraction_notes=f"API error: {e}")


# ── Full roster scan (multi-page) ───────────────────────────────────────────

async def scan_clan_roster(browser, config: dict) -> list[RosterMember]:
    """Navigate to Members tab and extract all clan members.

    Scrolls through the entire member list, extracting names from each
    visible page. Deduplicates across pages.

    Args:
        browser: TBBrowser instance (logged in, calibrated)
        config: App config

    Returns:
        Deduplicated list of RosterMember objects
    """
    ss_dir = ROOT / config["storage"]["screenshot_dir"] / "roster"
    ss_dir.mkdir(parents=True, exist_ok=True)

    # Use browser's calibrated navigation
    try:
        await browser.navigate_to_members()
    except RuntimeError as e:
        log.error(f"Cannot navigate to members: {e}")
        return []

    # ── Scroll and extract ───────────────────────────────────────────────
    all_members: dict[str, RosterMember] = {}  # name_lower → member (dedup)
    page_num = 0
    max_pages = 20  # Safety limit

    while page_num < max_pages:
        # Screenshot current view
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        ss_path = str(ss_dir / f"members_p{page_num:02d}_{ts}.png")
        await browser.page.screenshot(path=ss_path, full_page=False)

        extraction = extract_members_from_screenshot(ss_path, config)
        new_on_page = 0

        for member in extraction.members:
            name_key = member.player_name.strip().lower()
            if name_key not in all_members:
                all_members[name_key] = member
                new_on_page += 1

        log.info(
            f"Members page {page_num + 1}: {len(extraction.members)} visible, "
            f"{new_on_page} new (total: {len(all_members)})"
        )

        if not extraction.has_more:
            log.info("Reached end of member list.")
            break

        if new_on_page == 0 and page_num > 0:
            log.info("No new members on this page — likely reached the end.")
            break

        # Scroll down
        await browser.scroll_members_down()
        page_num += 1

    # ── Close panel ──────────────────────────────────────────────────────
    await browser.navigate_back_to_main()

    result = list(all_members.values())
    log.info(f"Roster scan complete: {len(result)} unique members found.")
    return result
