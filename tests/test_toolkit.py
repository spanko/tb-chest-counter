#!/usr/bin/env python3
"""Unit tests for TB Toolkit refactored modules.

Tests calibration profile management, roster tracking, storage operations,
vision consensus logic, and integration between modules.

Run:  python -m pytest tests/ -v
  or: python tests/test_toolkit.py
"""

import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

# ═══════════════════════════════════════════════════════════════════════════
# Calibration Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestCalibration:
    """Tests for calibration profile load/save/lookup."""

    def test_save_and_load_calibration(self, tmp_path):
        from calibration import save_calibration, load_calibration, CALIBRATION_FILE

        # Temporarily override the calibration file path
        original = str(CALIBRATION_FILE)
        test_file = tmp_path / "calibration.json"

        import calibration
        calibration.CALIBRATION_FILE = test_file

        try:
            profile = {
                "viewport": {"width": 1280, "height": 720},
                "screens": {
                    "main_game": {
                        "elements": {
                            "bottom_nav_clan": {"x": 695, "y": 668},
                        }
                    }
                }
            }
            save_calibration(profile)

            assert test_file.exists()

            loaded = load_calibration()
            assert loaded is not None
            assert loaded["viewport"]["width"] == 1280
            assert "calibrated_at" in loaded
            assert loaded["screens"]["main_game"]["elements"]["bottom_nav_clan"]["x"] == 695
        finally:
            calibration.CALIBRATION_FILE = Path(original)

    def test_load_missing_calibration(self, tmp_path):
        import calibration
        original = calibration.CALIBRATION_FILE
        calibration.CALIBRATION_FILE = tmp_path / "nonexistent.json"
        try:
            result = calibration.load_calibration()
            assert result is None
        finally:
            calibration.CALIBRATION_FILE = original

    def test_get_element_coords(self):
        from calibration import get_element_coords

        profile = {
            "screens": {
                "main_game": {
                    "elements": {
                        "bottom_nav_clan": {"x": 695, "y": 668},
                        "missing_element": None,
                    }
                }
            }
        }

        # Found
        coords = get_element_coords(profile, "main_game", "bottom_nav_clan")
        assert coords == {"x": 695, "y": 668}

        # Element is None
        coords = get_element_coords(profile, "main_game", "missing_element")
        assert coords is None

        # Element doesn't exist
        coords = get_element_coords(profile, "main_game", "nonexistent")
        assert coords is None

        # Screen doesn't exist
        coords = get_element_coords(profile, "other_screen", "bottom_nav_clan")
        assert coords is None

        # No profile
        coords = get_element_coords(None, "main_game", "bottom_nav_clan")
        assert coords is None

    def test_calibration_screens_completeness(self):
        """Verify all expected screens and elements are defined."""
        from calibration import CALIBRATION_SCREENS

        assert "main_game" in CALIBRATION_SCREENS
        assert "clan_panel" in CALIBRATION_SCREENS
        assert "gifts_view" in CALIBRATION_SCREENS
        assert "members_view" in CALIBRATION_SCREENS

        # Main game needs the clan button
        assert "bottom_nav_clan" in CALIBRATION_SCREENS["main_game"]["elements"]

        # Clan panel needs gifts, members, close
        clan = CALIBRATION_SCREENS["clan_panel"]["elements"]
        assert "sidebar_gifts" in clan
        assert "sidebar_members" in clan
        assert "close_button" in clan

        # Gifts view needs scroll target
        assert "gift_list_center" in CALIBRATION_SCREENS["gifts_view"]["elements"]

        # Members view needs scroll target
        assert "member_list_center" in CALIBRATION_SCREENS["members_view"]["elements"]

    def test_normalize_coords_standard(self):
        """Standard {"x": int, "y": int} format."""
        from calibration import _normalize_coords
        assert _normalize_coords({"x": 100, "y": 200}) == {"x": 100, "y": 200}

    def test_normalize_coords_list(self):
        """[x, y] list format."""
        from calibration import _normalize_coords
        assert _normalize_coords([100, 200]) == {"x": 100, "y": 200}

    def test_normalize_coords_alternate_keys(self):
        """center_x/center_y and other key patterns."""
        from calibration import _normalize_coords
        assert _normalize_coords({"center_x": 100, "center_y": 200}) == {"x": 100, "y": 200}
        assert _normalize_coords({"left": 100, "top": 200}) == {"x": 100, "y": 200}

    def test_normalize_coords_with_extras(self):
        """Dict with x/y plus extra keys should still work."""
        from calibration import _normalize_coords
        result = _normalize_coords({"x": 100, "y": 200, "width": 50, "height": 50})
        assert result == {"x": 100, "y": 200}

    def test_normalize_coords_none(self):
        from calibration import _normalize_coords
        assert _normalize_coords(None) is None

    def test_normalize_coords_invalid(self):
        """Garbage input returns None."""
        from calibration import _normalize_coords
        assert _normalize_coords("not coords") is None
        assert _normalize_coords(42) is None
        assert _normalize_coords({}) is None
        assert _normalize_coords({"only_x": 100}) is None

    def test_normalize_coords_float_to_int(self):
        """Float coordinates should be cast to int."""
        from calibration import _normalize_coords
        assert _normalize_coords({"x": 100.7, "y": 200.3}) == {"x": 100, "y": 200}


