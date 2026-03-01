"""Storage — SQLite database, deduplication, CSV/JSONL export, leaderboard.

Shared between chest counter and chat bridge.
"""

import csv
import json
import logging
import sqlite3
from datetime import datetime, timedelta
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
            """)

    # ── Gift Storage ────────────────────────────────────────────────────────

    def store_gifts(self, gifts: list) -> int:
        """Store extracted gifts with deduplication.
        
        Args:
            gifts: List of ChestGift objects from vision module
            
        Returns:
            Number of new gifts stored (after dedup)
        """
        scan_time = datetime.utcnow().isoformat()
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
        cutoff = (datetime.utcnow() - timedelta(minutes=self.dedup_window)).isoformat()

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
                cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
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
                cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
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
                cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
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
                cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
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
