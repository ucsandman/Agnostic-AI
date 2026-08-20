"""
tests/test_tools_fixes.py — Regression Tests for Tool-Layer Honesty Fixes
Covers @file secret refusal, exact/unique apply_patch, removed stub tool
registrations, read-only subagent tool subsets, output truncation, preserved
line endings, regex grep with honest caps, and symbol lookup.
"""

import sys
import threading
import time

import pytest

from agent.tools.indexer import CodebaseIndexer
from agent.tools import registry as registry_mod
from agent.tools.registry import ToolRegistry


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / ".env").write_text("OPENAI_API_KEY=sk-live-do-not-leak\n", encoding="utf-8")
    (ws / "notes.txt").write_text("hello\n", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("OUTSIDE_SECRET=1\n", encoding="utf-8")
    return ws


# --- 1. @file expansion must be guarded ---


def test_resolve_file_refuses_secret_files(workspace):
    indexer = CodebaseIndexer(workspace_root=str(workspace))
    res = indexer.resolve_file(".env")
    assert res is not None
    _, content = res
    assert "refused" in content.lower()
    assert "sk-live-do-not-leak" not in content


def test_resolve_file_refuses_out_of_workspace(workspace):
    indexer = CodebaseIndexer(workspace_root=str(workspace))
    res = indexer.resolve_file("../outside.txt")
    assert res is not None
    _, content = res
    assert "refused" in content.lower()
    assert "OUTSIDE_SECRET" not in content


def test_resolve_file_still_reads_normal_files(workspace):
    indexer = CodebaseIndexer(workspace_root=str(workspace))
    res = indexer.resolve_file("notes.txt")
    assert res is not None
    assert res[1] == "hello\n"


# --- 2. apply_patch must match exactly and uniquely ---

ORIGINAL = "def f():\n    return 1\n\n\ndef g():\n    return 2\n"


def _patch_tool(workspace, patch, file_name="mod.py"):
    target = workspace / file_name
    reg = ToolRegistry(workspace_root=str(workspace))
    res = reg.execute("apply_patch", {"file_path": file_name, "patch_content": patch})
    return res, target.read_text(encoding="utf-8")


def test_apply_patch_zero_match_fails_and_does_not_write(workspace):
    (workspace / "mod.py").write_text(ORIGINAL, encoding="utf-8")
    patch = "@@\n def f():\n-    return 999\n+    return 42\n"
    res, after = _patch_tool(workspace, patch)
    assert res.is_error is True
    assert "success" not in res.output.lower()
    assert after == ORIGINAL


def test_apply_patch_unique_match_writes_correctly(workspace):
    (workspace / "mod.py").write_text(ORIGINAL, encoding="utf-8")
    patch = "@@\n def f():\n-    return 1\n+    return 42\n"
    res, after = _patch_tool(workspace, patch)
    assert res.is_error is False, res.output
    assert after == "def f():\n    return 42\n\n\ndef g():\n    return 2\n"


def test_apply_patch_ignores_indentation_only_matches(workspace):
    """A removed line whose indentation does not match must NOT be applied."""
    (workspace / "mod.py").write_text(ORIGINAL, encoding="utf-8")
    patch = "@@\n def f():\n-return 1\n+return 42\n"
    res, after = _patch_tool(workspace, patch)
    assert res.is_error is True
    assert after == ORIGINAL


def test_apply_patch_duplicate_block_refuses(workspace):
    dup = "def f():\n    return 1\n\n\ndef f():\n    return 1\n"
    (workspace / "dup.py").write_text(dup, encoding="utf-8")
    patch = "@@\n def f():\n-    return 1\n+    return 42\n"
    res, after = _patch_tool(workspace, patch, file_name="dup.py")
    assert res.is_error is True
    assert "unique" in res.output.lower() or "occurrence" in res.output.lower()
    assert after == dup


def test_apply_patch_search_replace_duplicate_refuses(workspace):
    dup = "alpha\nbeta\nalpha\n"
    (workspace / "dup.txt").write_text(dup, encoding="utf-8")
    patch = "<<<<<<< SEARCH\nalpha\n=======\ngamma\n>>>>>>> REPLACE"
    res, after = _patch_tool(workspace, patch, file_name="dup.txt")
    assert res.is_error is True
    assert after == dup


# --- 3. Stub tools must not be advertised ---

REMOVED_STUBS = {
    "call_mcp_tool",
    "send_message",
    "define_subagent",
    "schedule",
    "manage_task",
    # Tools the model could never use successfully: no input channel, no reader,
    # no working action.
    "ask_question",
    "generate_artifact",
    "manage_subagents",
}


def test_stub_tools_are_not_registered(workspace):
    reg = ToolRegistry(workspace_root=str(workspace))
    names = {t["function"]["name"] for t in reg.get_openai_tools()}
    assert REMOVED_STUBS.isdisjoint(names), f"stubs still registered: {REMOVED_STUBS & names}"
    assert "read_file" in names and "apply_patch" in names


# --- 4. Non-implementer subagents get a read-only registry ---


def test_researcher_subagent_registry_is_read_only(tmp_path):
    from agent.tools.subagent import SubagentWorker

    worker = SubagentWorker(
        role="researcher",
        system_prompt="",
        client=None,
        workspace_root=tmp_path,
    )
    names = {t["function"]["name"] for t in worker.build_registry().get_openai_tools()}
    assert "write_file" not in names
    assert "run_command" not in names
    assert "apply_patch" not in names
    assert "edit_file" not in names
    assert "read_file" in names
    assert "grep_search" in names


def test_implementer_subagent_without_confirm_callback_is_read_only(tmp_path):
    from agent.tools.subagent import SubagentWorker

    worker = SubagentWorker(
        role="tester",
        system_prompt="",
        client=None,
        workspace_root=tmp_path,
    )
    names = {t["function"]["name"] for t in worker.build_registry().get_openai_tools()}
    assert "run_command" not in names
    assert "write_file" not in names


def test_implementer_subagent_with_confirm_callback_gets_full_toolset(tmp_path):
    from agent.tools.subagent import SubagentWorker

    worker = SubagentWorker(
        role="tester",
        system_prompt="",
        client=None,
        workspace_root=tmp_path,
        confirm_callback=lambda _msg: True,
    )
    names = {t["function"]["name"] for t in worker.build_registry().get_openai_tools()}
    assert "run_command" in names
    assert "write_file" in names


# --- 6. apply_patch matching is line-anchored ---


def test_apply_patch_does_not_match_mid_line(workspace):
    """A removed line must match whole lines, never a fragment of a longer line."""
    src = "class A:\n    def __init__(self):\n        self.total = 1\n"
    (workspace / "midline.py").write_text(src, encoding="utf-8")
    patch = "@@\n-total = 1\n+total = 2\n"
    res, after = _patch_tool(workspace, patch, file_name="midline.py")
    assert res.is_error is True
    assert after == src


def test_apply_patch_uniqueness_ignores_mid_line_occurrences(workspace):
    """A whole-line match stays unique even when the text recurs inside another line."""
    src = "x = 1\nself.x = 1\n"
    (workspace / "uniq.py").write_text(src, encoding="utf-8")
    patch = "@@\n-x = 1\n+x = 2\n"
    res, after = _patch_tool(workspace, patch, file_name="uniq.py")
    assert res.is_error is False, res.output
    assert after == "x = 2\nself.x = 1\n"


# --- 7. Presentation must never fail a tool ---


def _break_console(monkeypatch):
    """Simulate a cp1252 stdout that cannot encode the diff card's emoji."""
    import rich.console

    def _boom(self, *_args, **_kwargs):
        raise UnicodeEncodeError("charmap", "\u2705", 0, 1, "character maps to <undefined>")

    monkeypatch.setattr(rich.console.Console, "print", _boom)


def test_apply_patch_survives_console_encoding_error(workspace, monkeypatch):
    (workspace / "mod.py").write_text(ORIGINAL, encoding="utf-8")
    _break_console(monkeypatch)
    patch = "@@\n def f():\n-    return 1\n+    return 42\n"
    res, after = _patch_tool(workspace, patch)
    assert res.is_error is False, res.output
    assert after == "def f():\n    return 42\n\n\ndef g():\n    return 2\n"


def test_write_and_edit_survive_console_encoding_error(workspace, monkeypatch):
    reg = ToolRegistry(workspace_root=str(workspace))
    reg.execute("write_file", {"file_path": "mod.py", "content": ORIGINAL})
    _break_console(monkeypatch)

    res = reg.execute("write_file", {"file_path": "mod.py", "content": "def f():\n    return 3\n"})
    assert res.is_error is False, res.output

    res = reg.execute(
        "edit_file",
        {
            "file_path": "mod.py",
            "target_content": "return 3",
            "replacement_content": "return 4",
        },
    )
    assert res.is_error is False, res.output
    assert (workspace / "mod.py").read_text(encoding="utf-8") == "def f():\n    return 4\n"


# --- 8. The confirm channel must stay live after construction ---


def test_agent_loop_passes_a_live_confirm_callback_to_subagents(tmp_path):
    from agent.loop import AgentLoop
    from agent.tools.subagent import SubagentWorker

    agent = AgentLoop(workspace_root=str(tmp_path))
    seen = []
    # The TUI patches confirm_callback AFTER construction; the subagent manager
    # must honour the replacement, not the callback captured at __init__ time.
    agent.confirm_callback = lambda prompt: seen.append(prompt) or True

    cb = agent.subagents.confirm_callback
    assert cb is not None, "subagent manager must receive a confirm channel"
    assert cb("proceed?") is True
    assert seen == ["proceed?"]

    worker = SubagentWorker(
        role="tester",
        system_prompt="",
        client=None,
        workspace_root=tmp_path,
        confirm_callback=cb,
    )
    names = {t["function"]["name"] for t in worker.build_registry().get_openai_tools()}
    assert "run_command" in names
    assert "write_file" in names


def test_swarm_worktree_manager_inherits_the_confirm_callback(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from agent.workflows import swarm as swarm_mod

    created = []

    class RecordingManager:
        def __init__(self, client=None, workspace_root=None, confirm_callback=None):
            created.append(confirm_callback)

        def spawn(self, role, prompt):
            return f"report from {role}"

    monkeypatch.setattr(swarm_mod, "SubagentManager", RecordingManager)

    def _confirm(_prompt):
        return True

    parent = SimpleNamespace(workspace_root=tmp_path, confirm_callback=_confirm)
    client = SimpleNamespace(
        chat_completion=lambda _messages: SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="plan"))]
        )
    )
    coord = swarm_mod.SwarmCoordinator(parent, client)
    monkeypatch.setattr(coord, "_create_isolated_worktree", lambda role: tmp_path)
    monkeypatch.setattr(coord, "_cleanup_worktree", lambda wt: None)

    coord.dispatch_swarm("do a thing", use_worktrees=True)
    assert created == [_confirm, _confirm, _confirm]


