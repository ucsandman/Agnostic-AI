"""
agent/tools/registry.py — Typed Tool Registry & Execution Engine
Provides safe terminal execution, surgical file editing, file viewing, search, and MCP tools.
Integrated with Audit Logger, Diff Viewer, and Undo Manager.
"""

import os
import json
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable
from agent import __version__
from agent.governance.guard import guard
from agent.governance.audit import audit_manager
from agent.governance.interceptor import interceptor
from agent.tools.indexer import DEFAULT_IGNORED_DIRS


class ToolResult:
    def __init__(self, output: str, is_error: bool = False):
        self.output = output
        self.is_error = is_error

    def to_dict(self) -> Dict[str, Any]:
        return {"output": self.output, "is_error": self.is_error}


READ_ONLY_TOOLS = ("read_file", "grep_search", "find_files", "get_outline")

# Honest identification — this is a coding agent, not a browser.
USER_AGENT = f"AgnosticAI/{__version__} (+https://github.com/ucsandman/agnostic-harness)"


def _is_search_skipped(path: Path) -> bool:
    """True for dot-paths and vendored dependency trees (node_modules, dist, .venv...).

    Checked before the guard so search never pays the policy cost for the tens of
    thousands of files it would discard anyway.
    """
    return any(part.startswith(".") or part in DEFAULT_IGNORED_DIRS for part in path.parts)


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
        if (i == 0 or haystack[i - 1] == "\n") and (end == len(haystack) or haystack[end] == "\n"):
            offsets.append(i)
        start = i + 1


