"""
agent/workflows/swarm.py — Parallel Multi-Subagent Swarm Engine (/swarm)
Dispatches parallel worker subagents (Researcher, Implementer, Security Reviewer) concurrently
and synthesizes their reports into a unified execution diff.
"""

import concurrent.futures
from typing import Dict
from rich.console import Console
from rich.panel import Panel

from agent.llm.client import LLMClient
from agent.tools.subagent import SubagentManager

console = Console()


class SwarmCoordinator:
    def __init__(self, subagent_manager: SubagentManager, llm_client: LLMClient):
        self.subagents = subagent_manager
        self.client = llm_client

    def dispatch_swarm(self, objective: str) -> str:
        console.print(
            Panel(
                f"🐝 [bold cyan]Initiating Parallel Swarm Mode (3 Workers)[/bold cyan]\nObjective: {objective}",
                border_style="cyan",
            )
        )

        worker_tasks = [
            (
                "researcher",
                f"Explore the codebase structure, call sites, and dependencies relevant to: '{objective}'",
            ),
            (
                "tester",
                f"Design unit test assertions, edge cases, and verification commands for: '{objective}'",
            ),
            (
                "reviewer",
                f"Inspect potential security risks, breaking API changes, or non-negotiable rules for: '{objective}'",
            ),
        ]

        results: Dict[str, str] = {}

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            future_to_role = {
                executor.submit(self.subagents.spawn, role, prompt): role
                for role, prompt in worker_tasks
            }
            for future in concurrent.futures.as_completed(future_to_role):
                role = future_to_role[future]
                try:
                    results[role] = future.result()
                    console.print(
                        f"[bold green]✓ Swarm Worker [{role.upper()}] completed report.[/bold green]"
                    )
                except Exception as e:
                    results[role] = f"Worker failed: {str(e)}"
                    console.print(
                        f"[bold red]✗ Swarm Worker [{role.upper()}] failed: {str(e)}[/bold red]"
                    )

        # Synthesis
        synthesis_prompt = (
            f"Synthesize the following 3 parallel subagent reports into a unified, actionable implementation strategy for '{objective}':\n\n"
            f"--- RESEARCH REPORT ---\n{results.get('researcher', '')}\n\n"
            f"--- TEST SUITE STRATEGY ---\n{results.get('tester', '')}\n\n"
            f"--- SECURITY & REVIEW REPORT ---\n{results.get('reviewer', '')}\n\n"
            "Provide a dense, structured implementation summary with concrete file edits to make."
        )

        synthesis = (
            self.client.chat_completion(
                [
                    {
                        "role": "system",
                        "content": "You are a Chief Software Architect synthesizing parallel agent reports into a final plan.",
                    },
                    {"role": "user", "content": synthesis_prompt},
                ]
            )
            .choices[0]
            .message.content.strip()
        )

        return synthesis
