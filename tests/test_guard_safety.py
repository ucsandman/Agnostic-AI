"""
tests/test_guard_safety.py — Regression tests for agent/governance/guard.py

Covers the two hard bypasses (no workspace containment, reader-verb-only secret
matching) and the fail-closed behaviour when core/safety/guards.json is unusable.
"""

import pytest

from agent.governance.guard import SafetyGuard


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    (tmp_path / "outside").mkdir()
    return ws


def test_path_containment(workspace, tmp_path):
    guard = SafetyGuard(workspace_root=str(workspace))

    outside = tmp_path / "outside" / "loot.txt"
    safe, reason = guard.check_path_access(str(outside))
    assert safe is False
    assert "workspace" in reason.lower()

    safe_up, _ = guard.check_path_access("../outside/loot.txt")
    assert safe_up is False

    inside, _ = guard.check_path_access("notes.txt")
    assert inside is True

    inside_abs, _ = guard.check_path_access(str(workspace / "src" / "main.py"))
    assert inside_abs is True


def test_path_secrets_still_blocked(workspace):
    guard = SafetyGuard(workspace_root=str(workspace))

    for path in (".env", ".env.local", ".secrets.env", "keys/id_rsa", "certs/a.pem"):
        safe, reason = guard.check_path_access(path)
        assert safe is False, path
        assert "Non-Negotiable Safety Rule" in reason


@pytest.mark.parametrize(
    "cmd",
    [
        "cat .env | head",
        "sed -n 1p .env",
        "python -c \"open('.env').read()\"",
        "cp .secrets.env x",
        "type .env > out.txt",
        "cat .env",
        # Bypasses found by adversarial review:
        "git show HEAD:.env",
        "git show :.env",
        "git cat-file -p HEAD:.env",
        "cat *.env",
        "cat .envrc",
        "cat .aws/credentials",
    ],
)
def test_secret_commands_blocked_regardless_of_verb(workspace, cmd):
    guard = SafetyGuard(workspace_root=str(workspace))
    blocked, _, reason = guard.check_command_safety(cmd)
    assert blocked is True, f"not blocked: {cmd} ({reason})"


def test_benign_command_allowed(workspace):
    guard = SafetyGuard(workspace_root=str(workspace))
    blocked, requires_approval, _ = guard.check_command_safety("cat README.md")
    assert blocked is False
    assert requires_approval is False


def test_hard_stops_loaded_from_policy(workspace):
    guard = SafetyGuard(workspace_root=str(workspace))
    assert guard.policy_error is None

    _, requires_approval, _ = guard.check_command_safety("git push origin main --force")
    assert requires_approval is True

    guard.set_trust_tier("all")
    _, requires_approval_all, _ = guard.check_command_safety("git push origin main --force")
    assert requires_approval_all is False


def test_malformed_policy_fails_closed(workspace, tmp_path):
    bad = tmp_path / "guards-broken.json"
    bad.write_text("{ not json", encoding="utf-8")

    guard = SafetyGuard(workspace_root=str(workspace), policy_path=str(bad))
    assert guard.policy_error is not None

    safe, _ = guard.check_path_access(".env")
    assert safe is False

    blocked, _, _ = guard.check_command_safety("cat .env")
    assert blocked is True

    _, requires_approval, _ = guard.check_command_safety("ls")
    assert requires_approval is True


def test_missing_policy_fails_closed(workspace, tmp_path):
    guard = SafetyGuard(workspace_root=str(workspace), policy_path=str(tmp_path / "nope.json"))
    assert guard.policy_error is not None

    blocked, _, _ = guard.check_command_safety("sed -n 1p .secrets.env")
    assert blocked is True
