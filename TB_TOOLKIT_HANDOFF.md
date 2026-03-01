# TB Toolkit — Claude Code Handoff

## What This Is

A Python automation toolkit for Total Battle that does two things:
1. **Chest Counter** — Screenshots the Clan Gifts tab → Claude Vision API extracts structured data → SQLite + CSV leaderboard
2. **Chat Bridge** — Intercepts Sendbird WebSocket chat messages → forwards to Telegram

Both share a single Playwright browser session logged into a utility TB account.

---

## What's Been Validated (Don't Re-Research)

### ✅ Playwright Stealth Works
- TB does NOT detect Playwright with our stealth patches
- Game loads fully, login works, all navigation including Gifts tab
- Bottom nav stays intact (earlier DevTools issue was viewport resize, not bot detection)
- Stealth patches: `navigator.webdriver=false`, fake plugins, chrome object, custom user agent
- Viewport: 1280x720

### ✅ Claude Vision Extraction Works — 100% Accuracy
- **Haiku 4.5** matches Sonnet 4.5 perfectly on this UI — use Haiku as default
- Cost: ~$0.004/page, ~$3/month at 5 scans/day
- Extracts: chest_type, player_name (From:), source (Level X Crypt/Citadel), time_left
- Correctly reads badge count (total gifts), detects last page via "Claim chests" button
- Full-viewport screenshots work better than cropped regions
- Test results saved in `test_output/05_gifts_tab_extraction.json` and `06_gifts_scrolled_extraction.json`

### ✅ Network Protocol Analyzed
- Game data: Binary MessagePack over HTTP POST to `game-us42.totalbattle.com/rubens-realm298` — NOT viable for interception
- Chat: Plain JSON over Sendbird WebSocket (`wss://ws-*.sendbird.com`) — fully readable, easy to intercept
- Message format: `MESG{"channel_url":"triumph_realm_channel_298","user":{"nickname":"Name"},"message":"text","ts":123}`
- Telemetry: JSON to `stat-collector.totalbattle.com` — reveals command names but no gift data

### ✅ Login Page is HTML (Not Canvas)
- "Register or Log In" page has real DOM elements: email input, password input, NEXT button
- Can use Playwright selectors, not coordinate clicking
- After login, a store/offers popup appears that needs dismissing (X at ~top-right, or Escape)

### ✅ Game UI After Login is Canvas/WASM
- All in-game navigation (clan icon, gifts tab, scrolling) requires coordinate-based clicking
- Coordinates mapped from real 1280x720 screenshots (see below)

---

## Coordinate Map (1280x720 Viewport)

From actual screenshots captured during Playwright testing:

| Element | Position (x, y) | Notes |
|---------|-----------------|-------|
| Store popup X (close) | (1258, 68) | Appears after login, may stack multiple |
| Clan shield icon | (57, 345) area | Left sidebar, has red notification badge |
| "Gifts" in clan sidebar | (258, 257) | Has red badge with count |
| "Triumphal Gifts" tab | (735, 133) | Right tab in Gifts view |
| Close clan panel X | (1098, 107) | Top-right of "My Clan" panel |
| Gift list scroll target | (700, 400) | Center of gift list for mouse.wheel |
| "Claim chests" button | (~995, 621) | Bottom of gift list — marks last page |

**These need verification on your machine — run with `--visible --pause` to confirm.**

---

## Architecture

```
Playwright (headless Chromium, stealth patches)
├── HTML login (Playwright selectors)
├── Dismiss store popup (coordinate click / Escape)
├── Navigate: Clan icon → Gifts tab (coordinate clicks)
│
├── CHEST COUNTER (periodic, every 4 hours)
│   ├── Screenshot full viewport (PNG)
│   ├── Send to Claude Haiku 4.5 Vision API
│   ├── Get structured JSON: [{player_name, chest_type, source, time_left, confidence}]
│   ├── Validate player names against clan roster (fuzzy match, optional)
│   ├── Deduplicate against recent scans (player + chest_type + time window)
│   ├── Normalize chest types against known values + point weights
│   ├── Store in SQLite → export CSV/JSONL
│   ├── Scroll → repeat until has_more=false
│   └── Navigate back to main
│
├── CHAT BRIDGE (continuous)
│   ├── Inject WebSocket interceptor (overrides WebSocket prototype)
│   ├── Filter Sendbird MESG frames by channel_url
│   ├── Parse: {nickname, message, timestamp, channel}
│   ├── Log to SQLite + chat_log.jsonl
│   └── Forward to Telegram Bot API (optional)
│
└── DASHBOARD (Flask, localhost:5000)
    ├── Leaderboard (points by player, filterable by time range)
    ├── Player detail (chest type breakdown)
    └── Chat log viewer
```

