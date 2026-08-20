"""
agent/tools/mcp.py — Model Context Protocol client (stdio transport)
Speaks JSON-RPC 2.0 over newline-delimited JSON to a child process, so external
tool servers can be plugged into the registry. Stdlib only — no MCP SDK.
"""

import atexit
import json
import logging
import os
import queue
import re
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent import __version__

# Pinned: the client only implements what this revision requires of a tools-only client.
PROTOCOL_VERSION = "2025-03-26"
DEFAULT_TIMEOUT = 60.0
CLIENT_INFO = {"name": "agnostic-ai", "version": __version__}

_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

log = logging.getLogger(__name__)


class McpError(RuntimeError):
    """Any failure talking to an MCP server: spawn, protocol, timeout, or exit."""


class McpServer:
    """One stdio MCP server. Spawns lazily — construction never starts a process."""

    def __init__(
        self,
        name: str,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.name = name
        self.command = command
        self.args = list(args or [])
        self.env = dict(env or {})
        self.cwd = cwd
        self.timeout = timeout
        self.proc: Optional[subprocess.Popen] = None
        self._incoming: "queue.Queue" = queue.Queue()
        # Kept for error messages only: a server that dies usually explains itself on stderr.
        self._stderr_tail = deque(maxlen=20)
        self._next_id = 0
        # One in-flight request per server: replies are matched by id, but serialising
        # keeps the queue drain trivial and MCP servers are not throughput-critical.
        self._lock = threading.RLock()

    @property
    def state(self) -> str:
        if self.proc is None:
            return "stopped"
        return "running" if self.proc.poll() is None else "exited"

    # --- lifecycle ---

    def start(self) -> None:
        """Spawn the child and complete the initialize handshake. Idempotent."""
        with self._lock:
            if self.proc is not None and self.proc.poll() is None:
                return
            child_env = {**os.environ, **self.env}
            try:
                self.proc = subprocess.Popen(
                    [self.command, *self.args],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    # A separate pipe, NOT merged into stdout like the subscription
                    # bridge does: stdout is the protocol stream here, so log chatter
                    # would corrupt it. The drain thread is what stops a chatty server
                    # from filling the stderr buffer and deadlocking both sides.
                    stderr=subprocess.PIPE,
                    cwd=self.cwd,
                    env=child_env,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                )
            except OSError as e:
                raise McpError(f"MCP server '{self.name}' failed to start ({self.command}): {e}")

            threading.Thread(target=self._read_stdout, daemon=True).start()
            threading.Thread(target=self._drain_stderr, daemon=True).start()

            self._request(
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": CLIENT_INFO,
                },
            )
            self._notify("notifications/initialized")

    def stop(self) -> None:
        """Terminate the child and close its pipes. Safe to call twice."""
        proc = self.proc
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
        except Exception as e:  # a server we cannot reap must not break shutdown
            log.warning("MCP server '%s' did not stop cleanly: %s", self.name, e)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            try:
                if stream is not None:
                    stream.close()
            except Exception:  # closing a pipe the reader thread still holds
                pass

    # --- protocol ---

    def list_tools(self) -> List[Dict[str, Any]]:
        self.start()
        tools: List[Dict[str, Any]] = []
        cursor = None
        while True:
            res = self._request("tools/list", {"cursor": cursor} if cursor else {})
            tools.extend(res.get("tools") or [])
            cursor = res.get("nextCursor")
            if not cursor:
                return tools

    def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Tuple[str, bool]:
        """Call a remote tool. Returns (concatenated text content, is_error)."""
        self.start()
        res = self._request("tools/call", {"name": name, "arguments": arguments or {}})
        parts = []
        for item in res.get("content") or []:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                parts.append(item.get("text", ""))
            else:
                # Images/audio/resources: the agent's tool channel is text-only.
                parts.append(f"[{item.get('type', 'unknown')} content omitted]")
        return "\n".join(parts), bool(res.get("isError"))

    # --- transport ---

    def _read_stdout(self) -> None:
        proc = self.proc
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    self._incoming.put(json.loads(line))
                except ValueError:
                    # Servers that log to stdout are out of spec but common; skip the noise.
                    log.debug("MCP server '%s' emitted non-JSON stdout: %s", self.name, line[:200])
        except Exception as e:
            log.debug("MCP server '%s' stdout reader stopped: %s", self.name, e)
        finally:
            self._incoming.put(None)  # EOF sentinel: wakes any waiting request

    def _drain_stderr(self) -> None:
        proc = self.proc
        try:
            for line in proc.stderr:
                self._stderr_tail.append(line.rstrip("\r\n"))
        except Exception:  # the pipe is closed by stop(); nothing left to drain
            pass

    def _send(self, message: Dict[str, Any]) -> None:
        proc = self.proc
        if proc is None or proc.stdin is None or proc.poll() is not None:
            raise McpError(f"MCP server '{self.name}' is not running.{self._stderr_hint()}")
        try:
            proc.stdin.write(json.dumps(message) + "\n")
            proc.stdin.flush()
        except OSError as e:
            raise McpError(f"MCP server '{self.name}' stdin closed: {e}{self._stderr_hint()}")

    def _notify(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def _request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        with self._lock:
            self._next_id += 1
            req_id = self._next_id
            deadline = time.monotonic() + self.timeout
            self._send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}})
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise McpError(
                        f"MCP server '{self.name}' did not answer '{method}' within "
                        f"{self.timeout}s.{self._stderr_hint()}"
                    )
                try:
                    msg = self._incoming.get(timeout=remaining)
                except queue.Empty:
                    continue
                if msg is None:
                    raise McpError(
                        f"MCP server '{self.name}' exited during '{method}'.{self._stderr_hint()}"
                    )
                if msg.get("id") != req_id:
                    # Notification, or a server->client request we do not serve.
                    continue
                if msg.get("error"):
                    err = msg["error"]
                    detail = err.get("message", err) if isinstance(err, dict) else err
                    raise McpError(f"MCP server '{self.name}' rejected '{method}': {detail}")
                result = msg.get("result")
                return result if isinstance(result, dict) else {}

    def _stderr_hint(self) -> str:
        tail = [line for line in self._stderr_tail if line.strip()]
        return f" Server stderr: {' | '.join(tail[-5:])}" if tail else ""


