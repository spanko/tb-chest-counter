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

        # Use persistent context to save login session between runs
        user_data_dir = ROOT / "data" / "browser_data"
        user_data_dir.mkdir(parents=True, exist_ok=True)

        log.info(f"Using persistent browser context at {user_data_dir}")
        self.context = await self.playwright.chromium.launch_persistent_context(
            str(user_data_dir),
            headless=self.headless,
            viewport=vp,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Safari/537.36"
            ),
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-session-crashed-bubble",  # Suppress "restore pages?" popup
                "--disable-infobars",  # Suppress info bars
            ],
        )
        self.browser = self.context.browser  # For compatibility
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        return self

    async def __aexit__(self, *args):
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()

    # ── Login ───────────────────────────────────────────────────────────────

    async def login(self):
        """Navigate to TB and log in with utility account credentials.

        With persistent context, login is only needed once. After the first manual
        login, cookies persist and you'll stay logged in across runs.
        """
        url = self.config["game"]["url"]

        log.info(f"Navigating to {url}...")
        await self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(3)  # Give page time to fully render

        # Dismiss any Chromium crash/restore popups before doing anything else
        try:
            # Look for common Chromium restore dialog buttons
            restore_buttons = [
                "button:has-text('Restore')",
                "button:has-text('Cancel')",
                "text='Restore pages?'",
            ]
            for selector in restore_buttons:
                try:
                    btn = self.page.locator(selector).first
                    if await btn.is_visible(timeout=1000):
                        # Click Cancel/close if found
                        if "Cancel" in selector or "Close" in selector:
                            await btn.click()
                            log.info("Dismissed Chromium restore popup")
                        break
                except Exception:
                    continue
        except Exception:
            pass  # No popup found, continue

        await asyncio.sleep(2)

        # Check if already logged in by looking for the game canvas
        try:
            canvas = await self.page.locator("canvas").first.is_visible(timeout=10000)
            if canvas:
                log.info("Already logged in (game canvas detected)")
                await asyncio.sleep(10)  # Let game fully load
                await self._dismiss_popups()
                log.info("Login check complete.")
                return
        except Exception:
            log.info("Not logged in yet - need to authenticate")

        # If not logged in, attempt automated login or prompt for manual login
        username = self.config["game"]["username"]
        password = self.config["game"]["password"]

        # ── Step 1: Click "Log In" link in top navigation bar ──
        # This opens a popup with email/password fields
        log.info("Looking for 'Log In' link in top navigation...")
        try:
            await self.page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass  # Continue even if networkidle times out

        # The "Log in" link is in the top right navigation bar
        # Use get_by_text which is case-insensitive for exact matches
        clicked = False
        try:
            # Try to find and click "Log in" text (case matters in screenshots)
            login_link = self.page.get_by_text("Log in", exact=True)
            count = await login_link.count()
            log.info(f"Found {count} 'Log in' elements on page")

            if count > 0:
                # Click the first one (top navigation)
                await login_link.first.click()
                log.info("Clicked 'Log in' link (top navigation)")
                clicked = True
                await asyncio.sleep(3)  # Wait for popup to appear
        except Exception as e:
            log.warning(f"Failed to click 'Log in' link: {e}")

        if not clicked:
            log.warning("Could not find 'Log in' link - will try manual login")

        # ── Step 2: Fill email field in the popup ──
        log.info("Looking for email input field in login popup...")
        email_filled = False
        try:
            # The popup has an input with placeholder "Email"
            email_input = self.page.get_by_placeholder("Email")
            if await email_input.is_visible(timeout=5000):
                await email_input.click()  # Focus the field first
                await asyncio.sleep(0.5)
                await email_input.fill(username)
                log.info(f"Entered email: {username}")
                email_filled = True
        except Exception as e:
            log.debug(f"Email placeholder selector failed: {e}")
            # Fallback to other selectors
            for selector in [
                "input[type='email']",
                "input[name='email']",
                "input[placeholder*='mail' i]",
            ]:
                try:
                    email_input = self.page.locator(selector).first
                    if await email_input.is_visible(timeout=2000):
                        await email_input.click()
                        await asyncio.sleep(0.5)
                        await email_input.fill(username)
                        log.info(f"Entered email: {username}")
                        email_filled = True
                        break
                except Exception as e2:
                    log.debug(f"Email selector {selector} failed: {e2}")
                    continue

        if not email_filled:
            log.error("Could not find email input field.")
            if not self.headless:
                log.info("=" * 60)
                log.info("MANUAL LOGIN REQUIRED")
                log.info("=" * 60)
                log.info("Please log in manually in the browser window.")
                log.info("After logging in, the session will be saved and you")
                log.info("won't need to log in again on future runs.")
                log.info("Waiting for game to load (up to 5 minutes)...")
                try:
                    await self.page.wait_for_selector("canvas", timeout=300000)
                    log.info("Game canvas detected - login successful!")
                    await asyncio.sleep(15)  # Let game fully initialize
                    await self._dismiss_popups()
                    log.info("Login complete. Session saved for future runs.")
                    return
                except Exception:
                    log.error("Timeout waiting for game - login may have failed")
            else:
                log.error("Running in headless mode - cannot prompt for manual login")
                log.error("Please run with --visible flag for first-time setup")
            return

        # ── Step 3: Fill password field ──
        # The popup shows email+password together, no NEXT button needed
        try:
            password_input = self.page.get_by_placeholder("Password")
            if await password_input.is_visible(timeout=5000):
                await password_input.click()
                await asyncio.sleep(0.5)
                await password_input.fill(password)
                log.info("Entered password")
            else:
                raise Exception("Password field not visible")
        except Exception as e:
            log.error(f"No password input found: {e}")
            return

        # ── Step 4: Submit login ──
        try:
            # Click the LOGIN button (shown in popup)
            login_btn = self.page.get_by_role("button", name="LOGIN")
            if await login_btn.is_visible(timeout=2000):
                await login_btn.click()
                log.info("Clicked LOGIN button")
            else:
                # Fallback to text search
                for selector in ["text=LOGIN", "text=Log In", "button[type='submit']"]:
                    btn = self.page.locator(selector).first
                    if await btn.is_visible(timeout=2000):
                        await btn.click()
                        log.info(f"Clicked submit button: {selector}")
                        break
        except Exception as e:
            log.warning(f"No LOGIN button found: {e} — pressing Enter")
            await self.page.keyboard.press("Enter")

        # ── Step 5: Wait for game to load ──
        log.info("Waiting for game to load...")
        try:
            await self.page.wait_for_selector("canvas", timeout=60000)
            log.info("Canvas detected — game is loading")
        except Exception:
            log.warning("No canvas after 60s — login may have failed")

        await asyncio.sleep(10)  # Let WASM fully initialize

        # ── Step 6: Dismiss store popup if present ──
        await self._dismiss_popups()

        log.info("Login complete.")

    async def _dismiss_popups(self):
        """Close any popups that appear after login (store, offers, etc).

        Tries multiple strategies to close various popup types.
        Multiple popups may stack, so we try several times.
        """
        # Common X button positions for 1280x720 viewport
        # These are based on observed popup patterns in Total Battle
        x_button_positions = [
            (1015, 115),  # Special Offer "Capitol Level 15 Sale" X button
            (1258, 68),   # Store popup top-right
            (1200, 100),  # Special offer variant 1
            (1150, 120),  # Special offer variant 2
            (900, 150),   # Centered popup top-right
            (1100, 80),   # Event popup
            (1240, 90),   # Daily reward popup
            (1020, 110),  # Special offer variant 3
        ]

        log.debug("Starting popup dismissal...")
        initial_screenshot = await self._debug_screenshot("popup_dismiss_start")
        log.debug(f"Initial state: {initial_screenshot}")

        for attempt in range(8):  # More attempts for multiple stacked popups
            popup_closed = False

            # Try HTML close buttons first
            try:
                close_btn = self.page.locator("[class*='close'], [aria-label='close'], .popup-close").first
                if await close_btn.is_visible(timeout=1000):
                    await close_btn.click()
                    log.info(f"Closed popup via HTML button (attempt {attempt+1})")
                    popup_closed = True
                    await asyncio.sleep(1.5)
                    debug_path = await self._debug_screenshot(f"popup_dismiss_html_{attempt}")
                    log.debug(f"After HTML close: {debug_path}")
            except Exception:
                pass

            # Try each known X button position
            if not popup_closed:
                for i, (x, y) in enumerate(x_button_positions):
                    try:
                        # Add visual marker before clicking
                        await self._add_click_marker(x, y, f"X{i+1}")
                        await asyncio.sleep(0.2)

                        await self.page.mouse.click(x, y)
                        await asyncio.sleep(0.5)
                        log.debug(f"Clicked position ({x}, {y}) - attempt {attempt+1}")
                        popup_closed = True

                        debug_path = await self._debug_screenshot(f"popup_dismiss_pos_{attempt}_{i}")
                        log.debug(f"After position click: {debug_path}")
                        break  # Move to next attempt after clicking
                    except Exception:
                        pass

            # Also try Escape key as fallback
            await self.page.keyboard.press("Escape")
            await asyncio.sleep(0.5)

            # Check if we can see the game UI (clan button visible)
            # If yes, we've probably cleared all popups
            try:
                # Quick check - try to take a screenshot to see current state
                # This helps verify if popups are actually gone
                await asyncio.sleep(0.5)
            except Exception:
                pass

        final_screenshot = await self._debug_screenshot("popup_dismiss_complete")
        log.debug(f"Popup dismissal complete: {final_screenshot}")

    # ── Navigation ──────────────────────────────────────────────────────────

    async def navigate_to_gifts(self):
        """Navigate to Clan → Gifts tab.

        Coordinate map (1280x720 viewport, from real screenshots):
        - Bottom nav CLAN button: approximately (700, 640)
        - "My Clan" panel opens with tabs at top
        - "Gifts" tab in top nav: approximately (570, 133) based on Triumphal Gifts position
        - Close panel X: approximately (1098, 107)
        """
        log.info("Navigating to Clan → Gifts...")

        # First dismiss any popups (including building info popups)
        await self._dismiss_popups()
        await asyncio.sleep(1)

        # Take debug screenshot before any actions
        debug_path = await self._debug_screenshot("01_start_navigation")
        log.info(f"Debug screenshot saved: {debug_path}")

        # Close any open popups using Escape key
        log.info("Closing any popups with Escape key...")
        for _ in range(5):
            await self.page.keyboard.press("Escape")
            await asyncio.sleep(0.3)
        await asyncio.sleep(1)

        # Take screenshot after Escape presses
        debug_path = await self._debug_screenshot("02_after_escape")
        log.info(f"After escape presses: {debug_path}")

        # Add visual marker before clicking CLAN button
        await self._add_click_marker(695, 668, "CLAN")
        debug_path = await self._debug_screenshot("03_before_clan_click")
        log.info(f"Click marker added at (695, 668): {debug_path}")

        log.info("Clicking CLAN button in bottom navigation...")
        # CLAN button is the 6th button in bottom nav, has a shield icon
        # CRITICAL: The Lumberjack building is RIGHT ABOVE the CLAN button
        # Based on debug screenshots, the button is at approximately y=668
        # Click in the center of the button to avoid hitting buildings
        await self.page.mouse.click(695, 668)  # Center of CLAN button
        log.info("Clicked at (695, 668) - CLAN button center")
        await asyncio.sleep(4)  # Give more time for clan panel to open

        # Take screenshot after CLAN button click
        debug_path = await self._debug_screenshot("04_after_clan_click")
        log.info(f"After CLAN click: {debug_path}")

        # DON'T dismiss popups here - it closes the clan panel!
        # The clan panel itself shouldn't trigger popups
        # If there ARE popups, we'll handle them more carefully

        # Take screenshot to verify clan panel is still open
        debug_path = await self._debug_screenshot("05_clan_panel_open")
        log.info(f"Clan panel should be open: {debug_path}")

        log.info("Clan panel should be open — looking for Gifts in left sidebar...")

        # Verify the clan panel is actually open by checking for the "My Clan" header
        # If not open, try clicking CLAN again
        try:
            # Quick check - take a screenshot to verify state
            verify_path = await self._debug_screenshot("05b_verify_clan_open")
            log.debug(f"Verifying clan panel: {verify_path}")

            # You could also add a visual check here if needed
            # For now, we'll proceed assuming it's open
        except Exception as e:
            log.warning(f"Could not verify clan panel state: {e}")

        # Add visual marker before clicking Gifts
        await self._add_click_marker(259, 257, "GIFTS")
        debug_path = await self._debug_screenshot("06_before_gifts_click")
        log.info(f"Click marker added at (259, 257): {debug_path}")

        # Click "Gifts" in the left sidebar of the clan panel
        # From screenshot: "Gifts" is in the brown left sidebar at approximately (259, 257)
        await self.page.mouse.click(259, 257)
        await asyncio.sleep(2)

        # Take screenshot after Gifts click
        debug_path = await self._debug_screenshot("07_after_gifts_click")
        log.info(f"After Gifts click: {debug_path}")

        log.info("Clicked Gifts in left sidebar.")

    async def navigate_to_triumphal_gifts(self):
        """Click the 'Triumphal Gifts' tab (right tab in the Gifts view)."""
        log.info("Navigating to Triumphal Gifts tab...")

        # Take screenshot before clicking
        debug_path = await self._debug_screenshot("08_before_triumphal_click")
        log.debug(f"Before Triumphal Gifts click: {debug_path}")

        # Add visual marker
        await self._add_click_marker(735, 133, "TRIUMPHAL")
        debug_path = await self._debug_screenshot("09_triumphal_marker")
        log.debug(f"Click marker for Triumphal Gifts: {debug_path}")

        # From screenshots: "Triumphal Gifts" tab is at approximately (735, 133)
        await self.page.mouse.click(735, 133)
        await asyncio.sleep(2)

        # Take screenshot after clicking
        debug_path = await self._debug_screenshot("10_after_triumphal_click")
        log.debug(f"After Triumphal Gifts click: {debug_path}")

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

    async def _debug_screenshot(self, name: str) -> str:
        """Take a debug screenshot with a specific name."""
        ss_dir = ROOT / self.config["storage"]["screenshot_dir"] / "debug"
        ss_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"debug_{name}_{ts}.png"
        fpath = ss_dir / fname

        await self.page.screenshot(path=str(fpath), full_page=False)
        return str(fpath)

    async def _add_click_marker(self, x: int, y: int, label: str = ""):
        """Add a visual marker on the page to show where we're about to click.

        This helps debug click positioning issues by showing exactly where
        the automation is trying to click.
        """
        try:
            # Inject a red circle with label at the click position
            await self.page.evaluate(f"""
                (() => {{
                    // Remove any existing markers
                    const existing = document.querySelectorAll('.tb-click-marker');
                    existing.forEach(el => el.remove());

                    // Create marker container
                    const marker = document.createElement('div');
                    marker.className = 'tb-click-marker';
                    marker.style.position = 'absolute';
                    marker.style.left = '{x - 15}px';
                    marker.style.top = '{y - 15}px';
                    marker.style.width = '30px';
                    marker.style.height = '30px';
                    marker.style.border = '3px solid red';
                    marker.style.borderRadius = '50%';
                    marker.style.backgroundColor = 'rgba(255, 0, 0, 0.3)';
                    marker.style.zIndex = '999999';
                    marker.style.pointerEvents = 'none';

                    // Add crosshair
                    const crosshair = document.createElement('div');
                    crosshair.style.position = 'absolute';
                    crosshair.style.left = '13px';
                    crosshair.style.top = '13px';
                    crosshair.style.width = '4px';
                    crosshair.style.height = '4px';
                    crosshair.style.backgroundColor = 'red';
                    marker.appendChild(crosshair);

                    // Add label if provided
                    if ('{label}') {{
                        const text = document.createElement('div');
                        text.style.position = 'absolute';
                        text.style.left = '35px';
                        text.style.top = '5px';
                        text.style.color = 'red';
                        text.style.fontSize = '14px';
                        text.style.fontWeight = 'bold';
                        text.style.backgroundColor = 'white';
                        text.style.padding = '2px 5px';
                        text.style.border = '1px solid red';
                        text.style.whiteSpace = 'nowrap';
                        text.innerText = '{label}';
                        marker.appendChild(text);
                    }}

                    document.body.appendChild(marker);

                    // Remove marker after 5 seconds
                    setTimeout(() => marker.remove(), 5000);
                }})();
            """)
        except Exception as e:
            log.debug(f"Could not add click marker: {e}")

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
