"""
agent/tools/subagent.py — Subagent Orchestration Engine
Spawns isolated worker subagents (e.g. Researcher, Code Reviewer, Tester) with their own scratchpads
and distills the findings back to the main agent loop, avoiding context rot (Claude Code pattern).
"""

import time
import uuid
import shutil
import subprocess
import threading
import copy
from typing import Callable, Optional, Literal, Any
from pathlib import Path
from agent.llm.client import LLMClient

WorkspaceMode = Literal["inherit", "branch"]

# Roles that must never mutate the workspace, whatever the model asks for.
READ_ONLY_ROLES = {"researcher", "reviewer"}


class SubagentWorker:
    """A scoped, isolated worker subagent with its own context window and optional workspace isolation."""

    def __init__(
        self,
        role: str,
        system_prompt: str,
        client: LLMClient,
        workspace_root: Path,
        workspace_mode: WorkspaceMode = "inherit",
        confirm_callback: Optional[Callable[[str], bool]] = None,
        cancel_event: Optional[threading.Event] = None,
    ):
        self.role = role
        self.system_prompt = system_prompt
        self.client = client
        self.workspace_root = workspace_root
        self.workspace_mode = workspace_mode
        self.confirm_callback = confirm_callback
        self.cancel_event = cancel_event
        self.workspace_note = ""
        self.active_workspace = self._prepare_workspace()

    def build_registry(self):
        """Build this worker's tool registry.

        Non-implementer roles get the read-only subset. An implementer role only gets
        mutating tools when a lead-agent confirm_callback is available to approve them.
        """
        from agent.tools.registry import ToolRegistry

        read_only = self.role.lower().strip() in READ_ONLY_ROLES or self.confirm_callback is None
        return ToolRegistry(
            workspace_root=str(self.active_workspace),
            read_only=read_only,
            cancel_event=self.cancel_event,
            load_mcp=False,
        )

    def _prepare_workspace(self) -> Path:
        """Provisions workspace based on selected isolation mode.

        Only a real git worktree gives isolation; anything else inherits the real
        workspace. An empty scratch dir looks like a repo with no code, and the worker
        then reports 'no such file' with total confidence.
        """
        if self.workspace_mode != "branch":
            return self.workspace_root

        subagent_id = str(uuid.uuid4())[:8]
        scratch_dir = self.workspace_root.parent / f".agnostic_scratch_{self.role}_{subagent_id}"
        try:
            res = subprocess.run(
                f"git worktree add -b scratch-{subagent_id} {scratch_dir} HEAD",
                cwd=self.workspace_root,
                shell=True,
                capture_output=True,
                text=True,
                timeout=15,
            )
            if res.returncode == 0 and scratch_dir.exists():
                return scratch_dir
        except (
            OSError,
            subprocess.SubprocessError,
        ):  # no worktree support; fall through to the shared workspace
            pass

        self.workspace_note = (
            "[Note: no git worktree could be created, so this subagent ran in the shared "
            "workspace instead of an isolated branch.]"
        )
        return self.workspace_root

    def cleanup(self):
        """Cleans up isolated workspaces after task completion."""
        if self.active_workspace != self.workspace_root:
            if self.workspace_mode == "branch":
                try:
                    subprocess.run(
                        f"git worktree remove --force {self.active_workspace}",
                        cwd=self.workspace_root,
                        shell=True,
                        capture_output=True,
                        timeout=15,
                    )
                except (
                    OSError,
                    subprocess.SubprocessError,
                ):  # worktree already gone; rmtree below still runs
                    pass
            if self.active_workspace.exists():
                shutil.rmtree(self.active_workspace, ignore_errors=True)

    def run_task(self, prompt: str, max_turns: int = 8) -> str:
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt},
        ]

        # Dedicated subagent tool subset (safe reads & searches in active workspace)
        from agent.tools.registry import parse_tool_args

        sub_registry = self.build_registry()

        try:
            for _ in range(max_turns):
                if self.cancel_event and self.cancel_event.is_set():
                    return "[Subagent cancelled by user]"
                try:
                    response = self.client.chat_completion(
                        messages=messages,
                        tools=sub_registry.get_openai_tools(),
                        tool_choice="auto",
                    )
                    msg = response.choices[0].message

                    # Check for tool calls
                    if not msg.tool_calls:
                        return msg.content or "[Worker finished with empty response]"

                    # Append assistant message with tool calls
                    messages.append(
                        {
                            "role": "assistant",
                            "content": msg.content,
                            "tool_calls": [
                                {
                                    "id": tc.id,
                                    "type": "function",
                                    "function": {
                                        "name": tc.function.name,
                                        "arguments": tc.function.arguments,
                                    },
                                }
                                for tc in msg.tool_calls
                            ],
                        }
                    )

                    # Execute tools in worker context
                    for tc in msg.tool_calls:
                        fn_name = tc.function.name
                        args, arg_error = parse_tool_args(tc.function.arguments)
                        if arg_error:
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tc.id,
                                    "content": arg_error,
                                }
                            )
                            continue

                        res = sub_registry.execute(
                            fn_name, args, confirm_callback=self.confirm_callback
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": res.output[
                                    :4000
                                ],  # Clip to prevent subagent context blowout
                            }
                        )
                except Exception as e:
                    return f"[Subagent '{self.role}' error: {str(e)}]"

            return f"[Subagent '{self.role}' reached max turns limit ({max_turns})]"
        finally:
            self.cleanup()


