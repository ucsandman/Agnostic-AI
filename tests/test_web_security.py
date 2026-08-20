"""
tests/test_web_security.py — Security regression tests for the local companion web server.
Covers loopback-only binding, session-token auth, POST-only mutations, and Origin/CSRF rejection.
"""

import json
import urllib.error
import urllib.request

import pytest

from agent.web import server as web


@pytest.fixture
def companion(monkeypatch):
    """Boot the companion server on an ephemeral loopback port with undo stubbed out."""
    calls = []

    def fake_rollback():
        calls.append(1)
        return True, "rolled back"

    monkeypatch.setattr(web.undo_manager, "rollback_last", fake_rollback)
    monkeypatch.setattr(web, "_server_instance", None)
    monkeypatch.setattr(web, "_server_thread", None)

    ok, url = web.start_companion_server(port=0)
    assert ok, url
    try:
        yield url, calls
    finally:
        web._server_instance.shutdown()
        web._server_instance.server_close()
        web._server_instance = None
        web._server_thread = None


def _request(url, method="GET", headers=None, token=None):
    req = urllib.request.Request(url, method=method, data=b"" if method == "POST" else None)
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    if token:
        req.add_header("X-Companion-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            return res.status, res.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_server_binds_loopback_only(companion):
    host, port = web._server_instance.server_address[:2]
    assert host == "127.0.0.1"
    assert port != 0


def test_get_undo_is_rejected_and_performs_nothing(companion):
    url, calls = companion
    status, _ = _request(f"{url}/api/undo")
    assert status in (403, 405)
    assert calls == []


def test_post_undo_without_token_is_forbidden(companion):
    url, calls = companion
    status, _ = _request(f"{url}/api/undo", method="POST")
    assert status == 403
    assert calls == []


def test_post_undo_with_token_and_loopback_origin_runs(companion):
    url, calls = companion
    status, body = _request(
        f"{url}/api/undo",
        method="POST",
        headers={"Origin": url},
        token=web.SESSION_TOKEN,
    )
    assert status == 200
    assert json.loads(body)["success"] is True
    assert calls == [1]


def test_post_undo_with_foreign_origin_is_rejected(companion):
    url, calls = companion
    status, _ = _request(
        f"{url}/api/undo",
        method="POST",
        headers={"Origin": "http://evil.example"},
        token=web.SESSION_TOKEN,
    )
    assert status == 403
    assert calls == []


def test_read_only_status_still_works_without_token(companion):
    url, _ = companion
    status, body = _request(f"{url}/api/status")
    assert status == 200
    assert json.loads(body)["status"] == "online"


def test_quick_actions_show_output_and_lock_the_button(companion):
    """/api/test and /api/distill return an 'output' field, but the page rendered
    only data.message — a failing suite read 'Tests failed (Exit 1)' with no
    traceback — and nothing disabled the button during a 600s run."""
    url, _ = companion
    status, body = _request(f"{url}/")
    assert status == 200
    page = body.decode("utf-8")
    assert 'id="action-output"' in page, "nothing renders the API 'output' field"
    assert "data.output" in page, "triggerApi never reads data.output"
    assert "btn.disabled = true" in page, "the clicked button is never disabled"


def test_served_page_carries_the_session_token(companion):
    url, _ = companion
    status, body = _request(f"{url}/")
    assert status == 200
    assert web.SESSION_TOKEN in body.decode("utf-8")


# --- Availability: one parked connection must not stall the whole server ---------


def test_server_still_answers_while_another_connection_is_open(companion):
    """socketserver.TCPServer handles one connection at a time: a client that
    connects and says nothing parks the accept loop, and the page's 1 Hz
    /api/status poll (and every other request) hangs behind it."""
    import socket

    url, _ = companion
    host, port = web._server_instance.server_address[:2]
    parked = socket.create_connection((host, port), timeout=5)
    try:
        req = urllib.request.Request(f"{url}/api/status")
        try:
            with urllib.request.urlopen(req, timeout=3) as res:
                assert res.status == 200
        except OSError as e:
            pytest.fail(f"server stopped answering while a connection was open: {e!r}")
    finally:
        parked.close()


def test_second_start_reports_the_port_actually_bound(companion):
    """/web called twice used to echo back the port that was *asked* for, so the
    user was handed a URL nothing is listening on."""
    url, _ = companion
    bound = web._server_instance.server_address[1]
    assert bound != 7843

    ok, again = web.start_companion_server(7843)
    assert ok, again
    assert again == f"http://127.0.0.1:{bound}" == url


def test_server_uses_daemon_threads(companion):
    import socketserver

    assert isinstance(web._server_instance, socketserver.ThreadingMixIn)
    assert web._server_instance.daemon_threads is True


# --- Availability: long subprocess runs must be bounded -------------------------


def _post(url, path):
    return _request(
        f"{url}{path}",
        method="POST",
        headers={"Origin": url},
        token=web.SESSION_TOKEN,
    )


@pytest.mark.parametrize("path", ["/api/test", "/api/distill"])
def test_subprocess_routes_pass_a_timeout_and_report_expiry(companion, monkeypatch, path):
    """Both routes ran subprocess.run() with no timeout while the browser polled
    /api/status once a second — a hung test/distill run wedged the server."""
    import subprocess

    url, _ = companion
    seen = {}

    def fake_run(cmd, **kwargs):
        seen.update(kwargs)
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 0))

    monkeypatch.setattr(web.subprocess, "run", fake_run)

    try:
        status, body = _post(url, path)
    except Exception as e:  # noqa: BLE001 - any failure here is the regression
        pytest.fail(
            f"{path} did not survive a subprocess timeout: {e!r} "
            f"(timeout kwarg passed: {seen.get('timeout')!r})"
        )
    assert seen.get("timeout"), f"{path} must pass a timeout= to subprocess.run"
    data = json.loads(body)
    assert data["success"] is False
    assert "timed out" in data["message"].lower(), data


# --- Consistency: /api/compact must not rewrite history mid-turn ----------------


def test_compact_is_refused_while_a_turn_is_running(companion, monkeypatch):
    """Replacing agent.history from the HTTP thread while run_turn() is appending
    to it corrupts the conversation. Busy => 409, history untouched."""
    from types import SimpleNamespace

    url, _ = companion
    history = [{"role": "system", "content": "sys"}] + [
        {"role": "user", "content": f"turn {i}"} for i in range(8)
    ]
    agent = SimpleNamespace(history=list(history), is_busy=True)
    monkeypatch.setattr(web.companion_telemetry, "_agent_instance", agent)

    status, body = _post(url, "/api/compact")
    assert status == 409, f"expected 409 while busy, got {status}: {body!r}"
    assert json.loads(body)["success"] is False
    assert agent.history == history, "history was rewritten mid-turn"


def test_compact_still_runs_when_the_agent_is_idle(companion, monkeypatch):
    from types import SimpleNamespace

    url, _ = companion
    history = [{"role": "system", "content": "sys"}] + [
        {"role": "user", "content": f"turn {i}"} for i in range(8)
    ]
    agent = SimpleNamespace(history=list(history), is_busy=False)
    monkeypatch.setattr(web.companion_telemetry, "_agent_instance", agent)

    status, body = _post(url, "/api/compact")
    assert status == 200
    assert json.loads(body)["success"] is True
    assert len(agent.history) < len(history)
