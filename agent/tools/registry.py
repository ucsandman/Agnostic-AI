"""
agent/tools/registry.py — Typed Tool Registry & Execution Engine
Provides safe terminal execution, surgical file editing, file viewing, search, and MCP tools.
Integrated with Audit Logger, Diff Viewer, and Undo Manager.
"""

import fnmatch
import logging
import os
import json
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict, Any, Iterator, List, Optional, Callable
from agent import __version__
from agent.governance.guard import SafetyGuard, guard
from agent.governance.audit import audit_manager
from agent.governance.interceptor import interceptor
from agent.tools.indexer import DEFAULT_IGNORED_DIRS, DEFAULT_IGNORED_EXTS


class ToolResult:
    def __init__(self, output: str, is_error: bool = False):
        self.output = output
        self.is_error = is_error

    def to_dict(self) -> Dict[str, Any]:
        return {"output": self.output, "is_error": self.is_error}


READ_ONLY_TOOLS = ("read_file", "grep_search", "find_files", "get_outline", "find_symbol")

# Honest identification — this is a coding agent, not a browser.
USER_AGENT = f"AgnosticAI/{__version__} (+https://github.com/ucsandman/agnostic-harness)"

log = logging.getLogger(__name__)


def _truncate(text: str, limit: int = 120) -> str:
    """Head/tail truncation so one tool call cannot flood the context window."""
    lines = text.splitlines()
    if len(lines) <= limit:
        return text
    keep = limit // 3
    return (
        "\n".join(lines[:keep])
        + f"\n\n... [Truncated {len(lines) - 2 * keep} lines to preserve context] ...\n\n"
        + "\n".join(lines[-keep:])
    )


def _match_newlines(text: str, content: str) -> str:
    """Re-encode `text` with the line endings `content` already uses.

    Models emit '\\n'; a file read verbatim may hold '\\r\\n'. Normalising the search
    text (never the stored content) keeps matching working without rewriting the file.
    """
    if "\r\n" in content and "\r\n" not in text:
        return text.replace("\n", "\r\n")
    return text


def parse_tool_args(raw_args: Any):
    """Parse tool-call arguments. Returns (args, error) — error is set when the
    model emitted unusable JSON, in which case the tool must NOT be executed."""
    if not isinstance(raw_args, str):
        return (raw_args or {}), None
    if not raw_args.strip():
        return {}, None
    try:
        return json.loads(raw_args), None
    except Exception as e:
        return None, (
            f"[Tool call rejected] The arguments you supplied were not valid JSON, "
            f"so the tool was NOT executed. Parse error: {e}. "
            f"Raw arguments received: {raw_args[:500]!r}. "
            f"Re-issue the tool call with well-formed JSON arguments."
        )


def _line_anchored_offsets(haystack: str, needle: str) -> List[int]:
    """Offsets where `needle` occupies whole lines of `haystack`.

    Plain substring matching would let a hunk removing 'total = 1' rewrite the
    middle of '    self.total = 1'.
    """
    offsets: List[int] = []
    start = 0
    while True:
        i = haystack.find(needle, start)
        if i < 0:
            return offsets
        end = i + len(needle)
        if (i == 0 or haystack[i - 1] == "\n") and (
            end == len(haystack) or haystack[end] in "\r\n"
        ):
            offsets.append(i)
        start = i + 1


