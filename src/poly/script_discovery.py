"""Script discovery and categorization for TUI launcher.

Automatically discovers Python scripts in the scripts/ directory,
extracts their docstrings, and categorizes them by naming convention.
"""

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
    usage: Optional[str]  # Usage section from docstring
    has_args: bool  # Whether script uses argparse

    @property
    def display_name(self) -> str:
        """Human-readable name for display."""
        name = self.name.replace(".py", "")
        # Remove common prefixes
        for prefix in ["test_", "run_", "collect_"]:
            if name.startswith(prefix):
                name = name[len(prefix):]
                break
        return name.replace("_", " ").title()

    @property
    def short_description(self) -> str:
        """Truncated description for compact display."""
        if len(self.description) > 60:
            return self.description[:57] + "..."
        return self.description


# Category definitions with display info
CATEGORIES = {
    "trading": {"label": "Trading", "icon": "📈", "order": 1},
    "test": {"label": "Tests", "icon": "🧪", "order": 2},
    "simulation": {"label": "Simulations", "icon": "🎮", "order": 3},
    "collector": {"label": "Collectors", "icon": "📊", "order": 4},
    "utility": {"label": "Utilities", "icon": "🔧", "order": 5},
}


def categorize(filename: str) -> str:
    """Categorize script by naming convention.

    Args:
        filename: Script filename (e.g., "test_api.py")

    Returns:
        Category string: trading, test, simulation, collector, or utility
    """
    name = filename.lower()

    # Trading bots
    if any(p in name for p in ["_bot", "_trader", "trading"]):
        return "trading"

    # Tests
    if name.startswith("test_") or "benchmark" in name:
        return "test"

    # Simulations
    if any(p in name for p in ["simulation", "backtest", "simulate"]):
        return "simulation"

    # Collectors
    if "collector" in name or name.startswith("collect"):
        return "collector"

    # Default
    return "utility"


def parse_docstring(content: str) -> tuple[str, Optional[str]]:
    """Extract description and usage from module docstring.

    Args:
        content: Full file content

    Returns:
        Tuple of (description, usage) where usage may be None
    """
    try:
        tree = ast.parse(content)
        docstring = ast.get_docstring(tree)
    except SyntaxError:
        return "Unable to parse", None

    if not docstring:
        return "No description available", None

    lines = docstring.strip().split("\n")

    # First non-empty line is description
    description = ""
    for line in lines:
        line = line.strip()
        if line:
            description = line
            break

    if not description:
        return "No description available", None

    # Look for Usage section
    usage = None
    usage_pattern = re.compile(r"^Usage:?\s*$", re.IGNORECASE)
    in_usage = False
    usage_lines = []

    for line in lines:
        if usage_pattern.match(line.strip()):
            in_usage = True
            continue
        if in_usage:
            # Stop at next section or empty line after content
            if line.strip() and not line.startswith(" ") and ":" in line:
                break
            usage_lines.append(line)

    if usage_lines:
        usage = "\n".join(usage_lines).strip()

    return description, usage


def has_argparse(content: str) -> bool:
    """Check if script uses argparse.

    Args:
        content: Full file content

    Returns:
        True if script imports or uses argparse
    """
    return "argparse" in content or "ArgumentParser" in content


def discover_scripts(
    scripts_dir: Optional[Path] = None,
    categories: Optional[list[str]] = None,
) -> list[ScriptInfo]:
    """Discover all Python scripts in the scripts directory.

    Args:
        scripts_dir: Path to scripts directory. Defaults to project's scripts/
        categories: Filter to specific categories. None = all categories.

    Returns:
        List of ScriptInfo objects, sorted by category then name
    """
    if scripts_dir is None:
        # Default to project's scripts directory
        scripts_dir = Path(__file__).parent.parent.parent / "scripts"

    scripts = []

    if not scripts_dir.exists():
        return scripts

    for path in sorted(scripts_dir.glob("*.py")):
        # Skip __init__.py and similar
        if path.name.startswith("_"):
            continue

        # Skip the TUI itself
        if path.name == "tui.py":
            continue

        try:
            content = path.read_text()
        except Exception:
            continue

        category = categorize(path.name)

        # Filter by category if specified
        if categories and category not in categories:
            continue

        description, usage = parse_docstring(content)
        uses_args = has_argparse(content)

        scripts.append(
            ScriptInfo(
                path=path,
                name=path.name,
                category=category,
                description=description,
                usage=usage,
                has_args=uses_args,
            )
        )

    # Sort by category order, then by name
    def sort_key(s: ScriptInfo) -> tuple[int, str]:
        cat_order = CATEGORIES.get(s.category, {}).get("order", 99)
        return (cat_order, s.name)

    return sorted(scripts, key=sort_key)


def get_scripts_by_category(
    scripts_dir: Optional[Path] = None,
) -> dict[str, list[ScriptInfo]]:
    """Get scripts organized by category.

    Args:
        scripts_dir: Path to scripts directory

    Returns:
        Dict mapping category name to list of ScriptInfo
    """
    all_scripts = discover_scripts(scripts_dir)

    by_category: dict[str, list[ScriptInfo]] = {}
    for script in all_scripts:
        if script.category not in by_category:
            by_category[script.category] = []
        by_category[script.category].append(script)

    return by_category


def format_script_help(script: ScriptInfo) -> str:
    """Format full help text for a script.

    Args:
        script: ScriptInfo object

    Returns:
        Formatted help string
    """
    lines = [
        f"{'=' * 60}",
        f"  {script.name}",
        f"{'=' * 60}",
        "",
        f"Category: {CATEGORIES.get(script.category, {}).get('label', script.category)}",
        f"Path: {script.path}",
        "",
        "Description:",
        f"  {script.description}",
    ]

    if script.usage:
        lines.extend([
            "",
            "Usage:",
            *[f"  {line}" for line in script.usage.split("\n")],
        ])

    if script.has_args:
        lines.extend([
            "",
            "Note: This script accepts command-line arguments.",
            "Run with --help for details.",
        ])

    return "\n".join(lines)
