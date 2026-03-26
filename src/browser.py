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
                # Container stability - essential flags only
                "--disable-dev-shm-usage",  # Use /tmp instead of /dev/shm (limited in containers)
                "--no-sandbox",  # Required for container runtimes
                "--disable-setuid-sandbox",
                "--disable-gpu",  # No GPU in containers
            ],
        )
        self.browser = self.context.browser
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()

        # NOTE: We do NOT clear storage in cloud mode anymore.
        # The baked-in browser_data contains valid session cookies.
        # Clearing them forces a fresh login which is broken.

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

        # Dismiss any popups that might block the login form
        try:
            await self._dismiss_popups()
        except Exception:
            pass

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

                # Wait for the email input to actually appear AND be visible after clicking
                log.info("Waiting for email input field to appear...")
                try:
                    # First wait for it to exist in DOM
                    await self.page.wait_for_selector(
                        "input[type='email'], input[placeholder*='mail' i], input[name='email'], input[placeholder='Email']",
                        timeout=10000,
                        state="attached"  # Just needs to be in DOM
                    )
                    log.info("Email input field found in DOM, waiting for visibility...")

                    # Now wait for it to be visible
                    await self.page.wait_for_selector(
                        "input[type='email'], input[placeholder*='mail' i], input[name='email'], input[placeholder='Email']",
                        timeout=10000,
                        state="visible"  # Must be visible
                    )
                    log.info("Email input field is now visible")
                except Exception as e:
                    log.warning(f"Timeout waiting for email input: {e}")
                    # Take a debug screenshot to see what's on screen
                    await self._debug_screenshot("login_form_missing")

                    # Try to make it visible by clicking on the form area
                    log.info("Attempting to click on form area to activate it...")
                    try:
                        # Try clicking on the form/modal if it exists
                        form = self.page.locator("form, .modal, .dialog, .popup").first
                        if await form.is_visible(timeout=1000):
                            await form.click()
                            await asyncio.sleep(1)
                    except:
                        pass
        except Exception as e:
            log.warning(f"Failed to click 'Log in': {e}")

        # Step 2: Fill email
        email_filled = False

        # The login popup appears on the RIGHT side of the screen after clicking "Log in"
        # It contains Email, Password fields and a LOGIN button
        # We need to target the popup's inputs, NOT the left-side registration form

        # First, try to find the login popup container and target inputs within it
        # The popup has a "LOGIN" button which distinguishes it from the registration form
        try:
            # Look for a container that has both email input AND a LOGIN button (the popup)
            # The popup is typically the one with the LOGIN button visible
            login_button = self.page.locator("button:has-text('LOGIN')").first
            if await login_button.is_visible(timeout=2000):
                log.info("Found LOGIN button, looking for email field near it...")

                # Get all email-like inputs and find the one closest to the LOGIN button
                # or within the same container
                email_inputs = self.page.locator("input[type='email'], input[placeholder='Email']")
                count = await email_inputs.count()
                log.info(f"Found {count} email input(s)")

                # Try to find the email input that's in the same form/container as LOGIN button
                # The popup inputs should be after the registration form inputs in DOM order
                # So we try the LAST matching input, not the first
                if count > 1:
                    # Multiple inputs - try the last one (likely the popup)
                    el = email_inputs.nth(count - 1)
                    if await el.is_visible(timeout=1000):
                        await el.click()
                        await asyncio.sleep(0.5)
                        await el.fill(username)
                        log.info(f"Entered email using last email input (popup)")
                        email_filled = True
                elif count == 1:
                    el = email_inputs.first
                    if await el.is_visible(timeout=1000):
                        await el.click()
                        await asyncio.sleep(0.5)
                        await el.fill(username)
                        log.info(f"Entered email using single email input")
                        email_filled = True
        except Exception as e:
            log.debug(f"Popup-based email search failed: {e}")

        # Fallback: try specific selectors
        if not email_filled:
            email_selectors = [
                "input[placeholder='Email']",
                "input[placeholder*='mail' i]",
                "input[type='email']",
                "input[name='email']",
            ]

            for sel in email_selectors:
                try:
                    # Try the LAST matching element (popup is after registration form in DOM)
                    els = self.page.locator(sel)
                    count = await els.count()
                    if count > 0:
                        el = els.nth(count - 1) if count > 1 else els.first
                        if await el.is_visible(timeout=2000):
                            await el.click()
                            await asyncio.sleep(0.5)
                            await el.fill(username)
                            log.info(f"Entered email using selector (last match): {sel}")
                            email_filled = True
                            break
                except Exception as e:
                    log.debug(f"Selector {sel} failed: {e}")
                    continue

        if not email_filled:
            log.warning("Could not find email input via selectors, trying coordinate click...")
            # Take debug screenshot to see current state
            await self._debug_screenshot("email_input_not_found")

            # Fallback: click directly at coordinates where the login popup's email field is
            # Based on 1280x720 viewport, the right-side login popup has:
            # Email field at approximately (1017, 87)
            # Password field at approximately (1017, 135)
            # LOGIN button at approximately (1017, 212)
            try:
                log.info("Clicking at email field coordinates (1017, 87)...")
                await self.page.mouse.click(1017, 87)
                await asyncio.sleep(0.5)
                await self.page.keyboard.type(username, delay=50)
                log.info(f"Typed email via coordinates: {username}")
                email_filled = True
            except Exception as e:
                log.error(f"Coordinate click for email failed: {e}")

        if not email_filled:
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
        password_filled = False
        password_selectors = [
            "input[placeholder='Password']",
            "input[placeholder*='assword' i]",
            "input[type='password']",
            "input[name='password']",
            "input[autocomplete='current-password']",
        ]

        for sel in password_selectors:
            try:
                el = self.page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    await el.click()
                    await asyncio.sleep(0.5)
                    await el.fill(password)
                    log.info(f"Entered password using selector: {sel}")
                    password_filled = True
                    break
            except Exception:
                continue

        if not password_filled:
            try:
                pw = self.page.get_by_placeholder("Password")
                if await pw.is_visible(timeout=2000):
                    await pw.click()
                    await asyncio.sleep(0.5)
                    await pw.fill(password)
                    log.info("Entered password via placeholder")
                    password_filled = True
            except Exception:
                pass

        if not password_filled:
            log.warning("Could not find password input via selectors, trying coordinate click...")
            await self._debug_screenshot("password_input_not_found")

            # Fallback: click directly at password field coordinates
            try:
                log.info("Clicking at password field coordinates (1017, 135)...")
                await self.page.mouse.click(1017, 135)
                await asyncio.sleep(0.5)
                await self.page.keyboard.type(password, delay=50)
                log.info("Typed password via coordinates")
                password_filled = True
            except Exception as e:
                log.error(f"Coordinate click for password failed: {e}")
                return

        # Step 4: Submit
        login_clicked = False
        login_selectors = [
            "button:has-text('LOGIN')",
            "button:has-text('Log in')",
            "input[type='submit']",
            "button[type='submit']",
            ".login-btn",
            "[class*='login'][class*='button']",
        ]

        for sel in login_selectors:
            try:
                btn = self.page.locator(sel).first
                if await btn.is_visible(timeout=2000):
                    await btn.click()
                    log.info(f"Clicked login button: {sel}")
                    login_clicked = True
                    break
            except Exception:
                continue

        if not login_clicked:
            # Fallback: click at LOGIN button coordinates
            try:
                log.info("Clicking at LOGIN button coordinates (1017, 212)...")
                await self.page.mouse.click(1017, 212)
                log.info("Clicked LOGIN via coordinates")
                login_clicked = True
            except Exception as e:
                log.warning(f"Coordinate click for LOGIN failed: {e}")
                # Final fallback to Enter key
                log.info("Pressing Enter to submit login")
                await self.page.keyboard.press("Enter")

        # Step 5: Wait for game
        log.info("Waiting for game to load...")
        try:
            await self.page.wait_for_selector("canvas", timeout=60000)
            log.info("Canvas detected")
        except Exception as e:
            log.warning(f"No canvas after 60s: {e}")
            # Take debug screenshot to see where we ended up
            await self._debug_screenshot("post_login_no_canvas")
            # Check if we're still on login page
            try:
                if await self.page.locator("input[type='email'], input[placeholder='Email']").first.is_visible(timeout=1000):
                    log.error("Still on login page - login likely failed")
                    await self._debug_screenshot("still_on_login_page")
            except:
                pass

        # State machine approach: detect screen and take appropriate action
        # Loop every 10 seconds, identify screen type, act accordingly
        log.info("Starting state machine loop...")

        max_iterations = 40  # 5 min wait (30 * 10s) + 10 more attempts
        no_change_count = 0
        max_no_change = 6  # 60 seconds of no change = give up on current state

        for iteration in range(max_iterations):
            ss_path = await self._debug_screenshot(f"state_{iteration}")

            # Wait 5 minutes (30 iterations * 10 sec) for store to fully load
            # Then start clicking X button
            if iteration >= 30:
                log.info(f"Iteration {iteration}: Store should be loaded, clicking X button...")
                try:
                    await self._click_bonus_sales_x()
                except Exception as e:
                    log.warning(f"X click failed: {e}")
                await asyncio.sleep(10)
                continue

            # For iterations 0-29, just wait and take screenshots (let store load)
            log.info(f"Iteration {iteration}: Waiting for store to load...")
            await asyncio.sleep(10)

        # Final screenshot - don't fail if page is in transition
        try:
            await self._debug_screenshot("state_final")
        except Exception as e:
            log.warning(f"Could not capture final state screenshot: {e}")
        log.info("State machine complete.")

    async def _dismiss_popups(self):
        """Close popups with minimal, safe approach.

        Just press Escape a few times - this handles most dialogs without
        risking accidental clicks on game UI elements.
        """
        log.info("Dismissing popups (ESC only)...")

        for i in range(3):
            await self.page.keyboard.press("Escape")
            await asyncio.sleep(0.3)

    async def _dismiss_modal_popups(self):
        """Dismiss modal popups without closing the Clan panel.

        Uses Vision to detect if a popup is present and where the X button is.
        Only clicks if a popup is actually detected - NO blind clicking.
        NO ESC presses (ESC closes the Clan panel).
        """
        log.info("Checking for modal popups (Vision-based)...")

        # Use Vision to check if there's a popup and get X button coordinates
        popup_info = await self._detect_popup_with_coordinates()

        if not popup_info.get("has_popup", False):
            log.info("No popup detected - nothing to dismiss.")
            return

        # A popup was detected - try to dismiss it
        log.info(f"Popup detected: {popup_info.get('description', 'unknown')}")

        x_coords = popup_info.get("x_button_coords")
        if x_coords:
            x, y = x_coords.get("x"), x_coords.get("y")
            if x and y:
                log.info(f"Clicking X button at ({x}, {y})...")
                try:
                    await self.page.mouse.click(x, y)
                    await asyncio.sleep(0.5)
                    log.info("Popup X button clicked.")
                except Exception as e:
                    log.warning(f"Failed to click popup X at ({x}, {y}): {e}")
                log.info("Modal popup check complete.")
                return

        # No X button found - try clicking outside the dialog to dismiss
        # Payment dialogs are typically centered, so click in the dark margin areas
        log.info("No X button found - trying to click outside dialog...")
        outside_coords = [
            (50, 400),    # Far left margin
            (1230, 400),  # Far right margin
        ]
        for x, y in outside_coords:
            try:
                await self.page.mouse.click(x, y)
                await asyncio.sleep(0.3)
            except Exception as e:
                log.debug(f"Outside click at ({x}, {y}) failed: {e}")

        log.info("Modal popup check complete.")

    async def _detect_popup_with_coordinates(self) -> dict:
        """Use Claude Vision to detect popups and locate the X button.

        Returns:
            {
                "has_popup": bool,
                "description": str,
                "x_button_coords": {"x": int, "y": int} or None
            }
        """
        import base64
        try:
            import anthropic
        except ImportError:
            log.warning("anthropic not available for popup detection")
            return {"has_popup": False, "description": "anthropic not available"}

        ss_path = await self._debug_screenshot("popup_detect")

        api_key = self.config["vision"]["anthropic_api_key"]
        model = self.config["vision"].get("model_routine", "claude-haiku-4-5-20251001")

        with open(ss_path, "rb") as f:
            image_data = base64.standard_b64encode(f.read()).decode("utf-8")

        client = anthropic.Anthropic(api_key=api_key)

        try:
            response = client.messages.create(
                model=model,
                max_tokens=400,
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
                                "This is a 1280x720 screenshot from the game Total Battle. "
                                "Check if there's a MODAL POPUP that needs to be dismissed.\n\n"
                                "A modal popup is:\n"
                                "- A 'proposal' or offer dialog (e.g., 'A proposal from...')\n"
                                "- A payment/purchase dialog with USD prices\n"
                                "- Any centered dialog box overlaying the game\n\n"
                                "NOT a popup (don't dismiss):\n"
                                "- The Clan panel with sidebar tabs\n"
                                "- The Gifts list showing chests\n"
                                "- The Bonus Sales store (full-screen store with left sidebar)\n"
                                "- Normal game UI\n\n"
                                "If there IS a modal popup, look for a VISIBLE X button (usually top-right corner).\n"
                                "IMPORTANT: Only return x_button_coords if you can clearly see an X button.\n"
                                "If the popup has no visible X button, return null for x_button_coords.\n\n"
                                "Reply ONLY with JSON (no markdown):\n"
                                "{\"has_popup\": true/false, \"description\": \"what you see\", "
                                "\"x_button_coords\": {\"x\": number, \"y\": number} or null}"
                            ),
                        },
                    ],
                }],
            )

            text = response.content[0].text.strip()
            # Clean up markdown formatting if present
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]

            import json
            result = json.loads(text.strip())
            log.info(f"Popup detection: has_popup={result.get('has_popup')}, "
                    f"coords={result.get('x_button_coords')}, "
                    f"desc={result.get('description', 'unknown')}")
            return result

        except Exception as e:
            log.warning(f"Popup detection failed: {e}")
            # On error, assume no popup to avoid blind clicking
            return {"has_popup": False, "description": f"detection error: {e}"}

    async def _click_bonus_sales_x(self):
        """Close the Bonus Sales store by clicking the X button.

        The X button is at the far right edge of the screen, around x=1270.
        """
        log.info("Closing Bonus Sales store by clicking X button...")

        # Check if page is still alive before trying to interact
        try:
            _ = self.page.url
        except Exception as e:
            log.error(f"Page is no longer available: {e}")
            return

        # X button is at (1256, 67) - confirmed by Vision API
        x_coords = [
            (1256, 67),   # Primary target - Vision API confirmed
            (1254, 65),   # Slightly left/up
            (1258, 69),   # Slightly right/down
        ]

        try:
            for x, y in x_coords:
                log.info(f"Clicking X at ({x}, {y})...")
                await self.page.mouse.click(x, y)
                await asyncio.sleep(0.5)
        except Exception as e:
            log.warning(f"Error clicking X: {e}")
            return

        # Wait for store to close
        log.info("Waiting for store to close...")
        await asyncio.sleep(2)

        # Try to take screenshot
        try:
            await self._debug_screenshot("after_x_click")
        except Exception as e:
            log.warning(f"Could not capture after_x_click screenshot: {e}")

        log.info("Bonus Sales X click complete.")

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

        Simplified version without Vision verification to avoid API timeouts.
        """
        log.info("Navigating to Clan → Gifts...")

        # First, ensure the game is fully loaded before attempting any navigation
        log.info("Checking if game is fully loaded...")
        for attempt in range(10):  # Max 10 attempts (30 seconds total)
            loading_state = await self._check_loading_state()
            if loading_state.get("loading_complete", False):
                log.info("Game fully loaded, proceeding with navigation.")
                break
            percent = loading_state.get("loading_percent", "unknown")
            log.info(f"Game still loading ({percent}%), waiting... (attempt {attempt + 1}/10)")
            await asyncio.sleep(3)
        else:
            log.warning("Game may not be fully loaded after 30s, proceeding anyway...")

        # Dismiss any popups/stores that might be blocking
        log.info("Clearing any blocking UI...")
        await self._dismiss_popups()
        await asyncio.sleep(2)

        # Take a screenshot to see current state
        await self._debug_screenshot("before_clan_click")

        clan_btn = self._get_coords("main_game", "bottom_nav_clan")
        log.info(f"Clicking CLAN at ({clan_btn['x']}, {clan_btn['y']})")
        await self.page.mouse.click(clan_btn["x"], clan_btn["y"])
        await asyncio.sleep(4)

        # Take screenshot after clan click
        await self._debug_screenshot("after_clan_click")

        gifts_btn = self._get_coords("clan_panel", "sidebar_gifts")
        log.info(f"Clicking Gifts at ({gifts_btn['x']}, {gifts_btn['y']})")
        await self.page.mouse.click(gifts_btn["x"], gifts_btn["y"])
        await asyncio.sleep(3)

        # Dismiss any modal popups that appeared after navigation (payment offers, etc.)
        # Uses Vision-based detection - only clicks if a popup is actually present
        log.info("Checking for popups after navigation...")
        await self._dismiss_modal_popups()
        await asyncio.sleep(1)

        # Take screenshot to show gifts view
        await self._debug_screenshot("gifts_view")

        log.info("Gifts tab navigation complete.")

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

    # ── Open-and-collect approach ───────────────────────────────────────

    async def click_open_first_gift(self) -> bool:
        """Click the 'Open' button on the first (topmost) gift in the list.

        Returns:
            True if we clicked something, False if no Open button found.
        """
        open_btn = self._get_coords_or_none("gifts_view", "first_gift_open_button")

        if not open_btn:
            # Try to locate it dynamically from current screenshot
            log.info("Open button not calibrated — locating from current screen...")
            open_btn = await self._recalibrate("gifts_view", "first_gift_open_button")

        if not open_btn:
            log.warning("Could not find Open button on first gift.")
            return False

        log.debug(f"Clicking Open at ({open_btn['x']}, {open_btn['y']})")
        await self.page.mouse.click(open_btn["x"], open_btn["y"])
        await asyncio.sleep(0.05)  # Minimal pause for click to register
        return True

    async def dismiss_reward_popup(self):
        """Wait for the reward popup to fade, then continue.

        The reward popup shows what you got but doesn't block interaction.
        We can click through it to open the next gift.
        """
        # Minimal pause - we can click through the reward popup
        await asyncio.sleep(0.15)
        log.debug("Brief pause for reward popup.")

    async def recalibrate_open_button(self):
        """Re-locate the Open button after the gift list shifts.

        After opening a gift, the next gift slides into the top position.
        The Open button should be in roughly the same spot, but we
        recalibrate periodically to stay accurate.
        """
        coords = await self._recalibrate("gifts_view", "first_gift_open_button")
        return coords

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
        try:
            await self.page.screenshot(path=str(fpath), full_page=False, timeout=60000)
            log.info(f"Debug screenshot saved: {fpath}")
        except Exception as e:
            log.warning(f"Debug screenshot failed ({name}): {e}")
            return ""

        # Upload to Azure Blob Storage if in cloud mode
        if self.config.get("_cloud_mode") and self.config.get("_blob_conn"):
            try:
                import os
                try:
                    from azure.storage.blob import BlobServiceClient
                except ImportError as ie:
                    log.warning(f"Azure storage not available: {ie}")
                    return str(fpath)

                client = BlobServiceClient.from_connection_string(self.config["_blob_conn"])
                container_name = "scanner-screenshots"
                container = client.get_container_client(container_name)

                # Ensure container exists
                try:
                    container.create_container(public_access="blob")
                except:
                    pass  # Container already exists

                # Create blob name with debug context
                clan_id = self.config.get("_clan_id", "unknown")
                run_id = self.config.get("_run_id", 0)
                blob_name = f"{clan_id}/run_{run_id}/debug/{name}_{ts}.png"

                # Upload the screenshot
                with open(fpath, "rb") as data:
                    container.upload_blob(blob_name, data, overwrite=True)

                url = f"https://{client.account_name}.blob.core.windows.net/{container_name}/{blob_name}"
                log.info(f"Debug screenshot uploaded: {url}")
                return str(fpath)
            except ImportError as ie:
                log.warning(f"Azure storage module not available: {ie}")
            except Exception as e:
                log.warning(f"Debug screenshot upload failed: {e}")

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
                await asyncio.sleep(0.1)

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

    # ── Vision-based State Detection ─────────────────────────────────────

    async def _identify_screen_state(self, screenshot_path: str) -> dict:
        """Use Claude Vision to identify what screen/state we're on.

        Returns:
            {
                "state": "login" | "loading" | "bonus_sales_loading" | "bonus_sales_loaded" | "store" | "main_game" | "unknown",
                "description": str,
                "progress_changed": bool (for loading state)
            }
        """
        import base64
        try:
            import anthropic
        except ImportError:
            return {"state": "unknown", "description": "anthropic not available"}

        api_key = self.config["vision"]["anthropic_api_key"]
        model = self.config["vision"].get("model_routine", "claude-haiku-4-5-20251001")

        with open(screenshot_path, "rb") as f:
            image_data = base64.standard_b64encode(f.read()).decode("utf-8")

        # Use 30-second timeout to prevent long waits that cause game session timeouts
        client = anthropic.Anthropic(api_key=api_key, timeout=30.0)

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
                                "Identify this Total Battle game screen. What state is it in?\n\n"
                                "States:\n"
                                "- 'login': Shows email/password input fields\n"
                                "- 'loading': Shows 'TOTAL BATTLE' splash with castle, may have loading bar at bottom\n"
                                "- 'bonus_sales_loading': Shows Bonus Sales store BUT has a progress bar at the TOP (around y=100, runs from x=330 to x=950). Shows percentage like '45%'. CANNOT click X button yet!\n"
                                "- 'bonus_sales_loaded': Shows Bonus Sales store with NO progress bar at top - store is fully loaded and ready to close\n"
                                "- 'store': Any other store/shop popup with items for purchase\n"
                                "- 'main_game': Normal game view - city/map visible, bottom nav bar with icons, NO store overlay\n"
                                "- 'unknown': Can't identify\n\n"
                                "IMPORTANT: For Bonus Sales, look carefully at the TOP of the store panel for a loading progress bar. "
                                "If there's a bar with percentage (e.g., '67%'), it's 'bonus_sales_loading'. "
                                "If the top is clear with no progress bar, it's 'bonus_sales_loaded'.\n\n"
                                "Reply ONLY with JSON: "
                                "{\"state\": \"one of the states above\", \"description\": \"brief description\", "
                                "\"loading_percent\": number or null}"
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

            # Track loading progress changes
            loading_pct = result.get("loading_percent")
            if hasattr(self, "_last_loading_pct"):
                result["progress_changed"] = (loading_pct != self._last_loading_pct)
            else:
                result["progress_changed"] = True
            self._last_loading_pct = loading_pct

            return result

        except Exception as e:
            log.warning(f"Screen state identification failed: {e}")
            return {"state": "unknown", "description": f"error: {e}"}

    async def _detect_screen_change(self, prev_path: str, curr_path: str) -> bool:
        """Use Claude Vision to detect if there's a meaningful change between two screenshots.

        Args:
            prev_path: Path to the previous screenshot
            curr_path: Path to the current screenshot

        Returns:
            True if there's a meaningful change (loading progress, new UI, etc.)
            False if screens look the same
        """
        import base64
        try:
            import anthropic
        except ImportError:
            log.warning("anthropic not available, assuming change")
            return True

        api_key = self.config["vision"]["anthropic_api_key"]
        model = self.config["vision"].get("model_routine", "claude-haiku-4-5-20251001")

        with open(prev_path, "rb") as f:
            prev_data = base64.standard_b64encode(f.read()).decode("utf-8")
        with open(curr_path, "rb") as f:
            curr_data = base64.standard_b64encode(f.read()).decode("utf-8")

        client = anthropic.Anthropic(api_key=api_key)

        try:
            response = client.messages.create(
                model=model,
                max_tokens=200,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Compare these two game screenshots. Is there ANY meaningful change between them?",
                        },
                        {
                            "type": "text",
                            "text": "PREVIOUS screenshot:",
                        },
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": prev_data,
                            },
                        },
                        {
                            "type": "text",
                            "text": "CURRENT screenshot:",
                        },
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": curr_data,
                            },
                        },
                        {
                            "type": "text",
                            "text": (
                                "Look for ANY change:\n"
                                "- Loading bar progress (even 1% change)\n"
                                "- Different screen/UI appearing\n"
                                "- Popup appearing or disappearing\n"
                                "- Any animation or movement\n"
                                "- Text changes\n\n"
                                "Reply ONLY with JSON: {\"changed\": true/false, \"description\": \"brief description\"}"
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
            changed = result.get("changed", False)
            desc = result.get("description", "unknown")
            log.info(f"Change detection: changed={changed}, desc={desc}")
            return changed

        except Exception as e:
            log.warning(f"Change detection failed: {e}")
            # On error, assume change to keep waiting
            return True

    async def _check_loading_state(self) -> dict:
        """Use Claude Vision to check if the game has finished loading.

        Returns:
            {"loading_complete": bool, "description": str, "loading_percent": int|None}
        """
        import base64
        try:
            import anthropic
        except ImportError:
            return {"loading_complete": True, "description": "anthropic not available"}

        ss_path = await self._debug_screenshot("loading_check")

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
                                "This is a screenshot from the game Total Battle. "
                                "I need to know if the game has FULLY LOADED to the playable state.\n\n"
                                "The game is STILL LOADING if:\n"
                                "- You see the 'TOTAL BATTLE' splash screen with the castle\n"
                                "- There is any loading text or percentage at the bottom\n"
                                "- The screen shows a cinematic castle view (not gameplay UI)\n\n"
                                "The game is FULLY LOADED when:\n"
                                "- You see the actual GAME UI (bottom navigation bar with icons)\n"
                                "- You see the city/map view with interactive elements\n"
                                "- You see popup dialogs like 'Bonus Sales' (game loaded but popup showing)\n"
                                "- There is NO 'TOTAL BATTLE' splash logo visible\n\n"
                                "Reply ONLY with JSON (no markdown): "
                                "{\"loading_complete\": true/false, \"description\": \"brief description\", "
                                "\"loading_percent\": number or null if no loading bar visible}"
                            ),
                        },
                    ],
                }],
            )

            text = response.content[0].text.strip()
            # Clean up markdown formatting if present
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]

            import json
            result = json.loads(text.strip())
            log.info(f"Loading check: complete={result.get('loading_complete')}, "
                    f"percent={result.get('loading_percent')}, "
                    f"desc={result.get('description', 'unknown')}")
            return result

        except Exception as e:
            log.warning(f"Loading state check failed: {e}")
            # On error, assume not complete to be safe
            return {"loading_complete": False, "description": f"check error: {e}"}

    async def _check_popup_state(self) -> dict:
        """Use Claude Vision to check if popups/stores have been dismissed.

        Returns:
            {"popup_dismissed": bool, "description": str, "popup_type": str|None}
        """
        import base64
        try:
            import anthropic
        except ImportError:
            return {"popup_dismissed": True, "description": "anthropic not available"}

        ss_path = await self._debug_screenshot("popup_check")

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
                                "This is a screenshot from the game Total Battle. "
                                "I need to know if we are on the MAIN GAME VIEW (not in a store/shop).\n\n"
                                "We are NOT on main game view if we see:\n"
                                "- 'Bonus Sales' store screen (showing items for sale, prices in USD, left sidebar with menu)\n"
                                "- Any store or shop interface with items and prices\n"
                                "- A popup with purchase options\n\n"
                                "We ARE on main game view when:\n"
                                "- We can see the game loading screen with 'TOTAL BATTLE' logo and castle (this IS main game)\n"
                                "- We can see the game map with buildings/terrain\n"
                                "- We can see a castle/city view without store UI overlay\n"
                                "- There is NO store sidebar visible on the left with categories like Limited/Featured/Battles\n\n"
                                "IMPORTANT: The loading screen showing the castle with 'TOTAL BATTLE' text "
                                "IS the main game view - return popup_dismissed: true for this.\n\n"
                                "Reply ONLY with JSON (no markdown): "
                                "{\"popup_dismissed\": true/false, \"description\": \"brief description\", "
                                "\"popup_type\": \"type of popup/store\" or null if main game view}"
                            ),
                        },
                    ],
                }],
            )

            text = response.content[0].text.strip()
            # Clean up markdown formatting if present
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]

            import json
            result = json.loads(text.strip())
            log.info(f"Popup check: dismissed={result.get('popup_dismissed')}, "
                    f"type={result.get('popup_type')}, "
                    f"desc={result.get('description', 'unknown')}")
            return result

        except Exception as e:
            log.warning(f"Popup state check failed: {e}")
            # On error, assume not dismissed to trigger retry
            return {"popup_dismissed": False, "description": f"check error: {e}"}