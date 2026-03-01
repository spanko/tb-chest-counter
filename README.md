# TB Toolkit — Chest Counter + Chat Bridge for Total Battle

Two tools that share a single Playwright session logged into a utility account:

1. **Chest Counter** — Screenshots the Gifts tab → Claude Vision extracts structured data → SQLite + CSV
2. **Chat Bridge** — Intercepts Sendbird WebSocket messages → forwards to Telegram

Both are read-only. The utility account never modifies anything in-game.

---

## Architecture

```
Playwright (headless Chromium)
├── Logs into TB web version with utility account
├── Injects WebSocket interceptor JavaScript
│   └── Captures Sendbird MESG frames → Chat Bridge → Telegram
├── Navigates to Clan → Gifts tab
│   └── Screenshots gift list → Claude Vision API → Structured JSON
└── Stores everything in SQLite + exports CSV/JSONL
```

### What We Learned from Network Analysis

| Channel | Protocol | Format | Contains |
|---------|----------|--------|----------|
| `game-us42.totalbattle.com` | HTTP POST | Binary MessagePack | All game data (encrypted/proprietary) |
| `ws-*.sendbird.com` | WebSocket | **Plain JSON** ✅ | Realm & clan chat messages |
| `stat-collector.totalbattle.com` | HTTP POST | JSON | Telemetry (command names, FPS, etc.) |

**Chat = easy** (plain JSON). **Game data = hard** (binary). That's why we use Claude Vision for chests and Sendbird interception for chat.

---

## Part 1: Utility Account Setup

> **NEVER use your main Total Battle account for automation.**

### Why a Utility Account?

- **Security** — Main account credentials never touch automation
- **Safety** — If banned/locked, main account is unaffected
- **Simplicity** — A level 1 account can see all clan gift data and chat
- **Read-only** — Script only reads Gifts tab and chat. Modifies nothing.

### Step-by-Step

1. **Create new account** in incognito window at https://totalbattle.com
   - Use a different email (Gmail `+` trick: `youremail+tbbot@gmail.com`)
   - Complete tutorial (~2 minutes to get past intro)
2. **Teleport to your Kingdom** using free tutorial teleporter or purchased one
3. **Leave auto-assigned clan** → Clan menu → Clan information → Leave
4. **Join your real clan** → Find a Clan → Search → Apply → Have leader accept
5. **Verify access** — Check Gifts tab shows same data as your main account
6. **Name it recognizably** — `ClanBot_YourClan`, `ChestTracker`, etc.

---

## Part 2: Setup

### Prerequisites

- **Python 3.10+**
- **Chrome/Chromium** (Playwright manages this)
- **Anthropic API key** (for Claude Vision chest extraction)
- **Telegram Bot Token** (optional, for chat bridge)

### Install

```bash
cd tb-toolkit

# Create virtual environment
python -m venv .venv

# Activate
# Windows: .venv\Scripts\activate
# Mac/Linux: source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
```

### Configure

```bash
cp config/settings.example.json config/settings.json
# Edit config/settings.json with your credentials
```

### API Keys Needed

| Service | What For | Cost | How to Get |
|---------|----------|------|------------|
| **Anthropic** | Claude Vision chest extraction | ~$3/mo | https://console.anthropic.com |
| **Telegram Bot** | Chat bridge forwarding | Free | Message @BotFather on Telegram |

---

## Part 3: Running

### Chest Counter Only

```bash
# First run — visible browser for calibration
python src/main.py chests --visible

# Production run — headless
python src/main.py chests

# Export existing data to CSV
python src/main.py export
```

### Chat Bridge Only

```bash
# Start chat bridge — stays running, forwards messages
python src/main.py chat --visible   # visible for testing
python src/main.py chat             # headless for production
```

### Both Together

```bash
# Run chat bridge continuously + chest scan every 4 hours
python src/main.py all --visible    # visible for testing
python src/main.py all              # headless for production
```

### Dashboard

```bash
python src/main.py dashboard
# Opens http://localhost:5000
```

