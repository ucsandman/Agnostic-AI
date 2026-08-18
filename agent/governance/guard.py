"""
agent/governance/guard.py — Governed Autonomy, Trust Tiers & Safety Guardrails
Enforces non-negotiables, sensitive path protection, and dangerous action confirmations.
Supports session-level trust tiers (/trust, /untrust) to streamline developer flow.
"""

import os
import re
from pathlib import Path
from typing import Tuple, Optional

# Non-negotiable sensitive patterns and paths (CANNOT be bypassed by any trust tier)
BLOCKED_PATTERNS = [
    r"\.env($|\.)",
    r"\.secrets\.env",
    r"id_rsa",
    r"id_ed25519",
    r"\.pem$",
    r"\.key$",
    r"credentials\.json",
    r"\.dashclaw-local[\\/]secrets",
]

# Actions requiring human confirmation (hard stops)
HARD_STOP_PATTERNS = [
    (r"\bgit\s+push\b", "Git push / publishing remote changes"),
    (r"\bgit\s+reset\s+--hard\b", "Hard reset of git working tree"),
    (
        r"\brm\s+-rf\b|\brmdir\s+/s\b|\bRemove-Item\s+-Recurse\b",
        "Recursive deletion of files/directories",
    ),
    (
        r"\bdrop\s+database\b|\bdrop\s+table\b|\btruncate\b",
        "Destructive database operation",
    ),
    (r"\bnpm\s+audit\s+fix\s+--force\b", "Forced dependency upgrade"),
    (r"\bdeploy\b|\bvercel\s+--prod\b|\brailway\s+up\b", "Production deployment"),
]


class SafetyGuard:
    def __init__(self, workspace_root: Optional[str] = None):
        self.workspace_root = Path(workspace_root or os.getcwd()).resolve()
        # Trust levels: 'strict', 'trust-reads', 'trust-tests', 'trust-all'
        self.trust_tier = "trust-reads"

    def set_trust_tier(self, tier: str) -> str:
        clean = tier.lower().strip()
        if clean in ("strict", "default"):
            self.trust_tier = "strict"
        elif clean in ("reads", "trust-reads", "read"):
            self.trust_tier = "trust-reads"
        elif clean in ("tests", "trust-tests", "test"):
            self.trust_tier = "trust-tests"
        elif clean in ("all", "trust-all", "full"):
            self.trust_tier = "trust-all"
        else:
            return f"Unknown trust tier '{tier}'. Options: strict, reads, tests, all."
        return f"Active Trust Tier set to: '{self.trust_tier}'"

    def get_trust_tier(self) -> str:
        return self.trust_tier

    def check_path_access(self, file_path: str) -> Tuple[bool, str]:
        """Verify if a file path is safe to read/write."""
        norm_path = os.path.normpath(file_path)

        # Check against blocked sensitive file patterns
        for pattern in BLOCKED_PATTERNS:
            if re.search(pattern, norm_path, re.IGNORECASE):
                return (
                    False,
                    f"Access blocked by Non-Negotiable Safety Rule: '{file_path}' matches protected secret pattern '{pattern}'.",
                )

        return True, "Allowed"

    def check_command_safety(self, command: str) -> Tuple[bool, bool, str]:
        """
        Check if a terminal command is safe, requires approval, or is blocked.
        Returns: (is_blocked, requires_approval, reason)
        """
        # 1. Check if command attempts to cat/grep secrets (NEVER allowed)
        for pattern in BLOCKED_PATTERNS:
            if re.search(
                r"(type|cat|Get-Content|grep|findstr|head|tail|more|less)\s+.*"
                + pattern,
                command,
                re.IGNORECASE,
            ):
                return (
                    True,
                    False,
                    f"Command attempts to inspect secret files matching '{pattern}'.",
                )

        # 2. Check for hard stops
        for pattern, desc in HARD_STOP_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                # Hard stops always require explicit confirmation unless trust-all is active
                if self.trust_tier != "trust-all":
                    return False, True, f"Hard Stop: {desc}"

        return False, False, "Safe"


guard = SafetyGuard()