class ToolRegistry:
    def __init__(
        self,
        workspace_root: Optional[str] = None,
        read_only: bool = False,
        cancel_event: Optional[threading.Event] = None,
        on_output: Optional[Callable[[str], None]] = None,
        load_mcp: bool = True,
        allowed_tools: Optional[set[str]] = None,
        record_undo: bool = True,
    ):
        self.workspace_root = Path(workspace_root or os.getcwd()).resolve()
        self.read_only = read_only
        # Set by the UI to stop a running turn; only run_command watches it.
        self.cancel_event = cancel_event
        # Called once per run_command output line, live, from the reader thread.
        self.on_output = on_output
        self.record_undo = record_undo
        # Path containment is workspace-specific. Trust remains session-global and
        # is synchronized immediately before each check.
        self.safety_guard = SafetyGuard(
            workspace_root=str(self.workspace_root), policy_path=guard.policy_path
        )
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._mcp_servers: Dict[str, Any] = {}
        self._mcp_status: List[Dict[str, Any]] = []
        self._register_default_tools()
        if read_only:
            self._tools = {n: t for n, t in self._tools.items() if n in READ_ONLY_TOOLS}
        if allowed_tools is not None:
            self.restrict_to(allowed_tools)
        # A read-only registry (reviewer subagents) must not gain third-party tools
        # that can write; MCP servers are opt-in for full registries only.
        if load_mcp and not read_only:
            self.attach_mcp()

    def register(self, name: str, description: str, parameters: Dict[str, Any], func: Callable):
        """Register a new tool callable with OpenAI-compatible function definition."""
        self._tools[name] = {
            "name": name,
            "description": description,
            "parameters": parameters,
            "func": func,
        }

    def unregister(self, name: str) -> None:
        """Remove an optional tool from future tool snapshots."""
        self._tools.pop(name, None)

    def restrict_to(self, allowed_tools) -> None:
        """Apply an explicit least-privilege allowlist to registered tools."""
        allowed = set(allowed_tools)
        self._tools = {name: tool for name, tool in self._tools.items() if name in allowed}

    def _active_guard(self) -> SafetyGuard:
        self.safety_guard.trust_tier = guard.get_trust_tier()
        return self.safety_guard

    def get_openai_tools(self) -> List[Dict[str, Any]]:
        """Return tools formatted for OpenAI / LM Studio / Ollama tool-calling API."""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["parameters"],
                },
            }
            for tool in self._tools.values()
        ]

    def execute(
        self,
        name: str,
        args: Dict[str, Any],
        confirm_callback: Optional[Callable[[str], bool]] = None,
    ) -> ToolResult:
        """Execute a registered tool with guardrail checks, lifecycle hooks, and audit recording."""
        if name not in self._tools:
            return ToolResult(
                f"Error: Unknown tool '{name}'. Available: {list(self._tools.keys())}",
                is_error=True,
            )

        # 1. Pre-tool lifecycle hook (DashClaw & Secret Guard)
        allowed, hook_err = interceptor.execute_lifecycle_hook(
            event="pre_tool", tool_name=name, args=args
        )
        if not allowed:
            audit_manager.record(
                event_type="governance_hardstop",
                description=f"Hook BLOCKED {name}",
                details={"hook_error": hook_err, "args": args},
                approved=False,
            )
            return ToolResult(f"BLOCKED by Lifecycle Hook: {hook_err}", is_error=True)

        tool = self._tools[name]
        try:
            res = tool["func"](args, confirm_callback=confirm_callback)

            # 2. Post-tool lifecycle hook (Correction Tracker & Audit)
            interceptor.execute_lifecycle_hook(
                event="post_tool", tool_name=name, args=args, result=res.output
            )

            audit_manager.record(
                event_type="tool_exec",
                description=f"Executed tool: {name}",
                details={"tool": name, "args": args, "is_error": res.is_error},
            )
            return res
        except Exception as e:
            return ToolResult(f"Error executing {name}: {str(e)}", is_error=True)

    # --- MCP (Model Context Protocol) ---

    def attach_mcp(self, workspace_root: Optional[str] = None):
        """Register every tool of every configured MCP server as mcp__<server>__<tool>.

        Servers are discovered from .agnostic/mcp.json, .mcp.json and ~/.agnostic/mcp.json.
        A missing, malformed or dead server is recorded in mcp_status() and skipped —
        it must never break registry construction.
        """
        from agent.tools.mcp import load_servers, register_atexit

        root = str(workspace_root or self.workspace_root)
        try:
            servers, notes = load_servers(root)
        except Exception as e:  # unreadable config dir, bad permissions, …
            log.warning("MCP config discovery failed: %s", e)
            self._mcp_status.append(
                {"server": "(config)", "state": "error", "tool_count": 0, "error": str(e)}
            )
            return

        for name, message in notes:
            log.warning("MCP %s: %s", name, message)
            self._mcp_status.append(
                {"server": name, "state": "skipped", "tool_count": 0, "error": message}
            )

        started = []
        for server in servers:
            entry = {"server": server.name, "state": "stopped", "tool_count": 0, "error": None}
            self._mcp_status.append(entry)
            self._mcp_servers[server.name] = server
            try:
                tools = server.list_tools()
            except Exception as e:  # one broken server must not cost the user the others
                log.warning("MCP server '%s' unavailable: %s", server.name, e)
                entry["state"] = "error"
                entry["error"] = str(e)
                server.stop()
                continue
            started.append(server)
            for tool in tools:
                tool_name = tool.get("name")
                if not tool_name:
                    continue
                schema = tool.get("inputSchema")
                self.register(
                    name=f"mcp__{server.name}__{tool_name}",
                    description=tool.get("description")
                    or f"MCP tool '{tool_name}' from server '{server.name}'.",
                    parameters=schema if isinstance(schema, dict) else {"type": "object"},
                    func=self._make_mcp_func(server, tool_name),
                )
                entry["tool_count"] += 1

        if started:
            register_atexit(started)

    def _make_mcp_func(self, server, tool_name: str) -> Callable:
        """Bind one remote tool. Calls still land in execute(), so governance applies."""

        def _call(args: Dict[str, Any], **_kwargs) -> ToolResult:
            try:
                text, is_error = server.call_tool(tool_name, args or {})
            except Exception as e:
                return ToolResult(f"MCP server '{server.name}' error: {e}", is_error=True)
            return ToolResult(_truncate(text) or "[no content returned]", is_error=is_error)

        return _call

    def mcp_status(self) -> List[Dict[str, Any]]:
        """Per-server MCP state for the /mcp command: server, state, tool_count, error."""
        rows = []
        for entry in self._mcp_status:
            row = dict(entry)
            server = self._mcp_servers.get(row["server"])
            if server is not None and row["state"] != "error":
                row["state"] = server.state
            rows.append(row)
        return rows

    def reload_mcp(self) -> str:
        """Stop every server, drop every mcp__* tool, re-attach from the config files.

        AgentLoop._run_turn snapshots registry.get_openai_tools() once per turn, so a
        reload takes effect on the NEXT turn, never mid-turn.
        """
        from agent.tools.mcp import stop_all

        stop_all(list(self._mcp_servers.values()))
        self._tools = {n: t for n, t in self._tools.items() if not n.startswith("mcp__")}
        self._mcp_servers.clear()
        self._mcp_status.clear()
        if not self.read_only:
            self.attach_mcp()
        tools = sum(1 for n in self._tools if n.startswith("mcp__"))
        return f"{len(self._mcp_servers)} server(s), {tools} tool(s)"

    def _register_default_tools(self):
        # 1. run_command
        self.register(
            name="run_command",
            description="Run a shell command safely in the project environment. Commands are checked against safety guardrails.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The exact shell command line to run.",
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Optional working directory relative to workspace root.",
                    },
                },
                "required": ["command"],
            },
            func=self._tool_run_command,
        )

        # 2. read_file
        self.register(
            name="read_file",
            description="Read content of a file from disk with optional start and end line ranges (1-indexed).",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Relative or absolute path to the file.",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "Optional 1-indexed starting line.",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Optional 1-indexed ending line (inclusive).",
                    },
                },
                "required": ["file_path"],
            },
            func=self._tool_read_file,
        )

        # 3. write_file
        self.register(
            name="write_file",
            description="Write content to a file. Overwrites if file exists, or creates new file and parent directories.",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Target file path."},
                    "content": {
                        "type": "string",
                        "description": "Full file content to write.",
                    },
                },
                "required": ["file_path", "content"],
            },
            func=self._tool_write_file,
        )

        # 4. edit_file
        self.register(
            name="edit_file",
            description="Perform a surgical replacement of an exact block of text in an existing file.",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Target file path."},
                    "target_content": {
                        "type": "string",
                        "description": "The exact substring/lines to replace.",
                    },
                    "replacement_content": {
                        "type": "string",
                        "description": "The replacement content.",
                    },
                },
                "required": ["file_path", "target_content", "replacement_content"],
            },
            func=self._tool_edit_file,
        )

        # 5. grep_search
        self.register(
            name="grep_search",
            description="Search for exact text or regex pattern across files in directory.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search pattern or string.",
                    },
                    "search_path": {
                        "type": "string",
                        "description": "Directory or file to search (defaults to workspace root).",
                    },
                    "file_pattern": {
                        "type": "string",
                        "description": "Optional glob pattern to filter files, e.g. '*.py' or '*.ts'",
                    },
                },
                "required": ["query"],
            },
            func=self._tool_grep_search,
        )

        # 6. find_files
        self.register(
            name="find_files",
            description="Find files matching a glob pattern.",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern, e.g. '**/*.py' or 'src/**/*.ts'",
                    },
                    "search_path": {
                        "type": "string",
                        "description": "Directory to search from.",
                    },
                },
                "required": ["pattern"],
            },
            func=self._tool_find_files,
        )

        # 7. apply_patch
        self.register(
            name="apply_patch",
            description="Apply a unified diff / patch to a file with fuzzy block matching tolerance.",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path of the file to patch.",
                    },
                    "patch_content": {
                        "type": "string",
                        "description": "Unified diff or search/replace hunk block.",
                    },
                },
                "required": ["file_path", "patch_content"],
            },
            func=self._tool_apply_patch,
        )

        # 8. get_outline
        self.register(
            name="get_outline",
            description="Extract class definitions, function signatures, methods, and docstrings from a file (AST symbol tree) without reading full lines.",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "File to generate symbol outline for.",
                    },
                },
                "required": ["file_path"],
            },
            func=self._tool_get_outline,
        )

        # 9. simulate_command
        self.register(
            name="simulate_command",
            description="Simulate and dry-run a shell command using AST/Regex safety inspection before actual execution.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to analyze and simulate.",
                    },
                },
                "required": ["command"],
            },
            func=self._tool_simulate_command,
        )

        # 10. read_url_content
        self.register(
            name="read_url_content",
            description="Fetch text or markdown content from a URL via HTTP request without launching a browser.",
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL to fetch content from.",
                    }
                },
                "required": ["url"],
            },
            func=self._tool_read_url_content,
        )

        # 11. search_web
        self.register(
            name="search_web",
            description="Search the web for technical documentation, library reference, or query terms.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query keywords.",
                    },
                    "domain": {
                        "type": "string",
                        "description": "Optional domain to restrict results to (e.g. github.com, python.org).",
                    },
                },
                "required": ["query"],
            },
            func=self._tool_search_web,
        )

        # 12. find_symbol
        self.register(
            name="find_symbol",
            description="Look up a class, function or method by name in the AST symbol index and return its location and source.",
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Symbol name, e.g. 'ToolRegistry' or 'ToolRegistry.execute'.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "How many near-matches to list when the name is not an exact hit (default 5).",
                    },
                },
                "required": ["name"],
            },
            func=self._tool_find_symbol,
        )

        # 13. read_project_memory
        self.register(
            name="read_project_memory",
            description="Read persistent project memory, learned conventions, architecture notes, or deviations.",
            parameters={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Optional specific memory key or section (e.g. 'conventions', 'architecture', 'deviations').",
                    }
                },
            },
            func=self._tool_read_project_memory,
        )

        # 14. write_project_memory
        self.register(
            name="write_project_memory",
            description="Persist learned conventions, deviations, architectural decisions, or state across sessions.",
            parameters={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Memory key or topic name (e.g. 'conventions', 'deviations', 'architecture').",
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to store.",
                    },
                },
                "required": ["key", "content"],
            },
            func=self._tool_write_project_memory,
        )

    # --- Tool Implementations ---

    def _tool_run_command(
        self,
        args: Dict[str, Any],
        confirm_callback: Optional[Callable[[str], bool]] = None,
    ) -> ToolResult:
        cmd = args["command"]
        cwd = args.get("cwd")
        if cwd:
            safe, reason = self._active_guard().check_path_access(str(cwd))
            if not safe:
                return ToolResult(reason, is_error=True)
        target_dir = (self.workspace_root / cwd).resolve() if cwd else self.workspace_root

        is_blocked, req_approval, reason = self._active_guard().check_command_safety(cmd)
        if is_blocked:
            audit_manager.record(
                event_type="governance_hardstop",
                description=f"Command BLOCKED: {cmd}",
                details={"reason": reason},
                approved=False,
            )
            return ToolResult(f"BLOCKED by Safety Guard: {reason}", is_error=True)

        if req_approval:
            # Deny by default: a hard-stop that survived the trust-tier check
            # requires an explicit approver. No wired callback means no human
            # said yes, so it must NOT auto-approve.
            if confirm_callback:
                approved = confirm_callback(
                    f"Command requires confirmation: {cmd}\nReason: {reason}"
                )
            else:
                approved = False
                reason = f"{reason} (no approver wired — denied by default)"
            audit_manager.record(
                event_type="governance_hardstop",
                description=f"Hard-Stop command: {cmd}",
                details={"reason": reason},
                approved=approved,
            )
            if not approved:
                return ToolResult("Command execution was rejected by user.", is_error=True)

        try:
            # Popen + a reader thread instead of subprocess.run: the reader hands every
            # line to the UI while the command is still running, and the poll loop is
            # what lets a cancelled turn kill a long child instead of waiting 120s.
            proc = subprocess.Popen(
                cmd,
                cwd=target_dir,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # one stream: interleaved as the user would see it
                text=True,
            )
            lines: List[str] = []

            def _read():
                for line in iter(proc.stdout.readline, ""):
                    lines.append(line)
                    if self.on_output:
                        self.on_output(line.rstrip("\r\n"))

            reader = threading.Thread(target=_read, daemon=True)
            reader.start()

            deadline = time.monotonic() + 120
            while proc.poll() is None:
                cancelled = self.cancel_event is not None and self.cancel_event.is_set()
                if cancelled or time.monotonic() >= deadline:
                    proc.kill()
                    reader.join(timeout=5)
                    return ToolResult(
                        "[cancelled by user]"
                        if cancelled
                        else "Error: Command execution timed out after 120s.",
                        is_error=True,
                    )
                time.sleep(0.05)
            reader.join(timeout=5)

            output = "".join(lines)
            if not output.strip():
                output = f"[Command completed with exit code {proc.returncode}]"

            # Smart output truncation to avoid context blowout while preserving crucial headers and errors
            return ToolResult(_truncate(output), is_error=(proc.returncode != 0))
        except Exception as e:
            return ToolResult(f"Error running command: {str(e)}", is_error=True)

    def _tool_read_file(self, args: Dict[str, Any], **_kwargs) -> ToolResult:
        raw_path = args["file_path"]
        safe, reason = self._active_guard().check_path_access(raw_path)
        if not safe:
            return ToolResult(reason, is_error=True)

        target_file = (self.workspace_root / raw_path).resolve()
        if not target_file.exists() or not target_file.is_file():
            return ToolResult(f"Error: File not found: {raw_path}", is_error=True)

        try:
            with open(target_file, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            start = max(1, args.get("start_line", 1)) - 1
            end = min(len(lines), args.get("end_line", len(lines)))

            numbered_lines = [f"{i + 1:4d}: {lines[i]}" for i in range(start, end)]
            body = "".join(numbered_lines)
            # An explicit range is the model paging deliberately — never truncate that.
            paging = args.get("start_line") is not None or args.get("end_line") is not None
            return ToolResult(body if paging else _truncate(body))
        except Exception as e:
            return ToolResult(f"Error reading file: {str(e)}", is_error=True)

    def _lint_note(self, target_file: Path) -> str:
        """Advisory ruff feedback after a successful .py write. Never fatal, and
        silent when ruff is missing, times out, or the file is clean."""
        if target_file.suffix != ".py":
            return ""
        clean, out = interceptor.run_quick_lint(target_file, self.workspace_root)
        return "" if clean or not out else f"\n[lint] {out}"

    def _tool_write_file(
        self,
        args: Dict[str, Any],
        confirm_callback: Optional[Callable[[str], bool]] = None,
        **_kwargs,
    ) -> ToolResult:
        raw_path = args["file_path"]
        content = args["content"]
        safe, reason = self._active_guard().check_path_access(raw_path)
        if not safe:
            return ToolResult(reason, is_error=True)

        target_file = (self.workspace_root / raw_path).resolve()
        prev_content = None
        if target_file.exists() and target_file.is_file():
            try:
                # newline='' keeps the file's own endings in the undo snapshot.
                with open(target_file, "r", encoding="utf-8", errors="replace", newline="") as f:
                    prev_content = f.read()
            except OSError:  # no undo snapshot for an unreadable file; the write still proceeds
                pass

        # Post-edit syntax interceptor validation
        from agent.governance.interceptor import CodeInterceptor

        valid, syntax_err = CodeInterceptor.validate_syntax(target_file, content)
        if not valid:
            return ToolResult(
                f"Validation Error (Intercepted before write): {syntax_err}. Modification aborted to avoid syntax breakage.",
                is_error=True,
            )

        try:
            target_file.parent.mkdir(parents=True, exist_ok=True)
            from agent.tools.diff_viewer import DiffViewer
            from rich.console import Console

            _con = Console()
            if prev_content is not None:
                # Presentation only — never fail the tool.
                try:
                    _con.print(DiffViewer.render_diff(target_file.name, prev_content, content))
                except Exception:  # presentation only: a render failure must never fail the write
                    pass
                import difflib

                raw_diff = "".join(
                    difflib.unified_diff(
                        prev_content.splitlines(keepends=True),
                        content.splitlines(keepends=True),
                        fromfile=f"a/{target_file.name}",
                        tofile=f"b/{target_file.name}",
                        n=2,
                    )
                )
                if raw_diff:
                    try:
                        from agent.web.server import companion_telemetry

                        companion_telemetry.set_diff(raw_diff, target_file.name)
                        companion_telemetry.log_event(
                            "diff", f"Wrote {target_file.name}:\n{raw_diff}"
                        )
                    except ImportError:  # web companion is optional
                        pass

            if self.record_undo:
                from agent.governance.undo import undo_manager

                undo_manager.record_change(
                    file_path=target_file,
                    previous_content=prev_content,
                    new_content=content,
                    action="write" if prev_content is not None else "create",
                )
            audit_manager.record(
                event_type="file_write" if prev_content is not None else "file_create",
                description=f"Wrote file {raw_path}",
                details={"file": raw_path, "bytes": len(content)},
            )
            with open(target_file, "w", encoding="utf-8", newline="") as f:
                f.write(content)
            return ToolResult(
                f"Successfully wrote {len(content)} characters to {raw_path}"
                + self._lint_note(target_file)
            )
        except Exception as e:
            return ToolResult(f"Error writing file: {str(e)}", is_error=True)

    def _tool_edit_file(
        self,
        args: Dict[str, Any],
        confirm_callback: Optional[Callable[[str], bool]] = None,
        **_kwargs,
    ) -> ToolResult:
        raw_path = args["file_path"]
        target = args["target_content"]
        replacement = args["replacement_content"]

        safe, reason = self._active_guard().check_path_access(raw_path)
        if not safe:
            return ToolResult(reason, is_error=True)

        target_file = (self.workspace_root / raw_path).resolve()
        if not target_file.exists():
            return ToolResult(f"Error: Target file {raw_path} does not exist.", is_error=True)

        try:
            with open(target_file, "r", encoding="utf-8", errors="replace", newline="") as f:
                content = f.read()

            target = _match_newlines(target, content)
            replacement = _match_newlines(replacement, content)

            if target not in content:
                return ToolResult(
                    f"Error: target_content not found in {raw_path}. Make sure whitespace and line breaks match exactly.",
                    is_error=True,
                )

            count = content.count(target)
            if count > 1:
                return ToolResult(
                    f"Error: target_content matched {count} occurrences in {raw_path}. Please provide a larger unique context block.",
                    is_error=True,
                )

            new_content = content.replace(target, replacement, 1)

            # Post-edit syntax interceptor validation
            from agent.governance.interceptor import CodeInterceptor

            valid, syntax_err = CodeInterceptor.validate_syntax(target_file, new_content)
            if not valid:
                return ToolResult(
                    f"Validation Error (Intercepted before save): {syntax_err}. File edit was reverted.",
                    is_error=True,
                )

            # Render visual diff card (presentation only — never fail the tool)
            try:
                from agent.tools.diff_viewer import DiffViewer
                from rich.console import Console

                Console().print(DiffViewer.render_diff(target_file.name, content, new_content))
            except Exception:  # presentation only: a render failure must never fail the edit
                pass
            import difflib

            raw_diff = "".join(
                difflib.unified_diff(
                    content.splitlines(keepends=True),
                    new_content.splitlines(keepends=True),
                    fromfile=f"a/{target_file.name}",
                    tofile=f"b/{target_file.name}",
                    n=2,
                )
            )
            if raw_diff:
                try:
                    from agent.web.server import companion_telemetry

                    companion_telemetry.set_diff(raw_diff, target_file.name)
                    companion_telemetry.log_event("diff", f"Edited {target_file.name}:\n{raw_diff}")
                except ImportError:  # web companion is optional
                    pass

            # Record in undo history & audit
            if self.record_undo:
                from agent.governance.undo import undo_manager

                undo_manager.record_change(
                    file_path=target_file,
                    previous_content=content,
                    new_content=new_content,
                    action="edit",
                )
            audit_manager.record(
                event_type="file_edit",
                description=f"Surgically edited {raw_path}",
                details={"file": raw_path},
            )

            with open(target_file, "w", encoding="utf-8", newline="") as f:
                f.write(new_content)

            return ToolResult(
                f"Successfully replaced 1 occurrence in {raw_path}" + self._lint_note(target_file)
            )
        except Exception as e:
            return ToolResult(f"Error editing file: {str(e)}", is_error=True)

    def _rel(self, p: Path) -> str:
        try:
            return str(p.relative_to(self.workspace_root)).replace("\\", "/")
        except ValueError:
            return str(p)

    def _walk_files(self, target_dir: Path, name_pattern: str = "") -> Iterator[Path]:
        """Yield searchable files under target_dir.

        Prunes dot-dirs and vendored trees in-place (same walk as the indexer) so the
        tens of thousands of files under node_modules are never stat'ed at all, and
        drops binary/lockfile extensions the model cannot use.
        """
        for root, dirs, files in os.walk(target_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in DEFAULT_IGNORED_DIRS]
            for f in files:
                if f.startswith(".") or Path(f).suffix.lower() in DEFAULT_IGNORED_EXTS:
                    continue
                if name_pattern and not fnmatch.fnmatch(f, name_pattern):
                    continue
                yield Path(root) / f

    def _tool_grep_search(self, args: Dict[str, Any], **_kwargs) -> ToolResult:
        import re

        query = args["query"]
        search_path = args.get("search_path", ".")
        file_pattern = args.get("file_pattern", "")

        target_dir = (self.workspace_root / search_path).resolve()
        if not target_dir.exists():
            return ToolResult(f"Search path not found: {search_path}", is_error=True)

        try:
            rx = re.compile(query, re.IGNORECASE)
            mode = "regex"
        except re.error as e:
            rx = re.compile(re.escape(query), re.IGNORECASE)
            mode = f"literal (not a valid regex: {e})"

        results: List[str] = []
        capped = False
        try:
            for file_path in self._walk_files(target_dir, file_pattern):
                try:
                    blob = file_path.read_bytes().decode("utf-8", errors="ignore")
                except OSError:  # unreadable file (permissions/race); skip it and keep searching
                    continue
                # Whole-file prefilter: most files hold no hit, and the guard check
                # and per-line scan are far more expensive than one search.
                if not rx.search(blob):
                    continue
                safe, _ = self._active_guard().check_path_access(str(file_path))
                if not safe:
                    continue
                rel_path = self._rel(file_path)
                for idx, line in enumerate(blob.splitlines(), 1):
                    if rx.search(line):
                        results.append(f"{rel_path}:{idx}: {line.strip()[:160]}")
                        if len(results) >= 40:
                            capped = True
                            break
                if capped:
                    break

            if not results:
                return ToolResult(f"No matches found for '{query}' ({mode} match).")
            if capped:
                results.append("[stopped at 40 results; narrow search_path or file_pattern]")
            return ToolResult(f"### [grep_search '{query}' — {mode} match]\n" + "\n".join(results))
        except Exception as e:
            return ToolResult(f"Error during grep search: {str(e)}", is_error=True)

    def _tool_find_files(self, args: Dict[str, Any], **_kwargs) -> ToolResult:
        pattern = args["pattern"]
        search_path = args.get("search_path", ".")
        target_dir = (self.workspace_root / search_path).resolve()

        # '**/' matches zero directories in pathlib but not in fnmatch, so try both.
        patterns = [pattern] + ([pattern[3:]] if pattern.startswith("**/") else [])
        try:
            matches: List[str] = []
            capped = False
            for p in self._walk_files(target_dir):
                rel = self._rel(p)
                if not any(fnmatch.fnmatch(rel, pat) for pat in patterns):
                    continue
                safe, _ = self._active_guard().check_path_access(str(p))
                if not safe:
                    continue
                matches.append(rel)
                if len(matches) >= 50:
                    capped = True
                    break

            if not matches:
                return ToolResult(f"No files matched pattern '{pattern}'.")
            if capped:
                matches.append("[stopped at 50 results; narrow search_path or pattern]")
            return ToolResult("\n".join(matches))
        except Exception as e:
            return ToolResult(f"Error finding files: {str(e)}", is_error=True)

    def _tool_apply_patch(
        self,
        args: Dict[str, Any],
        confirm_callback: Optional[Callable[[str], bool]] = None,
        **_kwargs,
    ) -> ToolResult:
        raw_path = args["file_path"]
        patch = args["patch_content"]

        safe, reason = self._active_guard().check_path_access(raw_path)
        if not safe:
            return ToolResult(reason, is_error=True)

        target_file = (self.workspace_root / raw_path).resolve()
        if not target_file.exists():
            return ToolResult(f"File not found: {raw_path}", is_error=True)

        try:
            with open(target_file, "r", encoding="utf-8", errors="replace", newline="") as f:
                original_content = f.read()

            hunks = self._parse_patch_hunks(patch)
            if isinstance(hunks, str):
                return ToolResult(f"PATCH FAILED: {hunks}", is_error=True)

            new_content = original_content
            for idx, (old_block, new_block) in enumerate(hunks, 1):
                old_block = _match_newlines(old_block, new_content)
                new_block = _match_newlines(new_block, new_content)
                offsets = _line_anchored_offsets(new_content, old_block)
                count = len(offsets)
                if count == 0:
                    return ToolResult(
                        f"PATCH FAILED (no write): hunk {idx} of {len(hunks)} did not match {raw_path}. "
                        "The removed block must match the file EXACTLY, including indentation. "
                        f"Searched for:\n{old_block}",
                        is_error=True,
                    )
                if count > 1:
                    return ToolResult(
                        f"PATCH FAILED (no write): hunk {idx} of {len(hunks)} matched {count} times in {raw_path} "
                        "and is not unique. Include more surrounding context lines. "
                        f"Searched for:\n{old_block}",
                        is_error=True,
                    )
                at = offsets[0]
                new_content = new_content[:at] + new_block + new_content[at + len(old_block) :]

            if new_content == original_content:
                return ToolResult(
                    f"PATCH FAILED (no write): patch produced no change to {raw_path}.",
                    is_error=True,
                )

            # Syntax interceptor
            from agent.governance.interceptor import CodeInterceptor

            valid, syntax_err = CodeInterceptor.validate_syntax(target_file, new_content)
            if not valid:
                return ToolResult(f"PATCH FAILED (no write): {syntax_err}", is_error=True)

            # Render visual diff card (presentation only — never fail the tool)
            try:
                from agent.tools.diff_viewer import DiffViewer
                from rich.console import Console

                Console().print(
                    DiffViewer.render_diff(target_file.name, original_content, new_content)
                )
            except Exception:  # presentation only: a render failure must never fail the patch
                pass
            import difflib

            raw_diff = "".join(
                difflib.unified_diff(
                    original_content.splitlines(keepends=True),
                    new_content.splitlines(keepends=True),
                    fromfile=f"a/{target_file.name}",
                    tofile=f"b/{target_file.name}",
                    n=2,
                )
            )
            if raw_diff:
                try:
                    from agent.web.server import companion_telemetry

                    companion_telemetry.set_diff(raw_diff, target_file.name)
                    companion_telemetry.log_event(
                        "diff", f"Patched {target_file.name}:\n{raw_diff}"
                    )
                except ImportError:  # web companion is optional
                    pass

            if self.record_undo:
                from agent.governance.undo import undo_manager

                undo_manager.record_change(target_file, original_content, new_content, "patch")
            audit_manager.record(
                event_type="file_patch",
                description=f"Applied patch to {raw_path}",
                details={"file": raw_path, "hunks": len(hunks)},
            )

            with open(target_file, "w", encoding="utf-8", newline="") as f:
                f.write(new_content)
            return ToolResult(
                f"Successfully applied patch to {raw_path} ({len(hunks)} hunk(s))"
                + self._lint_note(target_file)
            )

        except Exception as e:
            return ToolResult(f"Error applying patch: {str(e)}", is_error=True)

    @staticmethod
    def _parse_patch_hunks(patch: str):
        """Parse a patch into [(old_block, new_block)]. Returns an error string on failure.

        Text is preserved verbatim (indentation included); only the leading diff marker is stripped.
        """
        if "<<<<<<< SEARCH" in patch and "=======" in patch and ">>>>>>> REPLACE" in patch:
            import re

            blocks = re.findall(
                r"<<<<<<< SEARCH\n(.*?)\n=======\n(.*?)\n>>>>>>> REPLACE",
                patch,
                re.DOTALL,
            )
            if not blocks:
                return "could not parse SEARCH/REPLACE patch blocks."
            return blocks

        hunks = []
        removed, added = [], []

        def _flush():
            if removed or added:
                hunks.append(("\n".join(removed), "\n".join(added)))
            removed.clear()
            added.clear()

        for line in patch.strip("\n").splitlines():
            if line.startswith("@@"):
                _flush()
            elif line.startswith(("---", "+++", "diff ", "index ")):
                continue
            elif line.startswith("-"):
                removed.append(line[1:])
            elif line.startswith("+"):
                added.append(line[1:])
            else:
                # Context line (' ' prefixed or bare blank) belongs to both sides.
                ctx = line[1:] if line.startswith(" ") else line
                removed.append(ctx)
                added.append(ctx)
        _flush()

        hunks = [h for h in hunks if h[0] != h[1]]
        if not hunks:
            return "unrecognized patch format. Use a unified diff or SEARCH/REPLACE blocks."
        return hunks

    def _tool_get_outline(self, args: Dict[str, Any], **_kwargs) -> ToolResult:
        raw_path = args["file_path"]
        safe, reason = self._active_guard().check_path_access(raw_path)
        if not safe:
            return ToolResult(reason, is_error=True)

        target_file = (self.workspace_root / raw_path).resolve()
        if not target_file.exists():
            return ToolResult(f"File not found: {raw_path}", is_error=True)

        if target_file.suffix == ".py":
            import ast

            try:
                content = target_file.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(content, filename=str(target_file))
                outline = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        doc = ast.get_docstring(node)
                        doc_str = f' — "{doc.splitlines()[0]}"' if doc else ""
                        outline.append(f"• class {node.name} (Line {node.lineno}){doc_str}")
                    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        args_list = [a.arg for a in node.args.args]
                        doc = ast.get_docstring(node)
                        doc_str = f' — "{doc.splitlines()[0]}"' if doc else ""
                        outline.append(
                            f"  └─ def {node.name}({', '.join(args_list)}) (Line {node.lineno}){doc_str}"
                        )

                if not outline:
                    return ToolResult(f"No classes or top-level functions found in {raw_path}")
                return ToolResult(
                    f"### [AST Outline: {raw_path}]\n" + _truncate("\n".join(outline))
                )
            except Exception as e:
                return ToolResult(f"Error generating Python AST outline: {str(e)}", is_error=True)

        # Fallback for JS/TS/Other files: Regex signature scanner
        try:
            content = target_file.read_text(encoding="utf-8", errors="replace")
            import re

            sig_matches = []
            for idx, line in enumerate(content.splitlines(), 1):
                clean = line.strip()
                if re.match(
                    r"^(export\s+)?(class|interface|type|function|const\s+[a-zA-Z0-9_]+\s*=\s*(?:async\s*)?\()",
                    clean,
                ):
                    sig_matches.append(f"Line {idx:3d}: {clean[:100]}")
            if sig_matches:
                return ToolResult(
                    f"### [Symbol Signatures: {raw_path}]\n" + "\n".join(sig_matches[:40])
                )
            return ToolResult(f"No symbols extracted from {raw_path}")
        except Exception as e:
            return ToolResult(f"Error reading outline: {str(e)}", is_error=True)

    def _tool_simulate_command(self, args: Dict[str, Any], **_kwargs) -> ToolResult:
        cmd = args["command"]
        is_blocked, req_approval, reason = self._active_guard().check_command_safety(cmd)

        sim_report = [
            f"### [Command Simulation & Safety Pre-Flight]: `{cmd}`",
            f"• **Hard-Stop Guard Status:** {'⛔ BLOCKED' if is_blocked else ('⚠️ REQUIRES CONFIRMATION' if req_approval else '✅ SAFE / ALLOWED')}",
            f"• **Policy Reason:** {reason or 'Standard safe development tool'}",
        ]

        # Check network indicators
        import re

        if re.search(r"\b(curl|wget|fetch|git push|ssh|scp|nc|ping)\b", cmd):
            sim_report.append("• **Network Activity:** 🌐 Outbound network request detected.")
        else:
            sim_report.append(
                "• **Network Activity:** 🔒 Local operation (no outbound network detected)."
            )

        # Check filesystem mutation indicators
        if re.search(r"\b(rm|del|rmdir|mkdir|touch|mv|cp|git clean|git reset)\b", cmd):
            sim_report.append("• **Filesystem Impact:** ⚠️ Modifies or removes files on disk.")
        else:
            sim_report.append("• **Filesystem Impact:** 📄 Read-only or process execution.")

        return ToolResult("\n".join(sim_report))

    def _tool_read_url_content(self, args: Dict[str, Any], **_kwargs) -> ToolResult:
        url = args["url"]
        try:
            import urllib.request
            import re

            req = urllib.request.Request(
                url,
                headers={"User-Agent": USER_AGENT},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw_bytes = resp.read()
                charset = resp.headers.get_content_charset() or "utf-8"
                text = raw_bytes.decode(charset, errors="replace")

            # Basic HTML to text cleaning if HTML
            if "<html" in text.lower():
                # Remove scripts, styles
                text = re.sub(
                    r"<(script|style).*?</\1>",
                    "",
                    text,
                    flags=re.DOTALL | re.IGNORECASE,
                )
                # Replace tags with spaces or line breaks
                text = re.sub(r"<br\s*/?>|</p>|</div>|</li>", "\n", text, flags=re.IGNORECASE)
                text = re.sub(r"<[^>]+>", " ", text)
                text = re.sub(r"\n\s*\n+", "\n\n", text).strip()

            clipped = text[:8000]
            if len(text) > 8000:
                clipped += f"\n\n... [Content truncated, total {len(text)} characters] ..."

            return ToolResult(f"### [URL Content: {url}]\n\n{clipped}")
        except Exception as e:
            return ToolResult(f"Error fetching URL '{url}': {str(e)}", is_error=True)

    def _tool_search_web(self, args: Dict[str, Any], **_kwargs) -> ToolResult:
        query = args["query"]
        domain = args.get("domain", "")
        full_query = f"site:{domain} {query}" if domain else query
        try:
            import urllib.request
            import urllib.parse
            import json
            import re

            # Query DuckDuckGo instant answer / html API
            encoded = urllib.parse.quote_plus(full_query)
            api_url = (
                f"https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1&skip_disambig=1"
            )
            req = urllib.request.Request(api_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))

            results = []
            if data.get("AbstractText"):
                results.append(
                    f"• **Summary**: {data['AbstractText']}\n  Source: {data.get('AbstractURL')}"
                )
            for topic in data.get("RelatedTopics", [])[:5]:
                if isinstance(topic, dict) and "Text" in topic:
                    results.append(f"• {topic['Text']}\n  URL: {topic.get('FirstURL', '')}")

            if not results:
                # Direct DuckDuckGo HTML Lite search parse
                lite_url = f"https://html.duckduckgo.com/html/?q={encoded}"
                lite_req = urllib.request.Request(
                    lite_url,
                    headers={"User-Agent": USER_AGENT},
                )
                with urllib.request.urlopen(lite_req, timeout=10) as resp:
                    html_content = resp.read().decode("utf-8", errors="replace")
                snippets = re.findall(
                    r'<a class="result__snippet[^>]*>(.*?)</a>', html_content, re.DOTALL
                )
                titles = re.findall(
                    r'<a class="result__url[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                    html_content,
                    re.DOTALL,
                )
                for idx, snip in enumerate(snippets[:4]):
                    clean_snip = re.sub(r"<[^>]+>", "", snip).strip()
                    url_match = titles[idx][0] if idx < len(titles) else ""
                    results.append(f"• {clean_snip}\n  Link: {url_match}")

            if not results:
                return ToolResult(f"Search completed for '{query}'. No immediate results found.")
            return ToolResult(f"### [Web Search Results: '{query}']\n" + "\n\n".join(results))
        except Exception as e:
            return ToolResult(f"Error performing web search: {str(e)}", is_error=True)

    def _tool_find_symbol(self, args: Dict[str, Any], **_kwargs) -> ToolResult:
        name = args["name"]
        max_results = args.get("max_results", 5)
        from agent.tools.indexer import code_indexer, CodebaseIndexer

        # The shared index is pointed at the CLI's cwd; a subagent worktree needs its own.
        indexer = code_indexer
        if indexer.workspace_root != self.workspace_root:
            if getattr(self, "_own_indexer", None) is None:
                self._own_indexer = CodebaseIndexer(workspace_root=str(self.workspace_root))
            indexer = self._own_indexer

        hit = indexer.resolve_symbol(name)
        if hit:
            location, snippet = hit
            return ToolResult(f"### [{name} — {location}]\n{_truncate(snippet)}")

        prefix = name.lstrip("#@").strip().lower()
        near = [s for s in indexer.get_all_symbols() if s.lower().startswith(prefix)][:max_results]
        if near:
            return ToolResult(f"No symbol named '{name}'. Closest indexed names: {', '.join(near)}")
        return ToolResult(f"No symbol named '{name}' in the index.", is_error=True)

    def _tool_read_project_memory(self, args: Dict[str, Any], **_kwargs) -> ToolResult:
        key = args.get("key")
        from agent.governance.state import state_manager

        content = state_manager.read_memory(key)
        return ToolResult(content)

    def _tool_write_project_memory(self, args: Dict[str, Any], **_kwargs) -> ToolResult:
        key = args["key"]
        content = args["content"]
        from agent.governance.state import state_manager

        res = state_manager.write_memory(key, content)
        return ToolResult(res)
