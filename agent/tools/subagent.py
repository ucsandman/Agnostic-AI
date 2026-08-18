"""
agent/tools/subagent.py — Subagent Orchestration Engine
Spawns isolated worker subagents (e.g. Researcher, Code Reviewer, Tester) with their own scratchpads
and distills the findings back to the main agent loop, avoiding context rot (Claude Code pattern).
"""

import json
from typing import Optional
from pathlib import Path
from agent.llm.client import LLMClient


class SubagentWorker:
    """A scoped, isolated worker subagent with its own context window."""

    def __init__(
        self, role: str, system_prompt: str, client: LLMClient, workspace_root: Path
    ):
        self.role = role
        self.system_prompt = system_prompt
        self.client = client
        self.workspace_root = workspace_root

    def run_task(self, prompt: str, max_turns: int = 8) -> str:
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt},
        ]

        # Dedicated subagent tool subset (safe reads & searches)
        from agent.tools.registry import ToolRegistry

        sub_registry = ToolRegistry(workspace_root=str(self.workspace_root))

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
        self, role: str, prompt: str, custom_instructions: Optional[str] = None
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
        )
        result = worker.run_task(prompt)

        # Distill response header
        return f"### [Subagent Report: {role.upper()}]\n{result}\n"
