"""Configuration loader — env vars (cloud) or settings.json (local).

In ACA Jobs, all config comes from environment variables injected by Bicep.
Locally, it falls back to config/settings.json for development.

Usage:
    from config import load_config
    cfg = load_config()
    cfg.tb_username  # works in both modes
"""

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class VisionConfig:
    api_key: str
    model_routine: str = "claude-haiku-4-5-20251001"
    model_verify: str = "claude-sonnet-4-5-20250929"
    verify_threshold: float = 0.85


@dataclass
class DatabaseConfig:
    host: str
    database: str
    user: str
    password: str
    sslmode: str = "require"
    port: int = 5432

    @property
    def dsn(self) -> str:
        return (
            f"host={self.host} port={self.port} dbname={self.database} "
            f"user={self.user} password={self.password} sslmode={self.sslmode}"
        )


@dataclass
class ScanConfig:
    max_pages: int = 10
    multi_frame_count: int = 2
    dedup_window_minutes: int = 60
    viewport_width: int = 1280
    viewport_height: int = 720
    gift_region: dict = field(default_factory=lambda: {
        "x": 200, "y": 150, "width": 880, "height": 500
    })


@dataclass
class Config:
    clan_id: str
    clan_name: str
    kingdom: int
    tb_username: str
    tb_password: str
    vision: VisionConfig
    database: DatabaseConfig
    scan: ScanConfig
    cloud_mode: bool = False
    headless: bool = True
    screenshot_dir: Optional[str] = None


def load_config(cloud: bool = False) -> Config:
    """Load configuration from env vars (cloud) or settings.json (local).

    Cloud mode is activated by --cloud flag or CLOUD_MODE=true env var.
    """
    cloud = cloud or os.environ.get("CLOUD_MODE", "").lower() in ("true", "1")

    if cloud:
        return _load_from_env()
    else:
        return _load_from_file()


def _load_from_env() -> Config:
    """Load all config from environment variables (ACA Job injection)."""
    log.info("Loading config from environment variables (cloud mode)")

    def req(key: str) -> str:
        val = os.environ.get(key)
        if not val:
            raise ValueError(f"Required env var {key} is not set")
        return val

    return Config(
        clan_id=req("CLAN_ID"),
        clan_name=req("CLAN_NAME"),
        kingdom=int(req("KINGDOM")),
        tb_username=req("TB_USERNAME"),
        tb_password=req("TB_PASSWORD"),
        vision=VisionConfig(
            api_key=req("ANTHROPIC_API_KEY"),
            model_routine=os.environ.get("VISION_MODEL_ROUTINE", "claude-haiku-4-5-20251001"),
            model_verify=os.environ.get("VISION_MODEL_VERIFY", "claude-sonnet-4-5-20250929"),
            verify_threshold=float(os.environ.get("VISION_VERIFY_THRESHOLD", "0.85")),
        ),
        database=DatabaseConfig(
            host=req("PG_HOST"),
            database=req("PG_DATABASE"),
            user=req("PG_USER"),
            password=req("PG_PASSWORD"),
            sslmode=os.environ.get("PG_SSLMODE", "require"),
            port=int(os.environ.get("PG_PORT", "5432")),
        ),
        scan=ScanConfig(
            max_pages=int(os.environ.get("SCAN_MAX_PAGES", "10")),
            multi_frame_count=int(os.environ.get("SCAN_MULTI_FRAME", "2")),
            dedup_window_minutes=int(os.environ.get("SCAN_DEDUP_WINDOW", "60")),
        ),
        cloud_mode=True,
        headless=True,
        screenshot_dir=os.environ.get("SCREENSHOT_DIR", "/tmp/screenshots"),
    )


def _load_from_file() -> Config:
    """Load from config/settings.json for local development."""
    config_path = Path(__file__).resolve().parent.parent / "config" / "settings.json"
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config not found: {config_path}\n"
            f"Copy config/settings.example.json → config/settings.json and fill in your values."
        )

    log.info(f"Loading config from {config_path}")
    with open(config_path) as f:
        raw = json.load(f)

    game = raw.get("game", {})
    vision = raw.get("vision", {})
    chest = raw.get("chest_counter", {})
    storage = raw.get("storage", {})

    # Local mode uses SQLite — database config is optional
    db_config = DatabaseConfig(
        host=raw.get("database", {}).get("host", "localhost"),
        database=raw.get("database", {}).get("database", "tbchests"),
        user=raw.get("database", {}).get("user", "tbadmin"),
        password=raw.get("database", {}).get("password", ""),
        sslmode=raw.get("database", {}).get("sslmode", "prefer"),
    )

    return Config(
        clan_id=raw.get("clan", {}).get("id", "local"),
        clan_name=raw.get("clan", {}).get("name", "Local"),
        kingdom=game.get("realm", game.get("kingdom", 0)),
        tb_username=game.get("username", ""),
        tb_password=game.get("password", ""),
        vision=VisionConfig(
            api_key=vision.get("anthropic_api_key", os.environ.get("ANTHROPIC_API_KEY", "")),
            model_routine=vision.get("model_routine", "claude-haiku-4-5-20251001"),
            model_verify=vision.get("model_verify", "claude-sonnet-4-5-20250929"),
            verify_threshold=float(vision.get("verify_threshold", 0.85)),
        ),
        database=db_config,
        scan=ScanConfig(
            max_pages=chest.get("max_pages", 10),
            multi_frame_count=chest.get("multi_frame_count", 2),
            dedup_window_minutes=chest.get("dedup_window_minutes", 60),
            gift_region=chest.get("gift_region", ScanConfig().gift_region),
        ),
        cloud_mode=False,
        headless=not raw.get("browser", {}).get("visible", False),
        screenshot_dir=storage.get("screenshot_dir", "data/screenshots"),
    )
