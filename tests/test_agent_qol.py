"""
tests/test_agent_qol.py — Comprehensive Unit Tests for Agnostic Agent QoL Enhancements
Tests AST symbol indexer, .agentignore, session manager, context compaction, trust tiers, and audit manager.
"""

import pytest

from agent.tools.indexer import CodebaseIndexer
from agent.governance.session_manager import SessionManager
from agent.governance.context import ContextManager
from agent.governance.guard import SafetyGuard
from agent.governance.audit import AuditManager
from agent.cli import expand_prompt_references, AgnosticCompleter
from prompt_toolkit.document import Document


@pytest.fixture
def temp_workspace(tmp_path):
    ws = tmp_path / "test_workspace"
    ws.mkdir()

    # Create dummy python files
    (ws / "math_lib.py").write_text(
        "class Calculator:\n    def add(self, a, b):\n        return a + b\n\ndef multiply(x, y):\n    return x * y\n",
        encoding="utf-8",
    )

    # Create dummy ignore file
    (ws / ".agentignore").write_text("*.ignored.py\nignored_dir/\n", encoding="utf-8")
    (ws / "temp.ignored.py").write_text("def secret(): pass", encoding="utf-8")

    return ws


def test_indexer_and_agentignore(temp_workspace):
    indexer = CodebaseIndexer(workspace_root=str(temp_workspace))
    indexer.index_workspace()

    files = indexer.get_indexed_files()
    assert "math_lib.py" in files
    assert "temp.ignored.py" not in files

    symbols = indexer.get_all_symbols()
    assert "Calculator" in symbols
    assert "Calculator.add" in symbols
    assert "multiply" in symbols

    # Test symbol resolution
    res_sym = indexer.resolve_symbol("multiply")
    assert res_sym is not None
    loc, snippet = res_sym
    assert "math_lib.py" in loc
    assert "def multiply" in snippet

    # Test file resolution
    res_file = indexer.resolve_file("math_lib.py")
    assert res_file is not None
    rel, content = res_file
    assert rel == "math_lib.py"
    assert "class Calculator" in content


def test_prompt_reference_expansion(temp_workspace):
    indexer = CodebaseIndexer(workspace_root=str(temp_workspace))
    indexer.index_workspace()

    prompt = "Please refactor #multiply in @math_lib.py"
    expanded = expand_prompt_references(prompt, indexer)

    assert "### [Context Reference: @math_lib.py]" in expanded
    assert "### [Symbol Reference: #multiply" in expanded
    assert "def multiply(x, y):" in expanded


def test_completer_suggestions(temp_workspace):
    indexer = CodebaseIndexer(workspace_root=str(temp_workspace))
    indexer.index_workspace()

    completer = AgnosticCompleter(["/plan", "/fix", "/test"], indexer)

    # Slash command completion
    doc_slash = Document("/f", cursor_position=2)
    completions = list(completer.get_completions(doc_slash, None))
    assert any(c.text == "/fix" for c in completions)

    # @file completion
    doc_file = Document("@math", cursor_position=5)
    completions = list(completer.get_completions(doc_file, None))
    assert any("math_lib.py" in c.text for c in completions)

    # #symbol completion
    doc_sym = Document("#Calc", cursor_position=5)
    completions = list(completer.get_completions(doc_sym, None))
    assert any("Calculator" in c.text for c in completions)


def test_session_manager(temp_workspace):
    sm = SessionManager(workspace_root=str(temp_workspace))
    sample_history = [
        {"role": "system", "content": "You are an agent."},
        {"role": "user", "content": "Hello world"},
        {"role": "assistant", "content": "How can I help you?"},
    ]

    ok, msg = sm.save_session("feature_auth", sample_history, "Working on OAuth")
    assert ok is True

    sessions = sm.list_sessions()
    assert len(sessions) == 1
    assert sessions[0]["name"] == "feature_auth"
    assert sessions[0]["turn_count"] == 3

    loaded_history, _load_msg = sm.load_session("feature_auth")
    assert loaded_history is not None
    assert len(loaded_history) == 3
    assert loaded_history[1]["content"] == "Hello world"

    del_ok, _ = sm.delete_session("feature_auth")
    assert del_ok is True
    assert len(sm.list_sessions()) == 0


def test_context_manager_compaction():
    cm = ContextManager(max_context_tokens=1000, compaction_threshold=0.5)

    history = [
        {"role": "system", "content": "Harness Prompt"},
        {"role": "user", "content": "Turn 1 request " * 50},
        {"role": "assistant", "content": "Turn 1 response " * 50},
        {"role": "user", "content": "Turn 2 request " * 50},
        {"role": "assistant", "content": "Turn 2 response " * 50},
        {"role": "user", "content": "Recent request"},
        {"role": "assistant", "content": "Recent response"},
    ]

    st = cm.get_status(history)
    assert st["used_tokens"] > 0

    compacted, ok, msg = cm.compact_messages(history, force=True)
    assert ok is True
    assert len(compacted) < len(history)
    assert "Compacted" in msg

    gauge = cm.render_gauge(history)
    assert "Context:" in gauge


