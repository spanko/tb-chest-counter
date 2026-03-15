"""Helper script to find and calibrate the scrollbar position."""

import asyncio
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import sys

async def find_scrollbar_coordinates():
    """Take a screenshot and add coordinate grid overlay."""
    # Import after we know we're in the right directory
    from browser import TBBrowser
    import json

    # Load config
    ROOT = Path(__file__).resolve().parent.parent
    CONFIG_PATH = ROOT / "config" / "settings.json"

    with open(CONFIG_PATH) as f:
        config = json.load(f)

    print("Opening browser and navigating to gifts page...")
    print("This will take about 45 seconds...")

    async with TBBrowser(config, headless=False) as browser:
        await browser.login()
        await browser.navigate_to_gifts()

        print("\nTaking screenshot...")
        screenshot_path = await browser.capture_screenshot("scrollbar_grid")
        print(f"Screenshot saved to: {screenshot_path}")

        # Open the image and add grid overlay
        img = Image.open(screenshot_path)
        draw = ImageDraw.Draw(img)
        width, height = img.size

        # Draw vertical lines every 50 pixels with labels
        for x in range(0, width + 1, 50):
            # Main grid lines every 100px
            if x % 100 == 0:
                draw.line([(x, 0), (x, height)], fill=(255, 0, 0, 128), width=2)
                # Add x coordinate label
                draw.text((x + 2, 10), str(x), fill=(255, 255, 0))
            else:
                draw.line([(x, 0), (x, height)], fill=(128, 128, 128, 64), width=1)

        # Draw horizontal lines every 50 pixels with labels
        for y in range(0, height + 1, 50):
            # Main grid lines every 100px
            if y % 100 == 0:
                draw.line([(0, y), (width, y)], fill=(255, 0, 0, 128), width=2)
                # Add y coordinate label
                draw.text((10, y + 2), str(y), fill=(255, 255, 0))
            else:
                draw.line([(0, y), (width, y)], fill=(128, 128, 128, 64), width=1)

        # Highlight key regions
        # Gift list area (approximate)
        draw.rectangle([(350, 250), (850, 550)], outline=(0, 255, 0), width=3)
        draw.text((355, 255), "GIFT LIST AREA", fill=(0, 255, 0))

        # Scrollbar area (approximate - right side)
        draw.rectangle([(850, 250), (950, 550)], outline=(0, 0, 255), width=3)
        draw.text((855, 255), "SCROLLBAR?", fill=(0, 0, 255))

        # Save grid image
        grid_path = str(Path(screenshot_path).parent / "scrollbar_grid_overlay.png")
        img.save(grid_path)
        print(f"\nGrid overlay saved to: {grid_path}")

        print("\n" + "="*60)
        print("COORDINATE GRID REFERENCE")
        print("="*60)
        print("The image has been saved with a coordinate grid overlay.")
        print("- Red lines mark 100-pixel intervals")
        print("- Gray lines mark 50-pixel intervals")
        print("- Green box shows approximate gift list area")
        print("- Blue box shows where scrollbar might be")
        print("\nPlease look at the image and identify:")
        print("1. The exact X coordinate of the scrollbar")
        print("2. The Y range where the scrollbar track is visible")
        print("3. The position of the scrollbar handle/thumb")
        print("\nYou can use the grid coordinates to tell me exactly where")
        print("the scrollbar elements are located.")
        print("="*60)

        return grid_path

if __name__ == "__main__":
    result = asyncio.run(find_scrollbar_coordinates())
    print(f"\nDone! Check the image at: {result}")