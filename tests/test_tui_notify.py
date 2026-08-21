"""
tests/test_tui_notify.py — the turn-done bell + toast.

A 4-minute turn used to end with one line in a window nobody was looking at.
Three halves here: the pure predicate and the toast text, the workspace settings
file the toggle persists into, and the focus tracking that makes the whole thing
safe-off on a terminal that never reports focus.

The guard that busy_indicator survived the shared _clock extraction lives next to
its siblings in tests/test_ui_common.py.
"""

import asyncio
import threading
from types import SimpleNamespace

from textual import events

import agent.tui as tui
from agent.governance.state import StateManager
from agent.ui_common import should_notify, turn_summary


# --- The predicate: three conditions, no 'always' mode ----------------------------


def test_should_notify_needs_enabled_unfocused_and_a_long_turn():
    assert should_notify(True, False, 5.0) is True
    assert should_notify(True, False, 60.0) is True
    # Focused: the user is already looking at the answer.
    assert should_notify(True, True, 60.0) is False
    # Just under the floor — a bell on every quick turn is what users switch off.
    assert should_notify(True, False, 4.9) is False
    assert should_notify(False, False, 60.0) is False


def test_turn_summary_reads_as_a_sentence():
    assert turn_summary(0, 12) == "no files changed · 12s"
    assert turn_summary(1, 7) == "1 file changed · 7s"
    assert turn_summary(3, 134) == "3 files changed · 2m14s"


# --- The workspace settings file ---------------------------------------------------


def test_settings_round_trip_and_survive_a_corrupt_file(tmp_path):
    sm = StateManager(str(tmp_path))

    assert sm.get_setting("notify", True) is True, "no file yet: the default"
    sm.set_setting("notify", False)
    assert StateManager(str(tmp_path)).get_setting("notify", True) is False
    # A second key must not clobber the first.
    sm.set_setting("theme", "dark")
    assert sm.get_setting("notify", True) is False and sm.get_setting("theme") == "dark"

    sm.settings_file.write_text("{not json", encoding="utf-8")
    assert sm.get_setting("notify", True) is True, "corrupt settings read as the default"
    # ...and a write over the corrupt file still works, starting from scratch.
    sm.set_setting("notify", False)
    assert sm.get_setting("notify", True) is False


# --- Focus tracking ---------------------------------------------------------------


def _agent(tmp_path):
    return SimpleNamespace(
        confirm_callback=None,
        output_callback=None,
        cancel_event=threading.Event(),
        workspace_root=tmp_path,
        history=[],
    )


def _app(tmp_path, monkeypatch=None):
    if monkeypatch is not None:
        monkeypatch.setattr(tui, "index_workspace", lambda: None)
    return tui.AgnosticTUI(
        agent=_agent(tmp_path),
        code_indexer_inst=SimpleNamespace(get_all_symbols=list, get_indexed_files=list),
        detected_model="test-model",
        doctor=None,
        test_runner=None,
        # Non-empty detection: on_mount then skips _detect_model_bg, which would
        # AttributeError on doctor=None inside a worker thread.
        detection={"status": "offline", "base_url": "http://x/v1"},
    )


def test_blur_arms_the_notification_and_focus_disarms_it(tmp_path, monkeypatch):
    """AppBlur/AppFocus are what Textual's drivers turn DECSET 1004 into. Unfocused
    and long enough -> bell + toast; focused -> silence."""
    rung, toasts = [], []

    async def drive():
        app = _app(tmp_path, monkeypatch)
        async with app.run_test() as pilot:
            app._notify_enabled = True
            app.bell = lambda: rung.append("bell")
            app.notify = lambda message, **kwargs: toasts.append((message, kwargs))

            app.post_message(events.AppBlur())
            await pilot.pause()
            assert app._focused is False and app._saw_focus_event is True
            app._notify_turn_done(10.0)
            await pilot.pause()

            assert rung == ["bell"]
            assert len(toasts) == 1
            message, kwargs = toasts[0]
            assert message == turn_summary(0, 10.0)
            assert kwargs["title"] == "Turn complete"
            assert kwargs["severity"] == "information"
            assert kwargs["timeout"] == 10

            app.post_message(events.AppFocus())
            await pilot.pause()
            assert app._focused is True
            app._notify_turn_done(600.0)
            await pilot.pause()
            assert rung == ["bell"] and len(toasts) == 1, "focused: nothing may fire"

    asyncio.run(drive())


def test_notify_command_toggles_persists_and_reports_the_focus_truth(tmp_path, monkeypatch):
    """/notify on|off writes through to the settings file; bare /notify says whether
    this terminal has ever reported focus — 'on' alone would be a lie on one that
    never will."""
    import agent.tui_commands as tui_commands

    sm = StateManager(str(tmp_path))
    monkeypatch.setattr(tui_commands, "state_manager", sm)
    app = _app(tmp_path)
    out = []
    app._write_output = out.append

    assert app._handle_slash_command("/notify off") is True
    assert app._notify_enabled is False and sm.get_setting("notify") is False
    assert app._handle_slash_command("/notify on") is True
    assert app._notify_enabled is True and sm.get_setting("notify") is True

    out.clear()
    assert app._handle_slash_command("/notify") is True
    assert str(out[-1]) == (
        "notifications: on (this terminal never reported focus — notifications will not fire)"
    )

    app._saw_focus_event = True
    app._handle_slash_command("/notify")
    assert str(out[-1]) == "notifications: on (this terminal reports focus)"


def test_notify_survives_a_read_only_workspace(tmp_path, monkeypatch):
    """A settings file that cannot be written is not a reason to refuse the toggle."""
    import agent.tui_commands as tui_commands

    sm = StateManager(str(tmp_path))
    monkeypatch.setattr(sm, "set_setting", _raise_oserror)
    monkeypatch.setattr(tui_commands, "state_manager", sm)
    app = _app(tmp_path)
    out = []
    app._write_output = out.append

    assert app._handle_slash_command("/notify on") is True
    assert app._notify_enabled is True
    assert str(out[-1]) == "notifications: on (for this session only — .agnostic is not writable)"


def _raise_oserror(*args, **kwargs):
    raise OSError("read-only file system")


def test_a_terminal_that_never_reported_focus_never_notifies(tmp_path):
    """SAFE-OFF: _focused starts True, so an older conhost or a tmux without
    focus-events stays silent instead of ringing through every turn."""
    app = _app(tmp_path)
    app._notify_enabled = True
    rung, toasts = [], []
    app.bell = lambda: rung.append("bell")
    app.notify = lambda message, **kwargs: toasts.append(message)

    assert app._focused is True and app._saw_focus_event is False
    app._notify_turn_done(60.0)
    assert rung == [] and toasts == []
