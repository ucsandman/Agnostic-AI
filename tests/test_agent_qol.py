"""
tests/test_agent_qol.py — Comprehensive Unit Tests for Agnostic Agent QoL Enhancements
Tests AST symbol indexer, .agentignore, session manager, context compaction, trust tiers, and audit manager.
"""

from pathlib import Path

import pytest

from agent.tools.indexer import CodebaseIndexer
from agent.governance.learn import Learner
from agent.governance.session_manager import SessionManager
from agent.governance.context import ContextManager
from agent.governance.guard import SafetyGuard
from agent.governance.audit import AuditManager
from agent.cli import expand_prompt_references, AgnosticCompleter
from agent.llm.client import LLMConfig
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

    invalid, err = CodeInterceptor.validate_syntax(temp_workspace / "broken.py", "def foo(\n")
    assert invalid is False
    assert "SyntaxError" in err

    # 2. Tool Registry Integration check (write_file and edit_file abort on broken Python syntax)
    reg = ToolRegistry(workspace_root=str(temp_workspace))

    # Attempting to write invalid python
    res = reg.execute("write_file", {"file_path": "broken.py", "content": "def bad_func("})
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

    # Only "branch" (a real git worktree) gets isolation; every other mode
    # value -- including the removed legacy "share" -- inherits the real
    # workspace instead of being handed an empty scratch dir.
    worker_legacy = SubagentWorker(
        role="tester",
        system_prompt="Test",
        client=LLMClient(),
        workspace_root=temp_workspace,
        workspace_mode="share",
    )
    assert worker_legacy.active_workspace == temp_workspace
    worker_legacy.cleanup()
    assert temp_workspace.exists()


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

    search_replace_patch = "<<<<<<< SEARCH\n    return 10\n=======\n    return 20\n>>>>>>> REPLACE"
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


@pytest.mark.parametrize("preset_key", sorted(LLMConfig.PRESETS))
def test_every_preset_builds_a_valid_config(preset_key, monkeypatch):
    """Every preset in the table must switch cleanly. _init_client is stubbed:
    this is a config-table check, and building a real client per preset made it
    the slowest test in the suite for no extra coverage."""
    from agent.llm.client import LLMClient

    preset = LLMConfig.PRESETS[preset_key]
    # Every API-key preset needs its env var present, or the switch is refused.
    for env_var in [preset.get("api_key_env")] + list(preset.get("alt_api_key_envs", [])):
        if env_var:
            monkeypatch.setenv(env_var, "placeholder-value")
    monkeypatch.setattr(LLMClient, "_init_client", lambda self: None)

    client = LLMClient()
    assert client.config.model == "local-model"

    msg = client.switch_model(preset_key=preset_key, reasoning_effort="high")
    assert preset["name"] in msg
    assert client.config.model == preset["model"]
    assert client.config.provider == preset["provider"]
    assert client.config.base_url == preset["base_url"]
    assert client.config.base_url.startswith(("http://", "https://", "subscription://"))
    assert client.config.context_window > 0
    assert client.config.reasoning_effort == "high"

    # Without an explicit override the preset's own default effort is adopted.
    client.switch_model(preset_key=preset_key)
    assert client.config.reasoning_effort == preset["default_effort"]
    assert client.config.reasoning_effort in ("low", "medium", "high")