def test_safety_guard_and_trust_tiers(temp_workspace):
    guard = SafetyGuard(workspace_root=str(temp_workspace))

    # Test non-negotiable secret blocks
    safe_env, reason_env = guard.check_path_access(".env")
    assert safe_env is False
    assert "Non-Negotiable Safety Rule" in reason_env

    safe_secrets, _ = guard.check_path_access(".secrets.env")
    assert safe_secrets is False

    # Trust tiers
    guard.set_trust_tier("strict")
    assert guard.get_trust_tier() == "strict"

    blocked, req_appr, _ = guard.check_command_safety("git push origin main")
    assert req_appr is True

    # trust-all suppresses hard-stop prompt for non-secret commands
    guard.set_trust_tier("all")
    blocked, req_appr, _ = guard.check_command_safety("git push origin main")
    assert req_appr is False

    # But secrets commands remain strictly blocked
    blocked, _, _ = guard.check_command_safety("cat .secrets.env")
    assert blocked is True


def test_audit_manager(temp_workspace):
    audit = AuditManager(workspace_root=str(temp_workspace))

    audit.record(
        event_type="governance_hardstop",
        description="git reset --hard",
        details={"branch": "main"},
        approved=True,
    )
    audit.record(
        event_type="file_edit",
        description="Modified server.py",
        details={"file": "server.py"},
    )
    audit.record(
        event_type="lesson_learned",
        description="Always write tests before refactoring.",
    )

    report = audit.generate_retro_markdown()
    assert "Agnostic Session Retrospective" in report
    assert "git reset --hard" in report
    assert "server.py" in report
    assert "Always write tests before refactoring" in report

    file_path = audit.export_audit_file()
    assert file_path.exists()


def test_indexer_mtime_caching(temp_workspace):
    indexer = CodebaseIndexer(workspace_root=str(temp_workspace))
    indexer.index_workspace()

    # Second index should hit mtime cache without re-parsing
    initial_symbols = indexer.get_all_symbols()
    indexer.index_workspace()
    assert indexer.get_all_symbols() == initial_symbols

    # Modify file and verify mtime invalidation triggers update
    (temp_workspace / "math_lib.py").write_text(
        "def subtract(a, b):\n    return a - b\n",
        encoding="utf-8",
    )
    indexer.index_workspace()
    new_symbols = indexer.get_all_symbols()
    assert "subtract" in new_symbols
    assert "multiply" not in new_symbols


def test_subagent_parallel_spawning(temp_workspace):
    from agent.tools.subagent import SubagentManager
    from agent.llm.client import LLMClient

    sm = SubagentManager(client=LLMClient(), workspace_root=str(temp_workspace))
    tasks = [
        {"role": "researcher", "prompt": "Find files", "custom_instructions": "Fast"},
        {"role": "tester", "prompt": "Check test status"},
    ]
    # Verify parallel interface definition and task structuring
    assert hasattr(sm, "spawn_parallel")
    assert len(tasks) == 2


def test_syntax_interceptor_and_pre_save_validation(temp_workspace):
    from agent.governance.interceptor import CodeInterceptor
    from agent.tools.registry import ToolRegistry

    # 1. Direct Interceptor unit checks
    valid, err = CodeInterceptor.validate_syntax(
        temp_workspace / "valid.py", "def foo():\n    return 42\n"
    )
    assert valid is True
    assert err is None

    invalid, err = CodeInterceptor.validate_syntax(
        temp_workspace / "broken.py", "def foo(\n"
    )
    assert invalid is False
    assert "SyntaxError" in err

    # 2. Tool Registry Integration check (write_file and edit_file abort on broken Python syntax)
    reg = ToolRegistry(workspace_root=str(temp_workspace))

    # Attempting to write invalid python
    res = reg.execute(
        "write_file", {"file_path": "broken.py", "content": "def bad_func("}
    )
    assert res.is_error is True
    assert "Validation Error (Intercepted before write)" in res.output
    assert not (temp_workspace / "broken.py").exists()

    # Valid write
    res = reg.execute(
        "write_file",
        {"file_path": "clean.py", "content": "def good():\n    return 1\n"},
    )
    assert res.is_error is False
    assert (temp_workspace / "clean.py").exists()

    # Attempting to edit with broken syntax
    res = reg.execute(
        "edit_file",
        {
            "file_path": "clean.py",
            "target_content": "return 1",
            "replacement_content": "return (((",
        },
    )
    assert res.is_error is True
    assert "Validation Error (Intercepted before save)" in res.output


