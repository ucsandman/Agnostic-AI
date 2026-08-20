"""
agent/loop.py — Autonomous Coding Agent Loop & Orchestrator
Connects Harness System Prompt, LLM Tool Calling, Subagents, and Dynamic Workflows.
"""

import os
import json
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
from agent.llm.client import LLMClient, LLMConfig
from agent.tools.registry import (
    READ_ONLY_TOOLS,
    ToolRegistry,
    ToolResult,
    parse_tool_args,
)
from agent.tools.subagent import SubagentManager
from agent.tools.mcp_client import MCPBridge


class AgentLoop:
    def __init__(
        self,
        workspace_root: Optional[str] = None,
        llm_config: Optional[LLMConfig] = None,
        confirm_callback: Optional[Callable[[str], bool]] = None,
        output_callback: Optional[Callable[[str, str], None]] = None,
    ):
        self.workspace_root = Path(workspace_root or os.getcwd()).resolve()
        self.llm_client = LLMClient(llm_config or LLMConfig())
        self.registry = ToolRegistry(workspace_root=str(self.workspace_root))
        self.confirm_callback = confirm_callback or self._default_confirm
        # Delegate, not the value: the TUI replaces confirm_callback after
        # construction and subagents must honour the replacement.
        self.subagents = SubagentManager(
            client=self.llm_client,
            workspace_root=str(self.workspace_root),
            confirm_callback=lambda prompt: self.confirm_callback(prompt),
        )
        self.mcp_bridge = MCPBridge(self.registry)  # noqa: vulture

        self.output_callback = output_callback or self._default_output
        self.history: List[Dict[str, Any]] = []
        self.turn_lock = threading.Lock()

        self._register_subagent_tool()
        self._load_harness_system_prompt()

        try:
            from agent.web.server import companion_telemetry

            companion_telemetry.bind_agent(self)
        except ImportError:  # web companion is optional
            pass

    def _default_confirm(self, prompt: str) -> bool:
        print(f"\n⚠️  [CONFIRMATION REQUIRED]: {prompt}")
        ans = input("Proceed? [y/N]: ").strip().lower()
        return ans in ("y", "yes")

    def _default_output(self, msg_type: str, content: str):
        try:
            from agent.web.server import companion_telemetry

            companion_telemetry.log_event(msg_type, content)
        except ImportError:  # web companion is optional
            pass

        if msg_type == "tool_start":
            print(f"\n⚙️  [Tool: {content}]")
        elif msg_type == "tool_end":
            print(f"✔️  [Tool Output]:\n{content[:500]}{'...' if len(content) > 500 else ''}")
        elif msg_type == "assistant":
            print(f"\n🤖 [Agent]:\n{content}")
        elif msg_type == "subagent":
            print(f"\n🐝 {content}")
        elif msg_type == "error":
            print(f"\n❌ [Error]: {content}")

    def _register_subagent_tool(self):
        self.registry.register(
            name="invoke_subagent",
            description="Spawn an isolated worker subagent (e.g. 'researcher', 'reviewer', 'tester') with its own context window and optional workspace isolation mode ('inherit', 'share', 'branch').",
            parameters={
                "type": "object",
                "properties": {
                    "role": {
                        "type": "string",
                        "description": "Subagent role: 'researcher', 'reviewer', or 'tester'",
                    },
                    "task_prompt": {
                        "type": "string",
                        "description": "Specific, clear instructions for the subagent.",
                    },
                    "custom_instructions": {
                        "type": "string",
                        "description": "Optional extra system instructions.",
                    },
                    "workspace_mode": {
                        "type": "string",
                        "enum": ["inherit", "share", "branch"],
                        "description": "Workspace isolation mode: 'inherit' (shared root), 'share' (shallow clone), or 'branch' (isolated git worktree).",
                    },
                },
                "required": ["role", "task_prompt"],
            },
            func=self._tool_invoke_subagent,
        )

    def _tool_invoke_subagent(self, args: Dict[str, Any], **kwargs) -> ToolResult:
        role = args["role"]
        prompt = args["task_prompt"]
        custom = args.get("custom_instructions")
        mode = args.get("workspace_mode", "inherit")
        self.output_callback(
            "subagent", f"Spawning Subagent '{role}' (workspace: {mode}) for task..."
        )
        result = self.subagents.spawn(
            role=role, prompt=prompt, custom_instructions=custom, workspace_mode=mode
        )
        return ToolResult(result)

    @property
    def is_busy(self) -> bool:
        """True while a turn is running (the UI and web companion poll this)."""
        return self.turn_lock.locked()

    # Kept as an alias: the parser now lives in the registry, shared with subagents.
    _parse_tool_args = staticmethod(parse_tool_args)

    def _load_harness_system_prompt(self, compact: bool = False):
        """Loads compiled system prompt from agnostic-harness SSOT, with optional compact mode for small context local models."""
        # Check workspace storage first, then fall back to the agnostic-ai repository root
        prompt_candidates = [
            self.workspace_root / "storage" / "compiled" / "system_prompt.md",
            Path(__file__).resolve().parent.parent / "storage" / "compiled" / "system_prompt.md",
        ]

        full_prompt = None
        for candidate in prompt_candidates:
            if candidate.exists():
                try:
                    full_prompt = candidate.read_text(encoding="utf-8")
                    break
                except OSError:  # unreadable candidate; fall through to the next path
                    pass

        if full_prompt:
            if compact:
                # Include the core SSOT working agreement badge & distilled non-negotiables
                system_prompt = (
                    "🛡️ [Agnostic Harness v1.2.0 | DashClaw Governed]\n\n"
                    "You are an autonomous AI coding agent bound to the Agnostic AI Harness SSOT.\n\n"
                    "NON-NEGOTIABLES & CORE RULES:\n"
                    "1. NEVER open or read secret env files (.env, .secrets.env). No exceptions.\n"
                    "2. Minimal, surgical code changes. Do not overcomplicate or add unrequested abstractions.\n"
                    "3. Think before coding: state assumptions, inspect existing repo style before modifying.\n"
                    "4. Goal-driven execution: verify changes before claiming done. Evidence over assertions.\n"
                    "5. Use tools (read_file, edit_file, write_file, run_command, grep_search, find_files, invoke_subagent) to execute tasks.\n"
                )
            else:
                system_prompt = full_prompt
        else:
            system_prompt = (
                "🛡️ [Agnostic Harness v1.2.0 | DashClaw Governed]\n"
                "You are an elite, autonomous software engineering agent bound to the Agnostic AI Harness. "
                "Use tools to inspect the repository, write code, run tests, and verify results."
            )

        self.history = [{"role": "system", "content": system_prompt}]

    def run_turn(self, user_input: str, max_steps: int = 15) -> str:
        """Run a single interactive turn, processing tool calls iteratively until completion."""
        self.turn_lock.acquire()
        try:
            return self._run_turn(user_input, max_steps)
        finally:
            self.turn_lock.release()

    def _run_turn(self, user_input: str, max_steps: int) -> str:
        # 1. Check and trigger auto-compaction if context threshold is near
        from agent.governance.context import context_manager

        self.history, compacted, compact_msg = context_manager.auto_compact(self.history)
        if compacted:
            self.output_callback("system", compact_msg)

        self.history.append({"role": "user", "content": user_input})

        tools = self.registry.get_openai_tools()

        for _ in range(max_steps):
            try:
                response = self.llm_client.chat_completion(
                    messages=self.history,
                    tools=tools,
                    tool_choice="auto",
                    stream=True,
                    stream_callback=lambda chunk: self.output_callback("assistant_chunk", chunk),
                )
                msg = response.choices[0].message

                # Check if tool calling was triggered
                if not msg.tool_calls:
                    final_content = msg.content or ""
                    self.history.append({"role": "assistant", "content": final_content})
                    self.output_callback("assistant", final_content)
                    return final_content

                # Assistant made tool calls
                tool_calls_data = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ]

                self.history.append(
                    {
                        "role": "assistant",
                        "content": msg.content or "",
                        "tool_calls": tool_calls_data,
                    }
                )

                if msg.content:
                    self.output_callback("assistant", msg.content)

                # A response cut off at max_tokens mid-arguments yields a broken
                # tool call — feed it back instead of executing it.
                if getattr(response.choices[0], "finish_reason", None) == "length":
                    trunc_msg = (
                        "[Tool call rejected] The response hit the output token limit "
                        "while emitting tool-call arguments, so the call was truncated "
                        "and NOT executed. Retry with a smaller/simpler tool call."
                    )
                    self.output_callback("error", trunc_msg)
                    for tc in msg.tool_calls:
                        self.history.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": trunc_msg,
                            }
                        )
                    continue

                # Process tool calls (parallel for read-only tools, sequential for mutating tools)
                import concurrent.futures

                all_read_only = len(msg.tool_calls) > 1 and all(
                    tc.function.name in READ_ONLY_TOOLS for tc in msg.tool_calls
                )

                if all_read_only:
                    # Execute concurrently using ThreadPoolExecutor
                    def _exec_single(tc):
                        fn_name = tc.function.name
                        args, arg_error = self._parse_tool_args(tc.function.arguments)
                        if arg_error:
                            self.output_callback("error", f"{fn_name}: {arg_error}")
                            return tc, ToolResult(arg_error, is_error=True)
                        self.output_callback(
                            "tool_start",
                            f"⚡ [Parallel] {fn_name}({json.dumps(args, ensure_ascii=False)[:120]})",
                        )
                        res = self.registry.execute(
                            fn_name,
                            args,
                            confirm_callback=self.confirm_callback,
                        )
                        return tc, res

                    with concurrent.futures.ThreadPoolExecutor(
                        max_workers=min(8, len(msg.tool_calls))
                    ) as executor:
                        results = list(executor.map(_exec_single, msg.tool_calls))

                    for tc, res in results:
                        self.output_callback("tool_end", res.output)
                        self.history.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": res.output,
                            }
                        )
                else:
                    # Execute sequentially
                    for tc in msg.tool_calls:
                        fn_name = tc.function.name
                        args, arg_error = self._parse_tool_args(tc.function.arguments)
                        if arg_error:
                            self.output_callback("error", f"{fn_name}: {arg_error}")
                            self.history.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tc.id,
                                    "content": arg_error,
                                }
                            )
                            continue

                        self.output_callback(
                            "tool_start",
                            f"{fn_name}({json.dumps(args, ensure_ascii=False)[:120]})",
                        )

                        res = self.registry.execute(
                            fn_name,
                            args,
                            confirm_callback=self.confirm_callback,
                        )

                        self.output_callback("tool_end", res.output)

                        self.history.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": res.output,
                            }
                        )

            except Exception as e:
                err_str = str(e)
                if "400" in err_str and ("API key" in err_str or "INVALID_ARGUMENT" in err_str):
                    err_msg = (
                        f"Turn execution error: {err_str}\n"
                        f"💡 [Tip]: Ensure GEMINI_API_KEY (or GOOGLE_API_KEY) is set in your environment, "
                        f"or switch provider/model using /model."
                    )
                elif "401" in err_str or "authentication" in err_str.lower():
                    err_msg = (
                        f"Turn execution error: {err_str}\n"
                        f"💡 [Tip]: Authentication failed. Check your API key for the active provider."
                    )
                else:
                    err_msg = f"Turn execution error: {err_str}"
                self.output_callback("error", err_msg)
                return err_msg

        cap_msg = (
            f"[Reached maximum tool call limit ({max_steps} steps) for this turn — "
            f"the task is likely INCOMPLETE. Send another message to continue.]"
        )
        self.output_callback("error", cap_msg)
        return cap_msg
