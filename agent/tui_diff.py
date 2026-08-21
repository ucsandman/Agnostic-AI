"""
agent/tui_diff.py — the `/diff` turn browser for the Textual TUI.

One arrow-key step on the shared PickerScreen: the turns of this session,
newest first, each row saying how many files that turn changed. The counts are
computed by the caller, so the screen itself touches neither the undo history
nor the filesystem. Dismisses with the turn's checkpoint name, or None.
"""

from typing import Dict, List, Tuple

from rich.text import Text
from textual.widgets import OptionList

from agent.tui_picker import PickerScreen

TurnMark = Tuple[str, str, list]


class DiffPickerScreen(PickerScreen):
    FOOTER_KEYS = "↑/↓ move · Space/Enter show diff · Esc cancel"

    def __init__(self, marks: List[TurnMark], counts: Dict[str, int]) -> None:
        super().__init__()
        self._marks = marks
        self._counts = counts

    def on_mount(self) -> None:
        self._push(self._show_turns)

    # ── steps ────────────────────────────────────────────────────────────────
    def _show_turns(self) -> None:
        options = []
        for name, clock, _history in reversed(self._marks):
            n = self._counts.get(name, 0)
            # 'no files' is still a selectable row: "nothing changed" is an answer.
            files = "no files" if not n else f"{n} file{'s' if n > 1 else ''}"
            label = Text(name, style="bold")
            label.append(f"  {clock} · {files}", style="dim")
            options.append((name, label))
        self._fill("Which turn?", options)

    # ── selection ────────────────────────────────────────────────────────────
    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)