# --- configuration discovery ---


def config_paths(workspace_root: str) -> List[Path]:
    """Config files in priority order; the first file to claim a server name wins."""
    ws = Path(workspace_root)
    return [
        ws / ".agnostic" / "mcp.json",
        ws / ".mcp.json",  # Claude Code / Codex project format
        Path.home() / ".agnostic" / "mcp.json",
    ]


def _expand_env(value: str, name: str, notes: List[Tuple[str, str]]) -> str:
    """Expand ${VAR} from the real environment; unset vars become '' plus a note."""

    def repl(match):
        var = match.group(1)
        if var in os.environ:
            return os.environ[var]
        notes.append((name, f"env var '{var}' is not set — substituted an empty string"))
        return ""

    return _ENV_REF.sub(repl, value)


def load_servers(
    workspace_root: str, timeout: float = DEFAULT_TIMEOUT
) -> Tuple[List[McpServer], List[Tuple[str, str]]]:
    """Read every config file and build the servers. Returns (servers, notes).

    Notes are (server-or-file, message) pairs for anything skipped — they are shown
    by /mcp rather than raised, so one bad entry never costs the user the good ones.
    """
    servers: List[McpServer] = []
    notes: List[Tuple[str, str]] = []
    claimed = set()

    for path in config_paths(workspace_root):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            notes.append((str(path), f"unreadable MCP config: {e}"))
            continue

        entries = data.get("mcpServers") if isinstance(data, dict) else None
        if not isinstance(entries, dict):
            notes.append((str(path), "no 'mcpServers' object in config"))
            continue

        for name, spec in entries.items():
            if name in claimed:
                continue  # a higher-priority file already defined this server
            claimed.add(name)
            if not isinstance(spec, dict):
                notes.append((name, "server entry is not an object"))
                continue
            kind = spec.get("type") or "stdio"
            if kind != "stdio":
                notes.append((name, f"skipped: transport '{kind}' is not supported (stdio only)"))
                continue
            command = spec.get("command")
            if not command:
                notes.append((name, "skipped: no 'command' in server entry"))
                continue
            env = {
                str(k): _expand_env(str(v), name, notes) for k, v in (spec.get("env") or {}).items()
            }
            servers.append(
                McpServer(
                    name=name,
                    command=str(command),
                    args=[str(a) for a in (spec.get("args") or [])],
                    env=env,
                    cwd=str(spec.get("cwd") or workspace_root),
                    timeout=float(spec.get("timeout") or timeout),
                )
            )
    return servers, notes


def stop_all(servers: List[McpServer]) -> None:
    """Reap every child. Registered with atexit so servers never outlive the agent."""
    for server in servers:
        try:
            server.stop()
        except Exception:  # shutdown path: never raise
            pass


def register_atexit(servers: List[McpServer]) -> None:
    atexit.register(stop_all, list(servers))
