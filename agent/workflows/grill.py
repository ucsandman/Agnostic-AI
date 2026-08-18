"""
agent/workflows/grill.py — Interactive Design & Requirement Interview Mode (/grill-me)
Before coding a major architectural task, interrogates the operator with sharp, multiple-choice questions
to eliminate assumptions, clarify trade-offs, and align requirements.
"""

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from agent.llm.client import LLMClient

console = Console()


class DesignInterviewer:
    def __init__(self, llm_client: LLMClient):
        self.client = llm_client

    def interview(self, task_description: str) -> str:
        console.print(
            Panel(
                f"🎯 [bold cyan]Grill-Me Alignment Interview:[/bold cyan] {task_description}",
                border_style="cyan",
            )
        )

        prompt = (
            f"The user wants to implement this feature/task:\n'{task_description}'\n\n"
            "As an elite lead software architect, formulate exactly 3 sharp, critical design or architectural trade-off questions "
            "that must be decided before writing code. For each question, provide 2 to 3 concise multiple choice options (A, B, C).\n"
            "Format cleanly as JSON:\n"
            '{"questions": [{"id": 1, "question": "...", "options": ["A) ...", "B) ..."]}]}'
        )

        try:
            res = (
                self.client.chat_completion(
                    [
                        {
                            "role": "system",
                            "content": "You are a software architect. Output only valid JSON with questions and options.",
                        },
                        {"role": "user", "content": prompt},
                    ]
                )
                .choices[0]
                .message.content.strip()
            )

            # Parse JSON
            import json
            import re

            json_match = re.search(r"\{.*\}", res, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
            else:
                data = {"questions": []}

            answers = []
            for q in data.get("questions", []):
                console.print(
                    f"\n[bold yellow]Q{q.get('id', '?')}: {q.get('question')}[/bold yellow]"
                )
                for opt in q.get("options", []):
                    console.print(f"  {opt}")
                ans = Prompt.ask("[bold cyan]Your Choice / Answer[/bold cyan]").strip()
                answers.append(f"Q: {q.get('question')}\nAnswer: {ans}")

            summary = "\n\n".join(answers)
            console.print(
                Panel(
                    summary,
                    title="✅ Aligned Requirements Summary",
                    border_style="green",
                )
            )
            return summary

        except Exception as e:
            console.print(f"[red]Grill-Me error: {str(e)}[/red]")
            return f"Aligned with task: {task_description}"
