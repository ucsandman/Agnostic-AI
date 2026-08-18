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

    def read_state(self) -> str:
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


state_manager = StateManager()
