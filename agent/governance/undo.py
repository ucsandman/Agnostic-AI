"""
agent/governance/undo.py — Snapshot & Undo Manager
Tracks file modifications across the session to enable instant one-command rollbacks (/undo).
"""

import os
from pathlib import Path
from typing import List, Optional, Tuple


class FileSnapshot:
    def __init__(
        self,
        file_path: Path,
        previous_content: Optional[str],
        new_content: str,
        action: str,
    ):
        self.file_path = file_path
        self.previous_content = previous_content  # None if file was newly created
        self.new_content = new_content
        self.action = action  # 'edit', 'write', 'create'


class UndoManager:
    def __init__(self, workspace_root: Optional[str] = None):
        self.workspace_root = Path(workspace_root or os.getcwd()).resolve()
        self.history: List[FileSnapshot] = []
        self.checkpoints: dict[str, List[FileSnapshot]] = {}

    def record_change(
        self,
        file_path: Path,
        previous_content: Optional[str],
        new_content: str,
        action: str,
    ):
        self.history.append(
            FileSnapshot(file_path, previous_content, new_content, action)
        )

    def create_checkpoint(self, name: str) -> str:
        """Saves a named checkpoint snapshot of current undo history state."""
        self.checkpoints[name] = list(self.history)
        return f"Checkpoint '{name}' created with {len(self.history)} active history entries."

    def rollback_to_checkpoint(self, name: str) -> Tuple[bool, str]:
        """Rolls back all file changes made since the named checkpoint."""
        if name not in self.checkpoints:
            return (
                False,
                f"Checkpoint '{name}' not found. Available: {list(self.checkpoints.keys())}",
            )

        target_history_len = len(self.checkpoints[name])
        if len(self.history) <= target_history_len:
            return (
                True,
                f"Already at or before checkpoint '{name}'. No changes to revert.",
            )

        reverted_files = []
        while len(self.history) > target_history_len:
            last_snapshot = self.history.pop()
            target = last_snapshot.file_path
            try:
                if last_snapshot.previous_content is None:
                    if target.exists():
                        target.unlink()
                    reverted_files.append(f"Deleted {target.name}")
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with open(target, "w", encoding="utf-8") as f:
                        f.write(last_snapshot.previous_content)
                    reverted_files.append(f"Restored {target.name}")
            except Exception as e:
                return False, f"Error rolling back {target.name}: {str(e)}"

        return (
            True,
            f"Rolled back to checkpoint '{name}'. Reverted: {', '.join(reverted_files)}",
        )

    def rollback_last(self) -> Tuple[bool, str]:
        """Rolls back the most recent file change."""
        if not self.history:
            return False, "No file changes in undo history to revert."

        last_snapshot = self.history.pop()
        target = last_snapshot.file_path

        try:
            if last_snapshot.previous_content is None:
                # File was newly created, delete it
                if target.exists():
                    target.unlink()
                return True, f"Reverted creation of {target.name} (file removed)."
            else:
                # Restore previous content
                target.parent.mkdir(parents=True, exist_ok=True)
                with open(target, "w", encoding="utf-8") as f:
                    f.write(last_snapshot.previous_content)
                return (
                    True,
                    f"Reverted changes to {target.name} (restored previous version).",
                )
        except Exception as e:
            return False, f"Failed to revert {target.name}: {str(e)}"

    def get_history_summary(self) -> List[str]:  # noqa: vulture
        return [
            f"{s.action.upper()}: {s.file_path.name}" for s in reversed(self.history)
        ]


undo_manager = UndoManager()
