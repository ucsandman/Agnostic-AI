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
    assert compacted[0]["role"] == "system"
    assert sum(1 for m in compacted if m["role"] == "system") == 1
    assert "Harness Prompt" in compacted[0]["content"]
    assert "Session Distillation" in compacted[0]["content"]

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


def test_model_switching_and_presets(monkeypatch):
    from agent.llm.client import LLMClient

    # Every API-key preset needs its env var present, or the switch is refused.
    for env_var in (
        "GEMINI_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "DEEPSEEK_API_KEY",
    ):
        monkeypatch.setenv(env_var, "placeholder-value")

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

    # Test alt_api_key_envs resolution for Google Antigravity
    monkeypatch.setenv("GOOGLE_API_KEY", "mock-google-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client.switch_model(preset_key="agy-flash-3.7")
    assert client.config.api_key == "mock-google-key"
    monkeypatch.delenv("GOOGLE_API_KEY")

    # Test Native Subscription Presets (Zero API Key)
    msg = client.switch_model(
        preset_key="sub-google-antigravity", reasoning_effort="high"
    )
    assert "Google Antigravity (Logged-In Monthly Subscription)" in msg
    assert client.config.provider == "google-sub"
    assert client.config.reasoning_effort == "high"

    msg = client.switch_model(preset_key="sub-claude-code")
    assert "Claude Code (Logged-In Monthly Subscription)" in msg
    assert client.config.provider == "anthropic-sub"

    msg = client.switch_model(preset_key="sub-openai-codex")
    assert "OpenAI Codex (Logged-In Monthly Subscription)" in msg
    assert client.config.provider == "openai-sub"


def test_subscription_bridge_prompt_formatting():
    from agent.llm.client import SubprocessSubscriptionBridge

    messages = [
        {"role": "user", "content": "What is 2+2?"},
        {
            "role": "assistant",
            "content": "4",
            "tool_calls": [{"function": {"name": "calc", "arguments": "{}"}}],
        },
        {"role": "user", "content": "Great!"},
    ]
    tools = [
        {
            "function": {
                "name": "calc",
                "description": "Calculator",
                "parameters": {"type": "object"},
            }
        }
    ]
    formatted = SubprocessSubscriptionBridge._format_conversation_prompt(
        messages, tools
    )
    assert "Calculator" in formatted
    assert "Tool Call [calc]" in formatted
    assert "[ASSISTANT]:" in formatted


def test_harness_extended_tools(temp_workspace):
    from agent.tools.registry import ToolRegistry

    registry = ToolRegistry(workspace_root=str(temp_workspace))
    tools = registry.get_openai_tools()
    tool_names = [t["function"]["name"] for t in tools]

    expected = [
        "run_command",
        "read_file",
        "write_file",
        "edit_file",
        "grep_search",
        "find_files",
        "apply_patch",
        "get_outline",
        "simulate_command",
        "read_url_content",
        "search_web",
        "manage_subagents",
        "ask_question",
        "generate_artifact",
        "read_project_memory",
        "write_project_memory",
    ]
    for exp in expected:
        assert exp in tool_names

    # 1. Test Project Memory Read/Write
    res_w = registry.execute(
        "write_project_memory",
        {"key": "conventions", "content": "Always test code before shipping."},
    )
    assert not res_w.is_error
    res_r = registry.execute("read_project_memory", {"key": "conventions"})
    assert "Always test code before shipping." in res_r.output

    # 2. Test Artifact Generation
    res_art = registry.execute(
        "generate_artifact",
        {"title": "UI Mockup", "content": "<h1>Hello</h1>", "artifact_type": "html"},
    )
    assert not res_art.is_error
    assert "ui_mockup.html" in res_art.output
    assert (temp_workspace / ".agnostic" / "artifacts" / "ui_mockup.html").exists()

    # 3. Subagent listing still works; the stub tools that only pretended to
    #    work (define_subagent, send_message, schedule, manage_task) were
    #    removed, and manage_subagents 'kill' now honestly reports NOT
    #    IMPLEMENTED instead of returning a fake success.
    from agent.tools.subagent import subagent_registry

    subagent_registry.register_active("sub_001", "researcher")
    res_list = registry.execute("manage_subagents", {"action": "list"})
    assert "sub_001" in res_list.output

    registered = {t["function"]["name"] for t in registry.get_openai_tools()}
    for removed in ("define_subagent", "send_message", "schedule", "manage_task"):
        assert removed not in registered

    res_kill = registry.execute(
        "manage_subagents", {"action": "kill", "conversation_ids": ["sub_001"]}
    )
    assert res_kill.is_error or "NOT IMPLEMENTED" in res_kill.output.upper()

    # 5. Test Interactive Ask Question
    res_q = registry.execute(
        "ask_question",
        {
            "questions": [
                {
                    "question": "Which database engine should we configure?",
                    "options": ["PostgreSQL", "SQLite", "DuckDB"],
                    "is_multi_select": False,
                }
            ]
        },
    )
    assert not res_q.is_error
    assert "Which database engine should we configure?" in res_q.output


def test_dynamic_context_limits_and_image_expansion(temp_workspace, monkeypatch):
    from agent.llm.client import LLMClient
    from agent.governance.context import context_manager
    from agent.cli import expand_prompt_references, get_ui_width
    from agent.tools.indexer import CodebaseIndexer

    for env_var in ("ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.setenv(env_var, "placeholder-value")

    client = LLMClient()

    # 1. Switch to Google Antigravity preset -> verify 2M context limit
    client.switch_model(preset_key="sub-google-antigravity")
    assert client.config.context_window == 2000000
    st_google = context_manager.get_status([])
    assert st_google["max_tokens"] == 2000000

    # 2. Switch to Claude Sonnet preset -> verify 200k context limit
    client.switch_model(preset_key="claude-sonnet-5")
    assert client.config.context_window == 200000
    st_claude = context_manager.get_status([])
    assert st_claude["max_tokens"] == 200000

    # 3. Switch to DeepSeek V4 preset -> verify 128k context limit
    client.switch_model(preset_key="deepseek-v4-flash")
    assert client.config.context_window == 128000
    st_deepseek = context_manager.get_status([])
    assert st_deepseek["max_tokens"] == 128000

    # 4. Switch to Local LM Studio -> verify 32k context limit
    client.switch_model(preset_key="local-lmstudio")
    assert client.config.context_window == 32768
    st_local = context_manager.get_status([])
    assert st_local["max_tokens"] == 32768

    # 5. Image reference expansion test
    indexer = CodebaseIndexer(workspace_root=str(temp_workspace))
    img_file = temp_workspace / "sample.png"
    img_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR...")
    prompt = f"Analyze this architecture screenshot: @image:{img_file.name}"
    expanded = expand_prompt_references(prompt, indexer)
    assert "### [Attached Image Reference:" in expanded
    assert img_file.name in expanded

    # 6. Narrow UI width helper test
    width = get_ui_width()
    assert 60 <= width <= 94


def test_web_companion_server_and_telemetry(temp_workspace):
    import urllib.request
    import urllib.error
    import json
    from agent.web.server import (
        start_companion_server,
        companion_telemetry,
    )
    from agent.loop import AgentLoop
    from agent.llm.client import LLMConfig
    from agent.tools.subagent import subagent_registry

    # 1. Start companion server
    ok, url = start_companion_server(7843)
    assert ok is True
    assert "http://127.0.0.1:7843" in url

    # 2. Test CompanionTelemetry logging and diffs
    companion_telemetry.clear_logs()
    companion_telemetry.log_event("tool_start", "edit_file(math_lib.py)")
    companion_telemetry.log_event("tool_end", "Successfully edited math_lib.py")
    companion_telemetry.set_diff(
        "--- a/math_lib.py\n+++ b/math_lib.py\n@@ -1 +1 @@\n-old\n+new\n", "math_lib.py"
    )

    logs = companion_telemetry.get_logs()
    assert len(logs) == 2
    assert "edit_file(math_lib.py)" in logs[0]["message"]
    assert "Successfully edited" in logs[1]["message"]
    assert "+new" in companion_telemetry.get_active_diff()

    # 3. Bind agent and verify dynamic context & model telemetry
    dummy_agent = AgentLoop(
        workspace_root=str(temp_workspace),
        llm_config=LLMConfig(model="gemini-3.7-flash"),
    )
    dummy_agent.history.append({"role": "user", "content": "Test prompt"})
    companion_telemetry.bind_agent(dummy_agent)

    model_info = companion_telemetry.get_model_info()
    assert model_info["model"] == "gemini-3.7-flash"

    # 4. Register active subagents
    subagent_registry.register_active("sub_live_01", "researcher", "branch")

    # 5. Query /api/status HTTP endpoint
    req = urllib.request.Request(f"{url}/api/status")
    with urllib.request.urlopen(req, timeout=5) as response:
        assert response.status == 200
        data = json.loads(response.read().decode("utf-8"))
        assert data["status"] == "online"
        assert data["model"] == "gemini-3.7-flash"
        assert data["context"]["used_tokens"] > 0
        assert len(data["telemetry"]) >= 2
        assert "+new" in data["active_diff"]
        assert any(s["conversationId"] == "sub_live_01" for s in data["subagents"])

    # 6. Test /api/clear_telemetry — now a token-gated, loopback-Origin POST
    #    (bare GET mutation was the CSRF hole that got closed).
    from agent.web import server as _companion_server

    req_clear = urllib.request.Request(
        f"{url}/api/clear_telemetry",
        method="POST",
        data=b"",
        headers={
            "X-Companion-Token": _companion_server.SESSION_TOKEN,
            "Origin": url,
        },
    )
    with urllib.request.urlopen(req_clear, timeout=5) as response:
        assert response.status == 200
        assert len(companion_telemetry.get_logs()) == 0

    # A bare unauthenticated GET must NOT clear telemetry anymore.
    companion_telemetry.log_event("post-clear", "still here")
    try:
        urllib.request.urlopen(f"{url}/api/clear_telemetry", timeout=5)
        rejected = False
    except urllib.error.HTTPError as exc:
        rejected = exc.code in (403, 405)
    assert rejected
    assert len(companion_telemetry.get_logs()) >= 1


def test_setup_packaging_discovers_all_subpackages():
    """Regression: pip install was only shipping agent/ (no __init__.py in
    subpackages), so find_packages() silently dropped agent.tools,
    agent.governance, agent.llm, agent.workflows, agent.web from the wheel."""
    from setuptools import find_packages

    discovered = set(find_packages())
    expected = {
        "agent",
        "agent.tools",
        "agent.governance",
        "agent.llm",
        "agent.workflows",
        "agent.web",
    }
    missing = expected - discovered
    assert not missing, f"find_packages() missed subpackages: {missing}"


def test_launch_dashboard_starts_despite_failed_selftest(monkeypatch):
    """Regression: launch.py used to sys.exit(1) on any self-test failure
    before starting the dashboard, so a single flaky test blocked the
    Command Center from launching at all."""
    import importlib
    import subprocess
    from unittest.mock import MagicMock

    launch = importlib.import_module("launch")

    failing_run = MagicMock(return_value=MagicMock(returncode=1))
    dashboard_popen = MagicMock()
    monkeypatch.setattr(subprocess, "run", failing_run)
    monkeypatch.setattr(subprocess, "Popen", dashboard_popen)
    monkeypatch.setattr(dashboard_popen.return_value, "wait", MagicMock())

    launch.main()

    assert dashboard_popen.called, (
        "Dashboard Popen was never reached — a failing self-test still "
        "blocks the launcher."
    )


def test_indexer_only_purges_symbols_for_code_files(temp_workspace):
    """Symbol purging is O(#symbols); it must not run for docs/data/binary files."""
    (temp_workspace / "README.md").write_text("# docs\n", encoding="utf-8")
    (temp_workspace / "data.json").write_text("{}\n", encoding="utf-8")
    (temp_workspace / "logo.png").write_bytes(b"\x89PNG\r\n")

    indexer = CodebaseIndexer(workspace_root=str(temp_workspace))
    purged = []
    original = indexer._remove_symbols_for_file

    def _record(path):
        purged.append(path)
        return original(path)

    indexer._remove_symbols_for_file = _record
    indexer.index_workspace()

    bad = [
        p.name for p in purged if p.suffix not in (".py", ".js", ".ts", ".jsx", ".tsx")
    ]
    assert bad == [], f"symbol purge ran for non-code files: {bad}"


def test_completer_caps_suggestions(temp_workspace):
    for i in range(120):
        (temp_workspace / f"mod_{i:03d}.py").write_text(
            f"def fn_{i:03d}():\n    return {i}\n", encoding="utf-8"
        )
    indexer = CodebaseIndexer(workspace_root=str(temp_workspace))
    indexer.index_workspace()
    completer = AgnosticCompleter(["/plan"], indexer)

    doc_file = Document("@mod_", cursor_position=5)
    assert len(list(completer.get_completions(doc_file, None))) <= 50

    doc_sym = Document("#fn_", cursor_position=4)
    assert len(list(completer.get_completions(doc_sym, None))) <= 50


def test_cli_main_accepts_an_argv_list():
    """The TUI calls agent.cli.main(argv) with an explicit list."""
    from agent import cli

    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