### Scheduled Chest Scans (without chat bridge)

**Windows Task Scheduler:**
```powershell
schtasks /create /tn "TB Chest Counter" /tr "python C:\path\to\src\main.py chests" /sc HOURLY /mo 4
```

**Mac/Linux cron (every 4 hours):**
```bash
0 */4 * * * cd /path/to/tb-toolkit && .venv/bin/python src/main.py chests >> data/cron.log 2>&1
```

---

## Part 4: Project Structure

```
tb-toolkit/
├── README.md
├── requirements.txt
├── config/
│   ├── settings.example.json     # Template — copy to settings.json
│   ├── settings.json             # YOUR config (git-ignored)
│   └── chest_values.json         # Point weights per chest type + aliases
├── src/
│   ├── main.py                   # CLI entry point + orchestrator
│   ├── browser.py                # Playwright session (login, navigate, screenshot)
│   ├── vision.py                 # Claude Vision API → structured chest extraction
│   ├── chat_bridge.py            # Sendbird WebSocket interceptor → Telegram
│   ├── storage.py                # SQLite + CSV/JSONL export + leaderboard
│   └── dashboard.py              # Flask web dashboard
├── data/
│   ├── toolkit.db                # SQLite database (auto-created)
│   ├── chest_log.jsonl           # Raw chest extraction log
│   ├── chat_log.jsonl            # Raw chat message log
│   ├── screenshots/              # Captured gift screenshots
│   └── exports/                  # CSV exports
└── .gitignore
```

---

## Part 5: How It Works

### Chest Counter Pipeline

```
Playwright → Login → Navigate to Clan → Gifts tab
    ↓
Screenshot gift list region (calibrated viewport)
    ↓
Send cropped PNG to Claude API with structured output schema
    ↓
Claude returns: [{player_name, chest_type, confidence}, ...]
    ↓
Validate against clan roster (fuzzy match)
    ↓
Deduplicate against previous scans
    ↓
Store in SQLite → Export CSV/JSONL
```

**Claude Vision pricing:** ~$0.002 per screenshot with Haiku, ~$0.017 with Sonnet.
At 5 scans/day × 5 pages each = ~$1.50-13/month depending on model choice.

### Chat Bridge Pipeline

```
Playwright → Login → Game loads → Sendbird WebSocket connects
    ↓
Injected JavaScript intercepts WebSocket.onmessage
    ↓
Filters for MESG frames on your clan's channel_url
    ↓
Extracts: {nickname, message, timestamp, channel}
    ↓
Forwards to Telegram Bot API (HTTP POST)
    ↓
Also logs to chat_log.jsonl and SQLite
```

**Sendbird message format (from HAR analysis):**
```
MESG{"channel_url":"triumph_realm_channel_298","user":{"nickname":"PlayerName"},"message":"text","ts":1772384895}
```

All plain JSON — no decryption needed.

---

## Part 6: Telegram Bot Setup

1. Open Telegram, message **@BotFather**
2. Send `/newbot`, follow prompts, get your **bot token**
3. Create a Telegram group for your clan's chat mirror
4. Add your bot to the group
5. Get the **chat ID** — send a message in the group, then visit:
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
   Look for `"chat":{"id":-100XXXXXXXXXX}`
6. Add both values to `config/settings.json`

---

## Troubleshooting

### Game menu disappears when DevTools is open
This is normal — TB detects viewport changes. The automation runs headless so this isn't an issue in production. For debugging, use `--visible` flag.

### Chat bridge stops receiving messages
Sendbird WebSocket may disconnect after idle periods. The bridge auto-reconnects and re-injects the interceptor.

### Claude returns low confidence for some chests
Check `data/screenshots/` for the raw image. If the screenshot region is misaligned, adjust `gift_region` in settings. If the game font changed, Claude adapts automatically (unlike traditional OCR).

### Chest data has duplicates
The deduplication system uses (player_name, chest_type, approximate_timestamp) as a composite key. Adjust the `dedup_window_minutes` setting if needed.