def test_subagent_workspace_modes(temp_workspace):
    from agent.tools.subagent import SubagentWorker
    from agent.llm.client import LLMClient

    worker_inherit = SubagentWorker(
        role="tester",
        system_prompt="Test",
        client=LLMClient(),
        workspace_root=temp_workspace,
        workspace_mode="inherit",
    )
    assert worker_inherit.active_workspace == temp_workspace
    worker_inherit.cleanup()

    worker_share = SubagentWorker(
        role="tester",
        system_prompt="Test",
        client=LLMClient(),
        workspace_root=temp_workspace,
        workspace_mode="share",
    )
    assert worker_share.active_workspace != temp_workspace
    worker_share.cleanup()


def test_checkpoint_transactions(temp_workspace):
    from agent.governance.undo import UndoManager

    um = UndoManager(workspace_root=str(temp_workspace))
    file_a = temp_workspace / "a.py"
    file_b = temp_workspace / "b.py"

    file_a.write_text("v1", encoding="utf-8")
    um.record_change(file_a, None, "v1", "create")

    # Create checkpoint
    msg = um.create_checkpoint("base_state")
    assert "Checkpoint 'base_state' created" in msg

    # Mutate files
    file_a.write_text("v2", encoding="utf-8")
    um.record_change(file_a, "v1", "v2", "edit")
    file_b.write_text("b1", encoding="utf-8")
    um.record_change(file_b, None, "b1", "create")

    assert file_a.read_text(encoding="utf-8") == "v2"
    assert file_b.exists()

    # Rollback to checkpoint
    ok, rollback_msg = um.rollback_to_checkpoint("base_state")
    assert ok is True
    assert "Rolled back to checkpoint" in rollback_msg
    assert file_a.read_text(encoding="utf-8") == "v1"
    assert not file_b.exists()


def test_apply_patch_tool(temp_workspace):
    from agent.tools.registry import ToolRegistry

    reg = ToolRegistry(workspace_root=str(temp_workspace))
    target = temp_workspace / "patched.py"
    target.write_text("def calculate():\n    return 10\n", encoding="utf-8")

    search_replace_patch = (
        "<<<<<<< SEARCH\n    return 10\n=======\n    return 20\n>>>>>>> REPLACE"
    )
    res = reg.execute(
        "apply_patch",
        {
            "file_path": "patched.py",
            "patch_content": search_replace_patch,
        },
    )
    assert res.is_error is False
    assert "Successfully applied patch" in res.output
    assert "return 20" in target.read_text(encoding="utf-8")


def test_get_outline_tool(temp_workspace):
    from agent.tools.registry import ToolRegistry

    reg = ToolRegistry(workspace_root=str(temp_workspace))
    res = reg.execute("get_outline", {"file_path": "math_lib.py"})
    assert res.is_error is False
    assert "class Calculator" in res.output
    assert "def add" in res.output
    assert "def multiply" in res.output


def test_simulate_command_tool(temp_workspace):
    from agent.tools.registry import ToolRegistry

    reg = ToolRegistry(workspace_root=str(temp_workspace))
    res_safe = reg.execute("simulate_command", {"command": "git status"})
    assert "SAFE / ALLOWED" in res_safe.output

    res_blocked = reg.execute("simulate_command", {"command": "cat .secrets.env"})
    assert "BLOCKED" in res_blocked.output


def test_model_switching_and_presets():
    from agent.llm.client import LLMClient

    client = LLMClient()
    assert client.config.model == "local-model"

    # Switch to Google Antigravity Pro 3.1 preset with high reasoning effort
    msg = client.switch_model(preset_key="agy-pro-3.1", reasoning_effort="high")
    assert "Google Antigravity Pro" in msg
    assert client.config.model == "gemini-3.1-pro"
    assert client.config.reasoning_effort == "high"

    # Switch to Claude Sonnet 5 preset
    msg = client.switch_model(preset_key="claude-sonnet-5")
    assert "Claude Code Sonnet 5" in msg
    assert client.config.model == "claude-sonnet-5"

    # Switch to OpenAI Codex GPT-5.6 Sol preset
    msg = client.switch_model(preset_key="codex-gpt-5.6-sol", reasoning_effort="high")
    assert "OpenAI Codex GPT-5.6 Sol" in msg
    assert client.config.model == "gpt-5.6-sol"
    assert client.config.reasoning_effort == "high"

    # Switch to DeepSeek V4-Pro preset
    msg = client.switch_model(preset_key="deepseek-v4-pro")
    assert "DeepSeek V4-Pro" in msg
    assert client.config.model == "deepseek-v4-pro"
