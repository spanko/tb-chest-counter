"""
Chest Parser — Converts raw OCR text into structured chest records.

Handles:
- Fuzzy matching player names against known clan members
- Identifying chest type from OCR text
- Applying chest type aliases (for common OCR misreadings)
- Assigning point values based on chest type
"""

import logging
import re
from datetime import datetime
from typing import Optional

from thefuzz import fuzz, process

log = logging.getLogger("tb-chest-counter.parser")


class ChestParser:
    """Parse OCR text from gift screenshots into structured data."""

    def __init__(self, clan_members: list[str], chest_values: dict):
        self.clan_members = clan_members
        self.chest_values = chest_values.get("chest_values", {})
        self.aliases = chest_values.get("aliases", {})

        # Build a normalized lookup for chest types
        self._chest_type_names = list(self.chest_values.keys())

    def parse(self, raw_text: str) -> Optional[dict]:
        """
        Parse OCR text from a gift screenshot.

        Expected text patterns from TB gift display:
            "PlayerName"
            "Common Crypt"
            -- or --
            "PlayerName explored a Common Crypt"
            -- or --
            "Gift from PlayerName"
            "Explored: Common Crypt"

        The exact format depends on game version and language.
        This parser tries multiple patterns.

        Returns:
            dict with keys: player, chest_type, points, timestamp
            or None if parsing fails
        """
        if not raw_text or len(raw_text.strip()) < 3:
            return None

        lines = [line.strip() for line in raw_text.strip().split("\n") if line.strip()]

        if not lines:
            return None

        # Try different parsing strategies
        result = (
            self._parse_two_line(lines)
            or self._parse_single_line(lines)
            or self._parse_gift_from(lines)
            or self._parse_fallback(lines)
        )

        if result:
            result["timestamp"] = datetime.now().isoformat()

        return result

    # ── Parsing Strategies ─────────────────────────────────────

    def _parse_two_line(self, lines: list[str]) -> Optional[dict]:
        """
        Pattern: Line 1 = Player name, Line 2 = Chest type
        Most common format in the Gifts tab.
        """
        if len(lines) < 2:
            return None

        player = self._match_player(lines[0])
        chest_type = self._match_chest_type(lines[1])

        if player and chest_type:
            return {
                "player": player,
                "chest_type": chest_type,
                "points": self.chest_values.get(chest_type, 1),
            }
        return None

    def _parse_single_line(self, lines: list[str]) -> Optional[dict]:
        """
        Pattern: "PlayerName explored a Common Crypt"
        """
        text = " ".join(lines)

        # Look for "explored", "completed", "defeated" keywords
        patterns = [
            r"(.+?)\s+explored\s+(?:a\s+)?(.+)",
            r"(.+?)\s+completed\s+(?:a\s+)?(.+)",
            r"(.+?)\s+defeated\s+(?:a\s+)?(.+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                player = self._match_player(match.group(1))
                chest_type = self._match_chest_type(match.group(2))
                if player and chest_type:
                    return {
                        "player": player,
                        "chest_type": chest_type,
                        "points": self.chest_values.get(chest_type, 1),
                    }
        return None

    def _parse_gift_from(self, lines: list[str]) -> Optional[dict]:
        """
        Pattern: "Gift from PlayerName" / "Explored: Common Crypt"
        """
        text = " ".join(lines)

        match = re.search(r"gift\s+from\s+(.+)", text, re.IGNORECASE)
        if match:
            player = self._match_player(match.group(1).strip())
            # Look for chest type in remaining text
            chest_type = self._match_chest_type(text)
            if player:
                return {
                    "player": player,
                    "chest_type": chest_type or "Unknown",
                    "points": self.chest_values.get(chest_type or "Unknown", 1),
                }
        return None

    def _parse_fallback(self, lines: list[str]) -> Optional[dict]:
        """
        Last resort: Try to find any clan member name and any chest type
        anywhere in the text.
        """
        text = " ".join(lines)
        player = self._match_player(text)
        chest_type = self._match_chest_type(text)

        if player:
            return {
                "player": player,
                "chest_type": chest_type or "Unknown",
                "points": self.chest_values.get(chest_type or "Unknown", 1),
            }
        return None

    # ── Fuzzy Matching ─────────────────────────────────────────

    def _match_player(self, text: str) -> Optional[str]:
        """
        Fuzzy-match text against known clan member names.
        Returns the best match if confidence > 60%, else None.
        """
        if not text or not self.clan_members:
            return text.strip() if text else None

        # Clean up the text
        clean = text.strip()

        # Try exact match first
        for member in self.clan_members:
            if member.lower() == clean.lower():
                return member

        # Fuzzy match using thefuzz
        result = process.extractOne(
            clean,
            self.clan_members,
            scorer=fuzz.ratio,
            score_cutoff=60,
        )

        if result:
            matched_name, score, _ = result
            if score < 80:
                log.debug(f"Fuzzy matched '{clean}' → '{matched_name}' (score: {score})")
            return matched_name

        # No match found — return the raw text (might be a new/unknown player)
        log.warning(f"No clan member match for: '{clean}' — using raw OCR text")
        return clean

    def _match_chest_type(self, text: str) -> Optional[str]:
        """
        Identify chest type from text, including alias resolution.
        """
        if not text:
            return None

        clean = text.strip()

        # Check aliases first (common OCR misreadings)
        for alias, correct_name in self.aliases.items():
            if alias.lower() in clean.lower():
                return correct_name

        # Check known chest type names
        for chest_type in self._chest_type_names:
            if chest_type.lower() in clean.lower():
                return chest_type

        # Fuzzy match against chest types
        result = process.extractOne(
            clean,
            self._chest_type_names,
            scorer=fuzz.partial_ratio,
            score_cutoff=65,
        )

        if result:
            matched_type, score = result[0], result[1]
            if score < 80:
                log.debug(f"Fuzzy matched chest type '{clean}' → '{matched_type}' (score: {score})")
            return matched_type

        return None
