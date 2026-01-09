"""Script discovery and categorization for TUI launcher."""

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ScriptInfo:
    """Information about a discovered script."""

    path: Path
    name: str
    category: str  # trading, test, simulation, collector, utility
    description: str  # First line of docstring

    @property
    def display_name(self) -> str:
        """Human-readable name for display."""
        return f"{self.name}: {self.description}"


CATEGORIES = {
    "trading": "Trading Bots",
    "manual_trade": "Manual Trade",
    "query": "Queries",
    "backtest": "Backtest",
    "test": "Tests",
    "simulation": "Simulations",
    "collector": "Collectors",
    "utility": "Utilities",
}


def categorize(filename: str) -> str:
    """Categorize script by naming convention."""
    name = filename.lower()

    # Backtest scripts (historical analysis)
    if any(p in name for p in ["backtest", "extremes"]):
        return "backtest"
    # Simulation scripts
    if any(p in name for p in ["simulation", "simulate"]):
        return "simulation"
    # Manual trade scripts (bet_*.py, approve_*.py, check_balance, redeem_positions, list_orders)
    if name.startswith("bet_") or name.startswith("approve_") or name.startswith("redeem_") or name in ("check_balance.py", "list_orders.py"):
        return "manual_trade"
    # Query scripts (query_*.py) - but not extremes analysis
    if name.startswith("query_") and "extremes" not in name:
        return "query"
    if any(p in name for p in ["_bot", "_trader", "trading", "trade_"]):
        return "trading"
    if name.startswith("test_") or "benchmark" in name:
        return "test"
    if "collector" in name or name.startswith("collect"):
        return "collector"
    return "utility"


def parse_docstring(content: str) -> str:
    """Extract first line of module docstring."""
    try:
        tree = ast.parse(content)
        docstring = ast.get_docstring(tree)
    except SyntaxError:
        return "Unable to parse"

    if not docstring:
        return "No description"

    # First non-empty line
    for line in docstring.strip().split("\n"):
        line = line.strip()
        if line:
            return line[:60] + "..." if len(line) > 60 else line
    return "No description"


def discover_scripts(scripts_dir: Optional[Path] = None) -> list[ScriptInfo]:
    """Discover all Python scripts in the scripts directory."""
    if scripts_dir is None:
        scripts_dir = Path(__file__).parent.parent.parent / "scripts"

    scripts = []

    if not scripts_dir.exists():
        return scripts

    for path in sorted(scripts_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        if path.name == "tui.py":
            continue

        try:
            content = path.read_text()
        except Exception:
            continue

        category = categorize(path.name)
        description = parse_docstring(content)

        scripts.append(
            ScriptInfo(
                path=path,
                name=path.name,
                category=category,
                description=description,
            )
        )

    return scripts


def get_scripts_by_category(
    scripts_dir: Optional[Path] = None,
) -> dict[str, list[ScriptInfo]]:
    """Get scripts organized by category."""
    all_scripts = discover_scripts(scripts_dir)

    by_category: dict[str, list[ScriptInfo]] = {}
    for script in all_scripts:
        if script.category not in by_category:
            by_category[script.category] = []
        by_category[script.category].append(script)

    return by_category
