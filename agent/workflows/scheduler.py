"""
agent/workflows/scheduler.py — Temporal Autonomy & Routine Scheduler (/schedule, /loop)
Runs background timers, cron loops, and recurring checks (e.g. continuous test watch, PR polls).
"""

import threading
import time
import re
import uuid
from typing import Any, Callable, Dict, List, Optional
from rich.console import Console

console = Console()


class ScheduledTask:
    def __init__(
        self,
        task_id: str,
        prompt: str,
        interval_seconds: int,
        max_runs: Optional[int],
        callback: Callable[[str], None],
    ):
        self.task_id = task_id
        self.prompt = prompt
        self.interval_seconds = interval_seconds
        self.max_runs = max_runs
        self.callback = callback
        self.run_count = 0
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None

    def start(self):
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def _run_loop(self):
        while not self.stop_event.is_set():
            time.sleep(self.interval_seconds)
            if self.stop_event.is_set():
                break

            self.run_count += 1
            console.print(
                f"\n[bold magenta]⏰ [Scheduled Routine '{self.task_id}'] Triggered (Run {self.run_count})[/bold magenta]"
            )
            try:
                self.callback(self.prompt)
            except Exception as e:
                console.print(f"[red]Error in scheduled task '{self.task_id}': {str(e)}[/red]")

            if self.max_runs and self.run_count >= self.max_runs:
                console.print(
                    f"[dim]Scheduled task '{self.task_id}' reached max runs ({self.max_runs}). Stopping.[/dim]"
                )
                break


class TaskScheduler:
    def __init__(self):
        self.tasks: Dict[str, ScheduledTask] = {}

    def parse_and_schedule(self, command_str: str, agent_callback: Callable[[str], None]) -> str:
        """
        Parses commands like:
          /schedule "every 30s run /test"
          /schedule "every 5m check git status"
          /schedule list
          /schedule stop <task-id> | /schedule stop all
          /loop 3 "run pytest"
        """
        cmd = command_str.strip()

        # Manage what is already running. Both UIs hand the whole line to this
        # method, so wiring these here wires them in the TUI and the legacy CLI.
        parts = cmd.split()
        if len(parts) >= 2 and parts[0].lower() == "/schedule":
            if parts[1].lower() == "list":
                rows = self.list_tasks()
                if not rows:
                    return "No scheduled routines."
                return "\n".join(
                    "{id}  every {every}  {state}  {prompt}".format(
                        state="running" if r["running"] else "stopped", **r
                    )
                    for r in rows
                )
            if parts[1].lower() == "stop":
                target = parts[2] if len(parts) > 2 else ""
                if target == "all":
                    count = len(self.tasks)
                    self.cancel_all()
                    return f"Cancelled {count} scheduled routine(s)."
                if self.cancel_task(target):
                    return f"Cancelled scheduled routine '{target}'."
                return f"No scheduled routine '{target}'. Try /schedule list."

        # Parse /loop N "prompt"
        loop_match = re.match(r"^/loop\s+(\d+)\s+(?:\"([^\"]+)\"|(.+))$", cmd, re.IGNORECASE)
        if loop_match:
            count = int(loop_match.group(1))
            prompt = loop_match.group(2) or loop_match.group(3)
            # Hex suffix: two routines started in the same second must not
            # share an id, or the second one evicts the first from self.tasks.
            task_id = f"loop-{int(time.time())}-{uuid.uuid4().hex[:4]}"
            task = ScheduledTask(
                task_id,
                prompt,
                interval_seconds=3,
                max_runs=count,
                callback=agent_callback,
            )
            self.tasks[task_id] = task
            task.start()
            return f"Started loop routine '{task_id}': running '{prompt}' {count} times (every 3s)."

        # Parse /schedule every Xs/m/h "prompt"
        sched_match = re.match(
            r"^/schedule\s+(?:every\s+)?(\d+)\s*(s|m|h|sec|min|hour)?\s+(?:run\s+)?(?:\"([^\"]+)\"|(.+))$",
            cmd,
            re.IGNORECASE,
        )
        if sched_match:
            val = int(sched_match.group(1))
            unit = (sched_match.group(2) or "s").lower()
            prompt = sched_match.group(3) or sched_match.group(4)

            seconds = val
            if unit.startswith("m"):
                seconds = val * 60
            elif unit.startswith("h"):
                seconds = val * 3600

            task_id = f"sched-{int(time.time())}-{uuid.uuid4().hex[:4]}"
            task = ScheduledTask(
                task_id,
                prompt,
                interval_seconds=seconds,
                max_runs=None,
                callback=agent_callback,
            )
            self.tasks[task_id] = task
            task.start()
            return f"Scheduled task '{task_id}': running '{prompt}' every {seconds}s in background."

        return 'Usage format: /schedule every 30s "prompt" OR /loop 5 "prompt"'

    def list_tasks(self) -> List[Dict[str, Any]]:
        """One row per known routine: id, interval, prompt preview, running state."""
        return [
            {
                "id": t.task_id,
                "every": "{}s".format(t.interval_seconds)
                + (" x{}".format(t.max_runs) if t.max_runs else ""),
                "prompt": t.prompt[:60],
                "running": t.thread is not None and t.thread.is_alive(),
            }
            for t in self.tasks.values()
        ]

    def cancel_task(self, task_id: str) -> bool:
        """Stop one routine. False when no routine has that id."""
        task = self.tasks.pop(task_id, None)
        if task is None:
            return False
        task.stop()
        return True

    def cancel_all(self):
        for t in self.tasks.values():
            t.stop()
        self.tasks.clear()


scheduler = TaskScheduler()