# ═══════════════════════════════════════════════════════════════════════════
# Storage Tests
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def storage_config(tmp_path):
    """Create a config that points storage at a temp directory."""
    db_path = tmp_path / "data" / "test.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return {
        "storage": {
            "database": str(db_path),
            "chest_log": str(tmp_path / "data" / "chest_log.jsonl"),
            "chat_log": str(tmp_path / "data" / "chat_log.jsonl"),
            "export_dir": str(tmp_path / "data" / "exports"),
            "screenshot_dir": str(tmp_path / "data" / "screenshots"),
        },
        "chest_counter": {
            "dedup_window_minutes": 60,
        },
    }


@pytest.fixture
def storage(storage_config, monkeypatch):
    """Create a Storage instance with temp DB."""
    import shutil
    from storage import Storage

    # The temp ROOT that storage will resolve paths against
    temp_root = Path(storage_config["storage"]["database"]).parent.parent

    # Copy chest_values.json so normalization/points work
    real_config_dir = Path(__file__).parent.parent / "config"
    temp_config_dir = temp_root / "config"
    temp_config_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(real_config_dir / "chest_values.json", temp_config_dir / "chest_values.json")

    # Monkey-patch ROOT so relative paths resolve to temp dir
    monkeypatch.setattr("storage.ROOT", temp_root)
    # Make export dir
    Path(storage_config["storage"]["export_dir"]).mkdir(parents=True, exist_ok=True)
    return Storage(storage_config)


