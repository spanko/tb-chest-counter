#!/usr/bin/env python3
"""Minimal Playwright test — Can we load Total Battle without getting detected?

Usage:
    pip install playwright playwright-stealth
    playwright install chromium
    python test_playwright.py

This launches a VISIBLE browser so you can:
1. See if TB loads at all
2. Log in manually
3. Navigate to Clan → Gifts
4. Screenshots are auto-captured at each stage
"""

import asyncio
import time
from pathlib import Path
from playwright.async_api import async_playwright

# Where to save screenshots
OUT = Path("test_output")
OUT.mkdir(exist_ok=True)

# ── Stealth patches ─────────────────────────────────────────────────────────
# These run before any page JavaScript to mask Playwright's fingerprint

STEALTH_JS = """
() => {
    // 1. Hide webdriver flag
    Object.defineProperty(navigator, 'webdriver', { get: () => false });

    // 2. Fake plugins (headless Chrome has none)
    Object.defineProperty(navigator, 'plugins', {
        get: () => [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
            { name: 'Native Client', filename: 'internal-nacl-plugin' },
        ]
    });

    // 3. Fake languages
    Object.defineProperty(navigator, 'languages', {
        get: () => ['en-US', 'en']
    });

    // 4. Fake platform
    Object.defineProperty(navigator, 'platform', {
        get: () => 'Win32'
    });

    // 5. Fix chrome object (missing in Playwright)
    if (!window.chrome) {
        window.chrome = {
            runtime: {},
            loadTimes: function() {},
            csi: function() {},
            app: {}
        };
    }

    // 6. Fix permissions query
    const origQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : origQuery(parameters)
    );

    // 7. Prevent canvas fingerprint detection of headless
    // (Only needed if they fingerprint — TB probably doesn't)

    console.log('[Stealth] Patches applied');
}
"""


async def main():
    print("=" * 60)
    print("TB Playwright Stealth Test")
    print("=" * 60)
    print()
    print("This will open a Chrome window. You'll need to:")
    print("  1. Watch if the game loads normally")
    print("  2. Log in with your utility account manually")
    print("  3. Navigate to Clan → Gifts tab")
    print("  4. Press Enter in this terminal at each step")
    print()
    print(f"Screenshots will be saved to: {OUT.absolute()}")
    print()

    async with async_playwright() as p:
        # Launch VISIBLE browser with stealth flags
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-infobars",
                "--disable-extensions",
                # Prevent "Chrome is being controlled by automated test software" bar
                "--disable-component-extensions-with-background-pages",
            ],
        )

        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="America/Denver",
        )

        # Apply stealth patches before any page loads
        await context.add_init_script(STEALTH_JS)

        page = await context.new_page()

        # ── Step 1: Load TB ─────────────────────────────────────────────
        print("[Step 1] Loading totalbattle.com...")
        await page.goto("https://totalbattle.com", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(5)

        ss1 = OUT / "01_initial_load.png"
        await page.screenshot(path=str(ss1))
        print(f"  Screenshot: {ss1}")

        # Quick stealth check
        webdriver_flag = await page.evaluate("navigator.webdriver")
        chrome_exists = await page.evaluate("!!window.chrome")
        plugins_count = await page.evaluate("navigator.plugins.length")
        print(f"  Stealth check: webdriver={webdriver_flag}, chrome={chrome_exists}, plugins={plugins_count}")

        input("\n  → Look at the browser. Does the game appear to be loading?\n    Press Enter to continue...\n")

        # ── Step 2: Wait for game load ──────────────────────────────────
        print("[Step 2] Waiting for game to fully load...")

        # Check if a canvas element appears (game renders to canvas)
        try:
            await page.wait_for_selector("canvas", timeout=30000)
            print("  ✅ Canvas element detected — game is rendering")
        except Exception:
            print("  ⚠️  No canvas found after 30s — game may not have loaded")

        await asyncio.sleep(5)
        ss2 = OUT / "02_game_loaded.png"
        await page.screenshot(path=str(ss2))
        print(f"  Screenshot: {ss2}")

        input("\n  → Can you see the game UI? Is there a login prompt?\n    Log in with your utility account now.\n    Press Enter when you're logged in and at the main game screen...\n")

        # ── Step 3: Post-login ──────────────────────────────────────────
        print("[Step 3] Capturing post-login state...")
        ss3 = OUT / "03_logged_in.png"
        await page.screenshot(path=str(ss3))
        print(f"  Screenshot: {ss3}")

        # Check viewport dimensions match what we set
        viewport = await page.evaluate("({w: window.innerWidth, h: window.innerHeight})")
        print(f"  Viewport: {viewport['w']}x{viewport['h']}")

        input("\n  → Navigate to Clan menu (shield icon, bottom bar).\n    Press Enter when the Clan panel is open...\n")

        # ── Step 4: Clan menu ───────────────────────────────────────────
        print("[Step 4] Capturing Clan menu...")
        ss4 = OUT / "04_clan_menu.png"
        await page.screenshot(path=str(ss4))
        print(f"  Screenshot: {ss4}")

        input("\n  → Click on the Gifts tab within the Clan panel.\n    Press Enter when you can see the gift list...\n")

        # ── Step 5: Gifts tab — the money shot ─────────────────────────
        print("[Step 5] Capturing Gifts tab...")
        ss5 = OUT / "05_gifts_tab.png"
        await page.screenshot(path=str(ss5))
        print(f"  Screenshot: {ss5}")

        # Also capture at full resolution for Claude Vision
        ss5_full = OUT / "05_gifts_tab_full.png"
        await page.screenshot(path=str(ss5_full), full_page=False)
        print(f"  Full screenshot: {ss5_full}")

        # Try to get page URL for reference
        url = page.url
        print(f"  Current URL: {url}")

        input("\n  → Scroll down in the gift list if there are more entries.\n    Press Enter to capture another page...\n")

        # ── Step 6: Scrolled gifts ──────────────────────────────────────
        print("[Step 6] Capturing scrolled gifts...")
        ss6 = OUT / "06_gifts_scrolled.png"
        await page.screenshot(path=str(ss6))
        print(f"  Screenshot: {ss6}")

        # ── Done ────────────────────────────────────────────────────────
        print()
        print("=" * 60)
        print("Test complete! Screenshots saved to:")
        for f in sorted(OUT.glob("*.png")):
            size_kb = f.stat().st_size / 1024
            print(f"  {f.name}  ({size_kb:.0f} KB)")
        print()
        print("Next steps:")
        print("  1. Upload 05_gifts_tab.png to our chat")
        print("     → I'll run it through Claude Vision extraction")
        print("  2. If the game loaded normally, Playwright stealth works!")
        print("  3. If bottom nav was missing, we need to investigate further")
        print("=" * 60)

        input("\nPress Enter to close the browser...")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
