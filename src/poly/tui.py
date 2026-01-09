#!/usr/bin/env python3
"""Polymarket Trading Platform - TUI Launcher.

A simple terminal menu for launching project scripts.
Uses simple-term-menu for reliable cross-platform support.

Usage:
    poly-tui
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from simple_term_menu import TerminalMenu

from poly.script_discovery import (
    CATEGORIES,
    ScriptInfo,
    discover_scripts,
    get_scripts_by_category,
)

# Cached status to avoid slow Bigtable queries on every menu draw
_cached_status: Optional[str] = None


def get_collection_status(refresh: bool = False) -> Optional[str]:
    """Get Bigtable collection status summary (cached).

    Args:
        refresh: If True, force refresh from Bigtable.

    Returns status string or None.
    """
    global _cached_status

    if not refresh and _cached_status is not None:
        return _cached_status

    if not refresh:
        return None  # Don't query on first load

    try:
        from poly.bigtable_status import check_collection_status
        status = check_collection_status()

        parts = []
        for t in status.tables:
            name = t.table_name.replace("_snapshot", "")
            parts.append(f"{name}:{t.status_emoji}")

        _cached_status = " | ".join(parts)
        return _cached_status
    except Exception as e:
        _cached_status = f"Error: {str(e)[:30]}"
        return _cached_status


def clear_screen():
    """Clear terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")


# Script-specific option hints
SCRIPT_OPTIONS = {
    "trading_backtest.py": """
  Options:
    -a, --asset btc|eth     Asset to trade (default: btc)
    -t, --hours-ago N       Hours of history (default: 6)
    -c, --capital N         Initial capital USD (default: 100)
    -b, --bet-size N        Bet size USD (default: 10)
    -p, --profit-target N   Profit target ratio (default: 0.25)
    -m, --min-mispricing N  Min mispricing to trade (default: 0.05)
    -i, --trade-interval N  Seconds between trades (default: 60)
    -q, --quiet             Suppress trade-by-trade output

  Examples:
    -t 12 -q                12 hours, quiet mode
    -a eth -t 24            ETH, 24 hours
    -c 1000 -b 50 -t 12     $1000 capital, $50 bets""",

    "btc_15m_backtest.py": """
  Options: (none - runs with all available data)""",

    "query_btc_15m_extremes.py": """
  Options:
    -t, --threshold N       Threshold % (default: 10)
                            High = 100-N, Low = N

  Examples:
    (no args)               90% high / 10% low thresholds
    -t 15                   85% high / 15% low thresholds
    -t 20                   80% high / 20% low thresholds""",

    "run_trading_bot.py": """
  Options:
    --asset btc|eth         Asset to trade (default: btc)
    --interval N            Decision interval seconds (default: 3)""",

    "trade_dry_run.py": """
  Options:
    --live                  Place real test order (canceled immediately)""",

    "cloudrun_collector.py": """
  Options: (none - runs continuously)""",

    "query_bigtable.py": """
  Options:
    --count N               Number of rows to fetch (default: 10)
    --table NAME            Table name to query""",

    "bet_btc_15m.py": """
  Options:
    -A, --action buy|sell   Action (default: buy)
    -s, --side up|down      Side to trade (required)
    -a, --amount N          Amount in USD (buy only)
    -p, --price N           Limit price (default: best ask/bid)
    -n, --dry-run           Preview order without placing

  Examples:
    -s up -a 10             Buy $10 of UP shares
    -s up -a 10 -p 0.45     Buy at limit price 0.45
    -A sell -s up           Sell all UP shares
    -A sell -s down -p 0.55 Sell DOWN at limit""",

    "approve_usdc.py": """
  Options:
    -a, --amount N          Amount to approve (default: unlimited)
    -r, --revoke            Revoke approval (set to 0)
    -n, --dry-run           Preview transaction without sending

  Examples:
    (no args)               Approve unlimited USDC
    --amount 100            Approve $100 USDC
    --revoke                Revoke approval""",

    "redeem_positions.py": """
  Options:
    -n, --dry-run           List positions without redeeming
    -c, --condition ID      Redeem specific condition ID only

  Examples:
    --dry-run               List redeemable positions
    (no args)               Redeem all resolved positions""",

    "generate_rolling_klines.py": """
  Options:
    -w, --window N          Rolling window size in minutes (default: 3)
    --symbol SYMBOL         Trading pair symbol (default: BTCUSDT)
    --input PATH            Input database path (default: binance_klines.db)
    --output PATH           Output database path (auto-generated)

  Examples:
    (no args)               Generate 3-minute rolling klines
    -w 5                    Generate 5-minute rolling klines
    -w 15 --symbol ETHUSDT  15-minute klines for ETH""",

    "kline_volatility_stats.py": """
  Options:
    -w, --window N          Rolling window in minutes (default: 3)
    -s, --symbol SYMBOL     Trading pair symbol (default: BTCUSDT)
    --db PATH               Database path (default: binance_klines.db)

  Examples:
    (no args)               3-minute volatility stats
    -w 5                    5-minute volatility stats
    -w 15                   15-minute volatility stats
    -s ETHUSDT -w 5         ETH 5-minute stats""",

    "download_binance_klines.py": """
  Options:
    -d, --days N            Target days of history (default: 10)
    -s, --symbol SYMBOL     Trading pair symbol (default: BTCUSDT)
    -i, --interval INT      Kline interval (default: 1m)
    -c, --check             Check for gaps only (no download)
    -f, --force             Force re-download all dates (not incremental)

  Examples:
    (no args)               Incremental update, fill gaps
    -c                      Check coverage and gaps
    -d 100                  Ensure 100 days of history
    -d 1000 -f              Force re-download 1000 days
    -s ETHUSDT -d 30        30 days of ETH data""",
}


