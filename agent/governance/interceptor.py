"""
agent/governance/interceptor.py — Automated Syntax & Pre-Commit Linter Interceptor
Runs after every code change to intercept broken syntax, syntax errors, or unclosed brackets before completion.
"""

import ast
import subprocess
from pathlib import Path
from typing import Tuple, Optional


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


interceptor = CodeInterceptor()  # noqa: vulture
