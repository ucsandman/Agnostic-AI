"""
agent/tools/diff_viewer.py — Rich Colorized Diff Viewer for File Edits
Renders visual before/after unified diff cards in the terminal for file edits and writes.
"""

import difflib
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()


class DiffViewer:
    @staticmethod
    def render_diff(
        file_name: str, old_content: str, new_content: str, max_lines: int = 25
    ) -> Panel:
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)

        diff = list(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=f"a/{file_name}",
                tofile=f"b/{file_name}",
                n=2,
            )
        )

        if not diff:
            return Panel(
                f"[dim]No changes detected in {file_name}[/dim]",
                title=f"Diff: {file_name}",
                border_style="dim",
            )

        diff_text = Text()
        for idx, line in enumerate(diff[:max_lines]):
            if line.startswith("+++") or line.startswith("---"):
                diff_text.append(line, style="bold cyan")
            elif line.startswith("@@"):
                diff_text.append(line, style="bold magenta")
            elif line.startswith("+"):
                diff_text.append(line, style="green")
            elif line.startswith("-"):
                diff_text.append(line, style="red")
            else:
                diff_text.append(line, style="dim white")

        if len(diff) > max_lines:
            diff_text.append(
                f"\n... ({len(diff) - max_lines} more diff lines truncated)",
                style="dim italic",
            )

        return Panel(diff_text, title=f"📝 Diff Preview: {file_name}", border_style="cyan")
