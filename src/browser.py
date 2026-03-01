"""Playwright browser session for Total Battle.

Handles login, navigation, screenshot capture, and WebSocket interceptor injection.
Shared between chest counter and chat bridge.
"""

import asyncio
import json
import logging
from pathlib import Path
from datetime import datetime

from playwright.async_api import async_playwright, Page, Browser

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent

# ── WebSocket Interceptor JavaScript ────────────────────────────────────────
# Injected into the page to capture Sendbird messages without DevTools

WS_INTERCEPTOR_JS = """
(() => {
    // Avoid double-injection
    if (window.__tb_ws_interceptor) return;
    window.__tb_ws_interceptor = true;
    window.__tb_ws_messages = [];

    const OrigWS = window.WebSocket;
    window.WebSocket = function(...args) {
        const ws = new OrigWS(...args);
        const url = args[0] || '';

        // Only intercept Sendbird WebSocket
        if (url.includes('sendbird.com')) {
            console.log('[TB-Toolkit] Sendbird WebSocket intercepted:', url);

            ws.addEventListener('message', (event) => {
                if (typeof event.data === 'string') {
                    window.__tb_ws_messages.push({
                        type: 'receive',
                        data: event.data,
                        timestamp: Date.now(),
                        url: url
                    });
                }
            });

            // Also intercept sends (for debugging)
            const origSend = ws.send.bind(ws);
            ws.send = function(data) {
                if (typeof data === 'string' && data.startsWith('MESG')) {
                    window.__tb_ws_messages.push({
                        type: 'send',
                        data: data,
                        timestamp: Date.now(),
                        url: url
                    });
                }
                return origSend(data);
            };
        }

        return ws;
    };
    // Preserve prototype chain
    window.WebSocket.prototype = OrigWS.prototype;
    window.WebSocket.CONNECTING = OrigWS.CONNECTING;
    window.WebSocket.OPEN = OrigWS.OPEN;
    window.WebSocket.CLOSING = OrigWS.CLOSING;
    window.WebSocket.CLOSED = OrigWS.CLOSED;

    console.log('[TB-Toolkit] WebSocket interceptor installed');
})();
"""


