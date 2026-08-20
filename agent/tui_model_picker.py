"""
agent/tui_model_picker.py — the interactive /model picker for the Textual TUI.

Three arrow-key steps, each an OptionList: preset → concrete model (subscription
presets only: sub-claude-code can run claude-fable-5, claude-opus-5, …) → effort
(skipped when the chosen model ignores it). ↑/↓ move, Space or Enter select,
Esc goes back a step (or closes). Dismisses with (preset_key, sub_model, effort)
or None when cancelled.
"""

from typing import Callable, List, Optional, Tuple

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from agent.llm.client import LLMClient, LLMConfig
from agent.ui_common import EFFORT_LEVELS, model_preset_rows

_EFFORT_BLURB = {
    "low": "fastest, minimal reasoning",
    "medium": "balanced",
    "high": "deepest reasoning",
}


class ModelPickerScreen(ModalScreen):
    DEFAULT_CSS = """
    ModelPickerScreen { align: center middle; }
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

    def __init__(self, active_model: str, local_online: bool = False) -> None:
        super().__init__()
        self._active_model = active_model
        self._local_online = local_online
        self._preset_key: Optional[str] = None
        self._sub_model: Optional[str] = None
        # Each step is a thunk that (re)populates the list; Esc pops one.
        self._steps: List[Callable[[], None]] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-box"):
            yield Static("", id="picker-title")
            yield OptionList(id="picker-list")
            yield Static("↑/↓ move · Space/Enter select · Esc back", id="picker-hint")

    def on_mount(self) -> None:
        self._push(self._show_presets)

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

    def _show_presets(self) -> None:
        rows = model_preset_rows(LLMConfig.PRESETS, self._active_model, self._local_online)
        options = []
        for num, active, key, name, ctx, effort, avail in rows:
            label = Text()
            label.append(f"{active or ' '} {num:>2}  ", style="bold cyan" if active else "dim")
            label.append(f"{name}  ", style="bold" if active else "")
            label.append(f"{ctx} · {effort} · ", style="dim")
            label.append(
                avail, style="green" if avail.endswith(("ready", "set", "online")) else "yellow"
            )
            options.append((key, label))
        current = next((r[2] for r in rows if r[1]), None)
        self._fill("Model presets", options, highlight=current)

    def _show_sub_models(self) -> None:
        assert self._preset_key
        name = LLMConfig.PRESETS[self._preset_key]["name"]
        options = [
            ("__default__", Text("CLI default (whatever the logged-in CLI picks)", style="dim"))
        ]
        for model in LLMConfig.sub_models(self._preset_key):
            pretty = next(
                (
                    p["name"].split("(")[0].strip()
                    for p in LLMConfig.PRESETS.values()
                    if p["model"] == model
                ),
                model,
            )
            label = Text(model, style="bold")
            label.append(f"  {pretty}", style="dim")
            options.append((model, label))
        self._fill(f"{name} — which model?", options)

    def _show_effort(self) -> None:
        assert self._preset_key
        preset = LLMConfig.PRESETS[self._preset_key]
        options = [
            (lvl, Text(f"{lvl:<7}", style="bold").append(_EFFORT_BLURB[lvl], style="dim"))
            for lvl in EFFORT_LEVELS
        ]
        self._fill(
            f"{preset['name']} — reasoning effort", options, highlight=preset.get("default_effort")
        )

    # ── selection ────────────────────────────────────────────────────────────
    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        choice = event.option.id
        step = self._steps[-1]
        if step == self._show_presets:
            self._preset_key = choice
            self._sub_model = None
            self._advance()
        elif step == self._show_sub_models:
            self._sub_model = None if choice == "__default__" else choice
            self._advance()
        else:
            self.dismiss((self._preset_key, self._sub_model, choice))

    def _advance(self) -> None:
        """After preset (and sub-model) are known: ask for more or finish."""
        assert self._preset_key
        preset = LLMConfig.PRESETS[self._preset_key]
        provider = str(preset["provider"])
        if provider.endswith("-sub") and self._steps[-1] == self._show_presets:
            self._push(self._show_sub_models)
        elif LLMClient.effort_supported(provider, str(self._sub_model or preset["model"])):
            self._push(self._show_effort)
        else:
            self.dismiss((self._preset_key, self._sub_model, None))

    def action_pick(self) -> None:
        self.query_one("#picker-list", OptionList).action_select()

    def action_back(self) -> None:
        self._steps.pop()
        if self._steps:
            self._steps[-1]()
        else:
            self.dismiss(None)