class ToolRegistry:
    def __init__(self, workspace_root: Optional[str] = None, read_only: bool = False):
        self.workspace_root = Path(workspace_root or os.getcwd()).resolve()
        self.read_only = read_only
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._register_default_tools()
        if read_only:
            self._tools = {n: t for n, t in self._tools.items() if n in READ_ONLY_TOOLS}

    def register(self, name: str, description: str, parameters: Dict[str, Any], func: Callable):
        """Register a new tool callable with OpenAI-compatible function definition."""
        self._tools[name] = {
            "name": name,
            "description": description,
            "parameters": parameters,
            "func": func,
        }

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
            description="Find files and directories matching a glob pattern.",
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

        # 12. manage_subagents
        self.register(
            name="manage_subagents",
            description="List the subagents spawned during this session and their state.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list"],
                        "description": "Action to perform on subagents.",
                    },
                },
                "required": ["action"],
            },
            func=self._tool_manage_subagents,
        )

        # 13. ask_question
        self.register(
            name="ask_question",
            description="Prompt the human operator with structured interactive questions or multi-choice options to clarify requirements or resolve ambiguities.",
            parameters={
                "type": "object",
                "properties": {
                    "questions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "question": {"type": "string"},
                                "options": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "is_multi_select": {"type": "boolean"},
                            },
                            "required": ["question", "options"],
                        },
                        "description": "List of question objects to ask.",
                    }
                },
                "required": ["questions"],
            },
            func=self._tool_ask_question,
        )

        # 14. generate_artifact
        self.register(
            name="generate_artifact",
            description="Generate a visual UI card, HTML preview, or structured markdown artifact for human operator review.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Artifact title."},
                    "content": {
                        "type": "string",
                        "description": "Markdown, HTML, or SVG visual content.",
                    },
                    "artifact_type": {
                        "type": "string",
                        "enum": ["markdown", "html", "svg", "diff"],
                        "description": "Type of visual artifact.",
                    },
                },
                "required": ["title", "content"],
            },
            func=self._tool_generate_artifact,
        )

        # 15. read_project_memory
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

        # 16. write_project_memory
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
        target_dir = (self.workspace_root / cwd).resolve() if cwd else self.workspace_root

        is_blocked, req_approval, reason = guard.check_command_safety(cmd)
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
            res = subprocess.run(
                cmd,
                cwd=target_dir,
                shell=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            output = (res.stdout or "") + (res.stderr or "")
            if not output.strip():
                output = f"[Command completed with exit code {res.returncode}]"

            # Smart output truncation to avoid context blowout while preserving crucial headers and errors
            lines = output.splitlines()
            if len(lines) > 120:
                truncated_output = (
                    "\n".join(lines[:40])
                    + f"\n\n... [Truncated {len(lines) - 80} lines to preserve context] ...\n\n"
                    + "\n".join(lines[-40:])
                )
                output = truncated_output

            return ToolResult(output, is_error=(res.returncode != 0))
        except subprocess.TimeoutExpired:
            return ToolResult("Error: Command execution timed out after 120s.", is_error=True)
        except Exception as e:
            return ToolResult(f"Error running command: {str(e)}", is_error=True)

    def _tool_read_file(self, args: Dict[str, Any], **_kwargs) -> ToolResult:
        raw_path = args["file_path"]
        safe, reason = guard.check_path_access(raw_path)
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
            return ToolResult("".join(numbered_lines))
        except Exception as e:
            return ToolResult(f"Error reading file: {str(e)}", is_error=True)

    def _tool_write_file(
        self,
        args: Dict[str, Any],
        confirm_callback: Optional[Callable[[str], bool]] = None,
        **_kwargs,
    ) -> ToolResult:
        raw_path = args["file_path"]
        content = args["content"]
        safe, reason = guard.check_path_access(raw_path)
        if not safe:
            return ToolResult(reason, is_error=True)

        target_file = (self.workspace_root / raw_path).resolve()
        prev_content = None
        if target_file.exists() and target_file.is_file():
            try:
                prev_content = target_file.read_text(encoding="utf-8", errors="replace")
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
            from agent.governance.undo import undo_manager
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
            with open(target_file, "w", encoding="utf-8") as f:
                f.write(content)
            return ToolResult(f"Successfully wrote {len(content)} characters to {raw_path}")
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

        safe, reason = guard.check_path_access(raw_path)
        if not safe:
            return ToolResult(reason, is_error=True)

        target_file = (self.workspace_root / raw_path).resolve()
        if not target_file.exists():
            return ToolResult(f"Error: Target file {raw_path} does not exist.", is_error=True)

        try:
            with open(target_file, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

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

            with open(target_file, "w", encoding="utf-8") as f:
                f.write(new_content)

            return ToolResult(f"Successfully replaced 1 occurrence in {raw_path}")
        except Exception as e:
            return ToolResult(f"Error editing file: {str(e)}", is_error=True)

    def _tool_grep_search(self, args: Dict[str, Any], **_kwargs) -> ToolResult:
        query = args["query"]
        search_path = args.get("search_path", ".")
        file_pattern = args.get("file_pattern", "")

        target_dir = (self.workspace_root / search_path).resolve()
        if not target_dir.exists():
            return ToolResult(f"Search path not found: {search_path}", is_error=True)

        results = []
        try:
            pattern = f"**/{file_pattern}" if file_pattern else "**/*"
            for file_path in target_dir.glob(pattern):
                if file_path.is_file():
                    if _is_search_skipped(file_path):
                        continue
                    safe, _ = guard.check_path_access(str(file_path))
                    if not safe:
                        continue
                    try:
                        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                            for idx, line in enumerate(f, 1):
                                if query.lower() in line.lower():
                                    rel_path = file_path.relative_to(self.workspace_root)
                                    results.append(f"{rel_path}:{idx}: {line.strip()[:160]}")
                                    if len(results) >= 40:
                                        break
                    except (
                        OSError
                    ):  # unreadable file (permissions/race); skip it and keep searching
                        pass
                if len(results) >= 40:
                    break

            if not results:
                return ToolResult(f"No matches found for '{query}'.")
            return ToolResult("\n".join(results))
        except Exception as e:
            return ToolResult(f"Error during grep search: {str(e)}", is_error=True)

    def _tool_find_files(self, args: Dict[str, Any], **_kwargs) -> ToolResult:
        pattern = args["pattern"]
        search_path = args.get("search_path", ".")
        target_dir = (self.workspace_root / search_path).resolve()

        try:
            matches = []
            for p in target_dir.glob(pattern):
                if _is_search_skipped(p):
                    continue
                safe, _ = guard.check_path_access(str(p))
                if safe:
                    try:
                        rel = p.relative_to(self.workspace_root)
                        matches.append(str(rel))
                    except ValueError:
                        matches.append(str(p))
                if len(matches) >= 50:
                    break

            if not matches:
                return ToolResult(f"No files matched pattern '{pattern}'.")
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

        safe, reason = guard.check_path_access(raw_path)
        if not safe:
            return ToolResult(reason, is_error=True)

        target_file = (self.workspace_root / raw_path).resolve()
        if not target_file.exists():
            return ToolResult(f"File not found: {raw_path}", is_error=True)

        try:
            original_content = target_file.read_text(encoding="utf-8", errors="replace")

            hunks = self._parse_patch_hunks(patch)
            if isinstance(hunks, str):
                return ToolResult(f"PATCH FAILED: {hunks}", is_error=True)

            new_content = original_content
            for idx, (old_block, new_block) in enumerate(hunks, 1):
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

            from agent.governance.undo import undo_manager

            undo_manager.record_change(target_file, original_content, new_content, "patch")
            audit_manager.record(
                event_type="file_patch",
                description=f"Applied patch to {raw_path}",
                details={"file": raw_path, "hunks": len(hunks)},
            )

            target_file.write_text(new_content, encoding="utf-8")
            return ToolResult(f"Successfully applied patch to {raw_path} ({len(hunks)} hunk(s))")

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
        safe, reason = guard.check_path_access(raw_path)
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
                return ToolResult(f"### [AST Outline: {raw_path}]\n" + "\n".join(outline))
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
        is_blocked, req_approval, reason = guard.check_command_safety(cmd)

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

    def _tool_manage_subagents(self, args: Dict[str, Any], **_kwargs) -> ToolResult:
        action = args["action"].lower().strip()
        from agent.tools.subagent import subagent_registry

        if action == "list":
            subagents = subagent_registry.list_subagents()
            if not subagents:
                return ToolResult("No active or background subagents currently registered.")
            import json

            return ToolResult(json.dumps(subagents, indent=2))
        elif action in ("kill", "kill_all"):
            # Subagents run synchronously inside the caller's turn; nothing polls a
            # kill flag, so terminating one is not supported.
            return ToolResult(
                f"NOT IMPLEMENTED — no action taken. '{action}' cannot terminate a "
                "subagent: subagents run to completion inside the spawning turn.",
                is_error=True,
            )
        return ToolResult(f"Unknown action '{action}'.", is_error=True)

    def _tool_ask_question(
        self,
        args: Dict[str, Any],
        confirm_callback: Optional[Callable[[str], bool]] = None,
        **_kwargs,
    ) -> ToolResult:
        questions = args.get("questions", [])
        if not questions:
            return ToolResult("No questions provided.", is_error=True)

        asked = []
        for q in questions:
            q_text = q.get("question", "")
            opts = q.get("options", [])
            multi = q.get("is_multi_select", False)

            lines = [f"\n❓ Question: {q_text}"]
            for i, opt in enumerate(opts, 1):
                lines.append(f"   [{i}] {opt}")
            lines.append("   (Multi-select allowed)" if multi else "   (Single select)")

            formatted = "\n".join(lines)
            # Presentation only — never fail the tool.
            try:
                from rich.console import Console

                Console().print(f"[bold cyan]{formatted}[/bold cyan]")
            except Exception:
                print(formatted)
            asked.append(q_text)

        # The registry only receives a yes/no confirm_callback, which cannot carry a
        # choice. Never invent one: tell the model no human answer exists.
        listed = "\n".join(f"  - {q}" for q in asked)
        return ToolResult(
            "Questions were displayed to the operator, but NO answer was captured "
            "(this tool has no interactive input channel). The operator has not answered:\n"
            f"{listed}\n"
            "Do NOT assume any option was selected. Either proceed with your best "
            "judgement and state your assumption in plain text, or ask these questions "
            "in your text reply and stop."
        )

    def _tool_generate_artifact(self, args: Dict[str, Any], **_kwargs) -> ToolResult:
        title = args["title"]
        content = args["content"]
        art_type = args.get("artifact_type", "markdown")

        artifacts_dir = self.workspace_root / ".agnostic" / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        import re

        safe_title = re.sub(r"[^a-zA-Z0-9_\-]", "_", title.lower())
        ext = ".html" if art_type == "html" else ".svg" if art_type == "svg" else ".md"
        artifact_path = artifacts_dir / f"{safe_title}{ext}"
        artifact_path.write_text(content, encoding="utf-8")

        return ToolResult(
            f"✅ Generated {art_type.upper()} Artifact: {artifact_path.name}\nPath: {str(artifact_path)}"
        )

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
