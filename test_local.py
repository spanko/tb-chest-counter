#!/usr/bin/env python3
"""
Local testing script for TB Chest Counter
Simplifies testing headless vs visible modes without container deployment
"""

import sys
import subprocess
import argparse
from pathlib import Path

def check_playwright():
    """Check if Playwright is installed and install if needed."""
    try:
        import playwright
        print("✓ Playwright is installed")
        return True
    except ImportError:
        print("⚠ Playwright not found. Installing...")
        subprocess.run([sys.executable, "-m", "pip", "install", "playwright"], check=True)
        subprocess.run(["playwright", "install", "chromium"], check=True)
        print("✓ Playwright and Chromium installed")
        return True

def run_test(mode="smoke", headless=True, verbose=False):
    """Run the TB chest counter test."""
    print("\n" + "="*50)
    print(f"Running {mode} test in {'HEADLESS' if headless else 'VISIBLE'} mode")
    print("="*50 + "\n")

    cmd = [sys.executable, "src/main.py", mode]

    if not headless:
        cmd.append("--visible")

    if verbose:
        cmd.append("--verbose")

    print(f"Command: {' '.join(cmd)}\n")

    try:
        result = subprocess.run(cmd, capture_output=False, text=True)

        if result.returncode == 0:
            print(f"\n✓ {mode.capitalize()} test completed successfully!")
        else:
            print(f"\n✗ {mode.capitalize()} test failed with exit code {result.returncode}")

        return result.returncode
    except KeyboardInterrupt:
        print("\n\n⚠ Test interrupted by user")
        return 1
    except Exception as e:
        print(f"\n✗ Error running test: {e}")
        return 1

def main():
    parser = argparse.ArgumentParser(
        description="Test TB Chest Counter locally without container deployment",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python test_local.py              # Run smoke test in headless mode (default)
  python test_local.py --visible    # Run smoke test with browser visible
  python test_local.py --chests     # Run full chest scan in headless mode
  python test_local.py -cv          # Run chest scan visible with verbose logging

Notes:
  - Headless mode simulates the container environment
  - Visible mode helps debug login and navigation issues
  - Smoke test only validates login and navigation (no chest storage)
  - Chest scan performs full scanning and stores results locally
        """
    )

    parser.add_argument("--visible", "-v", action="store_true",
                        help="Show browser window (disable headless mode)")
    parser.add_argument("--chests", "-c", action="store_true",
                        help="Run full chest scan instead of smoke test")
    parser.add_argument("--verbose", "-V", action="store_true",
                        help="Enable verbose logging")

    args = parser.parse_args()

    print("TB Chest Counter - Local Test Runner")
    print("====================================\n")

    # Check Playwright installation
    if not check_playwright():
        return 1

    # Determine mode
    mode = "chests" if args.chests else "smoke"

    # Run the test
    return run_test(mode, headless=not args.visible, verbose=args.verbose)

if __name__ == "__main__":
    sys.exit(main())