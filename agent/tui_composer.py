"""
agent/tui_composer.py — the multi-line prompt box.

textual.widgets.Input is single-line by construction: its _on_paste keeps
`event.text.splitlines()[0]` and drops the rest, so pasting a stack trace or a
spec silently lost everything after the first line. TextArea._on_paste inserts
the pasted text whole, so the composer is a TextArea wearing an Input's clothes:
it posts Input.Submitted on Enter and exposes `.value` / `.cursor_position`,
which is what keeps every caller in tui.py — history walking, Tab completion,
the confirm border, the queue — working unchanged.
"""

from textual import events
from textual.widgets import Input, TextArea

PROMPT_PLACEHOLDER = "Type a message… (Enter to send, Shift+Enter/Alt+Enter for a newline)"

# Shift+Enter only reaches us on terminals that speak the kitty keyboard protocol
# (Textual's Windows and Linux drivers request it). Elsewhere it arrives as a plain
# 'enter' and sends — Alt+Enter and Ctrl+J are the guaranteed newline keys.
NEWLINE_KEYS = ("shift+enter", "alt+enter", "ctrl+j")


class PromptArea(TextArea):
    """A TextArea that submits like an Input."""

    async def _on_key(self, event: events.Key) -> None:
        """The only reliable interception point: TextArea._on_key stops and prevents
        'enter' itself, before any non-priority binding is ever consulted."""
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            self.post_message(Input.Submitted(self, self.text))
            return
        if event.key in NEWLINE_KEYS:
            event.stop()
            event.prevent_default()
            self.insert("\n")
            return
        if event.key in ("up", "down") and self.document.line_count <= 1:
            # A one-line box is a prompt, so the arrows walk prompt history. The App's
            # up/down bindings cannot win on their own: TextArea binds both to cursor
            # movement and sits ahead of the App in the focused-up binding chain. Once
            # the box holds 2+ lines the key falls through and moves the cursor instead.
            event.stop()
            event.prevent_default()
            walk = getattr(
                self.app,
                "action_history_prev" if event.key == "up" else "action_history_next",
                None,
            )
            if walk is not None:
                walk()
            return
        await super()._on_key(event)

    # --- Input compatibility shims ------------------------------------------------

    @property
    def value(self) -> str:
        return self.text

    @value.setter
    def value(self, text: str) -> None:
        self.load_text(text)

    @property
    def cursor_position(self) -> int:
        """The cursor as a character offset into `value`, the way Input reports it."""
        return self.document.get_index_from_location(self.cursor_location)

    @cursor_position.setter
    def cursor_position(self, offset: int) -> None:
        clamped = max(0, min(int(offset), len(self.text)))
        self.move_cursor(self.document.get_location_from_index(clamped))
