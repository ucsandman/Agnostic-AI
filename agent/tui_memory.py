"""
agent/tui_memory.py — the bare-`/memory` picker for the Textual TUI.

One arrow-key step on the shared PickerScreen: everything MemoryStore kept for
this workspace, newest first (store.list() hands them over oldest first).
Dismisses with the memory name, or None when cancelled.
"""

from typing import List, Tuple

from rich.text import Text
from textual.widgets import OptionList

from agent.governance.memory import Memory
from agent.tui_picker import PickerScreen


def _memory_rows(memories: List[Memory]) -> List[Tuple[str, Text]]:
    """(option id, label) per memory, newest first — the order every other picker
    in this app uses. Pure, so the labels are testable without mounting Textual."""
    rows = []
    for m in reversed(memories):
        label = Text(m.name, style="bold")
        label.append(f"  {m.type} · {m.created}", style="dim")
        if m.description:
            label.append(f"  {m.description[:60]}", style="dim")
        rows.append((m.name, label))
    return rows or [("__none__", Text("no memories saved yet", style="dim"))]


class MemoryPickerScreen(PickerScreen):
    FOOTER_KEYS = "↑/↓ move · Space/Enter show · Esc cancel"

    def __init__(self, memories: List[Memory]) -> None:
        super().__init__()
        self._memories = memories

    def on_mount(self) -> None:
        self._push(self._show_memories)

    # ── steps ────────────────────────────────────────────────────────────────
    def _show_memories(self) -> None:
        self._fill("Saved memories", _memory_rows(self._memories))

    # ── selection ────────────────────────────────────────────────────────────
    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        choice = event.option.id
        self.dismiss(None if choice == "__none__" else choice)
