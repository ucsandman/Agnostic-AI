"""
agent/workflows/swarm.py — Parallel Multi-Subagent Swarm Engine (/swarm)
Dispatches parallel worker subagents (Researcher, Implementer, Security Reviewer) concurrently
with optional Git Worktree branch isolation, and synthesizes their reports into a unified execution diff.
"""

import subprocess
import uuid
import concurrent.futures
from pathlib import Path
from typing import Dict, Optional
from rich.console import Console
from rich.panel import Panel

from agent.llm.client import LLMClient
from agent.tools.subagent import SubagentManager

console = Console()


class SwarmCoordinator:
    def __init__(self, subagent_manager: SubagentManager, llm_client: LLMClient):
        self.subagents = subagent_manager
        self.client = llm_client
        self.workspace_root = subagent_manager.workspace_root

    def _create_isolated_worktree(self, role: str) -> Optional[Path]:
        """Creates an isolated git worktree branch for subagent if git repo is clean/available."""
        try:
            # Unique per swarm: two concurrent swarms sharing wt_<role> would
            # delete each other's checkout mid-run.
            wt_dir = (
                self.workspace_root
                / ".agnostic"
                / "worktrees"
                / f"wt_{role}_{uuid.uuid4().hex[:8]}"
            )
            wt_dir.parent.mkdir(parents=True, exist_ok=True)

            res = subprocess.run(
                f'git worktree add --detach "{wt_dir}" HEAD',
                cwd=self.workspace_root,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if res.returncode == 0 and wt_dir.exists():
                return wt_dir
        except (OSError, subprocess.SubprocessError):  # no worktree support; caller runs in-place
            pass
        return None

    def _cleanup_worktree(self, wt_dir: Path):
        try:
            subprocess.run(
                f'git worktree remove --force "{wt_dir}"',
                cwd=self.workspace_root,
                shell=True,
                capture_output=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):  # worktree already removed / git hung
            pass

    def dispatch_swarm(self, objective: str, use_worktrees: bool = False) -> str:
        console.print(
            Panel(
                f"🐝 [bold cyan]Initiating Parallel Swarm Mode (3 Workers)[/bold cyan]\nObjective: {objective}"
                + ("\n[dim](Git Worktree Branch Isolation Active)[/dim]" if use_worktrees else ""),
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

        # The production manager owns concurrency, graph limits, cancellation, and
        # workspace leases. The fallback retains compatibility with lightweight
        # third-party/test managers that implement only spawn().
        if hasattr(self.subagents, "spawn_parallel"):
            reports = self.subagents.spawn_parallel(
                [
                    {
                        "role": role,
                        "prompt": prompt,
                        "workspace_mode": "branch" if use_worktrees else "inherit",
                    }
                    for role, prompt in worker_tasks
                ]
            )
            results.update(dict(zip((role for role, _ in worker_tasks), reports)))
            for role, _ in worker_tasks:
                console.print(
                    f"[bold green]✓ Swarm Worker [{role.upper()}] completed report.[/bold green]"
                )
        else:

            def _run_worker(role: str, prompt: str) -> str:
                wt = self._create_isolated_worktree(role) if use_worktrees else None
                try:
                    if wt:
                        manager = SubagentManager(
                            client=self.client,
                            workspace_root=str(wt),
                            confirm_callback=self.subagents.confirm_callback,
                        )
                        return manager.spawn(role, prompt)
                    return self.subagents.spawn(role, prompt)
                finally:
                    if wt:
                        self._cleanup_worktree(wt)

            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                future_to_role = {
                    executor.submit(_run_worker, role, prompt): role
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

        # Synthesis. A silent worker is labelled, never pasted in as "None".
        def report(role: str) -> str:
            return results.get(role) or "(no report — this worker returned nothing)"

        synthesis_prompt = (
            f"Synthesize the following 3 parallel subagent reports into a unified, actionable implementation strategy for '{objective}':\n\n"
            f"--- RESEARCH REPORT ---\n{report('researcher')}\n\n"
            f"--- TEST SUITE STRATEGY ---\n{report('tester')}\n\n"
            f"--- SECURITY & REVIEW REPORT ---\n{report('reviewer')}\n\n"
            "Provide a dense, structured implementation summary with concrete file edits to make."
        )

        message = (
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
            .message
        )

        return (message.content or "").strip()