# --- 9. grep/find must not walk vendored dependency trees ---


def _ignored_dir_workspace(tmp_path):
    ws = tmp_path / "ws"
    (ws / "node_modules").mkdir(parents=True)
    (ws / "node_modules" / "x.js").write_text("needle_pattern\n", encoding="utf-8")
    (ws / "src").mkdir()
    (ws / "src" / "app.js").write_text("needle_pattern\n", encoding="utf-8")
    return ws


def test_grep_search_skips_ignored_dirs(tmp_path, monkeypatch):
    ws = _ignored_dir_workspace(tmp_path)
    monkeypatch.setattr(registry_mod.guard, "workspace_root", ws.resolve())
    reg = ToolRegistry(workspace_root=str(ws))
    out = reg.execute("grep_search", {"query": "needle_pattern"}).output
    assert "app.js" in out
    assert "node_modules" not in out


def test_find_files_skips_ignored_dirs(tmp_path, monkeypatch):
    ws = _ignored_dir_workspace(tmp_path)
    monkeypatch.setattr(registry_mod.guard, "workspace_root", ws.resolve())
    reg = ToolRegistry(workspace_root=str(ws))
    out = reg.execute("find_files", {"pattern": "**/*.js"}).output
    assert "app.js" in out
    assert "node_modules" not in out


