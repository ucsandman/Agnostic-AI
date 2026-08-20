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
    def _local_guard_fallback(tool_name: str, args: dict) -> Tuple[bool, Optional[str]]:
        """Fail-closed fallback when the Node security hooks cannot run.

        Uses the in-process SafetyGuard (which loads core/safety/guards.json) to
        block secret access and hard-stop commands. A missing node binary or a
        hook timeout must never silently allow a governed tool call.
        """
        try:
            from agent.governance.guard import SafetyGuard

            guard = SafetyGuard()
            command = args.get("command")
            if command:
                blocked, req_approval, reason = guard.check_command_safety(command)
                if blocked or req_approval:
                    return False, f"[Local guard fallback] {reason}"
            for key in ("path", "file_path", "target_file", "file"):
                target = args.get(key)
                if target:
                    ok, reason = guard.check_path_access(str(target))
                    if not ok:
                        return False, f"[Local guard fallback] {reason}"
        except Exception:
            # If even the local guard cannot be evaluated, deny governed tools
            # that carry a command; allow pure reads to avoid a hard lock-up.
            if args.get("command"):
                return False, "[Local guard fallback] unable to verify command safety"
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

        # 1./2. Pre-tool Secret Guard + DashClaw governance hooks.
        # Both are spawned first and collected after, so a tool call pays one
        # node start-up latency instead of two. Semantics are unchanged: each
        # hook still blocks on a non-zero exit and still fails CLOSED.
        if event == "pre_tool":
            hook_names = [
                (hooks_dir / "secret-guard.cjs", "Blocked by secret-guard hook"),
                (hooks_dir / "dashclaw-guard.cjs", "Blocked by DashClaw hook"),
            ]
            encoded = json.dumps(payload)
            running = []
            for hook_path, default_err in hook_names:
                if not hook_path.exists():
                    continue
                try:
                    proc = subprocess.Popen(
                        ["node", str(hook_path)],
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                except Exception:
                    proc = None
                running.append((proc, default_err))

            try:
                for proc, default_err in running:
                    try:
                        if proc is None:
                            raise RuntimeError("hook process could not be started")
                        out, err_out = proc.communicate(input=encoded, timeout=5)
                        if proc.returncode != 0:
                            err = err_out or out or default_err
                            return False, err.strip()
                    except Exception:
                        # Node hook unavailable/timeout: fail CLOSED via the
                        # in-process guard rather than silently allowing the call.
                        ok, err = CodeInterceptor._local_guard_fallback(tool_name, args)
                        if not ok:
                            return False, err
            finally:
                # A denial returns early; never leave a spawned hook waiting on stdin.
                for proc, _default_err in running:
                    if proc is not None and proc.poll() is None:
                        try:
                            proc.kill()
                        except Exception:
                            pass

        # 3. Post-tool correction tracker hook
        elif event == "post_tool":
            tracker = hooks_dir / "correction-tracker.cjs"
            if tracker.exists():
                try:
                    # Fire-and-forget: the tracker's result is never read, so the
                    # tool call must not pay for its start-up or its runtime.
                    proc = subprocess.Popen(
                        ["node", str(tracker)],
                        stdin=subprocess.PIPE,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        text=True,
                    )
                    proc.stdin.write(json.dumps(payload))
                    proc.stdin.close()
                except Exception:
                    pass

        return True, None


interceptor = CodeInterceptor()
