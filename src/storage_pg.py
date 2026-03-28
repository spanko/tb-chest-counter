"""PostgreSQL storage for multi-clan chest data.

Drop-in replacement for the SQLite storage module. Same method signatures,
backed by PostgreSQL for cloud deployment. Config is a plain dict.
"""

import hashlib
import logging
from datetime import datetime, timezone

import psycopg2

log = logging.getLogger(__name__)


class Storage:
    """PostgreSQL-backed storage for chest scan data."""

    def __init__(self, config: dict):
        self.config = config
        self.clan_id = config.get("_clan_id", "local")
        self.clan_name = config.get("_clan_name", "Local")
        self.kingdom = config.get("_kingdom", 0)

        db = config["_database"]
        dsn = (
            f"host={db['host']} port={db.get('port', 5432)} "
            f"dbname={db['database']} user={db['user']} "
            f"password={db['password']} sslmode={db.get('sslmode', 'require')}"
        )

        self.conn = psycopg2.connect(dsn)
        self.conn.autocommit = False
        log.info(f"Connected to PostgreSQL: {db['host']}/{db['database']}")

        self._dedup_window = config.get("chest_counter", {}).get("dedup_window_minutes", 60)
        self._ensure_clan()

    def _ensure_clan(self):
        with self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO clans (clan_id, clan_name, kingdom)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (clan_id) DO UPDATE SET
                       clan_name = EXCLUDED.clan_name,
                       updated_at = NOW()""",
                (self.clan_id, self.clan_name, self.kingdom),
            )
        self.conn.commit()

    def start_run(self, vision_model: str) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO scan_runs (clan_id, vision_model)
                   VALUES (%s, %s) RETURNING run_id""",
                (self.clan_id, vision_model),
            )
            run_id = cur.fetchone()[0]
        self.conn.commit()
        log.info(f"Started scan run {run_id} for clan {self.clan_id}")
        return run_id

    def complete_run(self, run_id: int, pages: int, found: int, new: int,
                     cost_usd: float = 0.0):
        with self.conn.cursor() as cur:
            cur.execute(
                """UPDATE scan_runs
                   SET status = 'completed', completed_at = NOW(),
                       pages_scanned = %s, chests_found = %s,
                       chests_new = %s, vision_cost_usd = %s
                   WHERE run_id = %s""",
                (pages, found, new, cost_usd, run_id),
            )
        self.conn.commit()

    def fail_run(self, run_id: int, error: str):
        with self.conn.cursor() as cur:
            cur.execute(
                """UPDATE scan_runs
                   SET status = 'failed', completed_at = NOW(),
                       error_message = %s WHERE run_id = %s""",
                (error, run_id),
            )
        self.conn.commit()

    def store_chest(self, run_id: int, gift: dict) -> bool:
        player = gift["player_name"]
        chest_type = gift["chest_type"]
        time_left = gift.get("time_left", "")
        confidence = gift.get("confidence", 1.0)
        dedup_hash = self._dedup_hash(player, chest_type, time_left, run_id)

        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT id FROM chests
                   WHERE clan_id = %s AND dedup_hash = %s
                     AND scanned_at > NOW() - INTERVAL '%s minutes'
                   LIMIT 1""",
                (self.clan_id, dedup_hash, self._dedup_window),
            )
            if cur.fetchone():
                log.debug(f"Duplicate: {player} / {chest_type}")
                return False

        points = self._lookup_points(chest_type)

        with self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO chests
                   (clan_id, run_id, player_name, player_name_raw, chest_type,
                    chest_type_raw, source, points, confidence, verified,
                    time_remaining, screenshot_ref, dedup_hash)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (clan_id, dedup_hash) DO NOTHING""",
                (
                    self.clan_id, run_id, player,
                    gift.get("player_name_raw", player),
                    chest_type, gift.get("chest_type_raw", chest_type),
                    gift.get("source"), points, confidence,
                    gift.get("verified", False),
                    gift.get("time_left") or gift.get("time_remaining") or gift.get("time_ago"),
                    gift.get("screenshot_ref"), dedup_hash,
                ),
            )
        self.conn.commit()
        log.debug(f"Stored: {player} / {chest_type} ({points} pts)")
        return True

    def _dedup_hash(self, player_name: str, chest_type: str, time_left: str, run_id: int) -> str:
        # time_left is unique per chest (e.g. "23 hr 45 min") - makes each chest distinguishable
        raw = f"{self.clan_id}|{player_name}|{chest_type}|{time_left}|run_{run_id}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def _lookup_points(self, chest_type: str) -> int:
        with self.conn.cursor() as cur:
            cur.execute("SELECT points FROM chest_types WHERE chest_type = %s", (chest_type,))
            row = cur.fetchone()
            if row:
                return row[0]
            cur.execute("SELECT points FROM chest_types WHERE %s = ANY(aliases)", (chest_type.lower(),))
            row = cur.fetchone()
            if row:
                return row[0]
        log.warning(f"Unknown chest type: {chest_type} — defaulting to 1 point")
        return 1

    def get_roster(self) -> list[str]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT player_name FROM clan_members WHERE clan_id = %s AND is_active = TRUE",
                (self.clan_id,),
            )
            return [row[0] for row in cur.fetchall()]

    def close(self):
        if self.conn and not self.conn.closed:
            self.conn.close()
            log.info("PostgreSQL connection closed")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