# --- 10. indexer reuses one SafetyGuard per workspace root ---


def test_indexer_guard_is_cached_per_root(tmp_path, workspace):
    from agent.tools.indexer import _guard_for_root

    a1 = _guard_for_root(str(workspace))
    a2 = _guard_for_root(str(workspace))
    other = tmp_path / "other"
    other.mkdir()
    b1 = _guard_for_root(str(other))
    assert a1 is a2
    assert a1 is not b1


# --- 11. Read-only tool output is truncated to head and tail ---

BIG_FILE = "".join(f"x{i} = {i}\n" for i in range(400))


def test_read_file_truncates_long_output(workspace):
    (workspace / "big.py").write_text(BIG_FILE, encoding="utf-8")
    reg = ToolRegistry(workspace_root=str(workspace))
    out = reg.execute("read_file", {"file_path": "big.py"}).output
    assert "Truncated" in out, "read_file must truncate a 400-line file"
    assert len(out.splitlines()) < 120
    assert "x0 = 0" in out and "x399 = 399" in out


def test_read_file_line_range_is_never_truncated(workspace):
    """An explicit start/end range is the model paging deliberately — hand it back whole."""
    (workspace / "big.py").write_text(BIG_FILE, encoding="utf-8")
    reg = ToolRegistry(workspace_root=str(workspace))
    out = reg.execute("read_file", {"file_path": "big.py", "start_line": 1, "end_line": 200}).output
    assert "Truncated" not in out
    assert len(out.splitlines()) == 200


