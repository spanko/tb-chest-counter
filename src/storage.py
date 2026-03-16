"""Storage — SQLite database, deduplication, CSV/JSONL export, leaderboard.

Shared between chest counter and chat bridge.
"""

import csv
import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent

# ── Chest Values ────────────────────────────────────────────────────────────

def load_chest_values() -> dict:
    """Load chest type → point values from config."""
    path = ROOT / "config" / "chest_values.json"
    if path.exists():
        with open(path) as f:
            data = json.load(f)
        return data.get("chest_types", {})
    return {}


def normalize_chest_type(raw: str, chest_values: dict) -> tuple[str, int]:
    """Normalize a chest type string and return (canonical_name, points).

    Checks against known types and aliases.
    """
    raw_lower = raw.strip().lower()

    for canonical, info in chest_values.items():
        # Skip metadata keys (start with _)
        if canonical.startswith("_"):
            continue
        # Skip if info is not a dict (defensive check)
        if not isinstance(info, dict):
            continue

        if raw_lower == canonical.lower():
            return canonical, info.get("points", 1)
        for alias in info.get("aliases", []):
            if raw_lower == alias.lower():
                return canonical, info.get("points", 1)

    # Unknown type — keep original, assign 1 point
    log.debug(f"Unknown chest type: '{raw}' — using 1 point")
    return raw.strip(), 1


# ── Storage ─────────────────────────────────────────────────────────────────

