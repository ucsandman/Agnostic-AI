"""
agent/workflows/tester.py — Autonomous Test-and-Fix Loop (/test)
Runs test suites (pytest, npm test, cargo, python unittest), parses error traces,
and loops autonomous repairs until zero failures are observed.
"""

import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, Callable
from rich.console import Console
from rich.panel import Panel

console = Console()


class AutoTestRunner:
    def __init__(self, workspace_root: Path, agent_loop_func: Callable[[str], str]):
        self.workspace_root = workspace_root
        self.agent_loop_func = agent_loop_func

    def detect_test_command(self) -> Optional[str]:
        """Auto-detects the project test suite command."""
        # Node / JS project
        pkg_json = self.workspace_root / "package.json"
        if pkg_json.exists():
            return "npm test"

        # Python pytest
        if (self.workspace_root / "pytest.ini").exists() or (
            self.workspace_root / "tests"
        ).exists():
            return "pytest"

        # Rust cargo
        if (self.workspace_root / "Cargo.toml").exists():
            return "cargo test"

        return "npm test"

    def run_suite(self, custom_command: Optional[str] = None) -> Dict[str, Any]:
        cmd = custom_command or self.detect_test_command() or "npm test"
        try:
            res = subprocess.run(
                cmd,
                cwd=self.workspace_root,
                shell=True,
                capture_output=True,
                text=True,
                timeout=180,
            )
            output = (res.stdout or "") + (res.stderr or "")
            return {
                "command": cmd,
                "passed": (res.returncode == 0),
                "returncode": res.returncode,
                "output": output,
            }
        except subprocess.TimeoutExpired:
            return {
                "command": cmd,
                "passed": False,
                "returncode": -1,
                "output": "Test execution timed out.",
            }
        except Exception as e:
            return {"command": cmd, "passed": False, "returncode": -1, "output": str(e)}

    def auto_repair_loop(
        self, custom_command: Optional[str] = None, max_attempts: int = 4
    ):
        """Runs tests and loops repairs until tests pass or max attempts are reached."""
        for attempt in range(1, max_attempts + 1):
            console.print(
                f"\n[bold cyan]🧪 [Attempt {attempt}/{max_attempts}] Running test suite...[/bold cyan]"
            )
            result = self.run_suite(custom_command)

            if result["passed"]:
                console.print(
                    Panel(
                        f"✅ All tests passed cleanly on attempt {attempt}!\n\nCommand: {result['command']}",
                        border_style="green",
                    )
                )
                return True

            console.print(
                f"[bold red]❌ Test suite failed (Exit code {result['returncode']})[/bold red]"
            )
            clipped_output = result["output"][-2500:]  # Last 2500 chars of stack trace
            console.print(
                Panel(clipped_output, title="Test Failure Trace", border_style="red")
            )

            if attempt == max_attempts:
                console.print(
                    "[bold yellow]⚠️ Reached maximum auto-repair attempts. Stopping.[/bold yellow]"
                )
                return False

            fix_prompt = (
                f"The test suite failed with the following output:\n```\n{clipped_output}\n```\n"
                "Please inspect the failing files, identify the exact assertion/syntax bug, and use surgical edits to fix it."
            )
            console.print("[cyan]🤖 Dispatching autonomous repair agent turn...[/cyan]")
            self.agent_loop_func(fix_prompt)

        return False