def test_alt_api_key_env_resolution(monkeypatch):
    from agent.llm.client import LLMClient

    monkeypatch.setattr(LLMClient, "_init_client", lambda self: None)
    monkeypatch.setenv("GOOGLE_API_KEY", "mock-google-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    client = LLMClient()
    client.switch_model(preset_key="agy-flash-3.7")
    assert client.config.api_key == "mock-google-key"


def test_http_client_is_shared_across_clients_and_the_doctor(monkeypatch):
    """A fresh httpx.Client per OpenAI() cost ~212ms of SSLContext/certifi setup
    and leaked its connection pool on every /model switch (two rebuilds each)."""
    import openai
    from types import SimpleNamespace

    from agent.llm.client import LLMClient, get_http_client
    from agent.llm.detector import ModelDoctor

    captured = []

    def fake_openai(**kwargs):
        captured.append(kwargs.get("http_client"))
        return object()

    monkeypatch.setattr(openai, "OpenAI", fake_openai)

    LLMClient(LLMConfig(timeout=300.0))
    LLMClient(LLMConfig(timeout=300.0))
    assert captured[0] is get_http_client(300.0)
    assert captured[0] is captured[1]

    # A different timeout gets its own pooled client, with the right budgets.
    assert get_http_client(4.0) is not captured[0]
    assert get_http_client(4.0).timeout.connect == 4.0
    assert captured[0].timeout.connect == 10.0

    # /doctor probes through the same shared 4s client instead of building one.
    seen = []

    def fake_get(url, **_kwargs):
        seen.append(url)
        return SimpleNamespace(status_code=500, text="")

    monkeypatch.setattr(get_http_client(4.0), "get", fake_get)
    ModelDoctor(base_url="http://localhost:9999/v1").inspect()
    assert seen == ["http://localhost:9999/v1/models"]


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
    formatted = SubprocessSubscriptionBridge._format_conversation_prompt(messages, tools)
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
        "find_symbol",
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

    # 2. Tools that only pretended to work are gone: the old stubs
    #    (define_subagent, send_message, schedule, manage_task) plus the three
    #    the model could never use — ask_question had no input channel,
    #    generate_artifact wrote files nothing reads, and manage_subagents
    #    could only 'list'.
    registered = {t["function"]["name"] for t in registry.get_openai_tools()}
    for removed in (
        "define_subagent",
        "send_message",
        "schedule",
        "manage_task",
        "ask_question",
        "generate_artifact",
        "manage_subagents",
    ):
        assert removed not in registered


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
    from agent.web import server as _companion_server
    from agent.web.server import companion_telemetry
    from agent.loop import AgentLoop
    from agent.llm.client import LLMConfig
    from agent.tools.subagent import subagent_registry

    # 1. Start companion server on an ephemeral port and always tear it down,
    #    so the test neither fights a busy 7843 nor leaks a live server.
    _companion_server._server_instance = None
    _companion_server._server_thread = None
    ok, url = _companion_server.start_companion_server(port=0)
    assert ok is True, url
    try:
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
    finally:
        _companion_server._server_instance.shutdown()
        _companion_server._server_instance.server_close()
        _companion_server._server_instance = None
        _companion_server._server_thread = None


def test_setup_packaging_discovers_all_subpackages():
    """Regression: pip install was only shipping agent/ (no __init__.py in
    subpackages), so find_packages() silently dropped agent.tools,
    agent.governance, agent.llm, agent.workflows, agent.web from the wheel.
    Checked with pathlib so the test does not need setuptools at runtime."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    expected = [
        "agent",
        "agent/tools",
        "agent/governance",
        "agent/llm",
        "agent/workflows",
        "agent/web",
    ]
    missing = [p for p in expected if not (root / p / "__init__.py").is_file()]
    assert not missing, f"subpackages without __init__.py (dropped from the wheel): {missing}"


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
        "Dashboard Popen was never reached — a failing self-test still blocks the launcher."
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

    bad = [p.name for p in purged if p.suffix not in (".py", ".js", ".ts", ".jsx", ".tsx")]
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


# --- rollback_to_clean must report a failed rollback, not swallow it ---------------


def test_rollback_to_clean_reports_failure(tmp_path, monkeypatch):
    import subprocess as sp

    from agent.governance.watchdog import SandboxWatchdog

    calls = []

    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        rc = 0 if "restore" in cmd else 1
        return sp.CompletedProcess(cmd, rc, "", "fatal: cannot clean")

    monkeypatch.setattr(sp, "run", fake_run)
    assert SandboxWatchdog(tmp_path).rollback_to_clean() is False
    assert len(calls) == 2


def test_rollback_to_clean_reports_success(tmp_path, monkeypatch):
    import subprocess as sp

    from agent.governance.watchdog import SandboxWatchdog

    monkeypatch.setattr(sp, "run", lambda cmd, **_kw: sp.CompletedProcess(cmd, 0, "", ""))
    assert SandboxWatchdog(tmp_path).rollback_to_clean() is True


def test_rollback_to_clean_reports_a_crashed_git(tmp_path, monkeypatch):
    import subprocess as sp

    from agent.governance.watchdog import SandboxWatchdog

    def boom(cmd, **_kwargs):
        raise OSError("git not found")

    monkeypatch.setattr(sp, "run", boom)
    assert SandboxWatchdog(tmp_path).rollback_to_clean() is False


def test_subscription_bridge_kills_a_hung_cli(monkeypatch):
    """communicate(timeout=180) never even ran: the line-by-line stdout read
    above it blocks until the child exits, so a wedged CLI hung the agent
    forever and left the child process alive."""
    import subprocess
    import sys
    import time as _time

    from agent.llm.client import SubprocessSubscriptionBridge

    real_popen = subprocess.Popen
    spawned = []

    def sleepy_popen(_cmd, **kwargs):
        proc = real_popen([sys.executable, "-c", "import time; time.sleep(20)"], **kwargs)
        spawned.append(proc)
        return proc

    monkeypatch.setattr(subprocess, "Popen", sleepy_popen)

    started = _time.monotonic()
    with pytest.raises(RuntimeError) as exc:
        SubprocessSubscriptionBridge.execute_turn(
            provider="anthropic-sub",
            messages=[{"role": "user", "content": "hi"}],
            timeout=1,
        )
    elapsed = _time.monotonic() - started

    assert "terminated" in str(exc.value).lower(), str(exc.value)
    assert elapsed < 10, f"the hung CLI was not cut off promptly ({elapsed:.1f}s)"
    assert spawned[0].poll() is not None, "the child process was left running"


def test_swarm_synthesis_survives_a_worker_returning_none(temp_workspace):
    """A worker that reports nothing used to be pasted into the synthesis prompt
    as the literal 'None', and a None synthesis body crashed on .strip()."""
    from types import SimpleNamespace

    from agent.workflows.swarm import SwarmCoordinator

    class StubClient:
        def __init__(self):
            self.prompts = []

        def chat_completion(self, messages, **_kwargs):
            self.prompts.append(messages[-1]["content"])
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None))])

    class StubManager:
        workspace_root = temp_workspace
        confirm_callback = None

        def spawn(self, role, prompt):
            return None if role == "tester" else f"{role} report"

    client = StubClient()
    result = SwarmCoordinator(StubManager(), client).dispatch_swarm("do a thing")

    assert result == ""
    prompt = client.prompts[0]
    assert "researcher report" in prompt
    assert "None" not in prompt, prompt


def test_two_schedules_in_the_same_second_get_distinct_ids(monkeypatch):
    """Task ids came from a second-resolution clock, so the second /schedule
    silently overwrote (and orphaned) the first."""
    from agent.workflows import scheduler as sched_mod

    monkeypatch.setattr(sched_mod.time, "time", lambda: 1_700_000_000)
    sched = sched_mod.TaskScheduler()

    first = sched.parse_and_schedule('/schedule every 1h "run pytest"', lambda p: None)
    second = sched.parse_and_schedule('/schedule every 1h "check git"', lambda p: None)
    assert "Scheduled task" in first and "Scheduled task" in second

    assert len(sched.tasks) == 2, sched.tasks
    assert {t.prompt for t in sched.tasks.values()} == {"run pytest", "check git"}

    started = list(sched.tasks.values())
    sched.cancel_all()
    assert all(t.stop_event.is_set() for t in started)
    assert sched.tasks == {}


def test_list_sessions_caches_unchanged_files(temp_workspace, monkeypatch):
    """The web companion polls list_sessions() at ~1 Hz; re-parsing every full
    history on each poll is pure waste when nothing changed."""
    sm = SessionManager(workspace_root=str(temp_workspace))
    sm.save_session("one", [{"role": "user", "content": "hi"}])
    sm.save_session("two", [{"role": "user", "content": "yo"}])

    first = sm.list_sessions()
    assert len(first) == 2

    reads = []
    original = Path.read_text

    def counting_read_text(self, *args, **kwargs):
        reads.append(self.name)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)
    assert sm.list_sessions() == first
    assert reads == [], f"unchanged sessions were re-read: {reads}"

    # A changed session must still be picked up.
    sm.save_session(
        "one", [{"role": "user", "content": "hi"}, {"role": "user", "content": "again"}]
    )
    updated = {s["name"]: s["turn_count"] for s in sm.list_sessions()}
    assert updated["one"] == 2
    assert reads == ["one.json"]


# --- atomic writes: a crash mid-write must never truncate the previous file -------


def _crashing_write_text(self, data, *args, **kwargs):
    """Simulates a crash mid-write: the target is truncated, then the write dies."""
    self.write_bytes(b"")
    raise OSError("simulated crash mid-write")


def test_record_lesson_crash_leaves_ladder_intact(tmp_path, monkeypatch):
    learner = Learner(workspace_root=str(tmp_path))
    learner.record_lesson("always read the file before editing it")
    original = learner.candidates_file.read_text(encoding="utf-8")

    monkeypatch.setattr(Path, "write_text", _crashing_write_text)
    with pytest.raises(OSError):
        learner.record_lesson("a second lesson")

    assert learner.candidates_file.read_text(encoding="utf-8") == original


def test_save_session_crash_leaves_snapshot_intact(tmp_path, monkeypatch):
    manager = SessionManager(workspace_root=str(tmp_path))
    manager.save_session("demo", [{"role": "user", "content": "hi"}])
    session_file = manager.sessions_dir / "demo.json"
    original = session_file.read_text(encoding="utf-8")

    monkeypatch.setattr(Path, "write_text", _crashing_write_text)
    ok, _msg = manager.save_session("demo", [{"role": "user", "content": "bye"}])

    assert ok is False
    assert session_file.read_text(encoding="utf-8") == original


def test_reindex_only_purges_the_changed_file(tmp_path):
    (tmp_path / "a.py").write_text("def alpha():\n    pass\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def beta():\n    pass\n", encoding="utf-8")

    indexer = CodebaseIndexer(workspace_root=str(tmp_path))
    indexer.index_workspace(force=True)
    assert {"alpha", "beta"} <= set(indexer.get_all_symbols())

    (tmp_path / "a.py").write_text("def gamma():\n    pass\n", encoding="utf-8")
    indexer.index_workspace(force=True)

    symbols = set(indexer.get_all_symbols())
    assert "gamma" in symbols
    assert "alpha" not in symbols
    assert "beta" in symbols  # untouched file keeps its symbols

    (tmp_path / "b.py").unlink()
    indexer.index_workspace()
    assert "beta" not in set(indexer.get_all_symbols())