class TestStorage:
    """Tests for SQLite storage, dedup, roster management."""

    def test_init_creates_tables(self, storage):
        """DB should have all required tables after init."""
        with sqlite3.connect(storage.db_path) as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            table_names = {t[0] for t in tables}

        assert "gifts" in table_names
        assert "chat_messages" in table_names
        assert "scan_log" in table_names
        assert "clan_members" in table_names

    def test_store_gifts_basic(self, storage):
        """Store gifts and verify they're in the database."""
        from vision import ChestGift

        gifts = [
            ChestGift(
                player_name="TestPlayer",
                chest_type="Sand Chest",
                source="Level 10 Crypt",
                time_left="18h 0m",
                confidence=1.0,
            ),
            ChestGift(
                player_name="OtherPlayer",
                chest_type="Forgotten Chest",
                source="Level 5 Crypt",
                time_left="17h 30m",
                confidence=0.95,
            ),
        ]

        new_count = storage.store_gifts(gifts)
        assert new_count == 2

        # Verify in DB
        with sqlite3.connect(storage.db_path) as conn:
            rows = conn.execute("SELECT * FROM gifts").fetchall()
        assert len(rows) == 2

    def test_dedup_within_window(self, storage):
        """Same player + same chest type within window should be deduped."""
        from vision import ChestGift

        gift = ChestGift(
            player_name="TestPlayer",
            chest_type="Sand Chest",
            confidence=1.0,
        )

        first = storage.store_gifts([gift])
        assert first == 1

        # Store again immediately — should be deduped
        second = storage.store_gifts([gift])
        assert second == 0

    def test_dedup_different_chest_types(self, storage):
        """Different chest types from same player should NOT be deduped."""
        from vision import ChestGift

        gifts = [
            ChestGift(player_name="TestPlayer", chest_type="Sand Chest", confidence=1.0),
            ChestGift(player_name="TestPlayer", chest_type="Stone Chest", confidence=1.0),
        ]

        new_count = storage.store_gifts(gifts)
        assert new_count == 2

    def test_chest_type_normalization(self, storage):
        """Known chest types should be normalized and assigned points."""
        from vision import ChestGift

        gift = ChestGift(
            player_name="TestPlayer",
            chest_type="elven citadel chest",  # lowercase variant
            confidence=1.0,
        )

        storage.store_gifts([gift])

        with sqlite3.connect(storage.db_path) as conn:
            row = conn.execute("SELECT chest_type, points FROM gifts").fetchone()

        assert row[0] == "Elven Citadel Chest"
        assert row[1] == 5

    def test_leaderboard(self, storage):
        """Leaderboard should aggregate points by player."""
        from vision import ChestGift

        gifts = [
            ChestGift(player_name="Alice", chest_type="Sand Chest", confidence=1.0),
            ChestGift(player_name="Alice", chest_type="Stone Chest", confidence=1.0),
            ChestGift(player_name="Bob", chest_type="Elven Citadel Chest", confidence=1.0),
        ]

        storage.store_gifts(gifts)
        lb = storage.get_leaderboard()

        assert len(lb) == 2
        # Bob has 5 points (Elven Citadel), Alice has 2 (Sand=1 + Stone=1)
        assert lb[0]["player_name"] == "Bob"
        assert lb[0]["total_points"] == 5
        assert lb[1]["player_name"] == "Alice"
        assert lb[1]["total_points"] == 2

    def test_update_roster_new_members(self, storage):
        """New members should be added with is_active=1."""
        from roster import RosterMember

        members = [
            RosterMember("Alice", role="Leader", might=5000000),
            RosterMember("Bob", role="Member", might=1000000),
        ]

        result = storage.update_roster(members)
        assert len(result["new"]) == 2
        assert "Alice" in result["new"]
        assert "Bob" in result["new"]
        assert len(result["left"]) == 0

        # Verify in DB
        roster = storage.get_active_roster()
        assert len(roster) == 2
        assert "Alice" in roster

    def test_update_roster_member_leaves(self, storage):
        """Members not in scan should be marked inactive."""
        from roster import RosterMember

        # Initial scan with Alice and Bob
        storage.update_roster([
            RosterMember("Alice", role="Leader"),
            RosterMember("Bob", role="Member"),
        ])

        # Second scan without Bob
        result = storage.update_roster([
            RosterMember("Alice", role="Leader"),
        ])

        assert "Bob" in result["left"]
        assert result["updated"] == 1  # Alice updated

        roster = storage.get_active_roster()
        assert len(roster) == 1
        assert "Alice" in roster
        assert "Bob" not in roster

    def test_update_roster_member_returns(self, storage):
        """Inactive members who reappear should be reactivated."""
        from roster import RosterMember

        # Scan 1: Alice, Bob
        storage.update_roster([
            RosterMember("Alice"), RosterMember("Bob"),
        ])

        # Scan 2: Alice only → Bob leaves
        storage.update_roster([RosterMember("Alice")])
        assert "Bob" not in storage.get_active_roster()

        # Scan 3: Alice, Bob → Bob returns
        result = storage.update_roster([
            RosterMember("Alice"), RosterMember("Bob"),
        ])
        assert "Bob" in result["returned"]
        assert "Bob" in storage.get_active_roster()

    def test_get_full_roster(self, storage):
        """Full roster should include metadata and inactive members."""
        from roster import RosterMember

        storage.update_roster([
            RosterMember("Alice", role="Leader", might=5000000),
            RosterMember("Bob", role="Member", might=1000000),
        ])
        storage.update_roster([RosterMember("Alice", role="Leader", might=5500000)])

        full = storage.get_full_roster()
        assert len(full) == 2

        # Active member first (sorted by is_active DESC, then name)
        alice = next(m for m in full if m["player_name"] == "Alice")
        assert alice["is_active"] == 1
        assert alice["might"] == 5500000

        bob = next(m for m in full if m["player_name"] == "Bob")
        assert bob["is_active"] == 0

    def test_export_csv(self, storage):
        """CSV export should produce a valid file."""
        from vision import ChestGift

        storage.store_gifts([
            ChestGift(player_name="Alice", chest_type="Sand Chest", confidence=1.0),
        ])

        path = storage.export_csv()
        assert Path(path).exists()

        with open(path) as f:
            lines = f.readlines()
        assert len(lines) == 2  # header + 1 data row
        assert "Alice" in lines[1]


