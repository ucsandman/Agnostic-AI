"""
agent/workflows/scheduler.py — Temporal Autonomy & Routine Scheduler (/schedule, /loop)
Runs background timers, cron loops, and recurring checks (e.g. continuous test watch, PR polls).
"""

import threading
import time
import re
from typing import Callable, Optional, Dict
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
                console.print(
                    f"[red]Error in scheduled task '{self.task_id}': {str(e)}[/red]"
                )

            if self.max_runs and self.run_count >= self.max_runs:
                console.print(
                    f"[dim]Scheduled task '{self.task_id}' reached max runs ({self.max_runs}). Stopping.[/dim]"
                )
                break


class TaskScheduler:
    def __init__(self):
        self.tasks: Dict[str, ScheduledTask] = {}

    def parse_and_schedule(
        self, command_str: str, agent_callback: Callable[[str], None]
    ) -> str:
        """
        Parses commands like:
          /schedule "every 30s run /test"
          /schedule "every 5m check git status"
          /loop 3 "run pytest"
        """
        cmd = command_str.strip()

        # Parse /loop N "prompt"
        loop_match = re.match(
            r"^/loop\s+(\d+)\s+(?:\"([^\"]+)\"|(.+))$", cmd, re.IGNORECASE
        )
        if loop_match:
            count = int(loop_match.group(1))
            prompt = loop_match.group(2) or loop_match.group(3)
            task_id = f"loop-{int(time.time())}"
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

            task_id = f"sched-{int(time.time())}"
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

    def cancel_all(self):
        for t in self.tasks.values():
            t.stop()
        self.tasks.clear()


scheduler = TaskScheduler()
