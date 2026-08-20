"""
tests/test_tools_fixes.py — Regression Tests for Tool-Layer Honesty Fixes
Covers @file secret refusal, exact/unique apply_patch, non-fabricated ask_question,
removed stub tool registrations, and read-only subagent tool subsets.
"""

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


# --- 3. ask_question must never fabricate an answer ---


def test_ask_question_does_not_fabricate_selection(workspace):
    reg = ToolRegistry(workspace_root=str(workspace))
    res = reg.execute(
        "ask_question",
        {
            "questions": [
                {
                    "question": "Which database?",
                    "options": ["Postgres", "SQLite"],
                    "is_multi_select": False,
                }
            ]
        },
    )
    out = res.output
    assert '"selected"' not in out
    assert "User responses captured" not in out
    # No option may be echoed back — an echoed option reads as a chosen answer.
    assert "Postgres" not in out and "SQLite" not in out
    assert "Which database?" in out
    assert "no answer" in out.lower() or "not answered" in out.lower()


# --- 4. Stub tools must not be advertised ---

REMOVED_STUBS = {
    "call_mcp_tool",
    "send_message",
    "define_subagent",
    "schedule",
    "manage_task",
}


def test_stub_tools_are_not_registered(workspace):
    reg = ToolRegistry(workspace_root=str(workspace))
    names = {t["function"]["name"] for t in reg.get_openai_tools()}
    assert REMOVED_STUBS.isdisjoint(names), f"stubs still registered: {REMOVED_STUBS & names}"
    assert "read_file" in names and "apply_patch" in names


def test_mcp_bridge_registers_no_fake_tool(workspace):
    from agent.tools.mcp_client import MCPBridge

    reg = ToolRegistry(workspace_root=str(workspace))
    MCPBridge(reg)
    names = {t["function"]["name"] for t in reg.get_openai_tools()}
    assert "call_mcp_tool" not in names


def test_manage_subagents_kill_reports_not_implemented(workspace):
    reg = ToolRegistry(workspace_root=str(workspace))
    res = reg.execute("manage_subagents", {"action": "kill", "conversation_ids": ["x"]})
    assert res.is_error is True
    assert "NOT IMPLEMENTED" in res.output


# --- 5. Non-implementer subagents get a read-only registry ---


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


def test_ask_question_survives_console_encoding_error(workspace, monkeypatch):
    _break_console(monkeypatch)
    reg = ToolRegistry(workspace_root=str(workspace))
    res = reg.execute(
        "ask_question",
        {"questions": [{"question": "Which database?", "options": ["A"]}]},
    )
    assert res.is_error is False, res.output
    assert "no answer" in res.output.lower()


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


# --- 6. grep/find must not walk vendored dependency trees ---


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


# --- 7. indexer reuses one SafetyGuard per workspace root ---


def test_indexer_guard_is_cached_per_root(tmp_path, workspace):
    from agent.tools.indexer import _guard_for_root

    a1 = _guard_for_root(str(workspace))
    a2 = _guard_for_root(str(workspace))
    other = tmp_path / "other"
    other.mkdir()
    b1 = _guard_for_root(str(other))
    assert a1 is a2
    assert a1 is not b1
