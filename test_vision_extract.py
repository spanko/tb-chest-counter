#!/usr/bin/env python3
"""Quick standalone test — extract gifts from a TB screenshot using Claude Vision.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python test_vision_extract.py 05_gifts_tab.png
    python test_vision_extract.py 05_gifts_tab.png --model claude-sonnet-4-5-20250929
    python test_vision_extract.py *.png
"""

import argparse
import base64
import json
import sys
import time
from pathlib import Path

try:
    import anthropic
except ImportError:
    print("Install the Anthropic SDK: pip install anthropic")
    sys.exit(1)

SYSTEM_PROMPT = """You are a precise data extraction assistant for the game Total Battle.
You are looking at screenshots of the Clan Gifts tab, which shows chest gifts
that clan members have earned from crypts, citadels, and other activities.

GIFT ENTRY LAYOUT (each entry is a row with):
- A chest icon on the left with a "Clan" badge
- **Chest type name** in bold (e.g., "Forgotten Chest", "Sand Chest", "Elven Citadel Chest")
- "From: PlayerName" — the clan member who earned it
- "Source: Level X Crypt" or "Source: Level X Citadel" — where it came from
- "Time left: Xh Ym" on the right — countdown until expiry
- A green "Open" button on the far right

PAGE STRUCTURE:
- Top: "Gifts" tab with a red badge showing total count (e.g., "23")
- Middle: List of gift entries (typically 4 visible at once)
- Bottom: "Delete expired chests" link and "Claim chests" button (if visible, this is the last page)

EXTRACTION RULES:
1. Extract EVERY visible gift entry. Do not skip any.
2. Be precise with player names from the "From:" field — they may contain spaces,
   numbers, or unusual capitalization. Do NOT correct unusual spellings.
3. Use the exact chest type name shown in bold.
4. Extract the source (e.g., "Level 10 Crypt", "Level 15 Citadel").
5. Extract the time remaining (e.g., "18h 12m").
6. If the red badge number is visible on the Gifts tab, include it as total_gift_count.
7. Set has_more=false if you can see "Claim chests" or "Delete expired chests" at the bottom.
8. If text is partially obscured or unclear, lower the confidence score.

RESPOND WITH ONLY valid JSON matching this exact schema (no markdown, no backticks):
{
  "gifts": [
    {
      "player_name": "string",
      "chest_type": "string",
      "source": "string or null",
      "time_left": "string or null",
      "quantity": 1,
      "confidence": 1.0
    }
  ],
  "total_gift_count": null,
  "has_more": false,
  "extraction_notes": ""
}"""

USER_PROMPT = "Extract all visible gift/chest entries from this Total Battle Gifts tab screenshot."


def extract(image_path: str, model: str, api_key: str) -> dict:
    """Send screenshot to Claude and get structured extraction."""
    with open(image_path, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")

    # Detect media type
    suffix = Path(image_path).suffix.lower()
    media_type = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(suffix, "image/png")

    client = anthropic.Anthropic(api_key=api_key)

    t0 = time.time()
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_data}},
                {"type": "text", "text": USER_PROMPT},
            ],
        }],
    )
    elapsed = time.time() - t0

    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    result = json.loads(text)

    # Add metadata
    result["_meta"] = {
        "model": model,
        "image": str(image_path),
        "elapsed_seconds": round(elapsed, 2),
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "cost_estimate_usd": round(
            response.usage.input_tokens * (0.001 if "haiku" in model else 0.003) / 1000
            + response.usage.output_tokens * (0.005 if "haiku" in model else 0.015) / 1000,
            5
        ),
    }

    return result


def main():
    parser = argparse.ArgumentParser(description="Test Claude Vision extraction on TB screenshots")
    parser.add_argument("images", nargs="+", help="Screenshot file(s) to process")
    parser.add_argument("--model", default="claude-haiku-4-5-20251001",
                        help="Claude model (default: haiku for cost efficiency)")
    parser.add_argument("--api-key", default=None,
                        help="Anthropic API key (or set ANTHROPIC_API_KEY env var)")
    parser.add_argument("--save", action="store_true",
                        help="Save JSON results to files")
    args = parser.parse_args()

    import os
    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: Set ANTHROPIC_API_KEY env var or pass --api-key")
        sys.exit(1)

    for image_path in args.images:
        if not Path(image_path).exists():
            print(f"SKIP: {image_path} not found")
            continue

        print(f"\n{'='*60}")
        print(f"Processing: {image_path}")
        print(f"Model: {args.model}")
        print(f"{'='*60}")

        try:
            result = extract(image_path, args.model, api_key)
        except json.JSONDecodeError as e:
            print(f"ERROR: Claude returned invalid JSON: {e}")
            continue
        except anthropic.APIError as e:
            print(f"ERROR: API call failed: {e}")
            continue

        # Pretty print results
        meta = result.pop("_meta")
        gifts = result.get("gifts", [])

        print(f"\nExtracted {len(gifts)} gifts in {meta['elapsed_seconds']}s")
        print(f"Tokens: {meta['input_tokens']} in / {meta['output_tokens']} out")
        print(f"Estimated cost: ${meta['cost_estimate_usd']:.5f}")

        if result.get("total_gift_count"):
            print(f"Total gift badge: {result['total_gift_count']}")
        print(f"Has more: {result.get('has_more', '?')}")

        if result.get("extraction_notes"):
            print(f"Notes: {result['extraction_notes']}")

        print(f"\n{'─'*60}")
        for i, g in enumerate(gifts, 1):
            conf = g.get('confidence', 1.0)
            conf_str = f"  ⚠️ {conf:.0%}" if conf < 1.0 else ""
            print(f"  {i}. {g['chest_type']}")
            print(f"     From: {g['player_name']}")
            if g.get('source'):
                print(f"     Source: {g['source']}")
            if g.get('time_left'):
                print(f"     Time left: {g['time_left']}")
            if conf_str:
                print(f"     Confidence: {conf_str}")
            print()

        # Save if requested
        if args.save:
            result["_meta"] = meta
            out_path = Path(image_path).stem + "_extraction.json"
            with open(out_path, "w") as f:
                json.dump(result, f, indent=2)
            print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
