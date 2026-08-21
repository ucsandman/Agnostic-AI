"""
tests/test_tui_memory.py — Regression Tests for the /memory slash command
Covers the picker's row labels (newest first, clipped description), the save /
show / forget branches against a real MemoryStore on disk, and the rule that
MemoryStore's own error messages reach the user verbatim instead of a stack trace.
"""

from types import SimpleNamespace

from rich.panel import Panel

from agent import tui_commands
from agent.governance.memory import MAX_BODY_BYTES, MemoryStore
from agent.tui_memory import _memory_rows


class FakeTUI:
    """The mixin's dispatcher over a stub host: same shape as the /compact test in
    tests/test_ui_common.py, plus the workspace_root the memory branch reads."""

    _handle_slash_command = tui_commands.SlashCommandMixin._handle_slash_command
    _show_memory = tui_commands.SlashCommandMixin._show_memory

    def __init__(self, workspace_root):
        self.agent = SimpleNamespace(workspace_root=str(workspace_root))
        self.written = []
        self.pushed = []

    def _write_output(self, *args, **kwargs):
        self.written.append(args[0])

    def push_screen(self, screen, callback=None):
        self.pushed.append((screen, callback))


def _plain(written):
    return "\n".join(
        r.renderable.plain if isinstance(r, Panel) else getattr(r, "plain", str(r)) for r in written
    )


def _app(tmp_path):
    return FakeTUI(tmp_path)


# --- the picker's rows ------------------------------------------------------------


def test_memory_rows_are_newest_first_and_clip_the_description(tmp_path):
    """store.list() hands memories over oldest first; every picker in this app shows
    newest first. The description is a one-line preview, not the body."""
    store = MemoryStore(str(tmp_path))
    store.save("alpha", "the first fact", "body of alpha")
    store.save("beta", "x" * 200, "body of beta")

    memories = store.list()
    rows = _memory_rows(memories)

    assert [oid for oid, _ in rows] == [m.name for m in reversed(memories)]
    labels = {oid: label.plain for oid, label in rows}
    assert "alpha" in labels and "the first fact" in labels["alpha"]
    assert "project" in labels["alpha"] and memories[0].created in labels["alpha"]
    assert "x" * 60 in labels["beta"] and "x" * 61 not in labels["beta"]


def test_memory_rows_of_an_empty_store_still_offer_a_dismissable_row(tmp_path):
    rows = _memory_rows(MemoryStore(str(tmp_path)).list())
    assert rows[0][0] == "__none__"
    assert rows[0][1].plain == "no memories saved yet"


def test_memory_rows_skip_the_files_that_are_not_memories(tmp_path):
    """A hand-edited file without frontmatter is reported as an index issue; it must
    never reach the picker (and must not crash it)."""
    store = MemoryStore(str(tmp_path))
    store.save("good", "kept", "a real memory")
    (store.memory_dir / "junk.md").write_text("no frontmatter here", encoding="utf-8")

    assert [oid for oid, _ in _memory_rows(store.list())] == ["good"]
    assert "junk.md" in store.index_text()


def test_memory_picker_mounts_and_dismisses_with_the_chosen_name(tmp_path):
    """The rows are pure, but _fill/dismiss are not — one headless walk proves the
    modal really mounts and hands the name back (Esc cancels with None)."""
    import asyncio

    from textual.app import App

    from agent.tui_memory import MemoryPickerScreen

    store = MemoryStore(str(tmp_path))
    store.save("alpha", "the first fact", "body of alpha")
    store.save("beta", "the second fact", "body of beta")
    memories = store.list()
    results = []

    class Host(App):
        def on_mount(self):
            self.push_screen(MemoryPickerScreen(list(memories)), callback=results.append)

    async def drive(keys_to_press):
        results.clear()
        app = Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            for k in keys_to_press:
                await pilot.press(k)
                await pilot.pause()

    asyncio.run(drive(["enter"]))  # first row is the newest memory
    assert results == ["beta"]

    asyncio.run(drive(["escape"]))
    assert results == [None]


