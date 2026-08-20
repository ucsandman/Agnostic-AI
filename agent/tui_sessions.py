"""
agent/tui_sessions.py — the bare-`/session` resume picker for the Textual TUI.

One arrow-key step on the shared PickerScreen: the saved sessions of this
workspace (.agnostic/sessions is cwd-local, so the list is scoped for free),
newest first — the order session_manager.list_sessions already returns.
Dismisses with the session name, or None when cancelled.
"""

from typing import Any, Dict, List

from rich.text import Text
from textual.widgets import OptionList

from agent.tui_picker import PickerScreen


class SessionPickerScreen(PickerScreen):
    FOOTER_KEYS = "↑/↓ move · Space/Enter load · Esc cancel"

    def __init__(self, sessions: List[Dict[str, Any]]) -> None:
        super().__init__()
        self._sessions = sessions

    def on_mount(self) -> None:
        self._push(self._show_sessions)

    # ── steps ────────────────────────────────────────────────────────────────
    def _show_sessions(self) -> None:
        options = []
        for s in self._sessions:
            label = Text(s["name"], style="bold")
            label.append(f"  {s['turn_count']} turns · {s['saved_at']}", style="dim")
            if s.get("notes"):
                label.append(f"  {s['notes'][:40]}", style="dim")
            options.append((s["name"], label))
        if not options:
            options = [("__none__", Text("no saved sessions", style="dim"))]
        self._fill("Resume a session", options)

    # ── selection ────────────────────────────────────────────────────────────
    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        choice = event.option.id
        self.dismiss(None if choice == "__none__" else choice)
