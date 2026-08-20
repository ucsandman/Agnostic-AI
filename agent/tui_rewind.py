"""
agent/tui_rewind.py — the double-Esc rewind picker for the Textual TUI.

Two arrow-key steps on the shared PickerScreen: which turn to go back to, then
what to restore — the files (undo_manager's per-turn checkpoint), the
conversation (the history snapshot taken when the turn started), or both.
Dismisses with (checkpoint_name, history_snapshot, scope) or None.
"""

from typing import List, Optional, Tuple

from rich.text import Text
from textual.widgets import OptionList

from agent.tui_picker import PickerScreen

_SCOPE_BLURB = (
    ("files", "revert file writes made since this turn"),
    ("conversation", "restore the conversation as it was"),
    ("both", "both"),
)

TurnMark = Tuple[str, str, list]


class RewindScreen(PickerScreen):
    FOOTER_KEYS = "↑/↓ move · Space/Enter select · Esc back/cancel"

    def __init__(self, marks: List[TurnMark]) -> None:
        super().__init__()
        self._marks = marks
        self._mark: Optional[TurnMark] = None

    def on_mount(self) -> None:
        self._push(self._show_turns)

    # ── steps ────────────────────────────────────────────────────────────────
    def _show_turns(self) -> None:
        options = []
        for name, clock, history in reversed(self._marks):
            label = Text(name, style="bold")
            label.append(f"  {clock} · {len(history)} messages", style="dim")
            options.append((name, label))
        if not options:
            options = [("__none__", Text("no turns yet", style="dim"))]
        self._fill("Rewind to which turn?", options)

    def _show_scope(self) -> None:
        assert self._mark
        options = [
            (scope, Text(f"{scope:<13}", style="bold").append(blurb, style="dim"))
            for scope, blurb in _SCOPE_BLURB
        ]
        self._fill(f"Rewind to {self._mark[0]} — restore what?", options)

    # ── selection ────────────────────────────────────────────────────────────
    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        choice = event.option.id
        if self._steps[-1] == self._show_turns:
            if choice == "__none__":
                self.dismiss(None)
                return
            self._mark = next(m for m in self._marks if m[0] == choice)
            self._push(self._show_scope)
        else:
            assert self._mark
            name, _clock, history = self._mark
            self.dismiss((name, history, choice))
