"""
agent/tools/diff_viewer.py — Rich Colorized Diff Viewer for File Edits
Renders visual before/after unified diff cards in the terminal for file edits and writes.
"""

import difflib
import subprocess
import threading
import time
import uuid
from typing import Any, Dict, List, Optional
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()  # noqa: vulture


class DiffViewer:
    @staticmethod
    def render_diff(
        file_name: str, old_content: str, new_content: str, max_lines: int = 25
    ) -> Panel:
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)

        diff = list(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=f"a/{file_name}",
                tofile=f"b/{file_name}",
                n=2,
            )
        )

        if not diff:
            return Panel(
                f"[dim]No changes detected in {file_name}[/dim]",
                title=f"Diff: {file_name}",
                border_style="dim",
            )

        diff_text = Text()
        for idx, line in enumerate(diff[:max_lines]):
            if line.startswith("+++") or line.startswith("---"):
                diff_text.append(line, style="bold cyan")
            elif line.startswith("@@"):
                diff_text.append(line, style="bold magenta")
            elif line.startswith("+"):
                diff_text.append(line, style="green")
            elif line.startswith("-"):
                diff_text.append(line, style="red")
            else:
                diff_text.append(line, style="dim white")

        if len(diff) > max_lines:
            diff_text.append(
                f"\n... ({len(diff) - max_lines} more diff lines truncated)",
                style="dim italic",
            )

        return Panel(
            diff_text, title=f"📝 Diff Preview: {file_name}", border_style="cyan"
        )


class BackgroundTask:
    def __init__(
        self, task_id: str, command: Optional[str] = None, prompt: Optional[str] = None
    ):
        self.task_id = task_id
        self.command = command
        self.prompt = prompt
        self.created_at = time.strftime("%Y-%m-%d %H:%M:%S")
        self.state = "running"
        self.output_buffer: List[str] = []
        self.process: Optional[subprocess.Popen] = None
        self.timer_thread: Optional[threading.Thread] = None  # noqa: vulture

    def to_dict(self) -> Dict[str, Any]:
        return {
            "taskId": self.task_id,
            "command": self.command,
            "prompt": self.prompt,
            "state": self.state,
            "createdAt": self.created_at,
            "outputLines": len(self.output_buffer),
        }


class TaskManager:
    def __init__(self):
        self._tasks: Dict[str, BackgroundTask] = {}

    def list_tasks(self) -> List[Dict[str, Any]]:
        return [t.to_dict() for t in self._tasks.values()]

    def get_status(self, task_id: str) -> str:
        if task_id not in self._tasks:
            return f"Error: Task '{task_id}' not found."
        t = self._tasks[task_id]
        recent_output = (
            "\n".join(t.output_buffer[-20:])
            if t.output_buffer
            else "[No output recorded]"
        )
        return (
            f"### [Task Status: {task_id}]\n"
            f"• **State:** {t.state}\n"
            f"• **Created:** {t.created_at}\n"
            f"• **Command/Prompt:** {t.command or t.prompt}\n"
            f"• **Recent Output:**\n```\n{recent_output}\n```"
        )

    def send_input(self, task_id: str, inp: str) -> str:
        if task_id not in self._tasks:
            return f"Error: Task '{task_id}' not found."
        t = self._tasks[task_id]
        if t.process and t.process.stdin:
            try:
                t.process.stdin.write(inp + "\n")
                t.process.stdin.flush()
                return f"Sent input to task '{task_id}'."
            except Exception as e:
                return f"Failed to send input: {str(e)}"
        return f"Task '{task_id}' is not an active interactive process."

    def kill_task(self, task_id: str) -> str:
        if task_id not in self._tasks:
            return f"Error: Task '{task_id}' not found."
        t = self._tasks[task_id]
        t.state = "killed"
        if t.process:
            try:
                t.process.terminate()
            except Exception:
                pass
        return f"Task '{task_id}' terminated."

    def schedule(
        self,
        prompt: str,
        duration_seconds: Optional[int] = None,
        cron_expression: Optional[str] = None,
    ) -> str:
        task_id = f"task_{str(uuid.uuid4())[:8]}"
        task = BackgroundTask(task_id=task_id, prompt=prompt)
        self._tasks[task_id] = task

        if duration_seconds:

            def _timer():
                time.sleep(duration_seconds)
                if task.state != "killed":
                    task.state = "completed"
                    task.output_buffer.append(f"🔔 [Timer Notification]: {prompt}")

            th = threading.Thread(target=_timer, daemon=True)
            task.timer_thread = th  # noqa: vulture
            th.start()
            return f"Scheduled one-shot timer (ID: {task_id}) for {duration_seconds}s with prompt: '{prompt}'"

        elif cron_expression:
            task.output_buffer.append(f"Scheduled recurring cron: {cron_expression}")
            return f"Scheduled cron schedule (ID: {task_id}) '{cron_expression}' with prompt: '{prompt}'"

        return f"Scheduled background task (ID: {task_id})"


task_manager = TaskManager()