class SubagentManager:
    """Manages subagent definitions, creation, and distillation back to the lead agent."""

    def __init__(
        self,
        client: LLMClient,
        workspace_root: Optional[str] = None,
        confirm_callback: Optional[Callable[[str], bool]] = None,
        cancel_event: Optional[threading.Event] = None,
        config=None,
        telemetry_callback: Optional[Callable[[str, str], None]] = None,
        client_factory=None,
    ):
        self.client = client
        self.workspace_root = Path(workspace_root or ".").resolve()
        # Lead-agent confirmation channel; without it subagents stay read-only.
        self.confirm_callback = confirm_callback
        self.cancel_event = cancel_event or threading.Event()
        self.subagent_roles = {
            "researcher": (
                "You are an expert Codebase Researcher. Your job is to thoroughly inspect, find files, grep patterns, "
                "and extract relevant logic from the workspace. Return a structured, dense summary of findings. Do NOT make code modifications."
            ),
            "reviewer": (
                "You are a rigorous Code Quality & Security Reviewer. Inspect proposed changes, find potential regressions, "
                "check for exposed secrets, and verify boundary cases. Provide concise, actionable feedback."
            ),
            "tester": (
                "You are a Test & Verification Specialist. Look at tests and recent changes, formulate edge cases, and run tests via commands to verify functionality."
            ),
        }
        from agent.orchestration.config import OrchestrationConfig, OrchestrationConfigError
        from agent.orchestration.runtime import OrchestrationManager

        try:
            orchestration_config = config or OrchestrationConfig.load(self.workspace_root)
            self.config_error = ""
        except OrchestrationConfigError as exc:
            orchestration_config = OrchestrationConfig.from_dict({})
            self.config_error = str(exc)
        if client_factory is None and type(client) is not LLMClient:

            def client_factory(model_config):
                cloned = copy.deepcopy(client)
                cloned.config = model_config
                if hasattr(cloned, "_step"):
                    cloned._step = 0
                return cloned

        self.orchestrator = OrchestrationManager(
            client,
            workspace_root=self.workspace_root,
            confirm_callback=confirm_callback,
            cancel_event=self.cancel_event,
            config=orchestration_config,
            telemetry_callback=telemetry_callback,
            client_factory=client_factory or LLMClient,
        )
        self.root_agent = self.orchestrator.register_root(orchestration_config.root_role)
        self.root_id = self.root_agent.agent_id

    def spawn(
        self,
        role: str,
        prompt: str,
        custom_instructions: Optional[str] = None,
        workspace_mode: WorkspaceMode = "inherit",
    ) -> str:
        role_key = role.lower().strip()
        if role_key in self.orchestrator.config.roles:
            try:
                result = self.orchestrator.delegate(
                    self.root_id,
                    role_key,
                    prompt,
                    custom_instructions=custom_instructions or "",
                    workspace_mode=workspace_mode,
                    inherit_model=not self.orchestrator.enabled,
                )
                return result.report()
            except Exception as exc:
                return f"### [Subagent Report: {role.upper()} - ERROR]\n{exc}\n"

        # Compatibility for callers that used arbitrary one-off role strings before
        # role profiles existed. These workers stay flat and inherit the root model.
        base_prompt = self.subagent_roles.get(
            role_key,
            f"You are a specialized subagent operating as '{role}'. Focus exclusively on completing the given task and return a distilled summary.",
        )
        if custom_instructions:
            base_prompt += f"\nAdditional Instructions:\n{custom_instructions}"
        legacy_config = self.orchestrator._clone_config(self.client.config)
        legacy_client = self.orchestrator.client_factory(legacy_config)
        worker = SubagentWorker(
            role=role,
            system_prompt=base_prompt,
            client=legacy_client,
            workspace_root=self.workspace_root,
            workspace_mode=workspace_mode,
            confirm_callback=self.confirm_callback,
            cancel_event=self.cancel_event,
        )
        subagent_id = f"sub_{str(uuid.uuid4())[:6]}"
        subagent_registry.register_active(subagent_id, role, workspace_mode)
        try:
            result = worker.run_task(prompt)
            subagent_registry.update_state(
                subagent_id, "completed", detail=f"Result len: {len(result)}"
            )
            return f"### [Subagent Report: {role.upper()}]\n{result}\n{worker.workspace_note}"
        except Exception as exc:
            subagent_registry.update_state(subagent_id, "error", detail=str(exc))
            return f"### [Subagent Report: {role.upper()} - ERROR]\n{exc}\n"

    def spawn_parallel(self, tasks: list[dict[str, Any]]) -> list[str]:
        """Spawn multiple subagents in parallel using concurrent worker threads."""
        import concurrent.futures

        def _run_single(task_def: dict[str, Any]) -> str:
            return self.spawn(
                role=task_def.get("role", "researcher"),
                prompt=task_def["prompt"],
                custom_instructions=task_def.get("custom_instructions"),
                workspace_mode=task_def.get("workspace_mode", "inherit"),
            )

        if all(
            str(task.get("role", "researcher")).lower() in self.orchestrator.config.roles
            for task in tasks
        ):
            packets = [
                {
                    "role": str(task.get("role", "researcher")).lower(),
                    "task": task["prompt"],
                    "custom_instructions": task.get("custom_instructions", ""),
                    "workspace_mode": task.get("workspace_mode", "inherit"),
                    "inherit_model": not self.orchestrator.enabled,
                }
                for task in tasks
            ]
            results = self.orchestrator.spawn_parallel(self.root_id, packets)
            return [result.report() for result in results]

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, len(tasks))) as executor:
            return list(executor.map(_run_single, tasks))


class SubagentRegistry:
    """Tracks active subagents spawned by the lead agent."""

    def __init__(self):
        self._subagents: dict[str, dict[str, Any]] = {}

    def register_active(self, subagent_id: str, role: str, mode: str = "inherit") -> dict[str, Any]:
        info = {
            "conversationId": subagent_id,
            "role": role,
            "type": role,
            "state": "running",
            "workspace_mode": mode,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S") if "time" in globals() else "",
        }
        self._subagents[subagent_id] = info
        return info

    def update_state(self, subagent_id: str, state: str, detail: str = ""):
        if subagent_id in self._subagents:
            self._subagents[subagent_id]["state"] = state
            if detail:
                self._subagents[subagent_id]["stateDetail"] = detail

    def list_subagents(self) -> list[dict[str, Any]]:
        return list(self._subagents.values())

    def kill(self, conversation_ids: list[str]) -> list[str]:
        killed = []
        for cid in conversation_ids:
            if cid in self._subagents:
                self._subagents[cid]["state"] = "killed"
                killed.append(cid)
        return killed


subagent_registry = SubagentRegistry()
