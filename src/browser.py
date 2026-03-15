"""Playwright browser session for Total Battle.

Handles login, navigation, screenshot capture, and WebSocket interceptor injection.
Shared between chest counter and chat bridge.

All in-game navigation uses Vision-calibrated coordinates from calibration.py
instead of hardcoded pixel positions. Run `python main.py calibrate` to generate
or update the calibration profile.
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

WS_INTERCEPTOR_JS = """
(() => {
    if (window.__tb_ws_interceptor) return;
    window.__tb_ws_interceptor = true;
    window.__tb_ws_messages = [];

    const OrigWS = window.WebSocket;
    window.WebSocket = function(...args) {
        const ws = new OrigWS(...args);
        const url = args[0] || '';

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
    window.WebSocket.prototype = OrigWS.prototype;
    window.WebSocket.CONNECTING = OrigWS.CONNECTING;
    window.WebSocket.OPEN = OrigWS.OPEN;
    window.WebSocket.CLOSING = OrigWS.CLOSING;
    window.WebSocket.CLOSED = OrigWS.CLOSED;

    console.log('[TB-Toolkit] WebSocket interceptor installed');
})();
"""


class TBBrowser:
    """Manages a Playwright browser session for Total Battle.

    Navigation uses calibrated coordinates from calibration.py.
    Run `python main.py calibrate --visible` after first login.
    """

    def __init__(self, config: dict, headless: bool = True):
        self.config = config
        self.headless = headless
        self.playwright = None
        self.browser: Browser = None
        self.page: Page = None
        self._screenshot_counter = 0
        self._calibration = None

    async def __aenter__(self):
        self.playwright = await async_playwright().start()
        vp = self.config["game"].get("viewport", {"width": 1280, "height": 720})

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
                "--disable-session-crashed-bubble",
                "--disable-infobars",
            ],
        )
        self.browser = self.context.browser
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()

        # Load calibration profile
        from calibration import load_calibration
        self._calibration = load_calibration()
        if self._calibration:
            log.info("Loaded calibration profile.")
        else:
            log.warning("No calibration profile. Run 'python main.py calibrate --visible'.")

        return self

    async def __aexit__(self, *args):
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()

    # ── Calibration helpers ─────────────────────────────────────────────

    def _get_coords(self, screen: str, element: str) -> dict:
        """Get calibrated coordinates. Raises RuntimeError if missing."""
        from calibration import get_element_coords
        coords = get_element_coords(self._calibration, screen, element)
        if not coords:
            raise RuntimeError(
                f"Calibration missing: {screen}.{element}. "
                f"Run 'python main.py calibrate --visible' to fix."
            )
        return coords

    def _get_coords_or_none(self, screen: str, element: str):
        """Get calibrated coordinates, returning None if missing."""
        from calibration import get_element_coords
        return get_element_coords(self._calibration, screen, element)

    async def _recalibrate(self, screen: str, element: str):
        """Take a fresh screenshot and re-locate a single element."""
        from calibration import recalibrate_element
        coords = await recalibrate_element(self, self.config, screen, element)
        if coords:
            from calibration import load_calibration
            self._calibration = load_calibration()
        return coords

    # ── Login ───────────────────────────────────────────────────────────

    async def login(self):
        """Navigate to TB and log in. Session persists across runs."""
        url = self.config["game"]["url"]

        log.info(f"Navigating to {url}...")
        await self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(3)

        # Dismiss Chromium crash/restore popups
        for selector in ["button:has-text('Cancel')", "button:has-text('Restore')"]:
            try:
                btn = self.page.locator(selector).first
                if await btn.is_visible(timeout=1000):
                    if "Cancel" in selector:
                        await btn.click()
                        log.info("Dismissed Chromium restore popup")
                    break
            except Exception:
                continue

        await asyncio.sleep(2)

        # Already logged in?
        try:
            if await self.page.locator("canvas").first.is_visible(timeout=10000):
                log.info("Already logged in (game canvas detected)")
                log.info("Waiting for game to fully load (30 seconds)...")
                await asyncio.sleep(30)  # Give game more time to fully load
                await self._dismiss_popups()
                log.info("Login check complete.")
                return
        except Exception:
            log.info("Not logged in yet — need to authenticate")

        username = self.config["game"]["username"]
        password = self.config["game"]["password"]

        # Step 1: Click "Log In" link (HTML, not canvas)
        log.info("Looking for 'Log In' link...")
        try:
            await self.page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass

        clicked = False
        try:
            login_link = self.page.get_by_text("Log in", exact=True)
            if await login_link.count() > 0:
                await login_link.first.click()
                log.info("Clicked 'Log in' link")
                clicked = True
                await asyncio.sleep(3)
        except Exception as e:
            log.warning(f"Failed to click 'Log in': {e}")

        # Step 2: Fill email
        email_filled = False
        try:
            email_input = self.page.get_by_placeholder("Email")
            if await email_input.is_visible(timeout=5000):
                await email_input.click()
                await asyncio.sleep(0.5)
                await email_input.fill(username)
                log.info(f"Entered email: {username}")
                email_filled = True
        except Exception:
            for sel in ["input[type='email']", "input[name='email']",
                        "input[placeholder*='mail' i]"]:
                try:
                    el = self.page.locator(sel).first
                    if await el.is_visible(timeout=2000):
                        await el.click()
                        await asyncio.sleep(0.5)
                        await el.fill(username)
                        email_filled = True
                        break
                except Exception:
                    continue

        if not email_filled:
            log.error("Could not find email input.")
            if not self.headless:
                log.info("=" * 60)
                log.info("MANUAL LOGIN REQUIRED")
                log.info("Please log in in the browser window.")
                log.info("Session will be saved for future runs.")
                log.info("=" * 60)
                try:
                    await self.page.wait_for_selector("canvas", timeout=300000)
                    await asyncio.sleep(15)
                    await self._dismiss_popups()
                    return
                except Exception:
                    log.error("Timeout waiting for game")
            else:
                log.error("Headless mode — run with --visible for first-time setup")
            return

        # Step 3: Fill password
        try:
            pw = self.page.get_by_placeholder("Password")
            if await pw.is_visible(timeout=5000):
                await pw.click()
                await asyncio.sleep(0.5)
                await pw.fill(password)
                log.info("Entered password")
            else:
                raise Exception("Password not visible")
        except Exception as e:
            log.error(f"No password input: {e}")
            return

        # Step 4: Submit
        try:
            btn = self.page.get_by_role("button", name="LOGIN")
            if await btn.is_visible(timeout=2000):
                await btn.click()
                log.info("Clicked LOGIN")
            else:
                for sel in ["text=LOGIN", "text=Log In", "button[type='submit']"]:
                    b = self.page.locator(sel).first
                    if await b.is_visible(timeout=2000):
                        await b.click()
                        break
        except Exception:
            await self.page.keyboard.press("Enter")

        # Step 5: Wait for game
        log.info("Waiting for game to load...")
        try:
            await self.page.wait_for_selector("canvas", timeout=60000)
            log.info("Canvas detected")
        except Exception:
            log.warning("No canvas after 60s")

        log.info("Waiting for game to fully load after login (30 seconds)...")
        await asyncio.sleep(30)  # Give game more time to fully load
        await self._dismiss_popups()
        log.info("Login complete.")

    async def _dismiss_popups(self):
        """Close popups using Escape and HTML close buttons.

        Avoids blind coordinate clicking — Escape is safe and works for
        most game popups. HTML buttons catch any DOM-based overlays.
        """
        log.debug("Dismissing popups...")
        for _ in range(6):
            await self.page.keyboard.press("Escape")
            await asyncio.sleep(1)
            try:
                close = self.page.locator(
                    "[class*='close'], [aria-label='close'], .popup-close"
                ).first
                if await close.is_visible(timeout=500):
                    await close.click()
                    log.info("Closed popup via HTML button")
                    await asyncio.sleep(1)
            except Exception:
                pass
        log.debug("Popup dismissal complete.")

    # ── Navigation (calibration-based) ──────────────────────────────────

    async def verify_current_screen(self, expected: str) -> dict:
        """Screenshot the current state and ask Vision what screen we're on.

        Args:
            expected: What we expect to see (e.g., "gifts tab with chest entries")

        Returns:
            {"on_expected_screen": bool, "description": str}
        """
        import base64
        try:
            import anthropic
        except ImportError:
            return {"on_expected_screen": True, "description": "anthropic not available"}

        ss_path = await self._debug_screenshot(f"verify_{expected.replace(' ', '_')[:20]}")

        api_key = self.config["vision"]["anthropic_api_key"]
        model = self.config["vision"].get("model_routine", "claude-haiku-4-5-20251001")

        with open(ss_path, "rb") as f:
            image_data = base64.standard_b64encode(f.read()).decode("utf-8")

        client = anthropic.Anthropic(api_key=api_key)

        try:
            response = client.messages.create(
                model=model,
                max_tokens=300,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_data,
                            },
                        },
                        {
                            "type": "text",
                            "text": (
                                f"I expected to see: {expected}\n\n"
                                "In 1-2 sentences, describe what this Total Battle screenshot "
                                "actually shows. Then answer: is this the expected screen? "
                                "Reply as JSON: {\"on_expected_screen\": true/false, "
                                "\"description\": \"what you see\"}"
                            ),
                        },
                    ],
                }],
            )

            text = response.content[0].text.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]

            import json
            result = json.loads(text.strip())
            log.info(f"Screen verification: {result.get('description', 'unknown')}")
            return result

        except Exception as e:
            log.warning(f"Screen verification failed: {e}")
            return {"on_expected_screen": True, "description": f"verification error: {e}"}

    async def navigate_to_gifts(self):
        """Navigate to Clan → Gifts tab using calibrated coordinates.

        Includes verification that we actually reached the gifts screen.
        If not, retries once with fresh calibration.
        """
        log.info("Navigating to Clan → Gifts...")

        for _ in range(3):
            await self.page.keyboard.press("Escape")
            await asyncio.sleep(0.3)
        await asyncio.sleep(1)

        clan_btn = self._get_coords("main_game", "bottom_nav_clan")
        log.info(f"Clicking CLAN at ({clan_btn['x']}, {clan_btn['y']})")
        await self.page.mouse.click(clan_btn["x"], clan_btn["y"])
        await asyncio.sleep(4)

        gifts_btn = self._get_coords("clan_panel", "sidebar_gifts")
        log.info(f"Clicking Gifts at ({gifts_btn['x']}, {gifts_btn['y']})")
        await self.page.mouse.click(gifts_btn["x"], gifts_btn["y"])
        await asyncio.sleep(3)

        # Verify we're on the gifts screen
        verify = await self.verify_current_screen(
            "the Clan Gifts tab showing a list of chest gift entries with player names"
        )
        if not verify.get("on_expected_screen", True):
            log.warning(f"NOT on gifts screen! Saw: {verify.get('description')}")
            log.warning("Retrying with recalibration...")

            # Close whatever we're on and retry
            await self.page.keyboard.press("Escape")
            await asyncio.sleep(1)

            # Recalibrate the sidebar_gifts position from current clan panel
            new_coords = await self._recalibrate("clan_panel", "sidebar_gifts")
            if new_coords:
                log.info(f"Recalibrated Gifts to ({new_coords['x']}, {new_coords['y']})")
                # Re-open clan panel and try again
                await self.page.mouse.click(clan_btn["x"], clan_btn["y"])
                await asyncio.sleep(4)
                await self.page.mouse.click(new_coords["x"], new_coords["y"])
                await asyncio.sleep(3)

        log.info("Gifts tab opened.")

    async def navigate_to_members(self):
        """Navigate to Clan → Members tab using calibrated coordinates."""
        log.info("Navigating to Clan → Members...")

        for _ in range(3):
            await self.page.keyboard.press("Escape")
            await asyncio.sleep(0.3)
        await asyncio.sleep(1)

        clan_btn = self._get_coords("main_game", "bottom_nav_clan")
        log.info(f"Clicking CLAN at ({clan_btn['x']}, {clan_btn['y']})")
        await self.page.mouse.click(clan_btn["x"], clan_btn["y"])
        await asyncio.sleep(4)

        members_btn = self._get_coords("clan_panel", "sidebar_members")
        log.info(f"Clicking Members at ({members_btn['x']}, {members_btn['y']})")
        await self.page.mouse.click(members_btn["x"], members_btn["y"])
        await asyncio.sleep(3)
        log.info("Members tab opened.")

    async def navigate_to_triumphal_gifts(self):
        """Click the 'Triumphal Gifts' tab if calibrated."""
        triumphal = self._get_coords_or_none("gifts_view", "triumphal_gifts_tab")
        if not triumphal:
            log.warning("Triumphal Gifts tab not calibrated — skipping.")
            return
        log.info(f"Clicking Triumphal Gifts at ({triumphal['x']}, {triumphal['y']})")
        await self.page.mouse.click(triumphal["x"], triumphal["y"])
        await asyncio.sleep(2)

    async def navigate_back_to_main(self):
        """Close clan panel and return to main view."""
        close_btn = self._get_coords_or_none("clan_panel", "close_button")
        if close_btn:
            await self.page.mouse.click(close_btn["x"], close_btn["y"])
            await asyncio.sleep(1)
        await self.page.keyboard.press("Escape")
        await asyncio.sleep(1)
        log.info("Closed clan panel.")

    async def scroll_gifts_down(self, method="wheel"):
        """Scroll the gift list down using various methods.

        Args:
            method: "wheel" (mouse wheel), "drag" (drag scrollbar),
                   "keyboard" (Page Down key), or "click" (click scrollbar track)
        """
        if method == "wheel":
            # Original mouse wheel approach
            target = self._get_coords_or_none("gifts_view", "gift_list_center")
            if not target:
                vp = self.config["game"].get("viewport", {"width": 1280, "height": 720})
                target = {"x": vp["width"] // 2, "y": vp["height"] // 2}
                log.warning("Gift list center not calibrated — using viewport center")

            await self.page.mouse.move(target["x"], target["y"])
            # Multiple smaller scrolls work better than one large scroll
            for _ in range(5):
                await self.page.mouse.wheel(0, 300)
                await asyncio.sleep(0.2)
            await asyncio.sleep(1.5)
            log.debug("Scrolled gifts list down using mouse wheel (5x300px).")

        elif method == "drag":
            # Drag the scrollbar handle down
            # User confirmed: scrollbar is at X=1100, handle is ~50px tall
            scrollbar_x = 1100  # Exact X position from user

            # Dynamic handle position tracking
            # As we scroll, the handle moves down, so we need to adjust where we grab it
            # Start at the top for first scroll, then progressively lower
            if not hasattr(self, '_scroll_position'):
                self._scroll_position = 0

            # AGGRESSIVE SCROLLING STRATEGY:
            # The scrollbar track runs from Y=275 to Y=525 (250px total)
            # With 130 gifts and only 4 visible at a time, we need to scroll through ~126 more
            # That's about 32 pages of 4 gifts each
            # So we should scroll in much larger increments

            if self._scroll_position == 0:
                # First scroll: grab at top, drag halfway down
                scrollbar_handle_y = 275
                drag_distance = 125  # Half the scrollbar
            elif self._scroll_position == 1:
                # Second scroll: grab at middle, drag to 3/4 down
                scrollbar_handle_y = 400
                drag_distance = 100
            elif self._scroll_position == 2:
                # Third scroll: grab at 3/4, drag to bottom
                scrollbar_handle_y = 475
                drag_distance = 75
            else:
                # Subsequent scrolls: small increments at the bottom
                scrollbar_handle_y = 500
                drag_distance = 50

            # Calculate drag end position
            drag_end_y = min(scrollbar_handle_y + drag_distance, 550)

            # Click and drag the handle down
            await self.page.mouse.move(scrollbar_x, scrollbar_handle_y)
            await self.page.mouse.down()
            await asyncio.sleep(0.1)
            # Drag to end position with more steps for smoother motion
            await self.page.mouse.move(scrollbar_x, drag_end_y, steps=20)
            await asyncio.sleep(0.2)
            await self.page.mouse.up()
            await asyncio.sleep(1.5)

            # Track that we've scrolled
            self._scroll_position += 1
            log.info(f"Scrolled gifts list: drag from Y={scrollbar_handle_y} to Y={drag_end_y} (distance={drag_distance}px)")

        elif method == "keyboard":
            # Use Page Down key to scroll
            # First click in the gift list area to focus it
            target = self._get_coords_or_none("gifts_view", "gift_list_center")
            if not target:
                vp = self.config["game"].get("viewport", {"width": 1280, "height": 720})
                target = {"x": vp["width"] // 2, "y": vp["height"] // 2}

            await self.page.mouse.click(target["x"], target["y"])
            await asyncio.sleep(0.2)
            # Press Page Down multiple times
            for _ in range(3):
                await self.page.keyboard.press("PageDown")
                await asyncio.sleep(0.3)
            await asyncio.sleep(1)
            log.debug("Scrolled gifts list down using Page Down key.")

        elif method == "click":
            # Click on the scrollbar track to jump down
            # User confirmed: scrollbar is at X=1100
            scrollbar_x = 1100  # Exact X position from user

            # Click multiple times in the lower portion of scrollbar track to jump down
            # Scrollbar track runs from Y=275 to Y=525
            click_positions = [400, 450, 500, 520]  # Progressive clicks down the track

            for click_y in click_positions:
                await self.page.mouse.click(scrollbar_x, click_y)
                await asyncio.sleep(0.3)

            log.debug(f"Scrolled gifts list down using scrollbar track clicks at X={scrollbar_x}.")
        else:
            log.warning(f"Unknown scroll method: {method}")

    async def scroll_members_down(self):
        """Scroll the members list down using calibrated list center."""
        target = self._get_coords_or_none("members_view", "member_list_center")
        if not target:
            vp = self.config["game"].get("viewport", {"width": 1280, "height": 720})
            target = {"x": vp["width"] // 2, "y": vp["height"] // 2}
            log.warning("Member list center not calibrated — using viewport center")

        await self.page.mouse.move(target["x"], target["y"])
        await self.page.mouse.wheel(0, 350)
        await asyncio.sleep(2)
        log.debug("Scrolled members list down.")

    # ── Screenshot Capture ──────────────────────────────────────────────

    async def _debug_screenshot(self, name: str) -> str:
        """Take a debug screenshot with a specific name."""
        ss_dir = ROOT / self.config["storage"]["screenshot_dir"] / "debug"
        ss_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fpath = ss_dir / f"debug_{name}_{ts}.png"
        await self.page.screenshot(path=str(fpath), full_page=False)
        return str(fpath)

    async def capture_gift_screenshots(self, count: int = 2) -> list[str]:
        """Capture multiple full-viewport screenshots for consensus extraction."""
        ss_dir = ROOT / self.config["storage"]["screenshot_dir"]
        ss_dir.mkdir(parents=True, exist_ok=True)
        paths = []

        for i in range(count):
            self._screenshot_counter += 1
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            fpath = ss_dir / f"gifts_{ts}_{self._screenshot_counter:04d}.png"
            await self.page.screenshot(path=str(fpath), full_page=False)
            paths.append(str(fpath))
            log.debug(f"Screenshot saved: {fpath}")
            if i < count - 1:
                await asyncio.sleep(0.5)

        return paths

    async def capture_screenshot(self, name: str = "capture") -> str:
        """Capture a single full-viewport screenshot with a custom name."""
        ss_dir = ROOT / self.config["storage"]["screenshot_dir"]
        ss_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fpath = ss_dir / f"{name}_{ts}.png"
        await self.page.screenshot(path=str(fpath), full_page=False)
        return str(fpath)

    # ── WebSocket Interceptor ───────────────────────────────────────────

    async def inject_ws_interceptor(self):
        """Inject JS to intercept Sendbird WebSocket messages."""
        log.info("Injecting WebSocket interceptor...")
        await self.context.add_init_script(WS_INTERCEPTOR_JS)
        await self.page.evaluate(WS_INTERCEPTOR_JS)

        log.info("Reloading to intercept existing WebSocket connections...")
        await self.page.reload(wait_until="networkidle", timeout=60000)
        await asyncio.sleep(10)
        log.info("WebSocket interceptor active.")

    async def poll_intercepted_messages(self) -> list[dict]:
        """Poll for new intercepted WebSocket messages."""
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
