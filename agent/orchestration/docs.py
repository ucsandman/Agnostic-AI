"""Generate the canonical orchestration role table in docs/orchestration.md."""

from __future__ import annotations

import argparse
from pathlib import Path

from agent.orchestration.config import OrchestrationConfig

START = "<!-- BEGIN GENERATED ROLE TABLE -->"
END = "<!-- END GENERATED ROLE TABLE -->"


def render_role_table() -> str:
    config = OrchestrationConfig.from_dict({})
    lines = [
        START,
        "| Role | Preferred model target | Delegates to | Advisors | Permissions |",
        "|---|---|---|---|---|",
    ]
    for name, role in config.roles.items():
        target = role.models[0]
        model = target.model or target.preset or ("parent" if target.inherit else "configured")
        children = ", ".join(role.allowed_children) or "none"
        advisors = ", ".join(role.allowed_advisors) or "none"
        permissions = ", ".join(role.permissions) or "none"
        lines.append(f"| `{name}` | `{model}` | {children} | {advisors} | {permissions} |")
    lines.append(END)
    return "\n".join(lines)


def update(path: Path, check: bool = False) -> int:
    text = path.read_text(encoding="utf-8")
    before, marker, tail = text.partition(START)
    if not marker or END not in tail:
        raise RuntimeError(f"generated role table markers are missing from {path}")
    _, _, after = tail.partition(END)
    expected = before + render_role_table() + after
    if check:
        if text != expected:
            print(f"[orchestration-docs] stale: {path}")
            return 1
        print(f"[orchestration-docs] current: {path}")
        return 0
    path.write_text(expected, encoding="utf-8", newline="\n")
    print(f"[orchestration-docs] wrote: {path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = Path(__file__).resolve().parents[2] / "docs" / "orchestration.md"
    return update(path, check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