class Storage:
    """SQLite storage with deduplication and export."""

    def __init__(self, config: dict):
        self.config = config
        db_path = ROOT / config["storage"]["database"]
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self.chest_log_path = ROOT / config["storage"]["chest_log"]
        self.export_dir = ROOT / config["storage"]["export_dir"]
        self.export_dir.mkdir(parents=True, exist_ok=True)

        self.dedup_window = config["chest_counter"].get("dedup_window_minutes", 60)
        self.chest_values = load_chest_values()

        self._init_db()

    def _init_db(self):
        """Create tables if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS gifts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    player_name TEXT NOT NULL,
                    chest_type TEXT NOT NULL,
                    chest_type_raw TEXT,
                    source TEXT,
                    points INTEGER DEFAULT 1,
                    quantity INTEGER DEFAULT 1,
                    confidence REAL DEFAULT 1.0,
                    time_left TEXT,
                    scan_time TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE INDEX IF NOT EXISTS idx_gifts_player ON gifts(player_name);
                CREATE INDEX IF NOT EXISTS idx_gifts_scan ON gifts(scan_time);
                CREATE INDEX IF NOT EXISTS idx_gifts_dedup
                    ON gifts(player_name, chest_type, scan_time);

                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_url TEXT,
                    channel_type TEXT,
                    user_id TEXT,
                    nickname TEXT,
                    message TEXT,
                    timestamp INTEGER,
                    datetime_utc TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE INDEX IF NOT EXISTS idx_chat_ts ON chat_messages(timestamp);
                CREATE INDEX IF NOT EXISTS idx_chat_nick ON chat_messages(nickname);

                CREATE TABLE IF NOT EXISTS scan_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scan_time TEXT NOT NULL,
                    gifts_found INTEGER DEFAULT 0,
                    gifts_new INTEGER DEFAULT 0,
                    pages_scanned INTEGER DEFAULT 0,
                    model_used TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS clan_members (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    player_name TEXT NOT NULL,
                    role TEXT,
                    might INTEGER,
                    first_seen TEXT DEFAULT (datetime('now')),
                    last_seen TEXT DEFAULT (datetime('now')),
                    is_active INTEGER DEFAULT 1
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_members_name
                    ON clan_members(player_name);
                CREATE INDEX IF NOT EXISTS idx_members_active
                    ON clan_members(is_active);
            """)

    # ── Gift Storage ────────────────────────────────────────────────────────

    def store_gifts(self, gifts: list) -> int:
        """Store extracted gifts with deduplication.
        
        Args:
            gifts: List of ChestGift objects from vision module
            
        Returns:
            Number of new gifts stored (after dedup)
        """
        scan_time = datetime.now(timezone.utc).isoformat()
        new_count = 0

        with sqlite3.connect(self.db_path) as conn:
            for gift in gifts:
                # Normalize chest type
                canonical, points = normalize_chest_type(
                    gift.chest_type, self.chest_values
                )

                # Dedup check: same player + same chest type within window
                if self._is_duplicate(conn, gift.player_name, canonical):
                    log.debug(f"Skipping duplicate: {gift.player_name} / {canonical}")
                    continue

                conn.execute("""
                    INSERT INTO gifts (player_name, chest_type, chest_type_raw,
                                       source, points, quantity, confidence, time_left, scan_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    gift.player_name,
                    canonical,
                    gift.chest_type,
                    getattr(gift, 'source', None),
                    points * gift.quantity,
                    gift.quantity,
                    gift.confidence,
                    getattr(gift, 'time_left', None),
                    scan_time,
                ))
                new_count += 1

        return new_count

    def _is_duplicate(self, conn: sqlite3.Connection,
                      player: str, chest_type: str) -> bool:
        """Check if this gift was already recorded within the dedup window."""
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=self.dedup_window)).isoformat()

        row = conn.execute("""
            SELECT COUNT(*) FROM gifts
            WHERE player_name = ? AND chest_type = ? AND scan_time > ?
        """, (player, chest_type, cutoff)).fetchone()

        return row[0] > 0

    # ── Chat Storage ────────────────────────────────────────────────────────

    def store_chat_message(self, msg_dict: dict):
        """Store a parsed chat message."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO chat_messages
                    (channel_url, channel_type, user_id, nickname,
                     message, timestamp, datetime_utc)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                msg_dict.get("channel_url"),
                msg_dict.get("channel_type"),
                msg_dict.get("user_id"),
                msg_dict.get("nickname"),
                msg_dict.get("message"),
                msg_dict.get("timestamp"),
                msg_dict.get("datetime_utc"),
            ))

    # ── Leaderboard Queries ─────────────────────────────────────────────────

    def get_leaderboard(self, days: Optional[int] = None,
                        limit: int = 50) -> list[dict]:
        """Get chest points leaderboard.
        
        Args:
            days: Only count gifts from last N days. None = all time.
            limit: Max results.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            if days:
                cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
                rows = conn.execute("""
                    SELECT player_name,
                           SUM(points) as total_points,
                           COUNT(*) as chest_count,
                           MAX(scan_time) as last_seen
                    FROM gifts
                    WHERE scan_time > ?
                    GROUP BY player_name
                    ORDER BY total_points DESC
                    LIMIT ?
                """, (cutoff, limit)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT player_name,
                           SUM(points) as total_points,
                           COUNT(*) as chest_count,
                           MAX(scan_time) as last_seen
                    FROM gifts
                    GROUP BY player_name
                    ORDER BY total_points DESC
                    LIMIT ?
                """, (limit,)).fetchall()

            return [dict(r) for r in rows]

    def get_gift_breakdown(self, player_name: str,
                           days: Optional[int] = None) -> list[dict]:
        """Get detailed chest type breakdown for one player."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            if days:
                cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
                rows = conn.execute("""
                    SELECT chest_type, SUM(points) as points,
                           COUNT(*) as count
                    FROM gifts
                    WHERE player_name = ? AND scan_time > ?
                    GROUP BY chest_type
                    ORDER BY points DESC
                """, (player_name, cutoff)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT chest_type, SUM(points) as points,
                           COUNT(*) as count
                    FROM gifts
                    WHERE player_name = ?
                    GROUP BY chest_type
                    ORDER BY points DESC
                """, (player_name,)).fetchall()

            return [dict(r) for r in rows]

    def get_recent_chat(self, limit: int = 100,
                        channel_url: Optional[str] = None) -> list[dict]:
        """Get recent chat messages."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if channel_url:
                rows = conn.execute("""
                    SELECT * FROM chat_messages
                    WHERE channel_url = ?
                    ORDER BY timestamp DESC LIMIT ?
                """, (channel_url, limit)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT * FROM chat_messages
                    ORDER BY timestamp DESC LIMIT ?
                """, (limit,)).fetchall()
            return [dict(r) for r in rows]

    # ── Export ──────────────────────────────────────────────────────────────

    def export_csv(self, days: Optional[int] = None) -> str:
        """Export gifts to CSV file. Returns the file path."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = f"_last{days}d" if days else "_all"
        fpath = self.export_dir / f"chests{suffix}_{ts}.csv"

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            if days:
                cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
                rows = conn.execute(
                    "SELECT * FROM gifts WHERE scan_time > ? ORDER BY scan_time DESC",
                    (cutoff,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM gifts ORDER BY scan_time DESC"
                ).fetchall()

        if not rows:
            log.warning("No data to export.")
            return str(fpath)

        with open(fpath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=dict(rows[0]).keys())
            writer.writeheader()
            for row in rows:
                writer.writerow(dict(row))

        log.info(f"Exported {len(rows)} rows to {fpath}")
        return str(fpath)

    def export_jsonl(self):
        """Append latest scan to JSONL log."""
        # Already handled inline during store_gifts, but this
        # does a full re-export for consistency
        pass

    def export_chat_csv(self, days: Optional[int] = None) -> str:
        """Export chat messages to CSV."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = f"_last{days}d" if days else "_all"
        fpath = self.export_dir / f"chat{suffix}_{ts}.csv"

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            if days:
                cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
                rows = conn.execute(
                    "SELECT * FROM chat_messages WHERE datetime_utc > ? ORDER BY timestamp DESC",
                    (cutoff,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM chat_messages ORDER BY timestamp DESC"
                ).fetchall()

        if not rows:
            log.warning("No chat data to export.")
            return str(fpath)

        with open(fpath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=dict(rows[0]).keys())
            writer.writeheader()
            for row in rows:
                writer.writerow(dict(row))

        log.info(f"Exported {len(rows)} chat messages to {fpath}")
        return str(fpath)

    # ── Roster Management ──────────────────────────────────────────────

    def update_roster(self, members: list) -> dict:
        """Update clan roster from a fresh scan.

        Compares scanned members against the database:
        - New members → INSERT with is_active=1
        - Existing members → UPDATE last_seen, role, might
        - Members in DB but NOT in scan → SET is_active=0

        Args:
            members: List of RosterMember objects from roster.py

        Returns:
            {"new": [...], "returned": [...], "left": [...], "updated": int}
        """
        now = datetime.now(timezone.utc).isoformat()
        scanned_names = {m.player_name.strip() for m in members}
        scanned_lookup = {m.player_name.strip(): m for m in members}

        result = {"new": [], "returned": [], "left": [], "updated": 0}

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Get all known members
            existing = conn.execute(
                "SELECT player_name, is_active FROM clan_members"
            ).fetchall()
            existing_map = {r["player_name"]: r["is_active"] for r in existing}

            for name in scanned_names:
                member = scanned_lookup[name]

                if name not in existing_map:
                    # Brand new member
                    conn.execute("""
                        INSERT INTO clan_members
                            (player_name, role, might, first_seen, last_seen, is_active)
                        VALUES (?, ?, ?, ?, ?, 1)
                    """, (name, member.role, member.might, now, now))
                    result["new"].append(name)
                    log.info(f"  New member: {name}")

                elif existing_map[name] == 0:
                    # Returned member (was inactive)
                    conn.execute("""
                        UPDATE clan_members
                        SET is_active = 1, last_seen = ?, role = ?, might = ?
                        WHERE player_name = ?
                    """, (now, member.role, member.might, name))
                    result["returned"].append(name)
                    log.info(f"  Returned member: {name}")

                else:
                    # Existing active member — update
                    conn.execute("""
                        UPDATE clan_members
                        SET last_seen = ?, role = ?, might = ?
                        WHERE player_name = ?
                    """, (now, member.role, member.might, name))
                    result["updated"] += 1

            # Members in DB but not in scan → mark inactive
            for db_name, was_active in existing_map.items():
                if db_name not in scanned_names and was_active == 1:
                    conn.execute("""
                        UPDATE clan_members SET is_active = 0 WHERE player_name = ?
                    """, (db_name,))
                    result["left"].append(db_name)
                    log.info(f"  Left clan: {db_name}")

        total = len(scanned_names)
        log.info(
            f"Roster update: {total} members scanned, "
            f"{len(result['new'])} new, {len(result['returned'])} returned, "
            f"{len(result['left'])} left, {result['updated']} unchanged"
        )
        return result

    def get_active_roster(self) -> list[str]:
        """Get list of currently active clan member names.

        Used by chest counter for fuzzy name validation.
        """
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT player_name FROM clan_members WHERE is_active = 1 ORDER BY player_name"
            ).fetchall()
            return [r[0] for r in rows]

    def get_full_roster(self) -> list[dict]:
        """Get full roster with metadata for dashboard display."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT player_name, role, might, first_seen, last_seen, is_active
                FROM clan_members
                ORDER BY is_active DESC, player_name
            """).fetchall()
            return [dict(r) for r in rows]

    # ── Cloud-compatible interface ──────────────────────────────────────────
    # These methods match storage_pg.py so main.py works in both local and
    # cloud mode without branching.

    def start_run(self, vision_model: str) -> int:
        """Start a scan run and return its ID."""
        scan_time = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO scan_log (scan_time, model_used) VALUES (?, ?)",
                (scan_time, vision_model),
            )
            return cursor.lastrowid

    def complete_run(self, run_id: int, pages: int, found: int, new: int,
                     cost: float = 0.0):
        """Mark a scan run as complete."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE scan_log SET pages_scanned = ?, gifts_found = ?, gifts_new = ? WHERE id = ?",
                (pages, found, new, run_id),
            )

    def fail_run(self, run_id: int, error: str):
        """Mark a scan run as failed."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE scan_log SET gifts_found = -1 WHERE id = ?",
                (run_id,),
            )

    def store_chest(self, run_id: int, gift: dict) -> bool:
        """Store a single gift dict with deduplication.

        Returns True if the gift was new, False if duplicate.
        """
        raw_type = gift.get("chest_type", "unknown")
        canonical, points = normalize_chest_type(raw_type, self.chest_values)
        player = gift.get("player_name", "unknown")

        with sqlite3.connect(self.db_path) as conn:
            if self._is_duplicate(conn, player, canonical):
                log.debug(f"Skipping duplicate: {player} / {canonical}")
                return False

            scan_time = datetime.now(timezone.utc).isoformat()
            conn.execute("""
                INSERT INTO gifts (player_name, chest_type, chest_type_raw,
                                   source, points, quantity, confidence, time_left, scan_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                player,
                canonical,
                raw_type,
                gift.get("source"),
                points * gift.get("quantity", 1),
                gift.get("quantity", 1),
                gift.get("confidence", 1.0),
                gift.get("time_left"),
                scan_time,
            ))
            return True

    def get_roster(self) -> list[str]:
        """Alias for get_active_roster — matches storage_pg interface."""
        return self.get_active_roster()

    def close(self):
        """No-op for SQLite (connections are opened/closed per call)."""
        pass