def prompt_for_args(script: ScriptInfo) -> list[str]:
    """Prompt user for script arguments.

    Returns empty list immediately if script has no documented options.
    """
    # Only prompt if script has documented options
    options_hint = SCRIPT_OPTIONS.get(script.name)
    if not options_hint:
        return []

    print(options_hint)
    print("\n  Enter arguments (or press Enter for defaults):")
    try:
        args_input = input("  > ").strip()
        if args_input:
            return args_input.split()
    except (EOFError, KeyboardInterrupt):
        pass
    return []


def run_script(script: ScriptInfo, prompt_args: bool = True) -> None:
    """Run a script and wait for user input after."""
    clear_screen()
    print(f"\n{'=' * 60}")
    print(f"  Running: {script.name}")
    print(f"  {script.description}")
    print(f"{'=' * 60}")

    # Prompt for arguments
    extra_args = []
    if prompt_args:
        extra_args = prompt_for_args(script)

    if extra_args:
        print(f"\n  Args: {' '.join(extra_args)}")

    print()

    project_root = Path(__file__).parent.parent.parent

    # Set environment variables for Bigtable and Python path
    env = os.environ.copy()
    env.setdefault("BIGTABLE_PROJECT_ID", "poly-collector")
    env.setdefault("BIGTABLE_INSTANCE_ID", "poly-data")
    env["PYTHONPATH"] = str(project_root / "src")

    try:
        cmd = [sys.executable, str(script.path)] + extra_args
        result = subprocess.run(
            cmd,
            cwd=project_root,
            env=env,
        )

        print(f"\n{'=' * 60}")
        if result.returncode == 0:
            print("  Script completed successfully")
        else:
            print(f"  Script exited with code {result.returncode}")
        print(f"{'=' * 60}")

    except KeyboardInterrupt:
        print("\n  Script interrupted by user")

    print("\nPress Enter to return to menu...")
    try:
        input()
    except EOFError:
        pass


def show_category_menu(category: str, scripts: list[ScriptInfo]) -> bool:
    """Show menu for a specific category. Returns False to go back."""
    while True:
        clear_screen()
        print(f"\n  {CATEGORIES.get(category, category).upper()}")
        print(f"  {'─' * 40}\n")

        options = [f"{s.name}  ({s.description})" for s in scripts]
        options.append("← Back to main menu")

        menu = TerminalMenu(
            options,
            title="  Select a script to run:\n",
            cursor_index=0,
            menu_cursor_style=("fg_cyan", "bold"),
            menu_highlight_style=("bg_cyan", "fg_black"),
        )

        choice = menu.show()

        if choice is None or choice == len(scripts):
            return True  # Go back

        run_script(scripts[choice])


def show_all_scripts_menu(all_scripts: list[ScriptInfo]) -> bool:
    """Show menu with all scripts. Returns False to go back."""
    while True:
        clear_screen()
        print(f"\n  ALL SCRIPTS")
        print(f"  {'─' * 40}\n")

        options = [f"{s.name}  ({s.description})" for s in all_scripts]
        options.append("← Back to main menu")

        menu = TerminalMenu(
            options,
            title="  Select a script to run:\n",
            cursor_index=0,
            menu_cursor_style=("fg_cyan", "bold"),
            menu_highlight_style=("bg_cyan", "fg_black"),
        )

        choice = menu.show()

        if choice is None or choice == len(all_scripts):
            return True

        run_script(all_scripts[choice])


def main():
    """Run the TUI application."""
    all_scripts = discover_scripts()
    by_category = get_scripts_by_category()

    while True:
        clear_screen()
        print("\n  POLYMARKET TRADING PLATFORM")
        print("  Script Launcher")
        print(f"  {'─' * 50}")

        # Show collection status (cached, use Refresh Status to update)
        status = get_collection_status()
        if status:
            print(f"  Status: {status}")
        else:
            print("  Status: (select 'Refresh Status' to check)")
        print(f"  {'─' * 50}")

        print(f"  {len(all_scripts)} scripts available\n")

        # Build main menu options
        main_options = []
        category_order = ["trading", "manual_trade", "query", "backtest", "test", "simulation", "collector", "utility"]

        for cat in category_order:
            if cat in by_category:
                count = len(by_category[cat])
                label = CATEGORIES.get(cat, cat)
                main_options.append(f"{label} ({count})")

        main_options.append(f"All Scripts ({len(all_scripts)})")
        main_options.append("Refresh Status")
        main_options.append("Quit")

        menu = TerminalMenu(
            main_options,
            title="  Select a category:\n",
            cursor_index=0,
            menu_cursor_style=("fg_cyan", "bold"),
            menu_highlight_style=("bg_cyan", "fg_black"),
        )

        choice = menu.show()

        if choice is None or main_options[choice] == "Quit":
            clear_screen()
            print("Goodbye!")
            break

        # Handle "Refresh Status" - fetch from Bigtable and redraw
        if main_options[choice] == "Refresh Status":
            print("\n  Fetching status from Bigtable...")
            get_collection_status(refresh=True)
            continue

        # Handle "All Scripts"
        if "All Scripts" in main_options[choice]:
            show_all_scripts_menu(all_scripts)
            continue

        # Find which category was selected
        selected_cat = None
        for cat in category_order:
            if cat in by_category:
                label = CATEGORIES.get(cat, cat)
                if main_options[choice].startswith(label):
                    selected_cat = cat
                    break

        if selected_cat and selected_cat in by_category:
            show_category_menu(selected_cat, by_category[selected_cat])


if __name__ == "__main__":
    main()
