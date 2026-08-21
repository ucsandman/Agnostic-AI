"""
tests/test_tui_mcp.py — /mcp: the server table, /mcp reload, and the status-bar glyph.
The reload tests drive a REAL child process (tests/fixtures/fake_mcp_server.py).
"""

import inspect
import json
import sys
from pathlib import Path

import pytest

from agent import tui, tui_commands
from agent.tools.registry import ToolRegistry
from agent.ui_common import mcp_table

FAKE_SERVER = Path(__file__).parent / "fixtures" / "fake_mcp_server.py"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Keep a real developer's ~/.agnostic/mcp.json out of discovery during tests."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))


def _write_fake_config(tmp_path):
    path = tmp_path / ".agnostic" / "mcp.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"mcpServers": {"fake": {"command": sys.executable, "args": [str(FAKE_SERVER)]}}}
        ),
        encoding="utf-8",
    )


def _mcp_tools(registry):
    return sorted(n for n in registry._tools if n.startswith("mcp__"))


# --- reload_mcp ------------------------------------------------------------------


def test_reload_keeps_the_tools_and_never_duplicates_them(tmp_path):
    _write_fake_config(tmp_path)
    registry = ToolRegistry(workspace_root=str(tmp_path))
    try:
        assert "mcp__fake__echo" in registry._tools
        builtins = [n for n in registry._tools if not n.startswith("mcp__")]

        assert registry.reload_mcp() == "1 server(s), 2 tool(s)"
        assert "mcp__fake__echo" in registry._tools
        first = _mcp_tools(registry)

        registry.reload_mcp()
        assert _mcp_tools(registry) == first  # a dict cannot duplicate, but the count can
        assert [n for n in registry._tools if not n.startswith("mcp__")] == builtins
        assert [r["server"] for r in registry.mcp_status()] == ["fake"]
    finally:
        for server in registry._mcp_servers.values():
            server.stop()


def test_reload_on_a_registry_that_never_loaded_mcp_registers_nothing(tmp_path):
    _write_fake_config(tmp_path)
    registry = ToolRegistry(workspace_root=str(tmp_path), load_mcp=False, read_only=True)
    assert registry.reload_mcp() == "0 server(s), 0 tool(s)"
    assert _mcp_tools(registry) == []
    assert registry.mcp_status() == []


# --- the rendered table ----------------------------------------------------------


def test_mcp_table_renders_a_bracket_bearing_error_as_text_not_markup():
    rows = [
        {"server": "fake", "state": "running", "tool_count": 2, "error": None},
        {"server": "ghost", "state": "error", "tool_count": 0, "error": "[WinError 2] not found"},
    ]
    from rich.console import Console

    console = Console(width=120, no_color=True)
    with console.capture() as cap:
        console.print(mcp_table(rows))
    text = cap.get()
    assert "[WinError 2] not found" in text  # survived verbatim: never parsed as markup
    assert "ghost" in text and "running" in text

    with console.capture() as cap:
        console.print(mcp_table([]))
    assert "No MCP servers configured" in cap.get()


# --- dispatch shape --------------------------------------------------------------


def _mcp_branch_source():
    src = inspect.getsource(tui_commands.SlashCommandMixin._handle_slash_command)
    start = src.index('elif cmd == "mcp":')
    return src[start : src.index('elif user_input == "/help":', start)]


def test_only_the_reload_arm_goes_to_a_background_worker():
    branch = _mcp_branch_source()
    reload_arm, _, list_arm = branch.partition('elif sub in ("", "list"):')
    assert "_dispatch_background" in reload_arm and "reload_mcp" in reload_arm
    assert "_dispatch_background" not in list_arm
    assert "mcp_status" in list_arm


def test_status_bar_flags_a_broken_server():
    src = inspect.getsource(tui.AgnosticTUI._update_status_bar)
    assert '"!mcp"' in src
    assert 'r.get("state") == "error"' in src
