"""PostgreSQL storage for multi-clan chest data.

Drop-in replacement for the SQLite storage module. Same method signatures,
backed by PostgreSQL for cloud deployment.

For local dev, set PG_HOST=localhost and run PostgreSQL locally,
or use the SQLite fallback in storage_sqlite.py.
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import psycopg2
import psycopg2.extras

from config import Config

log = logging.getLogger(__name__)


class Storage:
    """PostgreSQL-backed storage for chest scan data."""

    def __init__(self, config: Config):
        self.config = config
        self.clan_id = config.clan_id
        self.conn = psycopg2.connect(config.database.dsn)
        self.conn.autocommit = False
        log.info(f"Connected to PostgreSQL: {config.database.host}/{config.database.database}")

        # Ensure clan exists
        self._ensure_clan()

    def _ensure_clan(self):
        """Insert clan record if it doesn't exist."""
        with self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO clans (clan_id, clan_name, kingdom)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (clan_id) DO UPDATE SET
                       clan_name = EXCLUDED.clan_name,
                       updated_at = NOW()""",
                (self.clan_id, self.config.clan_name, self.config.kingdom),
            )
        self.conn.commit()

    # ── Scan Run Tracking ───────────────────────────────────────────────────

    def start_run(self, vision_model: str) -> int:
        """Create a new scan run record. Returns run_id."""
        with self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO scan_runs (clan_id, vision_model)
                   VALUES (%s, %s)
                   RETURNING run_id""",
                (self.clan_id, vision_model),
            )
            run_id = cur.fetchone()[0]
        self.conn.commit()
        log.info(f"Started scan run {run_id} for clan {self.clan_id}")
        return run_id

    def complete_run(self, run_id: int, pages: int, found: int, new: int,
                     cost_usd: float = 0.0):
        """Mark a scan run as completed."""
        with self.conn.cursor() as cur:
            cur.execute(
                """UPDATE scan_runs
                   SET status = 'completed',
                       completed_at = NOW(),
                       pages_scanned = %s,
                       chests_found = %s,
                       chests_new = %s,
                       vision_cost_usd = %s
                   WHERE run_id = %s""",
                (pages, found, new, cost_usd, run_id),
            )
        self.conn.commit()

    def fail_run(self, run_id: int, error: str):
        """Mark a scan run as failed."""
        with self.conn.cursor() as cur:
            cur.execute(
                """UPDATE scan_runs
                   SET status = 'failed',
                       completed_at = NOW(),
                       error_message = %s
                   WHERE run_id = %s""",
                (error, run_id),
            )
        self.conn.commit()

    # ── Chest Storage with Deduplication ────────────────────────────────────

    def store_chest(self, run_id: int, gift: dict) -> bool:
        """Store a chest gift. Returns True if new, False if duplicate.

        Deduplication uses a hash of (clan_id, player_name, chest_type)
        within the configured time window.

        Args:
            run_id: The current scan run ID
            gift: Dict with keys matching ChestGift schema:
                  player_name, chest_type, confidence, time_left, source, etc.
        """
        player = gift["player_name"]
        chest_type = gift["chest_type"]
        confidence = gift.get("confidence", 1.0)

        # Compute dedup hash
        dedup_hash = self._dedup_hash(player, chest_type)

        # Check for recent duplicate within window
        window_minutes = self.config.scan.dedup_window_minutes
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT id FROM chests
                   WHERE clan_id = %s
                     AND dedup_hash = %s
                     AND scanned_at > NOW() - INTERVAL '%s minutes'
                   LIMIT 1""",
                (self.clan_id, dedup_hash, window_minutes),
            )
            if cur.fetchone():
                log.debug(f"Duplicate: {player} / {chest_type}")
                return False

        # Look up point value
        points = self._lookup_points(chest_type)

        # Insert
        with self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO chests
                   (clan_id, run_id, player_name, player_name_raw, chest_type,
                    chest_type_raw, source, points, confidence, verified,
                    time_remaining, screenshot_ref, dedup_hash)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (clan_id, dedup_hash) DO NOTHING""",
                (
                    self.clan_id,
                    run_id,
                    player,
                    gift.get("player_name_raw", player),
                    chest_type,
                    gift.get("chest_type_raw", chest_type),
                    gift.get("source"),
                    points,
                    confidence,
                    gift.get("verified", False),
                    gift.get("time_left") or gift.get("time_remaining") or gift.get("time_ago"),
                    gift.get("screenshot_ref"),
                    dedup_hash,
                ),
            )
        self.conn.commit()
        log.debug(f"Stored: {player} / {chest_type} ({points} pts)")
        return True

    def _dedup_hash(self, player_name: str, chest_type: str) -> str:
        """Generate a deduplication hash.

        Uses clan_id + player + chest_type + hour bucket so the same
        chest gift within the dedup window gets the same hash.
        """
        # Round to nearest hour for time bucketing
        now = datetime.now(timezone.utc)
        bucket = now.strftime("%Y%m%d%H")
        raw = f"{self.clan_id}|{player_name}|{chest_type}|{bucket}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def _lookup_points(self, chest_type: str) -> int:
        """Look up point value for a chest type from the chest_types table."""
        with self.conn.cursor() as cur:
            # Exact match first
            cur.execute(
                "SELECT points FROM chest_types WHERE chest_type = %s",
                (chest_type,),
            )
            row = cur.fetchone()
            if row:
                return row[0]

            # Try alias match
            cur.execute(
                "SELECT points FROM chest_types WHERE %s = ANY(aliases)",
                (chest_type.lower(),),
            )
            row = cur.fetchone()
            if row:
                return row[0]

        log.warning(f"Unknown chest type: {chest_type} — defaulting to 1 point")
        return 1

    # ── Roster ──────────────────────────────────────────────────────────────

    def get_roster(self) -> list[str]:
        """Get active clan member names for fuzzy matching."""
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT player_name FROM clan_members
                   WHERE clan_id = %s AND is_active = TRUE""",
                (self.clan_id,),
            )
            return [row[0] for row in cur.fetchall()]

    # ── Cleanup ─────────────────────────────────────────────────────────────

    def close(self):
        if self.conn and not self.conn.closed:
            self.conn.close()
            log.info("PostgreSQL connection closed")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
