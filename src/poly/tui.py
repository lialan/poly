#!/usr/bin/env python3
"""Polymarket Trading Platform - TUI Launcher.

A centralized text user interface for launching project scripts.
Automatically discovers scripts and categorizes them into:
- Trading: Trading bots and strategies
- Tests: Test scripts and benchmarks
- Simulations: Backtesting and simulation scripts

Usage:
    poly-tui
"""

import os
import subprocess
import sys
from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Label,
    ListItem,
    ListView,
    Static,
    TabbedContent,
    TabPane,
)

from poly.script_discovery import (
    CATEGORIES,
    ScriptInfo,
    discover_scripts,
    format_script_help,
    get_scripts_by_category,
)


class ScriptItem(ListItem):
    """A list item representing a script."""

    def __init__(self, script: ScriptInfo) -> None:
        super().__init__()
        self.script = script

    def compose(self) -> ComposeResult:
        yield Static(f"[bold]{self.script.name}[/bold]", classes="script-name")
        yield Static(
            f"[dim]{self.script.short_description}[/dim]",
            classes="script-desc",
        )


class ScriptDetailScreen(ModalScreen[bool]):
    """Modal screen showing script details."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("enter", "run", "Run Script"),
    ]

    def __init__(self, script: ScriptInfo) -> None:
        super().__init__()
        self.script = script

    def compose(self) -> ComposeResult:
        with Container(id="detail-dialog"):
            yield Static(format_script_help(self.script), id="detail-content")
            with Horizontal(id="detail-buttons"):
                yield Button("Run", variant="primary", id="run-btn")
                yield Button("Close", variant="default", id="close-btn")

    @on(Button.Pressed, "#run-btn")
    def run_script(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#close-btn")
    def close_dialog(self) -> None:
        self.dismiss(False)

    def action_dismiss(self) -> None:
        self.dismiss(False)

    def action_run(self) -> None:
        self.dismiss(True)


class ScriptList(ListView):
    """List view for scripts."""

    def __init__(self, scripts: list[ScriptInfo], **kwargs) -> None:
        super().__init__(**kwargs)
        self.scripts = scripts

    def compose(self) -> ComposeResult:
        for script in self.scripts:
            yield ScriptItem(script)

    def get_selected_script(self) -> ScriptInfo | None:
        """Get the currently selected script."""
        if self.highlighted_child is not None:
            item = self.highlighted_child
            if isinstance(item, ScriptItem):
                return item.script
        return None


class PolyTUI(App):
    """Polymarket Trading Platform TUI Launcher."""

    CSS = """
    Screen {
        background: $surface;
    }

    #main-container {
        height: 100%;
        padding: 1;
    }

    TabbedContent {
        height: 100%;
    }

    TabPane {
        padding: 0 1;
    }

    ScriptList {
        height: 100%;
        border: solid $primary;
    }

    ScriptItem {
        padding: 0 1;
        height: 3;
    }

    ScriptItem:hover {
        background: $boost;
    }

    ScriptItem.-highlight {
        background: $accent;
    }

    .script-name {
        height: 1;
    }

    .script-desc {
        height: 1;
        color: $text-muted;
    }

    #empty-message {
        padding: 2;
        text-align: center;
        color: $text-muted;
    }

    #detail-dialog {
        width: 80%;
        height: 80%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #detail-content {
        height: 1fr;
        overflow-y: auto;
    }

    #detail-buttons {
        height: 3;
        align: center middle;
        padding-top: 1;
    }

    #detail-buttons Button {
        margin: 0 1;
    }

    #status-bar {
        dock: bottom;
        height: 1;
        padding: 0 1;
        background: $primary-background;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("enter", "run_script", "Run"),
        Binding("space", "show_details", "Details"),
        Binding("1", "tab_trading", "Trading", show=False),
        Binding("2", "tab_tests", "Tests", show=False),
        Binding("3", "tab_simulations", "Simulations", show=False),
        Binding("4", "tab_all", "All", show=False),
    ]

    TITLE = "Polymarket Trading Platform"
    SUB_TITLE = "Script Launcher"

    def __init__(self) -> None:
        super().__init__()
        self.scripts_by_category: dict[str, list[ScriptInfo]] = {}
        self.all_scripts: list[ScriptInfo] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="main-container"):
            with TabbedContent():
                with TabPane("Trading", id="tab-trading"):
                    yield self._create_script_list("trading")
                with TabPane("Tests", id="tab-tests"):
                    yield self._create_script_list("test")
                with TabPane("Simulations", id="tab-simulations"):
                    yield self._create_script_list("simulation")
                with TabPane("All", id="tab-all"):
                    yield self._create_script_list(None)
        yield Static("", id="status-bar")
        yield Footer()

    def _create_script_list(self, category: str | None) -> ScriptList | Static:
        """Create a script list for a category."""
        if category:
            scripts = self.scripts_by_category.get(category, [])
        else:
            scripts = self.all_scripts

        if not scripts:
            return Static(
                f"No {category or ''} scripts found.",
                id="empty-message",
            )

        return ScriptList(scripts, id=f"list-{category or 'all'}")

    def on_mount(self) -> None:
        """Load scripts on mount."""
        self._load_scripts()

    def _load_scripts(self) -> None:
        """Load and categorize scripts."""
        self.all_scripts = discover_scripts()
        self.scripts_by_category = get_scripts_by_category()
        self._update_status(f"Loaded {len(self.all_scripts)} scripts")

    def _update_status(self, message: str) -> None:
        """Update status bar message."""
        status = self.query_one("#status-bar", Static)
        status.update(f"[dim]{message}[/dim]")

    def _get_current_list(self) -> ScriptList | None:
        """Get the currently visible script list."""
        tabbed = self.query_one(TabbedContent)
        active_tab = tabbed.active
        if active_tab:
            try:
                return self.query_one(f"#{active_tab} ScriptList", ScriptList)
            except Exception:
                return None
        return None

    def _get_selected_script(self) -> ScriptInfo | None:
        """Get currently selected script."""
        script_list = self._get_current_list()
        if script_list:
            return script_list.get_selected_script()
        return None

    async def action_run_script(self) -> None:
        """Run the selected script."""
        script = self._get_selected_script()
        if script:
            await self._execute_script(script)

    async def action_show_details(self) -> None:
        """Show details for selected script."""
        script = self._get_selected_script()
        if script:
            should_run = await self.push_screen_wait(ScriptDetailScreen(script))
            if should_run:
                await self._execute_script(script)

    async def _execute_script(self, script: ScriptInfo) -> None:
        """Execute a script, suspending the TUI."""
        self._update_status(f"Running {script.name}...")

        # Suspend TUI and run script
        with self.suspend():
            print(f"\n{'=' * 60}")
            print(f"  Running: {script.name}")
            print(f"{'=' * 60}\n")

            project_root = Path(__file__).parent.parent.parent

            try:
                result = subprocess.run(
                    [sys.executable, str(script.path)],
                    cwd=project_root,
                )

                print(f"\n{'=' * 60}")
                if result.returncode == 0:
                    print(f"  Script completed successfully")
                else:
                    print(f"  Script exited with code {result.returncode}")
                print(f"{'=' * 60}")

            except KeyboardInterrupt:
                print(f"\n  Script interrupted by user")

            print("\nPress Enter to return to TUI...")
            try:
                input()
            except EOFError:
                pass

        self._update_status(f"Returned from {script.name}")

    def action_refresh(self) -> None:
        """Refresh script list."""
        self._load_scripts()
        self._update_status("Scripts refreshed")

    def action_tab_trading(self) -> None:
        """Switch to trading tab."""
        self.query_one(TabbedContent).active = "tab-trading"

    def action_tab_tests(self) -> None:
        """Switch to tests tab."""
        self.query_one(TabbedContent).active = "tab-tests"

    def action_tab_simulations(self) -> None:
        """Switch to simulations tab."""
        self.query_one(TabbedContent).active = "tab-simulations"

    def action_tab_all(self) -> None:
        """Switch to all tab."""
        self.query_one(TabbedContent).active = "tab-all"


def main():
    """Run the TUI application."""
    app = PolyTUI()
    app.run()


if __name__ == "__main__":
    main()