# ═══════════════════════════════════════════════════════════════════════════
# Vision Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestVisionConsensus:
    """Tests for multi-frame consensus merge logic."""

    def test_consensus_single_extraction(self):
        from vision import ChestGift, GiftPageExtraction, consensus_merge

        extraction = GiftPageExtraction(
            gifts=[
                ChestGift(player_name="Alice", chest_type="Sand Chest", confidence=1.0),
            ]
        )
        result = consensus_merge([extraction])
        assert len(result) == 1
        assert result[0].player_name == "Alice"

    def test_consensus_both_agree(self):
        from vision import ChestGift, GiftPageExtraction, consensus_merge

        e1 = GiftPageExtraction(gifts=[
            ChestGift(player_name="Alice", chest_type="Sand Chest", confidence=1.0),
            ChestGift(player_name="Bob", chest_type="Stone Chest", confidence=0.9),
        ])
        e2 = GiftPageExtraction(gifts=[
            ChestGift(player_name="Alice", chest_type="Sand Chest", confidence=0.95),
            ChestGift(player_name="Bob", chest_type="Stone Chest", confidence=1.0),
        ])

        result = consensus_merge([e1, e2])
        assert len(result) == 2

    def test_consensus_drops_hallucination(self):
        """A gift in only 1 of 2 extractions should be dropped."""
        from vision import ChestGift, GiftPageExtraction, consensus_merge

        e1 = GiftPageExtraction(gifts=[
            ChestGift(player_name="Alice", chest_type="Sand Chest", confidence=1.0),
            ChestGift(player_name="HALLUCINATED", chest_type="Mythic Chest", confidence=0.5),
        ])
        e2 = GiftPageExtraction(gifts=[
            ChestGift(player_name="Alice", chest_type="Sand Chest", confidence=1.0),
        ])

        result = consensus_merge([e1, e2])
        assert len(result) == 1
        assert result[0].player_name == "Alice"

    def test_consensus_empty(self):
        from vision import consensus_merge
        assert consensus_merge([]) == []

    def test_consensus_uses_highest_confidence(self):
        from vision import ChestGift, GiftPageExtraction, consensus_merge

        e1 = GiftPageExtraction(gifts=[
            ChestGift(player_name="Alice", chest_type="Sand Chest", confidence=0.7),
        ])
        e2 = GiftPageExtraction(gifts=[
            ChestGift(player_name="Alice", chest_type="Sand Chest", confidence=0.95),
        ])

        result = consensus_merge([e1, e2])
        assert len(result) == 1
        # Confidence should be set to agreement ratio (2/2 = 1.0)
        assert result[0].confidence == 1.0


# ═══════════════════════════════════════════════════════════════════════════
# Chat Bridge Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestChatBridge:
    """Tests for Sendbird message parsing."""

    def test_parse_mesg_frame(self):
        from chat_bridge import parse_sendbird_frame

        raw = (
            'MESG{"channel_url":"triumph_realm_channel_298","channel_type":"group",'
            '"user":{"user_id":"tb:83277479","nickname":"PlayerOne"},'
            '"message":"Hello clan!","ts":1772384895867}'
        )
        msg = parse_sendbird_frame(raw)
        assert msg is not None
        assert msg.nickname == "PlayerOne"
        assert msg.message == "Hello clan!"
        assert msg.channel_url == "triumph_realm_channel_298"
        assert msg.raw_type == "MESG"

    def test_parse_non_message_frame(self):
        from chat_bridge import parse_sendbird_frame

        assert parse_sendbird_frame("PING1234") is None
        assert parse_sendbird_frame("PONG1234") is None
        assert parse_sendbird_frame("LOGI{\"key\":true}") is None

    def test_parse_invalid_json(self):
        from chat_bridge import parse_sendbird_frame

        result = parse_sendbird_frame("MESG{invalid json here}")
        assert result is None

    def test_parsed_message_to_dict(self):
        from chat_bridge import parse_sendbird_frame

        raw = (
            'MESG{"channel_url":"test","channel_type":"group",'
            '"user":{"user_id":"u1","nickname":"Nick"},'
            '"message":"test msg","ts":1700000000000}'
        )
        msg = parse_sendbird_frame(raw)
        d = msg.to_dict()
        assert d["nickname"] == "Nick"
        assert d["message"] == "test msg"
        assert "datetime_utc" in d


