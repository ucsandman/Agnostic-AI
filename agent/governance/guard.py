"""
agent/governance/guard.py — Governed Autonomy, Trust Tiers & Safety Guardrails
Enforces non-negotiables, sensitive path protection, and dangerous action confirmations.
Supports session-level trust tiers (/trust, /untrust) to streamline developer flow.

All policy is loaded from core/safety/guards.json (single source of truth).
If that file is missing or malformed the guard FAILS CLOSED.
"""

import json
import os
import re
from pathlib import Path
from typing import Tuple, Optional

# Minimal fail-closed fallback. NOT policy — used only when guards.json is unusable.
FALLBACK_SECRET_REGEXES = [
    r"(?i)\.env\b",
    r"(?i)\.secrets\b",
    r"(?i)\bid_(rsa|ed25519|ecdsa|dsa)\b",
    r"(?i)\.(pem|pfx|p12|key)\b",
    r"(?i)\bcredentials\.json\b",
    r"(?i)\.npmrc\b",
    r"(?i)\.dashclaw-local[\\/]secrets",
]


def _find_guards_json() -> Optional[Path]:
    """Walk up from this file looking for core/safety/guards.json."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "core" / "safety" / "guards.json"
        if candidate.is_file():
            return candidate
    return None


def _glob_to_regex(glob: str) -> "re.Pattern":
    """Translate a guards.json blockedFiles glob into a full-path regex."""
    rx = re.escape(glob.replace("\\", "/"))
    rx = rx.replace(r"\*\*/", "(?:.*/)?").replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
    rx = rx.replace(r"\?", ".")
    return re.compile("^" + rx + "$", re.IGNORECASE)


class SafetyGuard:
    def __init__(
        self,
        workspace_root: Optional[str] = None,
        policy_path: Optional[str] = None,
    ):
        self.workspace_root = Path(workspace_root or os.getcwd()).resolve()
        # Trust levels: 'strict', 'trust-reads', 'trust-tests', 'trust-all'
        self.trust_tier = "trust-reads"
        self.policy_path = Path(policy_path) if policy_path else _find_guards_json()
        self.policy_error: Optional[str] = None
        self._load_policy()

    def _load_policy(self) -> None:
        try:
            if not self.policy_path or not self.policy_path.is_file():
                raise FileNotFoundError("core/safety/guards.json not found")
            guards = json.loads(self.policy_path.read_text(encoding="utf-8"))["guards"]
            secret_scan = guards["secretScan"]
            self.secret_regexes = [
                re.compile(p) for p in secret_scan["secretPathRegexes"]
            ]
            self.blocked_globs = [
                _glob_to_regex(g) for g in secret_scan.get("blockedFiles", [])
            ]
            self.hard_stops = [
                re.compile(p) for p in guards["hardStops"]["requireApprovalPatterns"]
            ]
        except Exception as e:  # missing, malformed, or wrong shape -> fail closed
            self.policy_error = f"{type(e).__name__}: {e}"
            self.secret_regexes = [re.compile(p) for p in FALLBACK_SECRET_REGEXES]
            self.blocked_globs = []
            self.hard_stops = []

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

    def _is_secret_path(self, text: str) -> Optional[str]:
        """Return the matching pattern if the text names a protected secret path."""
        for pattern in self.secret_regexes:
            if pattern.search(text):
                return pattern.pattern
        for pattern in self.blocked_globs:
            if pattern.match(text):
                return pattern.pattern
        return None

    def check_path_access(self, file_path: str) -> Tuple[bool, str]:
        """Verify if a file path is safe to read/write."""
        norm_path = os.path.normpath(file_path).replace("\\", "/")

        # 1. Non-negotiable secret paths
        hit = self._is_secret_path(norm_path)
        if hit:
            return (
                False,
                f"Access blocked by Non-Negotiable Safety Rule: '{file_path}' matches protected secret pattern '{hit}'.",
            )

        # 2. Workspace containment — relative paths resolve against the workspace
        target = Path(os.path.join(str(self.workspace_root), file_path)).resolve()
        try:
            target.relative_to(self.workspace_root)
        except ValueError:
            return (
                False,
                f"Access blocked: '{file_path}' resolves outside the workspace root ({self.workspace_root}).",
            )

        return True, "Allowed"

    def check_command_safety(self, command: str) -> Tuple[bool, bool, str]:
        """
        Check if a terminal command is safe, requires approval, or is blocked.
        Returns: (is_blocked, requires_approval, reason)
        """
        # 1. Any mention of a secret path anywhere in the command (NEVER allowed).
        #    Matches the PATH, not the reader verb, so pipes/redirects/interpreters
        #    cannot smuggle it past.
        hit = self._is_secret_path(command.replace("\\", "/"))
        if hit:
            return (
                True,
                False,
                f"Command references secret files matching '{hit}'.",
            )

        # 2. Hard stops
        for pattern in self.hard_stops:
            if pattern.search(command):
                # Hard stops always require explicit confirmation unless trust-all is active
                if self.trust_tier != "trust-all":
                    return False, True, f"Hard Stop: {pattern.pattern}"
                return False, False, "Safe"

        # 3. No usable policy: unknown commands require human approval
        if self.policy_error:
            return (
                False,
                True,
                f"Safety policy unavailable ({self.policy_error}) — failing closed, approval required.",
            )

        return False, False, "Safe"


guard = SafetyGuard()
