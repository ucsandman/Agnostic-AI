"""
tests/test_mcp.py — MCP (Model Context Protocol) stdio client and registry integration.
Every server here is a REAL child process (tests/fixtures/fake_mcp_server.py), not a mock.
"""

import json
import sys
from pathlib import Path

import pytest

from agent.tools.mcp import McpError, McpServer, config_paths, load_servers
from agent.tools.registry import ToolRegistry

FAKE_SERVER = Path(__file__).parent / "fixtures" / "fake_mcp_server.py"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Keep a real developer's ~/.agnostic/mcp.json out of discovery during tests."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))


@pytest.fixture
def fake_server():
    server = McpServer(
        name="fake",
        command=sys.executable,
        args=[str(FAKE_SERVER)],
        timeout=20.0,
    )
    yield server
    server.stop()


def _write_config(path: Path, servers: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")


def _fake_spec(**extra):
    spec = {"command": sys.executable, "args": [str(FAKE_SERVER)]}
    spec.update(extra)
    return spec


# --- protocol ---


def test_lazy_start_and_handshake(fake_server):
    assert fake_server.proc is None
    assert fake_server.state == "stopped"

    fake_server.start()
    assert fake_server.state == "running"

    # start() is idempotent — no second child.
    pid = fake_server.proc.pid
    fake_server.start()
    assert fake_server.proc.pid == pid


def test_list_tools_spawns_on_first_use(fake_server):
    tools = fake_server.list_tools()
    assert fake_server.state == "running"
    names = [t["name"] for t in tools]
    assert names == ["echo", "fail"]
    schema = next(t for t in tools if t["name"] == "echo")["inputSchema"]
    assert schema["properties"]["text"]["type"] == "string"


def test_call_tool_round_trip(fake_server):
    text, is_error = fake_server.call_tool("echo", {"text": "hello mcp"})
    assert text == "hello mcp"
    assert is_error is False


def test_call_tool_is_error_propagates(fake_server):
    text, is_error = fake_server.call_tool("fail", {})
    assert is_error is True
    assert "blew up" in text


def test_unknown_tool_raises_with_server_message(fake_server):
    with pytest.raises(McpError) as excinfo:
        fake_server.call_tool("nope", {})
    assert "unknown tool" in str(excinfo.value)


def test_chatty_stderr_does_not_deadlock(monkeypatch):
    """256 KB of stderr is far past the pipe buffer: without the drain thread the
    child blocks writing and the handshake never completes."""
    server = McpServer(
        name="noisy",
        command=sys.executable,
        args=[str(FAKE_SERVER)],
        env={"FAKE_MCP_NOISE_KB": "256"},
        timeout=30.0,
    )
    try:
        text, is_error = server.call_tool("echo", {"text": "still alive"})
        assert (text, is_error) == ("still alive", False)
    finally:
        server.stop()


def test_timeout_raises_and_leaves_no_zombie():
    """A child that never answers must time out, and stop() must reap it."""
    server = McpServer(
        name="hung",
        command=sys.executable,
        args=["-c", "import time; time.sleep(30)"],
        timeout=1.0,
    )
    with pytest.raises(McpError) as excinfo:
        server.start()
    assert "within 1.0s" in str(excinfo.value)

    proc = server.proc
    assert proc.poll() is None  # still hanging around before stop()
    server.stop()
    assert proc.poll() is not None
    assert server.state == "exited"


def test_missing_executable_raises_mcp_error():
    server = McpServer(name="ghost", command="definitely-not-a-real-binary-xyz")
    with pytest.raises(McpError) as excinfo:
        server.list_tools()
    assert "failed to start" in str(excinfo.value)


def test_stop_is_safe_before_start_and_twice(fake_server):
    fake_server.stop()  # never started
    fake_server.list_tools()
    fake_server.stop()
    fake_server.stop()
    assert fake_server.proc.poll() is not None


# --- config discovery ---


def test_config_paths_priority_order(tmp_path):
    paths = config_paths(str(tmp_path))
    assert paths[0] == tmp_path / ".agnostic" / "mcp.json"
    assert paths[1] == tmp_path / ".mcp.json"
    assert paths[2] == Path.home() / ".agnostic" / "mcp.json"


def test_loads_claude_code_mcp_json(tmp_path):
    _write_config(tmp_path / ".mcp.json", {"fake": _fake_spec(env={"TOKEN": "plain"})})
    servers, notes = load_servers(str(tmp_path))
    assert [s.name for s in servers] == ["fake"]
    assert servers[0].command == sys.executable
    assert servers[0].args == [str(FAKE_SERVER)]
    assert servers[0].env == {"TOKEN": "plain"}
    assert servers[0].cwd == str(tmp_path)
    assert notes == []


def test_agnostic_config_wins_over_project_config(tmp_path):
    _write_config(tmp_path / ".agnostic" / "mcp.json", {"fake": _fake_spec(env={"WHICH": "high"})})
    _write_config(tmp_path / ".mcp.json", {"fake": _fake_spec(env={"WHICH": "low"})})
    servers, _ = load_servers(str(tmp_path))
    assert len(servers) == 1
    assert servers[0].env == {"WHICH": "high"}


def test_env_var_expansion(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_TEST_TOKEN", "s3cr3t")
    monkeypatch.delenv("MCP_TEST_MISSING", raising=False)
    _write_config(
        tmp_path / ".mcp.json",
        {
            "fake": _fake_spec(
                env={
                    "TOKEN": "${MCP_TEST_TOKEN}",
                    "MIXED": "pre-${MCP_TEST_TOKEN}-post",
                    "GONE": "${MCP_TEST_MISSING}",
                }
            )
        },
    )
    servers, notes = load_servers(str(tmp_path))
    assert servers[0].env == {"TOKEN": "s3cr3t", "MIXED": "pre-s3cr3t-post", "GONE": ""}
    assert any("MCP_TEST_MISSING" in message for _, message in notes)


def test_non_stdio_transports_are_skipped_with_a_note(tmp_path):
    _write_config(
        tmp_path / ".mcp.json",
        {
            "remote": {"type": "http", "url": "https://example.invalid/mcp"},
            "streamed": {"type": "sse", "url": "https://example.invalid/sse"},
            "local": _fake_spec(type="stdio"),
        },
    )
    servers, notes = load_servers(str(tmp_path))
    assert [s.name for s in servers] == ["local"]
    skipped = {name: message for name, message in notes}
    assert "http" in skipped["remote"]
    assert "sse" in skipped["streamed"]


def test_malformed_config_is_noted_not_raised(tmp_path):
    (tmp_path / ".mcp.json").write_text("{not json", encoding="utf-8")
    servers, notes = load_servers(str(tmp_path))
    assert servers == []
    assert any("unreadable" in message for _, message in notes)


def test_entry_without_command_is_skipped(tmp_path):
    _write_config(tmp_path / ".mcp.json", {"broken": {"args": ["x"]}})
    servers, notes = load_servers(str(tmp_path))
    assert servers == []
    assert notes == [("broken", "skipped: no 'command' in server entry")]


def test_no_config_means_no_servers(tmp_path):
    servers, notes = load_servers(str(tmp_path))
    assert (servers, notes) == ([], [])


# --- registry integration ---


def test_registry_without_mcp_has_no_mcp_tools(tmp_path):
    _write_config(tmp_path / ".agnostic" / "mcp.json", {"fake": _fake_spec()})
    registry = ToolRegistry(workspace_root=str(tmp_path), load_mcp=False)
    assert not [n for n in registry._tools if n.startswith("mcp__")]
    assert registry.mcp_status() == []


def test_registry_registers_and_executes_mcp_tool(tmp_path):
    _write_config(tmp_path / ".agnostic" / "mcp.json", {"fake": _fake_spec()})
    registry = ToolRegistry(workspace_root=str(tmp_path))
    try:
        assert "mcp__fake__echo" in registry._tools
        assert "mcp__fake__fail" in registry._tools

        # The remote JSON schema is what the model sees.
        spec = next(
            t for t in registry.get_openai_tools() if t["function"]["name"] == "mcp__fake__echo"
        )
        assert spec["function"]["parameters"]["required"] == ["text"]
        assert spec["function"]["description"] == "Echo the supplied text back."

        # End to end through execute(), so governance and audit still apply.
        res = registry.execute("mcp__fake__echo", {"text": "through the registry"})
        assert res.output == "through the registry"
        assert res.is_error is False

        err = registry.execute("mcp__fake__fail", {})
        assert err.is_error is True

        assert registry.mcp_status() == [
            {"server": "fake", "state": "running", "tool_count": 2, "error": None}
        ]
    finally:
        registry._mcp_servers["fake"].stop()


def test_registry_survives_a_broken_server(tmp_path):
    _write_config(
        tmp_path / ".agnostic" / "mcp.json",
        {
            "ghost": {"command": "definitely-not-a-real-binary-xyz"},
            "fake": _fake_spec(),
        },
    )
    registry = ToolRegistry(workspace_root=str(tmp_path))
    try:
        assert "mcp__fake__echo" in registry._tools  # the healthy server still loaded
        assert "read_file" in registry._tools  # built-ins untouched
        ghost = next(r for r in registry.mcp_status() if r["server"] == "ghost")
        assert ghost["state"] == "error"
        assert "failed to start" in ghost["error"]
        assert ghost["tool_count"] == 0
    finally:
        for server in registry._mcp_servers.values():
            server.stop()


def test_read_only_registry_skips_mcp(tmp_path):
    _write_config(tmp_path / ".agnostic" / "mcp.json", {"fake": _fake_spec()})
    registry = ToolRegistry(workspace_root=str(tmp_path), read_only=True)
    assert not [n for n in registry._tools if n.startswith("mcp__")]
