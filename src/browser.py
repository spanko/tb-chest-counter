"""Playwright browser session for Total Battle.

Handles login and navigation using Vision-calibrated coordinates.
Run `python main.py calibrate` to generate or update the calibration profile.
"""

import asyncio
import json
import logging
from pathlib import Path
from datetime import datetime

from playwright.async_api import async_playwright, Page, Browser

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent


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

        # Wait for game to fully load (Bonus Sales store to appear)
        log.info("Waiting for game to fully load (30 seconds)...")
        await asyncio.sleep(30)

        # Dismiss popups with ESC
        await self._dismiss_popups()

        log.info("Login check complete.")

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


    async def navigate_to_gifts(self):
        """Navigate to Clan → Gifts tab using calibrated coordinates."""
        log.info("Navigating to Clan → Gifts...")

        # Close Bonus Sales store if it's open (clicks X at top-right)
        log.info("Closing any store overlays...")
        await self._click_bonus_sales_x()
        await asyncio.sleep(2)

        # Dismiss any other popups
        await self._dismiss_popups()
        await asyncio.sleep(1)

        clan_btn = self._get_coords("main_game", "bottom_nav_clan")
        log.info(f"Clicking CLAN at ({clan_btn['x']}, {clan_btn['y']})")
        await self.page.mouse.click(clan_btn["x"], clan_btn["y"])
        await asyncio.sleep(4)

        gifts_btn = self._get_coords("clan_panel", "sidebar_gifts")
        log.info(f"Clicking Gifts at ({gifts_btn['x']}, {gifts_btn['y']})")
        await self.page.mouse.click(gifts_btn["x"], gifts_btn["y"])
        await asyncio.sleep(3)

        # Dismiss any modal popups that appeared after navigation
        await self._dismiss_modal_popups()
        await asyncio.sleep(2)  # Wait for popup animation to fully clear

        log.info("Gifts tab navigation complete.")




    async def _debug_screenshot(self, name: str) -> str:
        """Take a debug screenshot with a specific name."""
        ss_dir = ROOT / self.config["storage"]["screenshot_dir"] / "debug"
        ss_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fpath = ss_dir / f"debug_{name}_{ts}.png"
        try:
            await self.page.screenshot(path=str(fpath), full_page=False, timeout=60000)
            log.debug(f"Debug screenshot: {fpath}")
        except Exception as e:
            log.warning(f"Debug screenshot failed ({name}): {e}")
            return ""
        return str(fpath)