class TBBrowser:
    """Manages a Playwright browser session for Total Battle."""

    def __init__(self, config: dict, headless: bool = True):
        self.config = config
        self.headless = headless
        self.playwright = None
        self.browser: Browser = None
        self.page: Page = None
        self._screenshot_counter = 0

    async def __aenter__(self):
        self.playwright = await async_playwright().start()
        vp = self.config["game"].get("viewport", {"width": 1280, "height": 720})
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self.context = await self.browser.new_context(
            viewport=vp,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Safari/537.36"
            ),
        )
        self.page = await self.context.new_page()
        return self

    async def __aexit__(self, *args):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    # ── Login ───────────────────────────────────────────────────────────────

    async def login(self):
        """Navigate to TB and log in with utility account credentials.
        
        Login page is HTML (not canvas), so we can use Playwright selectors.
        After login, a store popup appears that needs to be dismissed.
        """
        url = self.config["game"]["url"]
        username = self.config["game"]["username"]
        password = self.config["game"]["password"]

        log.info(f"Navigating to {url}...")
        await self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(3)

        # ── Step 1: Click "Log In" to switch from Register to Login form ──
        # The page loads showing "Register or Log In" with a "Log In" link.
        # There's also "Log in" in the top nav bar — try both.
        try:
            # Try the "Log In" link next to "Register or"
            login_link = self.page.locator("text=Log In").first
            await login_link.click(timeout=5000)
            log.info("Clicked 'Log In' link — switching to login form")
            await asyncio.sleep(1)
        except Exception:
            try:
                # Try top nav "Log in"
                nav_login = self.page.locator("text=Log in").first
                await nav_login.click(timeout=5000)
                log.info("Clicked nav 'Log in' — switching to login form")
                await asyncio.sleep(1)
            except Exception:
                log.warning("Could not find Log In link — may already be on login form")

        # ── Step 2: Fill email field ──
        try:
            email_input = self.page.locator("input[type='email'], input[name='email'], input[placeholder*='mail']").first
            await email_input.fill(username, timeout=5000)
            log.info(f"Entered email: {username}")
        except Exception:
            # Fallback: try any visible text input
            log.warning("Could not find email input by selector — trying generic input")
            inputs = self.page.locator("input[type='text'], input:not([type])")
            if await inputs.count() > 0:
                await inputs.first.fill(username)
            else:
                log.error("No email input found. Run with --visible to debug.")
                return

        # ── Step 3: Click NEXT or submit to get to password field ──
        try:
            next_btn = self.page.locator("text=NEXT").first
            await next_btn.click(timeout=5000)
            log.info("Clicked NEXT")
            await asyncio.sleep(2)
        except Exception:
            # Some flows show email+password together
            log.info("No NEXT button — may have email+password on same page")

        # ── Step 4: Fill password field ──
        try:
            password_input = self.page.locator("input[type='password']").first
            await password_input.fill(password, timeout=5000)
            log.info("Entered password")
        except Exception:
            log.error("No password input found. Run with --visible to debug.")
            return

        # ── Step 5: Submit login ──
        try:
            # Look for submit/login/next button
            for selector in ["button[type='submit']", "text=LOG IN", "text=Log In",
                             "text=NEXT", "text=Sign in", "text=PLAY"]:
                btn = self.page.locator(selector).first
                if await btn.is_visible(timeout=2000):
                    await btn.click()
                    log.info(f"Clicked submit button: {selector}")
                    break
        except Exception:
            # Fallback: press Enter
            log.info("No submit button found — pressing Enter")
            await self.page.keyboard.press("Enter")

        # ── Step 6: Wait for game to load ──
        log.info("Waiting for game to load...")
        try:
            await self.page.wait_for_selector("canvas", timeout=60000)
            log.info("Canvas detected — game is loading")
        except Exception:
            log.warning("No canvas after 60s — login may have failed")

        await asyncio.sleep(10)  # Let WASM fully initialize

        # ── Step 7: Dismiss store popup if present ──
        await self._dismiss_popups()

        log.info("Login complete.")

    async def _dismiss_popups(self):
        """Close any popups that appear after login (store, offers, etc).
        
        The store popup has an X button at approximately (1258, 68) on 1280x720.
        Multiple popups may stack, so we try several times.
        """
        for attempt in range(5):
            # Try HTML close buttons first
            try:
                close_btn = self.page.locator("[class*='close'], [aria-label='close'], .popup-close").first
                if await close_btn.is_visible(timeout=1000):
                    await close_btn.click()
                    log.info(f"Closed popup via HTML button (attempt {attempt+1})")
                    await asyncio.sleep(1)
                    continue
            except Exception:
                pass

            # Try canvas X button at known position (top-right of store popup)
            # On 1280x720: X is at approximately (1258, 68)
            try:
                await self.page.mouse.click(1258, 68)
                await asyncio.sleep(1)
                log.debug(f"Clicked popup close position (attempt {attempt+1})")
            except Exception:
                pass

            # Also try Escape key
            await self.page.keyboard.press("Escape")
            await asyncio.sleep(0.5)

        log.info("Popup dismissal complete.")

    # ── Navigation ──────────────────────────────────────────────────────────

    async def navigate_to_gifts(self):
        """Navigate to Clan → Gifts tab.
        
        Coordinate map (1280x720 viewport, from real screenshots):
        - Clan shield icon: left sidebar, approximately (57, 270)
          (the shield/coat-of-arms icon on the left side of screen)
        - "My Clan" panel opens with left nav: Information, Members, Gifts...
        - "Gifts" tab in left nav: approximately (258, 257)
        - Close panel X: approximately (1098, 107)
        """
        log.info("Navigating to Clan → Gifts...")

        # First dismiss any popups
        await self._dismiss_popups()
        await asyncio.sleep(1)

        # Click the clan icon on the left sidebar
        # This is the shield/coat-of-arms icon, visible in the game screenshots
        # Position varies — try the area where the "9" badge notification appears
        # In the screenshots: left side, around y=330 area
        # The shield icon with the red notification badge "9" is at ~(57, 345)
        clan_icon_positions = [
            (57, 345),   # Shield icon with notification badge
            (57, 270),   # Slightly higher
            (57, 310),   # Middle estimate
        ]

        for pos in clan_icon_positions:
            await self.page.mouse.click(pos[0], pos[1])
            await asyncio.sleep(2)

            # Check if clan panel opened by looking for a known state change
            # We can check if a screenshot shows the "My Clan" header
            # For now, just try clicking and proceed
            break

        log.info("Clicked clan icon — waiting for clan panel...")
        await asyncio.sleep(2)

        # Click "Gifts" in the left sidebar of the clan panel
        # From screenshot 04_clan_menu.png: "Gifts" text is at approximately (258, 257)
        # It has a red badge "22" next to it
        await self.page.mouse.click(258, 257)
        await asyncio.sleep(2)

        log.info("Clicked Gifts tab.")

    async def navigate_to_triumphal_gifts(self):
        """Click the 'Triumphal Gifts' tab (right tab in the Gifts view)."""
        # From screenshots: "Triumphal Gifts" tab is at approximately (735, 133)
        await self.page.mouse.click(735, 133)
        await asyncio.sleep(2)
        log.info("Clicked Triumphal Gifts tab.")

    async def navigate_back_to_main(self):
        """Close clan panel and return to main view."""
        # The X close button on "My Clan" panel is at approximately (1098, 107)
        await self.page.mouse.click(1098, 107)
        await asyncio.sleep(1)
        # Also try Escape as backup
        await self.page.keyboard.press("Escape")
        await asyncio.sleep(1)
        log.info("Closed clan panel.")

    async def scroll_gifts_down(self):
        """Scroll the gift list down to see more entries.
        
        The gift list is inside the clan panel. We scroll within the list area.
        Gift list center is approximately at (700, 400) on 1280x720.
        """
        # Position mouse over the gift list area, then scroll
        await self.page.mouse.move(700, 400)
        await self.page.mouse.wheel(0, 350)
        await asyncio.sleep(2)
        log.debug("Scrolled gifts list down.")

    # ── Screenshot Capture ──────────────────────────────────────────────────

    async def capture_gift_screenshots(self, count: int = 2) -> list[str]:
        """Capture multiple screenshots of the gift list for consensus extraction.
        
        Takes full-page screenshots (not cropped) — Claude Vision handles
        the full UI context better than a tight crop, and it's simpler.
        
        Args:
            count: Number of screenshots to take (for multi-frame consensus)
            
        Returns:
            List of file paths to saved screenshots
        """
        ss_dir = ROOT / self.config["storage"]["screenshot_dir"]
        ss_dir.mkdir(parents=True, exist_ok=True)
        paths = []

        for i in range(count):
            self._screenshot_counter += 1
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            fname = f"gifts_{ts}_{self._screenshot_counter:04d}.png"
            fpath = ss_dir / fname

            # Full viewport screenshot — Claude handles the context well
            # and we don't risk misaligned crop regions
            await self.page.screenshot(path=str(fpath), full_page=False)
            paths.append(str(fpath))
            log.debug(f"Screenshot saved: {fpath}")

            if i < count - 1:
                await asyncio.sleep(0.5)

        return paths

    async def is_last_gift_page(self) -> bool:
        """Check if 'Claim chests' button is visible, indicating last page.
        
        Uses a quick screenshot + simple check. In practice, the Vision
        extraction returns has_more=false when it sees the button, so
        this is a backup check.
        """
        # Take a quick screenshot of the bottom area
        ss_dir = ROOT / self.config["storage"]["screenshot_dir"]
        check_path = ss_dir / "_last_page_check.png"
        await self.page.screenshot(
            path=str(check_path),
            clip={"x": 370, "y": 580, "width": 740, "height": 60}
        )
        # The Vision extraction handles this — has_more flag
        # This method exists for direct programmatic checking if needed
        return False  # Let Vision decide

    # ── WebSocket Interceptor ───────────────────────────────────────────────

    async def inject_ws_interceptor(self):
        """Inject JavaScript to intercept Sendbird WebSocket messages.
        
        Must be called BEFORE the game establishes the WebSocket connection,
        or after a page reload. If the WS is already connected, you'll need
        to reload the page.
        """
        log.info("Injecting WebSocket interceptor...")

        # Add the interceptor script to run on every navigation
        await self.context.add_init_script(WS_INTERCEPTOR_JS)

        # Also inject into current page if already loaded
        await self.page.evaluate(WS_INTERCEPTOR_JS)

        # If WebSocket is already established, we need to reload
        # to catch it with our interceptor
        log.info("Reloading page to intercept existing WebSocket connections...")
        await self.page.reload(wait_until="networkidle", timeout=60000)
        await asyncio.sleep(10)  # Wait for game + Sendbird to reconnect

        log.info("WebSocket interceptor active.")

    async def poll_intercepted_messages(self) -> list[dict]:
        """Poll for new intercepted WebSocket messages.
        
        Returns list of message dicts and clears the buffer.
        """
        try:
            messages = await self.page.evaluate("""
                (() => {
                    const msgs = window.__tb_ws_messages || [];
                    window.__tb_ws_messages = [];
                    return msgs;
                })()
            """)
            return messages or []
        except Exception as e:
            log.debug(f"Poll error (page may be navigating): {e}")
            return []
