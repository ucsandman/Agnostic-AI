"""
agent/tools/subagent.py — Subagent Orchestration Engine
Spawns isolated worker subagents (e.g. Researcher, Code Reviewer, Tester) with their own scratchpads
and distills the findings back to the main agent loop, avoiding context rot (Claude Code pattern).
"""

import json
import uuid
import shutil
import subprocess
from typing import Optional, Literal, Any
from pathlib import Path
from agent.llm.client import LLMClient

WorkspaceMode = Literal["inherit", "share", "branch"]


class SubagentWorker:
    """A scoped, isolated worker subagent with its own context window and optional workspace isolation."""

    def __init__(
        self,
        role: str,
        system_prompt: str,
        client: LLMClient,
        workspace_root: Path,
        workspace_mode: WorkspaceMode = "inherit",
    ):
        self.role = role
        self.system_prompt = system_prompt
        self.client = client
        self.workspace_root = workspace_root
        self.workspace_mode = workspace_mode
        self.active_workspace = self._prepare_workspace()

    def _prepare_workspace(self) -> Path:
        """Provisions workspace based on selected isolation mode."""
        if self.workspace_mode == "inherit":
            return self.workspace_root

        subagent_id = str(uuid.uuid4())[:8]
        scratch_dir = (
            self.workspace_root.parent / f".agnostic_scratch_{self.role}_{subagent_id}"
        )

        if self.workspace_mode == "branch":
            try:
                # Attempt to create an isolated git worktree
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
            except Exception:
                pass

        # Fallback for 'share' or if git worktree fails: copy or shallow sandbox
        try:
            scratch_dir.mkdir(parents=True, exist_ok=True)
            return scratch_dir
        except Exception:
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
                except Exception:
                    pass
            if self.active_workspace.exists():
                shutil.rmtree(self.active_workspace, ignore_errors=True)

    def run_task(self, prompt: str, max_turns: int = 8) -> str:
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt},
        ]

        # Dedicated subagent tool subset (safe reads & searches in active workspace)
        from agent.tools.registry import ToolRegistry

        sub_registry = ToolRegistry(workspace_root=str(self.active_workspace))

        try:
            for _ in range(max_turns):
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
                        try:
                            args = (
                                json.loads(tc.function.arguments)
                                if isinstance(tc.function.arguments, str)
                                else tc.function.arguments
                            )
                        except Exception:
                            args = {}

                        res = sub_registry.execute(fn_name, args)
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

    def __init__(self, client: LLMClient, workspace_root: Optional[str] = None):
        self.client = client
        self.workspace_root = Path(workspace_root or ".").resolve()
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

    def spawn(
        self,
        role: str,
        prompt: str,
        custom_instructions: Optional[str] = None,
        workspace_mode: WorkspaceMode = "inherit",
    ) -> str:
        role_key = role.lower().strip()
        base_prompt = self.subagent_roles.get(
            role_key,
            f"You are a specialized subagent operating as '{role}'. Focus exclusively on completing the given task and return a distilled summary.",
        )
        if custom_instructions:
            base_prompt += f"\nAdditional Instructions:\n{custom_instructions}"

        worker = SubagentWorker(
            role=role,
            system_prompt=base_prompt,
            client=self.client,
            workspace_root=self.workspace_root,
            workspace_mode=workspace_mode,
        )
        result = worker.run_task(prompt)

        # Distill response header
        return f"### [Subagent Report: {role.upper()}]\n{result}\n"

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

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(6, len(tasks))
        ) as executor:
            return list(executor.map(_run_single, tasks))