# --- the dispatch branches --------------------------------------------------------


def test_bare_memory_opens_the_picker_over_the_saved_memories(tmp_path):
    from agent.tui_memory import MemoryPickerScreen

    MemoryStore(str(tmp_path)).save("alpha", "the first fact", "body of alpha")
    app = _app(tmp_path)

    assert app._handle_slash_command("/memory") is True
    screen, callback = app.pushed[0]
    assert isinstance(screen, MemoryPickerScreen)
    assert callback == app._show_memory
    assert [m.name for m in screen._memories] == ["alpha"]


def test_memory_save_writes_a_file_and_an_index_line(tmp_path):
    app = _app(tmp_path)
    body = "port 7843 is the one\nthe second line stays out of the index"

    assert app._handle_slash_command(f"/memory save dashboard port -- {body}") is True
    assert 'Saved memory "dashboard port"' in _plain(app.written)

    saved = MemoryStore(str(tmp_path)).get("dashboard port")
    assert saved.body == body
    assert saved.description == "port 7843 is the one"  # the first line only
    index = (tmp_path / ".agnostic" / "memory" / "MEMORY.md").read_text(encoding="utf-8")
    assert "- [dashboard port](dashboard-port.md) — port 7843 is the one" in index


def test_memory_save_without_the_separator_prints_the_usage_line(tmp_path):
    app = _app(tmp_path)
    assert app._handle_slash_command("/memory save just-a-name") is True
    assert "Usage: /memory save <name> -- <the thing to remember>" in _plain(app.written)
    assert not (tmp_path / ".agnostic" / "memory").exists()


def test_memory_forget_removes_it_once_and_says_so_the_second_time(tmp_path):
    app = _app(tmp_path)
    MemoryStore(str(tmp_path)).save("stale", "old news", "body")

    assert app._handle_slash_command("/memory forget stale") is True
    assert 'Forgot "stale".' in _plain(app.written)
    assert MemoryStore(str(tmp_path)).get("stale") is None

    app.written.clear()
    assert app._handle_slash_command("/memory forget stale") is True
    assert 'No memory named "stale".' in _plain(app.written)


def test_memory_show_prints_the_body_in_a_panel_or_says_it_is_missing(tmp_path):
    app = _app(tmp_path)
    # '[' in a body is routine (code snippets) and must not reach Rich's markup parser.
    MemoryStore(str(tmp_path)).save("guards", "the policy file", "see guards.json [strict]")

    assert app._handle_slash_command("/memory show guards") is True
    panel = app.written[0]
    assert isinstance(panel, Panel)
    assert panel.renderable.plain == "see guards.json [strict]"
    assert "🧠 guards (project, saved" in panel.title.plain

    app.written.clear()
    assert app._handle_slash_command("/memory show nope") is True
    assert 'No memory named "nope". Try /memory to list them.' in _plain(app.written)


def test_memory_store_errors_reach_the_user_verbatim(tmp_path):
    """MemoryStore's messages are already written for a human — an oversized body, an
    empty one and a name with a path separator must be printed, not swallowed."""
    app = _app(tmp_path)

    assert app._handle_slash_command("/memory save huge -- " + "x" * (MAX_BODY_BYTES + 1)) is True
    assert f"max {MAX_BODY_BYTES}" in _plain(app.written)
    assert "Store the durable fact, not the transcript." in _plain(app.written)

    app.written.clear()
    assert app._handle_slash_command("/memory save ../evil -- anything") is True
    assert "must not contain path separators" in _plain(app.written)

    app.written.clear()
    assert app._handle_slash_command("/memory forget ../evil") is True
    assert "must not contain path separators" in _plain(app.written)


def test_an_unknown_memory_subcommand_lists_all_four_forms(tmp_path):
    app = _app(tmp_path)
    assert app._handle_slash_command("/memory frobnicate") is True
    printed = _plain(app.written)
    for form in ("/memory [list]", "/memory show", "/memory save", "/memory forget"):
        assert form in printed