# --- 12. File edits must not rewrite the file's line endings ---


def test_edit_file_preserves_lf_line_endings(workspace):
    p = workspace / "lf.txt"
    p.write_bytes(b"alpha\nbeta\ngamma\n")
    reg = ToolRegistry(workspace_root=str(workspace))
    res = reg.execute(
        "edit_file",
        {"file_path": "lf.txt", "target_content": "beta", "replacement_content": "BETA"},
    )
    assert res.is_error is False, res.output
    assert p.read_bytes() == b"alpha\nBETA\ngamma\n"


def test_edit_file_matches_an_lf_target_against_a_crlf_file(workspace):
    """The model always emits \\n; a CRLF file must still match and stay CRLF."""
    p = workspace / "crlf.txt"
    p.write_bytes(b"alpha\r\nbeta\r\ngamma\r\n")
    reg = ToolRegistry(workspace_root=str(workspace))
    res = reg.execute(
        "edit_file",
        {
            "file_path": "crlf.txt",
            "target_content": "alpha\nbeta",
            "replacement_content": "alpha\nBETA",
        },
    )
    assert res.is_error is False, res.output
    assert p.read_bytes() == b"alpha\r\nBETA\r\ngamma\r\n"


def test_apply_patch_preserves_lf_line_endings(workspace):
    p = workspace / "mod.py"
    p.write_bytes(b"def f():\n    return 1\n")
    reg = ToolRegistry(workspace_root=str(workspace))
    res = reg.execute(
        "apply_patch",
        {"file_path": "mod.py", "patch_content": "@@\n def f():\n-    return 1\n+    return 42\n"},
    )
    assert res.is_error is False, res.output
    assert p.read_bytes() == b"def f():\n    return 42\n"


def test_undo_rollback_restores_the_original_bytes(workspace):
    from agent.governance.undo import undo_manager

    p = workspace / "lf.txt"
    p.write_bytes(b"alpha\nbeta\ngamma\n")
    reg = ToolRegistry(workspace_root=str(workspace))
    undo_manager.history.clear()
    reg.execute("write_file", {"file_path": "lf.txt", "content": "alpha\nBETA\ngamma\n"})
    ok, msg = undo_manager.rollback_last()
    assert ok, msg
    assert p.read_bytes() == b"alpha\nbeta\ngamma\n"


# --- 13. The undo history covers a full write-then-edit turn ---


