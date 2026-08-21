"""
tests/test_tui_diff.py — the /diff turn browser.

Two halves: UndoManager.changed_since (pure, no Textual — it is what turns the
per-write snapshots into one net change per file), and the /diff slash-command
branch that renders those changes through the existing DiffViewer.
"""

import io
import threading
from types import SimpleNamespace

from rich.console import Console

import agent.tui as tui
from agent.governance.undo import UndoManager, undo_manager


def _um(tmp_path) -> UndoManager:
    return UndoManager(workspace_root=str(tmp_path))


def test_changed_since_collapses_repeated_writes_to_one_net_change(tmp_path):
    um = _um(tmp_path)
    early = tmp_path / "before.py"
    target = tmp_path / "loop.py"

    um.record_change(early, "untouched\n", "touched before the turn\n", "edit")
    um.create_checkpoint("turn-1")
    um.record_change(target, "v0\n", "v1\n", "edit")
    um.record_change(target, "v1\n", "v2\n", "edit")

    changes = um.changed_since("turn-1")
    assert changes == [(target, "v0\n", "v2\n")], "first 'before' + last 'after', once per file"
    assert um.changed_since("no-such-turn") == []


def test_changed_since_reports_a_created_file_with_no_before(tmp_path):
    um = _um(tmp_path)
    um.create_checkpoint("turn-1")
    created = tmp_path / "new.py"
    um.record_change(created, None, "hello\n", "create")

    assert um.changed_since("turn-1") == [(created, None, "hello\n")]


def test_changed_since_drops_a_write_that_restored_the_original(tmp_path):
    um = _um(tmp_path)
    um.create_checkpoint("turn-1")
    target = tmp_path / "loop.py"
    um.record_change(target, "same\n", "different\n", "edit")
    um.record_change(target, "different\n", "same\n", "edit")

    assert um.changed_since("turn-1") == [], "net zero is not a change"


def _tui(tmp_path, out):
    app = tui.AgnosticTUI(
        agent=SimpleNamespace(
            confirm_callback=None,
            output_callback=None,
            cancel_event=threading.Event(),
            workspace_root=tmp_path,
        ),
        code_indexer_inst=None,
        detected_model="test-model",
        doctor=None,
        test_runner=None,
    )
    # Never mounted here, so there is no #output-log to write into.
    app._write_output = out.append
    return app


def test_diff_without_any_turn_says_so_and_opens_no_modal(tmp_path):
    out, pushed = [], []
    app = _tui(tmp_path, out)
    app.push_screen = lambda *a, **k: pushed.append(a)

    assert app._handle_slash_command("/diff") is True
    assert [str(o) for o in out] == ["No turns yet."]
    assert pushed == [], "nothing to browse: the picker must not open"


def test_diff_picker_lists_the_turns_newest_first_with_their_file_counts():
    """Newest turn on top, one row per mark, and a turn that changed nothing is still
    selectable — 'nothing changed' is an answer."""
    import asyncio
    from textual.app import App
    from textual.widgets import OptionList

    from agent.tui_diff import DiffPickerScreen

    marks = [("turn-1", "14:11:02", []), ("turn-2", "14:19:41", [])]
    counts = {"turn-1": 1, "turn-2": 0}
    results, labels = [], []

    class Host(App):
        def on_mount(self):
            self.push_screen(DiffPickerScreen(list(marks), counts), callback=results.append)

    async def drive(keys_to_press):
        results.clear()
        labels.clear()
        app = Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            lst = app.screen.query_one("#picker-list", OptionList)
            labels.extend(str(lst.get_option_at_index(i).prompt) for i in range(lst.option_count))
            for k in keys_to_press:
                await pilot.press(k)
                await pilot.pause()

    asyncio.run(drive(["enter"]))
    assert results == ["turn-2"]
    assert "no files" in labels[0] and "14:19:41" in labels[0]
    assert "1 file" in labels[1]

    asyncio.run(drive(["escape"]))
    assert results == [None]


def test_diff_of_one_turn_renders_the_added_and_removed_lines(tmp_path, monkeypatch):
    monkeypatch.setattr(undo_manager, "history", [])
    monkeypatch.setattr(undo_manager, "checkpoints", {})
    undo_manager.create_checkpoint("turn-1")
    undo_manager.record_change(tmp_path / "loop.py", "old line\n", "new line\n", "edit")

    out = []
    app = _tui(tmp_path, out)
    app._turn_marks.append(("turn-1", "14:22:03", []))

    assert app._handle_slash_command("/diff turn-1") is True
    assert len(out) == 1
    console = Console(file=io.StringIO(), width=100)
    console.print(out[0])
    rendered = console.file.getvalue()
    assert "+new line" in rendered
    assert "-old line" in rendered
    assert "loop.py" in rendered
