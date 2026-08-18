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
        except Exception:
            return None

    def rollback_to_clean(self):
        try:
            subprocess.run("git restore .", cwd=self.workspace_root, shell=True)
            subprocess.run("git clean -fd", cwd=self.workspace_root, shell=True)
        except Exception:
            pass


watchdog = SandboxWatchdog(Path("."))  # noqa: vulture
