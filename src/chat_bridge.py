"""Chat Bridge — Sendbird WebSocket interceptor → Telegram forwarder.

Parses intercepted Sendbird MESG frames from the browser,
logs them locally, and optionally forwards to a Telegram group.

Sendbird message format (from HAR analysis):
    MESG{"channel_url":"triumph_realm_channel_298","channel_type":"group",
         "user":{"user_id":"tb:83277479","nickname":"PlayerName"},
         "message":"actual text","ts":1772384895867}
"""

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent

# ── Sendbird Message Types ──────────────────────────────────────────────────
# Sendbird uses a prefix-based protocol over WebSocket:
#   MESG = chat message
#   FILE = file/image message
#   BRDM = broadcast message
#   ADMM = admin message
#   MEDI = media message
#   PING/PONG = keepalive
#   LOGI = login ack
#   ENTER/EXIT = channel join/leave

SENDBIRD_MSG_PATTERN = re.compile(r'^(MESG|FILE|BRDM|ADMM)(.*)', re.DOTALL)


class ParsedMessage:
    """A parsed Sendbird chat message."""

    def __init__(self, raw_type: str, channel_url: str, channel_type: str,
                 user_id: str, nickname: str, message: str, timestamp: int,
                 raw_data: str):
        self.raw_type = raw_type
        self.channel_url = channel_url
        self.channel_type = channel_type
        self.user_id = user_id
        self.nickname = nickname
        self.message = message
        self.timestamp = timestamp
        self.raw_data = raw_data
        self.dt = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)

    def to_dict(self) -> dict:
        return {
            "type": self.raw_type,
            "channel_url": self.channel_url,
            "channel_type": self.channel_type,
            "user_id": self.user_id,
            "nickname": self.nickname,
            "message": self.message,
            "timestamp": self.timestamp,
            "datetime_utc": self.dt.isoformat(),
        }

    def __repr__(self):
        return f"[{self.dt.strftime('%H:%M:%S')}] {self.nickname}: {self.message[:60]}"


# ── Parser ──────────────────────────────────────────────────────────────────

def parse_sendbird_frame(raw: str) -> Optional[ParsedMessage]:
    """Parse a raw Sendbird WebSocket frame into a structured message.
    
    Args:
        raw: Raw frame string, e.g. 'MESG{"channel_url":...}'
        
    Returns:
        ParsedMessage if it's a chat message, None for control frames.
    """
    match = SENDBIRD_MSG_PATTERN.match(raw)
    if not match:
        return None

    msg_type = match.group(1)
    json_str = match.group(2)

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        log.debug(f"Failed to parse Sendbird JSON: {json_str[:200]}")
        return None

    user = data.get("user", {})

    return ParsedMessage(
        raw_type=msg_type,
        channel_url=data.get("channel_url", ""),
        channel_type=data.get("channel_type", ""),
        user_id=user.get("user_id", ""),
        nickname=user.get("nickname", "Unknown"),
        message=data.get("message", ""),
        timestamp=data.get("ts", 0),
        raw_data=raw,
    )


# ── Chat Bridge ─────────────────────────────────────────────────────────────

class ChatBridge:
    """Handles intercepted Sendbird messages: logging, filtering, forwarding."""

    def __init__(self, config: dict):
        self.config = config
        self.chat_config = config.get("chat_bridge", {})

        # Channel filter
        self.channel_filter = self.chat_config.get("sendbird_channel_filter", [])
        self.ignored_nicknames = set(
            n.lower() for n in self.chat_config.get("ignored_nicknames", [])
        )

        # Telegram
        self.telegram_enabled = self.chat_config.get("forward_to_telegram", False)
        self.telegram_token = self.chat_config.get("telegram_bot_token", "")
        self.telegram_chat_id = self.chat_config.get("telegram_chat_id", "")
        self.telegram_format = self.chat_config.get("telegram_format", "**{nickname}**: {message}")

        # Log file
        self.log_to_file = self.chat_config.get("log_to_file", True)
        self.chat_log_path = ROOT / config["storage"].get("chat_log", "data/chat_log.jsonl")
        self.chat_log_path.parent.mkdir(parents=True, exist_ok=True)

        # HTTP client for Telegram
        self._http = httpx.AsyncClient(timeout=10)

        # Stats
        self.message_count = 0
        self.forwarded_count = 0

        log.info(f"Chat bridge initialized. Channel filter: {self.channel_filter or 'ALL'}")
        if self.telegram_enabled:
            log.info(f"Telegram forwarding: ENABLED (chat_id={self.telegram_chat_id})")
        else:
            log.info("Telegram forwarding: DISABLED")

    async def handle_message(self, raw_frame: dict):
        """Process a raw intercepted WebSocket frame.
        
        Args:
            raw_frame: Dict from browser poll with 'type', 'data', 'timestamp'
        """
        # Only process received messages (not sends)
        if raw_frame.get("type") != "receive":
            return

        raw_data = raw_frame.get("data", "")
        parsed = parse_sendbird_frame(raw_data)

        if not parsed:
            return  # Control frame (PING, PONG, LOGI, etc.)

        # Apply channel filter
        if self.channel_filter:
            if not any(parsed.channel_url.startswith(prefix) for prefix in self.channel_filter):
                return

        # Apply nickname filter
        if parsed.nickname.lower() in self.ignored_nicknames:
            return

        # Skip empty messages
        if not parsed.message.strip():
            return

        self.message_count += 1
        log.info(f"💬 {parsed}")

        # Log to file
        if self.log_to_file:
            self._log_to_file(parsed)

        # Forward to Telegram
        if self.telegram_enabled:
            await self._forward_to_telegram(parsed)

    def _log_to_file(self, msg: ParsedMessage):
        """Append message to JSONL log file."""
        try:
            with open(self.chat_log_path, "a") as f:
                f.write(json.dumps(msg.to_dict()) + "\n")
        except Exception as e:
            log.error(f"Failed to log message: {e}")

    async def _forward_to_telegram(self, msg: ParsedMessage):
        """Send message to Telegram group via Bot API."""
        if not self.telegram_token or not self.telegram_chat_id:
            log.warning("Telegram not configured — skipping forward")
            return

        # Format the message
        text = self.telegram_format.format(
            nickname=msg.nickname,
            message=msg.message,
            channel=msg.channel_url,
            time=msg.dt.strftime("%H:%M:%S UTC"),
            user_id=msg.user_id,
        )

        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        payload = {
            "chat_id": self.telegram_chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }

        try:
            resp = await self._http.post(url, json=payload)
            if resp.status_code == 200:
                self.forwarded_count += 1
                log.debug(f"Forwarded to Telegram: {text[:80]}")
            else:
                log.error(f"Telegram API error {resp.status_code}: {resp.text}")
        except httpx.TimeoutException:
            log.error("Telegram API timeout — message dropped")
        except Exception as e:
            log.error(f"Telegram forward failed: {e}")

    async def close(self):
        """Cleanup HTTP client."""
        await self._http.aclose()

    def get_stats(self) -> dict:
        """Return bridge statistics."""
        return {
            "messages_received": self.message_count,
            "messages_forwarded": self.forwarded_count,
            "telegram_enabled": self.telegram_enabled,
            "channel_filter": self.channel_filter,
        }
