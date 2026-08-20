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
        self.history.append(FileSnapshot(file_path, previous_content, new_content, action))

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
                    with open(target, "w", encoding="utf-8", newline="") as f:
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
                # newline='' — the snapshot already holds the file's original endings.
                with open(target, "w", encoding="utf-8", newline="") as f:
                    f.write(last_snapshot.previous_content)
                return (
                    True,
                    f"Reverted changes to {target.name} (restored previous version).",
                )
        except Exception as e:
            return False, f"Failed to revert {target.name}: {str(e)}"

    def get_history_summary(self) -> List[str]:
        return [f"{s.action.upper()}: {s.file_path.name}" for s in reversed(self.history)]


undo_manager = UndoManager()


class ThemeManager:
    """Manages CLI aesthetic themes, palette mappings, and Rich Console themes."""

    PALETTES = {
        "tokyo-night": {
            "name": "Tokyo Night (Cybernetic)",
            "primary": "#7aa2f7",
            "secondary": "#bb9af7",
            "accent": "#7dcfff",
            "success": "#9ece6a",
            "warning": "#e0af68",
            "error": "#f7768e",
            "dim": "#565f89",
            "border": "bright_blue",
            "prompt_badge": "[bold #7aa2f7]agnostic[/bold #7aa2f7]",
            "glow": "cyan",
        },
        "catppuccin-mocha": {
            "name": "Catppuccin Mocha (Smooth Pastel)",
            "primary": "#89b4fa",
            "secondary": "#cba6f7",
            "accent": "#89dceb",
            "success": "#a6e3a1",
            "warning": "#f9e2af",
            "error": "#f38ba8",
            "dim": "#6c7086",
            "border": "bright_magenta",
            "prompt_badge": "[bold #cba6f7]agnostic[/bold #cba6f7]",
            "glow": "magenta",
        },
        "cyberpunk-neon": {
            "name": "Cyberpunk Neon (High-Contrast 2077)",
            "primary": "#00f0ff",
            "secondary": "#ff007f",
            "accent": "#ffe600",
            "success": "#00ff66",
            "warning": "#ffaa00",
            "error": "#ff0033",
            "dim": "#445566",
            "border": "cyan",
            "prompt_badge": "[bold #00f0ff]agnostic[/bold #00f0ff]",
            "glow": "yellow",
        },
        "monokai-pro": {
            "name": "Monokai Pro (Classic Developer)",
            "primary": "#ffd866",
            "secondary": "#ab9df2",
            "accent": "#78dce8",
            "success": "#a9dc76",
            "warning": "#fc9867",
            "error": "#ff6188",
            "dim": "#727072",
            "border": "yellow",
            "prompt_badge": "[bold #ffd866]agnostic[/bold #ffd866]",
            "glow": "green",
        },
        "github-dark": {
            "name": "GitHub Dark (Professional Enterprise)",
            "primary": "#58a6ff",
            "secondary": "#bc8cff",
            "accent": "#39c5cf",
            "success": "#3fb950",
            "warning": "#d29922",
            "error": "#f85149",
            "dim": "#8b949e",
            "border": "blue",
            "prompt_badge": "[bold #58a6ff]agnostic[/bold #58a6ff]",
            "glow": "blue",
        },
    }

    def __init__(self, default_theme: str = "tokyo-night"):
        self.active_theme_key = default_theme if default_theme in self.PALETTES else "tokyo-night"

    def get_active_theme(self):
        return self.PALETTES.get(self.active_theme_key, self.PALETTES["tokyo-night"])

    def set_theme(self, theme_key: str) -> str:
        clean = theme_key.lower().strip()
        if clean in self.PALETTES:
            self.active_theme_key = clean
            return f"Theme switched to: {self.PALETTES[clean]['name']}"
        for k, v in self.PALETTES.items():
            if clean in k or clean in v["name"].lower():
                self.active_theme_key = k
                return f"Theme switched to: {v['name']}"
        valid = ", ".join(self.PALETTES.keys())
        return f"Unknown theme '{theme_key}'. Available themes: {valid}"

    def format_badge(self, text: str, style_type: str = "primary") -> str:
        t = self.get_active_theme()
        color = t.get(style_type, t["primary"])
        return f"[{color}]◆ {text}[/{color}]"


theme_manager = ThemeManager()
