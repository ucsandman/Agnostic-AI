"""
agent/tui_picker.py — the shared arrow-key picker modal for the Textual TUI.

A stack of steps, each an OptionList: a step is a thunk that (re)populates the
list, ↑/↓ move, Space or Enter select, Esc pops one step (or closes). Subclasses
push their own steps and dismiss with whatever value they collected.
"""

from typing import Callable, List, Optional, Tuple

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option


class PickerScreen(ModalScreen):
    FOOTER_KEYS = "↑/↓ move · Space/Enter select · Esc back"
    DEFAULT_CSS = """
    PickerScreen { align: center middle; }
    #picker-box { width: 96%; max-width: 120; height: auto; max-height: 90%;
                  border: round $accent; background: $surface; padding: 0 1; }
    #picker-title { text-style: bold; color: $accent; padding: 0 1; }
    #picker-list { height: auto; max-height: 30; border: none; }
    #picker-hint { color: $text-muted; padding: 0 1; }
    """
    BINDINGS = [
        Binding("escape", "back", "Back", show=False),
        Binding("space", "pick", "Select", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        # Each step is a thunk that (re)populates the list; Esc pops one.
        self._steps: List[Callable[[], None]] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-box"):
            yield Static("", id="picker-title")
            yield OptionList(id="picker-list")
            yield Static(self.FOOTER_KEYS, id="picker-hint")

    # ── steps ────────────────────────────────────────────────────────────────
    def _push(self, step: Callable[[], None]) -> None:
        self._steps.append(step)
        step()

    def _fill(
        self, title: str, options: List[Tuple[str, Text]], highlight: Optional[str] = None
    ) -> None:
        self.query_one("#picker-title", Static).update(title)
        lst = self.query_one("#picker-list", OptionList)
        lst.clear_options()
        lst.add_options([Option(label, id=oid) for oid, label in options])
        ids = [oid for oid, _ in options]
        lst.highlighted = ids.index(highlight) if highlight in ids else 0
        lst.focus()

    def action_pick(self) -> None:
        self.query_one("#picker-list", OptionList).action_select()

    def action_back(self) -> None:
        self._steps.pop()
        if self._steps:
            self._steps[-1]()
        else:
            self.dismiss(None)