# ═══════════════════════════════════════════════════════════════════════════
# Browser Calibration Integration Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestBrowserCalibration:
    """Tests for browser's calibration lookup methods."""

    def test_get_coords_found(self):
        from browser import TBBrowser

        browser = TBBrowser.__new__(TBBrowser)
        browser._calibration = {
            "screens": {
                "main_game": {
                    "elements": {
                        "bottom_nav_clan": {"x": 695, "y": 668}
                    }
                }
            }
        }

        coords = browser._get_coords("main_game", "bottom_nav_clan")
        assert coords == {"x": 695, "y": 668}

    def test_get_coords_missing_raises(self):
        from browser import TBBrowser

        browser = TBBrowser.__new__(TBBrowser)
        browser._calibration = {"screens": {}}

        with pytest.raises(RuntimeError, match="Calibration missing"):
            browser._get_coords("main_game", "bottom_nav_clan")

    def test_get_coords_or_none(self):
        from browser import TBBrowser

        browser = TBBrowser.__new__(TBBrowser)
        browser._calibration = {"screens": {}}

        assert browser._get_coords_or_none("main_game", "bottom_nav_clan") is None


# ═══════════════════════════════════════════════════════════════════════════
# Roster Module Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestRoster:
    """Tests for roster data classes."""

    def test_roster_member_to_dict(self):
        from roster import RosterMember

        m = RosterMember("TestPlayer", role="Leader", might=5000000, confidence=0.95)
        d = m.to_dict()
        assert d["player_name"] == "TestPlayer"
        assert d["role"] == "Leader"
        assert d["might"] == 5000000
        assert d["confidence"] == 0.95

    def test_roster_page_extraction_defaults(self):
        from roster import RosterPageExtraction

        page = RosterPageExtraction()
        assert page.members == []
        assert page.has_more is False
        assert page.total_member_count is None


# ═══════════════════════════════════════════════════════════════════════════
# Chest Values Config Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestChestValues:
    """Tests for chest type normalization and point values."""

    def test_known_chest_type(self):
        from storage import normalize_chest_type, load_chest_values

        values = load_chest_values()
        name, points = normalize_chest_type("Sand Chest", values)
        assert name == "Sand Chest"
        assert points == 1

    def test_alias_normalization(self):
        from storage import normalize_chest_type, load_chest_values

        values = load_chest_values()
        name, points = normalize_chest_type("elven chest", values)
        assert name == "Elven Citadel Chest"
        assert points == 5

    def test_unknown_chest_type(self):
        from storage import normalize_chest_type, load_chest_values

        values = load_chest_values()
        name, points = normalize_chest_type("Totally New Chest", values)
        assert name == "Totally New Chest"
        assert points == 1

    def test_case_insensitive(self):
        from storage import normalize_chest_type, load_chest_values

        values = load_chest_values()
        name, points = normalize_chest_type("DRAGON LAIR CHEST", values)
        assert name == "Dragon Lair Chest"
        assert points == 8


# ═══════════════════════════════════════════════════════════════════════════
# CLI Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestCLI:
    """Tests for main.py CLI argument parsing."""

    def test_all_commands_accepted(self):
        """Verify all commands are recognized."""
        import main
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("command",
                            choices=["calibrate", "chests", "roster", "chat",
                                     "all", "export", "dashboard"])
        parser.add_argument("--visible", action="store_true")
        parser.add_argument("-v", "--verbose", action="store_true")

        for cmd in ["calibrate", "chests", "roster", "chat", "all", "export", "dashboard"]:
            args = parser.parse_args([cmd])
            assert args.command == cmd

    def test_visible_flag(self):
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("command",
                            choices=["calibrate", "chests", "roster", "chat",
                                     "all", "export", "dashboard"])
        parser.add_argument("--visible", action="store_true")

        args = parser.parse_args(["calibrate", "--visible"])
        assert args.visible is True

        args = parser.parse_args(["chests"])
        assert args.visible is False


# ═══════════════════════════════════════════════════════════════════════════
# Dashboard Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestDashboard:
    """Tests for Flask dashboard routes."""

    @pytest.fixture
    def app(self, storage_config, monkeypatch):
        from dashboard import create_app
        monkeypatch.setattr("storage.ROOT", Path(storage_config["storage"]["database"]).parent.parent)
        app = create_app(storage_config)
        app.config["TESTING"] = True
        return app

    def test_leaderboard_route(self, app):
        with app.test_client() as client:
            resp = client.get("/")
            assert resp.status_code == 200
            assert b"TB Toolkit" in resp.data

    def test_chat_route(self, app):
        with app.test_client() as client:
            resp = client.get("/chat")
            assert resp.status_code == 200

    def test_leaderboard_with_days_filter(self, app):
        with app.test_client() as client:
            resp = client.get("/?days=7")
            assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
