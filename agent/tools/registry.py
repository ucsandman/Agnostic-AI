"""
agent/tools/registry.py — Typed Tool Registry & Execution Engine
Provides safe terminal execution, surgical file editing, file viewing, search, and MCP tools.
Integrated with Audit Logger, Diff Viewer, and Undo Manager.
"""

import os
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable
from agent.governance.guard import guard
from agent.governance.audit import audit_manager


class ToolResult:
    def __init__(self, output: str, is_error: bool = False):
        self.output = output
        self.is_error = is_error

    def to_dict(self) -> Dict[str, Any]:
        return {"output": self.output, "is_error": self.is_error}


class ToolRegistry:
    def __init__(self, workspace_root: Optional[str] = None):
        self.workspace_root = Path(workspace_root or os.getcwd()).resolve()
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._register_default_tools()

    def register(
        self, name: str, description: str, parameters: Dict[str, Any], func: Callable
    ):
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
        """Execute a registered tool with guardrail checks and audit recording."""
        if name not in self._tools:
            return ToolResult(
                f"Error: Unknown tool '{name}'. Available: {list(self._tools.keys())}",
                is_error=True,
            )

        tool = self._tools[name]
        try:
            res = tool["func"](args, confirm_callback=confirm_callback)
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

    # --- Tool Implementations ---

    def _tool_run_command(
        self,
        args: Dict[str, Any],
        confirm_callback: Optional[Callable[[str], bool]] = None,
    ) -> ToolResult:
        cmd = args["command"]
        cwd = args.get("cwd")
        target_dir = (
            (self.workspace_root / cwd).resolve() if cwd else self.workspace_root
        )

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
            approved = True
            if confirm_callback:
                approved = confirm_callback(
                    f"Command requires confirmation: {cmd}\nReason: {reason}"
                )
            audit_manager.record(
                event_type="governance_hardstop",
                description=f"Hard-Stop command: {cmd}",
                details={"reason": reason},
                approved=approved,
            )
            if not approved:
                return ToolResult(
                    "Command execution was rejected by user.", is_error=True
                )

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
            return ToolResult(
                "Error: Command execution timed out after 120s.", is_error=True
            )
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
            except Exception:
                pass

        try:
            target_file.parent.mkdir(parents=True, exist_ok=True)
            from agent.governance.undo import undo_manager
            from agent.tools.diff_viewer import DiffViewer
            from rich.console import Console

            _con = Console()
            if prev_content is not None:
                _con.print(
                    DiffViewer.render_diff(target_file.name, prev_content, content)
                )

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
            return ToolResult(
                f"Successfully wrote {len(content)} characters to {raw_path}"
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

        safe, reason = guard.check_path_access(raw_path)
        if not safe:
            return ToolResult(reason, is_error=True)

        target_file = (self.workspace_root / raw_path).resolve()
        if not target_file.exists():
            return ToolResult(
                f"Error: Target file {raw_path} does not exist.", is_error=True
            )

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

            # Render visual diff card
            from agent.tools.diff_viewer import DiffViewer
            from rich.console import Console

            Console().print(
                DiffViewer.render_diff(target_file.name, content, new_content)
            )

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
                    safe, _ = guard.check_path_access(str(file_path))
                    if not safe or any(
                        part.startswith(".") for part in file_path.parts
                    ):
                        continue
                    try:
                        with open(
                            file_path, "r", encoding="utf-8", errors="ignore"
                        ) as f:
                            for idx, line in enumerate(f, 1):
                                if query.lower() in line.lower():
                                    rel_path = file_path.relative_to(
                                        self.workspace_root
                                    )
                                    results.append(
                                        f"{rel_path}:{idx}: {line.strip()[:160]}"
                                    )
                                    if len(results) >= 40:
                                        break
                    except Exception:
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
                safe, _ = guard.check_path_access(str(p))
                if safe and not any(part.startswith(".git") for part in p.parts):
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
