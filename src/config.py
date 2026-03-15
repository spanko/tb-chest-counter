"""Configuration loader — env vars (cloud) or settings.json (local).

In ACA Jobs, all config comes from environment variables injected by Bicep.
Locally, it falls back to config/settings.json for development.

IMPORTANT: Returns a plain dict matching the settings.json structure so
browser.py, vision.py, and all existing code works unchanged.

Usage:
    from config import load_config
    cfg = load_config()
    cfg["game"]["username"]       # works in both modes
    cfg["_cloud_mode"]            # True if running in ACA
    cfg["_clan_id"]               # clan identifier
"""

import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent


def load_config(cloud: bool = False) -> dict:
    """Load configuration as a dict.

    Cloud mode is activated by --cloud flag or CLOUD_MODE=true env var.
    Returns the same dict shape as settings.json so all existing modules
    (browser.py, vision.py, storage.py) work without changes.
    """
    cloud = cloud or os.environ.get("CLOUD_MODE", "").lower() in ("true", "1")
    scan_mode = os.environ.get("SCAN_MODE", "")

    if cloud:
        config = _build_from_env()
    else:
        config = _load_from_file()

    config["_cloud_mode"] = cloud
    config["_scan_mode"] = scan_mode
    return config


def _build_from_env() -> dict:
    """Build a settings.json-shaped dict from environment variables."""
    log.info("Loading config from environment variables (cloud mode)")

    def req(key: str) -> str:
        val = os.environ.get(key)
        if not val:
            raise ValueError(f"Required env var {key} is not set")
        return val

    return {
        "_clan_id": req("CLAN_ID"),
        "_clan_name": req("CLAN_NAME"),
        "_kingdom": int(req("KINGDOM")),

        "game": {
            "url": os.environ.get("TB_URL", "https://totalbattle.com"),
            "username": req("TB_USERNAME"),
            "password": req("TB_PASSWORD"),
            "realm": int(os.environ.get("KINGDOM", "0")),
            "viewport": {
                "width": int(os.environ.get("VIEWPORT_WIDTH", "1280")),
                "height": int(os.environ.get("VIEWPORT_HEIGHT", "720")),
            },
        },

        "clan": {
            "id": req("CLAN_ID"),
            "name": req("CLAN_NAME"),
            "roster": [],
        },

        "vision": {
            "provider": "anthropic",
            "anthropic_api_key": req("ANTHROPIC_API_KEY"),
            "model_routine": os.environ.get("VISION_MODEL_ROUTINE", "claude-haiku-4-5-20251001"),
            "model_verify": os.environ.get("VISION_MODEL_VERIFY", "claude-sonnet-4-5-20250929"),
            "verify_threshold": float(os.environ.get("VISION_VERIFY_THRESHOLD", "0.85")),
        },

        "chest_counter": {
            "enabled": True,
            "max_pages": int(os.environ.get("SCAN_MAX_PAGES", "10")),
            "multi_frame_count": int(os.environ.get("SCAN_MULTI_FRAME", "2")),
            "dedup_window_minutes": int(os.environ.get("SCAN_DEDUP_WINDOW", "60")),
            "gift_region": {
                "x": 370, "y": 130, "width": 740, "height": 510,
            },
        },

        "storage": {
            "database": "data/toolkit.db",
            "chest_log": "data/chest_log.jsonl",
            "chat_log": "data/chat_log.jsonl",
            "export_dir": "data/exports",
            "screenshot_dir": os.environ.get("SCREENSHOT_DIR", "/tmp/screenshots"),
        },

        "dashboard": {
            "host": "127.0.0.1",
            "port": 5000,
        },

        # Database config for PostgreSQL (cloud only)
        "_database": {
            "host": req("PG_HOST"),
            "database": req("PG_DATABASE"),
            "user": req("PG_USER"),
            "password": req("PG_PASSWORD"),
            "sslmode": os.environ.get("PG_SSLMODE", "require"),
            "port": int(os.environ.get("PG_PORT", "5432")),
        },
    }


def _load_from_file() -> dict:
    """Load settings.json directly — returns the dict as-is."""
    config_path = ROOT / "config" / "settings.json"
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config not found: {config_path}\n"
            f"Copy config/settings.example.json -> config/settings.json"
        )

    log.info(f"Loading config from {config_path}")
    with open(config_path) as f:
        config = json.load(f)

    # Ensure API key can come from env var as fallback
    if not config.get("vision", {}).get("anthropic_api_key"):
        env_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if env_key:
            config.setdefault("vision", {})["anthropic_api_key"] = env_key

    # Add clan_id for local mode
    config["_clan_id"] = config.get("clan", {}).get("id", "local")
    config["_clan_name"] = config.get("clan", {}).get("name", "Local")

    return config