def test_write_then_edit_rolls_back_in_reverse_order(workspace):
    from agent.governance.undo import undo_manager

    (workspace / "existing.txt").write_bytes(b"old\n")
    reg = ToolRegistry(workspace_root=str(workspace))
    undo_manager.history.clear()

    assert not reg.execute("write_file", {"file_path": "created.txt", "content": "new\n"}).is_error
    assert not reg.execute(
        "edit_file",
        {"file_path": "existing.txt", "target_content": "old", "replacement_content": "changed"},
    ).is_error
    assert len(undo_manager.history) == 2

    ok, msg = undo_manager.rollback_last()
    assert ok, msg
    assert (workspace / "existing.txt").read_bytes() == b"old\n"

    ok, msg = undo_manager.rollback_last()
    assert ok, msg
    assert not (workspace / "created.txt").exists()


# --- 14. grep_search is a real regex search with honest caps ---


def _grep_workspace(tmp_path, monkeypatch):
    ws = tmp_path / "gws"
    ws.mkdir()
    monkeypatch.setattr(registry_mod.guard, "workspace_root", ws.resolve())
    return ws


def test_grep_search_matches_a_regex_and_names_the_mode(tmp_path, monkeypatch):
    ws = _grep_workspace(tmp_path, monkeypatch)
    (ws / "src.py").write_text("alpha1\nbeta\nalpha2\n", encoding="utf-8")
    reg = ToolRegistry(workspace_root=str(ws))
    out = reg.execute("grep_search", {"query": r"alpha\d"}).output
    assert "alpha1" in out and "alpha2" in out
    assert "beta" not in out
    assert "regex" in out.lower()


def test_grep_search_falls_back_to_literal_on_an_invalid_regex(tmp_path, monkeypatch):
    ws = _grep_workspace(tmp_path, monkeypatch)
    (ws / "src.py").write_text("a+b = 3\n", encoding="utf-8")
    reg = ToolRegistry(workspace_root=str(ws))
    out = reg.execute("grep_search", {"query": "+b"}).output
    assert "a+b = 3" in out
    assert "literal" in out.lower()


def test_grep_search_reports_hitting_the_result_cap(tmp_path, monkeypatch):
    ws = _grep_workspace(tmp_path, monkeypatch)
    (ws / "many.txt").write_text("needle\n" * 60, encoding="utf-8")
    reg = ToolRegistry(workspace_root=str(ws))
    out = reg.execute("grep_search", {"query": "needle"}).output
    assert "stopped at 40 results" in out


def test_find_files_reports_hitting_the_result_cap(tmp_path, monkeypatch):
    ws = _grep_workspace(tmp_path, monkeypatch)
    for i in range(60):
        (ws / "f{0}.txt".format(i)).write_text("x", encoding="utf-8")
    reg = ToolRegistry(workspace_root=str(ws))
    out = reg.execute("find_files", {"pattern": "**/*.txt"}).output
    assert "stopped at 50 results" in out


# --- 15. find_symbol resolves a symbol out of the AST index ---


def test_find_symbol_returns_location_and_snippet(tmp_path, monkeypatch):
    ws = _grep_workspace(tmp_path, monkeypatch)
    (ws / "mod.py").write_text(
        "def helper():\n    return 7\n\n\nclass Widget:\n    pass\n", encoding="utf-8"
    )
    reg = ToolRegistry(workspace_root=str(ws))
    out = reg.execute("find_symbol", {"name": "Widget"}).output
    assert "mod.py:5-6" in out
    assert "class Widget:" in out

    near = reg.execute("find_symbol", {"name": "help"}).output
    assert "helper" in near


# --- 16. run_command honours the cooperative cancel event ---


def test_run_command_is_killed_when_the_cancel_event_is_set(tmp_path):
    cancel = threading.Event()
    reg = ToolRegistry(workspace_root=str(tmp_path), cancel_event=cancel)
    timer = threading.Timer(0.5, cancel.set)
    timer.start()
    try:
        started = time.monotonic()
        res = reg._tool_run_command(
            {"command": '{0} -c "import time; time.sleep(30)"'.format(sys.executable)}
        )
        elapsed = time.monotonic() - started
    finally:
        timer.cancel()

    assert res.is_error and "cancelled" in res.output
    assert elapsed < 10, "cancel must kill the child, not wait it out ({0:.1f}s)".format(elapsed)


