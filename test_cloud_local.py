#!/usr/bin/env python3
"""Test cloud-like behavior locally with visible browser."""
import asyncio
import sys
sys.path.insert(0, 'src')
from config import load_config
from browser import TBBrowser

async def test():
    config = load_config()
    config['_cloud_mode'] = True  # Simulate cloud mode

    async with TBBrowser(config, headless=False) as browser:
        # This will clear cookies like cloud mode does
        print('Clearing cookies...')
        await browser.context.clear_cookies()
        for page in browser.context.pages:
            try:
                await page.evaluate('() => { localStorage.clear(); sessionStorage.clear(); }')
                print('Cleared localStorage/sessionStorage')
            except Exception as e:
                print(f'Could not clear storage: {e}')

        print('Starting login...')
        await browser.login()
        print('Done!')

if __name__ == '__main__':
    asyncio.run(test())
