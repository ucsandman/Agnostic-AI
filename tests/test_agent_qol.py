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
    blocked, _, reason = guard.check_command_safety("cat .secrets.env")
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
