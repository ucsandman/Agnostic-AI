"""
agent/governance/interceptor.py — Automated Syntax & Pre-Commit Linter Interceptor
Runs after every code change to intercept broken syntax, syntax errors, or unclosed brackets before completion.
"""

import ast
import subprocess
from pathlib import Path
from typing import Tuple, Optional


import json


class CodeInterceptor:
    @staticmethod
    def validate_syntax(file_path: Path, content: str) -> Tuple[bool, Optional[str]]:
        """Checks for Python AST syntax validity before saving to disk."""
        if file_path.suffix == ".py":
            try:
                ast.parse(content, filename=str(file_path))
                return True, None
            except SyntaxError as e:
                return False, f"Python SyntaxError at line {e.lineno}: {e.msg}"
        return True, None

    @staticmethod
    def run_quick_lint(
        file_path: Path, workspace_root: Path
    ) -> Tuple[bool, Optional[str]]:
        """Optionally runs quick ruff or eslint check if tools exist."""
        if file_path.suffix == ".py":
            try:
                res = subprocess.run(
                    f"ruff check {file_path}",
                    cwd=workspace_root,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if res.returncode != 0 and res.stdout:
                    return False, res.stdout.strip()
            except Exception:
                pass
        return True, None

    @staticmethod
    def execute_lifecycle_hook(
        event: str, tool_name: str, args: dict, result: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """Executes unified Agnostic and DashClaw lifecycle hooks."""
        hooks_candidates = [
            Path("engine/hooks"),
            Path(__file__).resolve().parent.parent.parent / "engine" / "hooks",
        ]
        hooks_dir = next((d for d in hooks_candidates if d.exists()), None)
        if not hooks_dir:
            return True, None

        payload = {
            "client": "agnostic-cli",
            "event": event,
            "tool_name": tool_name,
            "tool_input": args,
            "args": args,
            "result": (result or "")[:1500],
        }

        # 1. Pre-tool Secret Guard hook
        if event == "pre_tool":
            secret_hook = hooks_dir / "secret-guard.cjs"
            if secret_hook.exists():
                try:
                    proc = subprocess.run(
                        ["node", str(secret_hook)],
                        input=json.dumps(payload),
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if proc.returncode != 0:
                        err = (
                            proc.stderr or proc.stdout or "Blocked by secret-guard hook"
                        )
                        return False, err.strip()
                except Exception:
                    pass

            # 2. Pre-tool DashClaw governance hook
            dc_hook = hooks_dir / "dashclaw-guard.cjs"
            if dc_hook.exists():
                try:
                    proc = subprocess.run(
                        ["node", str(dc_hook)],
                        input=json.dumps(payload),
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if proc.returncode != 0:
                        err = proc.stderr or proc.stdout or "Blocked by DashClaw hook"
                        return False, err.strip()
                except Exception:
                    pass

        # 3. Post-tool correction tracker hook
        elif event == "post_tool":
            tracker = hooks_dir / "correction-tracker.cjs"
            if tracker.exists():
                try:
                    subprocess.Popen(
                        ["node", str(tracker)],
                        stdin=subprocess.PIPE,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        text=True,
                    ).communicate(input=json.dumps(payload), timeout=2)
                except Exception:
                    pass

        return True, None


interceptor = CodeInterceptor()
