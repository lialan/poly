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


def run_script(script: ScriptInfo) -> None:
    """Run a script and wait for user input after."""
    clear_screen()
    print(f"\n{'=' * 60}")
    print(f"  Running: {script.name}")
    print(f"  {script.description}")
    print(f"{'=' * 60}\n")

    project_root = Path(__file__).parent.parent.parent

    try:
        result = subprocess.run(
            [sys.executable, str(script.path)],
            cwd=project_root,
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
        category_order = ["trading", "test", "simulation", "collector", "utility"]

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