---

## Chest Types Found in Real Game

From actual screenshots (utility account in [FLR] Florents 1, Kingdom #298):

- Sand Chest (crypt)
- Stone Chest (crypt)
- Barbarian Chest (crypt)
- Forgotten Chest (crypt, various levels)
- Gnome Workshop Chest (crypt)
- Elven Citadel Chest (citadel)

There are many more — Claude Vision handles unknown types gracefully, and the `chest_values.json` config maps types to point values.

---

## Project Structure

```
tb-toolkit/
├── README.md                     # Full docs with utility account setup guide
├── requirements.txt              # playwright, anthropic, pydantic, thefuzz, flask, httpx, apscheduler
├── config/
│   ├── settings.example.json     # Template — copy to settings.json
│   ├── settings.json             # YOUR secrets (gitignored)
│   └── chest_values.json         # Chest type → point value mapping
├── src/
│   ├── main.py                   # CLI: chests | chat | all | export | dashboard
│   ├── browser.py                # Playwright session, stealth, login, navigation, WS interceptor
│   ├── vision.py                 # Claude Vision API, Pydantic schemas, consensus merge, roster validation
│   ├── chat_bridge.py            # Sendbird parser, Telegram forwarder
│   ├── storage.py                # SQLite, dedup, CSV/JSONL export, leaderboard queries
│   └── dashboard.py              # Flask web dashboard
├── test_playwright.py            # Step 1: Manual stealth validation (DONE)
├── test_vision_extract.py        # Step 2: Standalone Vision extraction test (DONE)
├── test_e2e.py                   # Step 3: Full automated flow test (NEXT)
├── data/
│   ├── toolkit.db                # SQLite (auto-created)
│   ├── chest_log.jsonl
│   ├── chat_log.jsonl
│   ├── screenshots/
│   └── exports/
└── .gitignore
```

---

## Existing Test Screenshots

These are in your `test_output/` folder from the Playwright test:

| File | What It Shows |
|------|---------------|
| 01_initial_load.png | Login page (HTML form) |
| 02_game_loaded.png | Store popup after login |
| 03_logged_in.png | Store popup (same as 02) |
| 04_clan_menu.png | Clan info panel with sidebar nav |
| 05_gifts_tab.png | Gifts list page (4 entries visible) |
| 05_gifts_tab_full.png | Same as above, full resolution |
| 06_gifts_scrolled.png | Scrolled gift list (different 4 entries) |

---

## CHECKLIST — What to Build

### Phase 1: Get E2E Working
- [ ] Initialize git repo
- [ ] Copy existing code files from tb-toolkit.zip (or recreate cleanly)
- [ ] Create `config/settings.json` from example with real utility account credentials
- [ ] Set `ANTHROPIC_API_KEY` env var
- [ ] Fix `test_e2e.py` — make it actually run end-to-end
  - [ ] Login flow: click "Log In" link → fill email → NEXT → fill password → submit
  - [ ] Dismiss store popup(s) after login
  - [ ] Click clan shield icon → click Gifts tab
  - [ ] Screenshot → send to Claude Haiku → parse JSON response
  - [ ] Scroll → repeat → stop when has_more=false
  - [ ] Print summary
- [ ] Verify all coordinates with `--visible --pause` mode
- [ ] Adjust any coordinates that miss their targets

### Phase 2: Chest Counter Production
- [ ] Multi-frame consensus (2 screenshots per page, keep gifts appearing in both)
- [ ] Deduplication (same player + chest type within configurable time window)
- [ ] Chest type normalization against `chest_values.json`
- [ ] Point value calculation
- [ ] SQLite storage
- [ ] CSV/JSONL export
- [ ] Clan roster fuzzy matching (optional, for name correction)
- [ ] Sonnet verification fallback when Haiku confidence < threshold
- [ ] Scheduled runs (every 4 hours via cron/Task Scheduler)

### Phase 3: Chat Bridge
- [ ] WebSocket interceptor injection (JS that overrides WebSocket prototype)
- [ ] Sendbird MESG frame parsing
- [ ] Channel filtering (clan chat vs realm chat vs all)
- [ ] Nickname filtering (ignore bots/system)
- [ ] Telegram Bot setup (BotFather → token → group → chat_id)
- [ ] Telegram forwarding via httpx
- [ ] Chat logging to SQLite + JSONL
- [ ] Auto-reconnect on WebSocket disconnect

### Phase 4: Dashboard
- [ ] Flask app with dark theme
- [ ] Leaderboard view (total points by player, filterable by days)
- [ ] Player detail view (chest type breakdown)
- [ ] Chat log viewer
- [ ] Export buttons (CSV download)

### Phase 5: Polish
- [ ] Persistent browser session (cookie/state directory so login survives restarts)
- [ ] Error recovery (page crash, network timeout, API errors)
- [ ] Triumphal Gifts tab support (second tab in Gifts view)
- [ ] Configurable point values per clan
- [ ] Move utility account to real clan (when ready)
- [ ] Documentation for clan members to view dashboard

---

## Key Decisions Already Made

| Decision | Choice | Why |
|----------|--------|-----|
| Vision model | Claude Haiku 4.5 | 100% accuracy, 1/3 cost of Sonnet |
| Screenshot approach | Full viewport | Claude handles context better than tight crops |
| OCR approach | Claude Vision only | Traditional OCR (Tesseract/Azure) not needed — Vision is perfect |
| Chat protocol | Sendbird WebSocket interception | Plain JSON, no decryption needed |
| Game data protocol | NOT intercepting | Binary MessagePack, too much reverse engineering |
| Browser automation | Playwright with stealth patches | Works, no detection |
| Login automation | HTML selectors (not coordinates) | Login page is real DOM |
| In-game navigation | Coordinate clicks | Game UI is Canvas/WASM |
| Storage | SQLite + JSONL | Simple, portable, no external DB needed |
| Dashboard | Flask | Lightweight, single file |

---

## API Keys & Secrets Needed

| Secret | Where to Get | Config Key |
|--------|-------------|------------|
| TB utility account email | Create at totalbattle.com | `game.username` |
| TB utility account password | You set it | `game.password` |
| Anthropic API key | console.anthropic.com | `vision.anthropic_api_key` or `ANTHROPIC_API_KEY` env |
| Telegram bot token | @BotFather on Telegram | `chat_bridge.telegram_bot_token` |
| Telegram chat ID | Bot API getUpdates | `chat_bridge.telegram_chat_id` |

---

## Known Issues / Gotchas

1. **TB login is two-step**: Email → NEXT → Password → Submit. Not a single form.
2. **Store popup after login**: May show multiple popups stacked. Need to dismiss all.
3. **Canvas rendering**: Game UI doesn't have DOM elements after login — all coordinate-based.
4. **Gift expiry**: Chests expire after ~20 hours. Scan every 4 hours = 5 chances to catch each.
5. **Viewport changes kill UI**: If browser resizes mid-session, game UI may break. Keep viewport fixed.
6. **Sendbird reconnects**: WebSocket may drop and reconnect. Interceptor needs to handle re-injection.
7. **Utility account needs to be in your real clan**: Currently in auto-assigned [FLR] Florents 1. Move it when ready.
8. **The `test_e2e.py` has a bug**: `config["vision"]` KeyError if settings.json doesn't have that section. Fixed version uses `.get()` with fallback to env var.

---

## Claude Code Context

When starting in Claude Code, point it at this document and say something like:

> "Read HANDOFF.md for full context. This is a TB Toolkit project for Total Battle game automation. Playwright stealth and Claude Vision extraction are both validated. Start by getting test_e2e.py working end-to-end — login, navigate to gifts, screenshot, extract, display results. Run with --visible --pause so I can verify coordinates."

The code in `src/` is a solid starting point but hasn't been run end-to-end yet. The test scripts (`test_playwright.py` and `test_vision_extract.py`) have both been run successfully.