# --- 17. A successful .py write carries advisory lint output ---


def _lint_workspace(tmp_path, monkeypatch):
    ws = tmp_path / "lws"
    ws.mkdir()
    monkeypatch.setattr(registry_mod.guard, "workspace_root", ws.resolve())
    return ws


def test_edit_file_appends_advisory_lint_output(tmp_path, monkeypatch):
    ws = _lint_workspace(tmp_path, monkeypatch)
    (ws / "mod.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(
        registry_mod.interceptor, "run_quick_lint", lambda path, root: (False, "E999 boom")
    )
    reg = ToolRegistry(workspace_root=str(ws))

    out = reg._tool_edit_file(
        {"file_path": "mod.py", "target_content": "x = 1", "replacement_content": "x = 2"}
    ).output

    assert "Successfully replaced" in out
    assert "[lint] E999 boom" in out
    assert (ws / "mod.py").read_text(encoding="utf-8") == "x = 2\n", "lint stays advisory"


def test_write_file_does_not_lint_a_non_python_file(tmp_path, monkeypatch):
    ws = _lint_workspace(tmp_path, monkeypatch)
    linted = []
    monkeypatch.setattr(
        registry_mod.interceptor,
        "run_quick_lint",
        lambda path, root: (linted.append(path), (True, None))[1],
    )
    reg = ToolRegistry(workspace_root=str(ws))

    out = reg._tool_write_file({"file_path": "notes.txt", "content": "hi\n"}).output

    assert "Successfully wrote" in out and "[lint]" not in out
    assert linted == [], "ruff must stay off the hot path for non-Python files"


# --- 18. run_command streams its output line by line ---


def test_run_command_streams_each_line_while_the_command_runs(tmp_path):
    """A long build used to sit silent until it finished; the UI needs the lines
    as they are printed, and the returned ToolResult must still carry them all."""
    seen = []
    reg = ToolRegistry(
        workspace_root=str(tmp_path),
        on_output=lambda line: seen.append((line, time.monotonic())),
    )
    script = (
        "import time; [(print('line' + str(i), flush=True), time.sleep(0.3)) for i in range(3)]"
    )

    res = reg._tool_run_command({"command": '{0} -c "{1}"'.format(sys.executable, script)})

    assert [line for line, _ in seen] == ["line0", "line1", "line2"]
    assert seen[-1][1] - seen[0][1] > 0.3, "lines must stream, not arrive in one dump at the end"
    assert "line0" in res.output and "line2" in res.output, "the full output is still returned"


# --- 19. /schedule can list and stop the routines it started ---


def test_schedule_list_and_stop_report_and_cancel_a_routine():
    from agent.workflows.scheduler import TaskScheduler

    sched = TaskScheduler()
    assert "No scheduled" in sched.parse_and_schedule("/schedule list", lambda p: None)

    sched.parse_and_schedule('/schedule every 1h "run pytest"', lambda p: None)
    task_id = next(iter(sched.tasks))
    task = sched.tasks[task_id]

    rows = sched.list_tasks()
    assert [r["id"] for r in rows] == [task_id]
    assert rows[0]["every"] == "3600s"
    assert rows[0]["prompt"] == "run pytest"
    assert rows[0]["running"] is True

    listing = sched.parse_and_schedule("/schedule list", lambda p: None)
    assert task_id in listing and "run pytest" in listing

    assert sched.cancel_task(task_id) is True
    assert task.stop_event.is_set()
    assert sched.tasks == {}
    assert sched.cancel_task(task_id) is False


def test_schedule_stop_all_cancels_every_routine():
    from agent.workflows.scheduler import TaskScheduler

    sched = TaskScheduler()
    sched.parse_and_schedule('/schedule every 1h "a"', lambda p: None)
    sched.parse_and_schedule('/schedule every 2h "b"', lambda p: None)
    started = list(sched.tasks.values())

    msg = sched.parse_and_schedule("/schedule stop all", lambda p: None)

    assert "2" in msg
    assert all(t.stop_event.is_set() for t in started)
    assert sched.tasks == {}
