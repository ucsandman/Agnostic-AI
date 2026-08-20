"""
agent/workflows/pr_pilot.py — PR & Branch Auto-Pilot (/pr, /branch)
Automates git feature branch creation, clean commit writing, and PR submission.
"""

import subprocess
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.markup import escape

from agent.llm.client import LLMClient

console = Console()


class PRAutoPilot:
    def __init__(self, workspace_root: Path, llm_client: LLMClient):
        self.workspace_root = workspace_root
        self.client = llm_client

    def create_feature_branch(self, branch_name: str) -> bool:
        clean_name = branch_name.lower().replace(" ", "-").replace("/", "-")
        try:
            res = subprocess.run(
                f"git checkout -b feature/{clean_name}",
                cwd=self.workspace_root,
                shell=True,
                capture_output=True,
                text=True,
            )
            if res.returncode == 0:
                console.print(
                    f"[bold green]✓ Created and switched to branch 'feature/{clean_name}'[/bold green]"
                )
                return True
            else:
                console.print(
                    f"[red]Error creating branch: {escape(res.stderr.strip())}[/red]"
                )
                return False
        except Exception as e:
            console.print(f"[red]Git branch error: {escape(str(e))}[/red]")
            return False

    def generate_pr_summary(self) -> str:
        try:
            diff = subprocess.run(
                "git diff main...",
                cwd=self.workspace_root,
                shell=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            if not diff:
                diff = subprocess.run(
                    "git diff HEAD~1",
                    cwd=self.workspace_root,
                    shell=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()

            prompt = (
                f"Generate a professional GitHub Pull Request description based on this diff preview:\n```\n{diff[:2500]}\n```\n"
                "Include: ## Summary, ## Changes Made, and ## Verification / Tests Passed."
            )
            summary = (
                self.client.chat_completion(
                    [
                        {
                            "role": "system",
                            "content": "You are a lead engineer writing clear PR release notes in Markdown.",
                        },
                        {"role": "user", "content": prompt},
                    ]
                )
                .choices[0]
                .message.content.strip()
            )

            console.print(
                Panel(
                    summary,
                    title="🚀 Generated Pull Request Description",
                    border_style="cyan",
                )
            )
            return summary
        except Exception as e:
            return f"PR Summary error: {str(e)}"
