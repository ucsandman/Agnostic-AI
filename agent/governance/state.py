"""
agent/governance/state.py — State Whiteboard & Persistent Workspace Memory
Maintains a clean .agnostic/state.md whiteboard across long sessions, allowing task resumption.
"""

from pathlib import Path
from typing import Optional, List


class StateManager:
    def __init__(self, workspace_root: Optional[str] = None):
        self.workspace_root = Path(workspace_root or ".").resolve()
        self.state_dir = self.workspace_root / ".agnostic"
        self.state_file = self.state_dir / "state.md"

    def read_state(self) -> str:  # noqa: vulture
        if not self.state_file.exists():
            return "No active state whiteboard. Use state commands or let tasks record goals."
        return self.state_file.read_text(encoding="utf-8")

    def update_whiteboard(
        self,
        objective: str,
        completed: List[str],
        remaining: List[str],
        notes: Optional[str] = None,
    ):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        md = [
            f"# 🎯 Active Project Objective: {objective}\n",
            "## Completed Steps:\n",
        ]
        for c in completed:
            md.append(f"- [x] {c}")
        if not completed:
            md.append("- None yet.")

        md.append("\n## Next Tasks / Open Steps:\n")
        for r in remaining:
            md.append(f"- [ ] {r}")
        if not remaining:
            md.append("- All open tasks resolved.")

        if notes:
            md.append(f"\n## Notes & Scratchpad:\n{notes}\n")

        self.state_file.write_text("\n".join(md) + "\n", encoding="utf-8")

    def read_memory(self, key: Optional[str] = None) -> str:
        """Reads persistent project memory notes or deviations."""
        mem_dir = self.state_dir / "memory"
        if not mem_dir.exists():
            return "No persistent project memory saved yet."

        if key:
            clean_key = key.lower().replace(" ", "_")
            target = mem_dir / f"{clean_key}.md"
            if target.exists():
                return (
                    f"### [Project Memory: {key}]\n{target.read_text(encoding='utf-8')}"
                )
            return f"No memory entry found for key '{key}'."

        # List all memory entries
        entries = []
        for mem_file in mem_dir.glob("*.md"):
            entries.append(
                f"### [{mem_file.stem}]\n{mem_file.read_text(encoding='utf-8')}\n"
            )
        return (
            "\n".join(entries) if entries else "No persistent project memory entries."
        )

    def write_memory(self, key: str, content: str) -> str:
        """Saves persistent project memory notes or deviations."""
        mem_dir = self.state_dir / "memory"
        mem_dir.mkdir(parents=True, exist_ok=True)
        clean_key = key.lower().replace(" ", "_")
        target = mem_dir / f"{clean_key}.md"
        target.write_text(content, encoding="utf-8")
        return f"Successfully saved project memory for '{key}'."


state_manager = StateManager()
