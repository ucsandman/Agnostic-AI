"""
tests/test_tui_composer.py — Regression tests for agent/tui_composer.py.

The prompt used to be a textual.widgets.Input, whose _on_paste keeps
`event.text.splitlines()[0]`: pasting a stack trace silently lost everything
after the first line. These tests pin the replacement — Enter submits,
Shift+Enter / Alt+Enter / Ctrl+J insert a newline, a pasted block arrives whole,
the box grows to 8 lines and stops — plus the two Input-shaped shims (`value`,
`cursor_position`) that keep history walking and Tab completion unchanged.
"""

import asyncio
import inspect
import threading
from types import SimpleNamespace

from textual import events

from agent import tui_composer
from agent.tui_composer import PROMPT_PLACEHOLDER, PromptArea

# The shared pilot harness lives with the rest of the TUI pilot tests; pytest puts
# tests/ on sys.path, so this is the same helper, not a second copy.
from test_ui_common import _pilot_tui


def _composer_app(monkeypatch):
    """A mountable TUI whose submissions are recorded instead of run."""
    agent = SimpleNamespace(
        confirm_callback=None,
        output_callback=None,
        history=[],
        cancel_event=threading.Event(),
    )
    app = _pilot_tui(agent, monkeypatch)
    submitted = []
    app._process_input = submitted.append
    return app, submitted


def test_shift_enter_makes_a_newline_and_enter_sends_the_whole_block(monkeypatch):
    """The core gesture: one submission, both lines, and the box left empty."""
    app, submitted = _composer_app(monkeypatch)
    left = []

    async def drive():
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("a", "shift+enter", "b")
            await pilot.press("enter")
            await pilot.pause()
            left.append(app.query_one("#prompt-input").value)

    asyncio.run(drive())

    assert submitted == ["a\nb"]
    assert left == [""], "the composer must be cleared after a send"


def test_alt_enter_and_ctrl_j_are_the_guaranteed_newline_keys(monkeypatch):
    """Shift+Enter needs the kitty protocol; these two do not, so they are what the
    placeholder and /multiline promise on a terminal without it."""
    app, submitted = _composer_app(monkeypatch)

    async def drive():
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("a", "alt+enter", "b", "ctrl+j", "c")
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(drive())

    assert submitted == ["a\nb\nc"]


def test_a_multiline_paste_keeps_every_line(monkeypatch):
    """The Input regression this widget exists for: Input._on_paste kept only
    'one'. A paste is a Paste event, never Key events, so it also cannot submit."""
    app, submitted = _composer_app(monkeypatch)
    pasted = []

    async def drive():
        async with app.run_test() as pilot:
            await pilot.pause()
            area = app.query_one("#prompt-input")
            # Posted at the app, which is the driver's own path: a Paste posted
            # straight at the widget is inserted once by the widget and then
            # forwarded back to it by App.on_event, i.e. pasted twice.
            app.post_message(events.Paste("one\ntwo\nthree"))
            await pilot.pause()
            pasted.append(area.value)

    asyncio.run(drive())

    assert pasted == ["one\ntwo\nthree"]
    assert submitted == [], "a paste ending mid-block must not send the prompt"


def test_the_box_grows_with_the_paste_and_stops_at_eight_lines(monkeypatch):
    """Grow to fit, then scroll — a 30-line paste must not eat the whole screen."""
    app, _ = _composer_app(monkeypatch)
    heights = []

    async def drive():
        async with app.run_test(size=(100, 24)) as pilot:
            await pilot.pause()
            area = app.query_one("#prompt-input")
            app.post_message(events.Paste("a\nb\nc"))
            await pilot.pause()
            heights.append(area.size.height)
            area.value = "\n".join(str(i) for i in range(30))
            await pilot.pause()
            heights.append(area.size.height)
            assert area.document.line_count == 30

    asyncio.run(drive())

    assert heights == [3, 8]


def test_the_arrows_walk_history_on_one_line_and_move_the_cursor_on_two(monkeypatch):
    """TextArea binds up/down to cursor movement and sits ahead of the App in the
    focused-up binding chain, so the composer has to hand a one-line box back to the
    history actions itself — and stop doing so the moment the box is a block."""
    app, _ = _composer_app(monkeypatch)
    seen = []

    async def drive():
        async with app.run_test() as pilot:
            await pilot.pause()
            area = app.query_one("#prompt-input")
            app._history.entries[:] = ["first prompt", "second prompt"]
            app._history.index = len(app._history.entries)
            await pilot.press("up")
            await pilot.pause()
            seen.append(area.value)
            await pilot.press("up")
            await pilot.pause()
            seen.append(area.value)
            await pilot.press("down")
            await pilot.pause()
            seen.append(area.value)

            area.value = "aaa\nbbb"
            area.cursor_position = len(area.value)
            await pilot.press("up")
            await pilot.pause()
            seen.append(area.value)
            seen.append(area.cursor_location)

    asyncio.run(drive())

    assert seen == ["second prompt", "first prompt", "second prompt", "aaa\nbbb", (0, 3)]


def test_value_shim_reads_and_writes_the_whole_document():
    """`.value` is what _walk_history, action_complete_slash and on_input_submitted
    all use; it must round-trip newlines, not just the first line."""
    area = PromptArea()
    assert area.value == ""
    area.value = "fix the parser\nthen run the tests"
    assert area.value == "fix the parser\nthen run the tests"
    assert area.document.line_count == 2
    area.value = ""
    assert area.value == ""


def test_cursor_position_shim_is_a_character_offset_and_is_clamped():
    """Input reports one integer offset; the shim keeps that contract across lines
    and never raises on an offset past the end (Tab completion sets len(value))."""
    area = PromptArea()
    area.value = "abc\ndefg"
    assert area.cursor_position == 0
    area.cursor_position = 6
    assert area.cursor_location == (1, 2)
    assert area.cursor_position == 6
    area.cursor_position = 999
    assert area.cursor_position == len(area.value) == 8
    area.cursor_position = -5
    assert area.cursor_position == 0


def test_enter_posts_the_input_submitted_message_the_tui_already_handles():
    """AgnosticTUI.on_input_submitted is the one entry point for a typed prompt.
    Renaming the message here would silently disconnect the whole composer."""
    src = inspect.getsource(PromptArea._on_key)
    assert "Input.Submitted(self, self.expand_pastes(self.text))" in src
    assert 'if event.key == "enter"' in src
    assert "NEWLINE_KEYS" in src
    assert tui_composer.NEWLINE_KEYS == ("shift+enter", "alt+enter", "ctrl+j")
    assert "Enter to send" in PROMPT_PLACEHOLDER
