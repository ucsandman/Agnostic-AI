"""
agent/governance/watchdog.py — Autonomous Sandbox Watchdog & Transactional Rollbacks
Wraps every agent turn in an atomic transaction; provides clean git restore if cancelled or failed.
"""

import subprocess
from pathlib import Path
from typing import Optional


class SandboxWatchdog:
    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root

    def get_clean_snapshot_hash(self) -> Optional[str]:
        try:
            res = subprocess.run(
                "git rev-parse HEAD",
                cwd=self.workspace_root,
                shell=True,
                capture_output=True,
                text=True,
            )
            return res.stdout.strip() if res.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):  # no git on PATH; caller sees None
            return None

    def rollback_to_clean(self) -> bool:
        """Restores the workspace to HEAD. Returns False if either git step failed —
        a rollback that silently did nothing would leave the agent's edits in place
        while the caller believes the turn was undone."""
        try:
            restore = subprocess.run(
                "git restore .",
                cwd=self.workspace_root,
                shell=True,
                capture_output=True,
                text=True,
            )
            clean = subprocess.run(
                "git clean -fd",
                cwd=self.workspace_root,
                shell=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return restore.returncode == 0 and clean.returncode == 0


watchdog = SandboxWatchdog(Path("."))  # noqa: vulture
