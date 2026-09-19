"""Extract every installed Claude Code skill into a roster the way the agent sees it.

One record per skill: the name, the description the index shows, and the opening of
SKILL.md for the second-pass read. Mirrors the shape of TypeSafe's hermes_roster.json
so the skill_suggestion cookbook's two-call design drops straight on top of it.

    python build_roster.py            # writes roster.json
    python build_roster.py --stats    # also print duplicate/collision analysis

Scope, verified 2026-09-17 against this session's offered-skills list: 80 of the 103
names on that list come from a SKILL.md and land here. The other 23 (dataviz, simplify,
code-review, loop, schedule, run, init, security-review, workflow-authoring, the
handoff-* and roadmap-run commands, ...) ship inside the Claude Code binary or as slash
commands under ~/.claude/commands, so they have no SKILL.md to read. A suggester built
on this roster can never propose them; that is a property of where they live, not a bug
to fix here.
"""

import json
import re
import sys
from pathlib import Path

CLAUDE = Path.home() / ".claude"
BODY_CHARS = 1600  # what the roster file stores; the run trims to EXCERPT_CHARS
OUT = Path(__file__).parent / "roster.json"


def parse_frontmatter(text):
    """Return (frontmatter dict, body) for a SKILL.md. Only name/description matter."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    raw, body = text[3:end], text[end + 4 :]
    meta = {}
    key, buf = None, []
    for line in raw.splitlines():
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if m:
            if key:
                meta[key] = " ".join(buf).strip()
            key, buf = m.group(1), [m.group(2)]
        elif key and line.strip():
            buf.append(line.strip())  # folded multi-line value
    if key:
        meta[key] = " ".join(buf).strip()
    return meta, body.lstrip()


def category_for(path: Path) -> str:
    """Where the skill came from, which is how collisions get explained later."""
    parts = path.parts
    if "plugins" in parts:
        i = parts.index("plugins")
        # .../plugins/marketplaces/<repo>/... or .../plugins/<name>/...
        tail = parts[i + 1 :]
        if tail and tail[0] == "marketplaces" and len(tail) > 1:
            return f"plugin:{tail[1]}"
        return f"plugin:{tail[0]}" if tail else "plugin"
    return "user"


# Paths that hold SKILL.md files the agent can never load: the versioned download
# cache under plugins/cache (same skills again, one copy per released version), the
# bundled reference/example files inside a skill, and this repo's own test fixtures.
# Counting them inflates the roster to 495 and fabricates duplicate names.
EXCLUDE = (
    "/node_modules/",
    "/.git/",
    "/references/",
    "/examples/",
    "/plugins/cache/",
    "/tests/",
    "/test/",
    "/fixture",
)


def discover():
    """Every SKILL.md that is an actual skill root, not a bundled reference file."""
    skills, seen = [], set()
    for skill_md in CLAUDE.rglob("SKILL.md"):
        p = str(skill_md).replace("\\", "/")
        if any(seg in p for seg in EXCLUDE):
            continue
        try:
            text = skill_md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        meta, body = parse_frontmatter(text)
        name = (meta.get("name") or skill_md.parent.name).strip()
        desc = (meta.get("description") or "").strip()
        if not desc:
            continue  # no description means the agent's index cannot show it either
        key = (name, desc[:80])
        if key in seen:
            continue
        seen.add(key)
        skills.append(
            {
                "name": name,
                "category": category_for(skill_md),
                "description": desc,
                "body": re.sub(r"\s+", " ", body)[:BODY_CHARS],
                "path": str(skill_md),
            }
        )
    return sorted(skills, key=lambda s: (s["category"], s["name"]))


def stats(skills):
    from collections import Counter

    names = Counter(s["name"] for s in skills)
    dupes = {n: c for n, c in names.items() if c > 1}
    widths = [len(s["description"]) for s in skills]
    print(f"{len(skills)} skills, {len({s['category'] for s in skills})} categories")
    print(f"description: {sum(widths) / len(widths):.0f} chars avg, {max(widths)} max")
    est = sum(len(s["name"]) + len(s["description"]) + 8 for s in skills) / 4
    print(f"roster as one Choice question: ~{est:,.0f} tokens")
    print(f"\nduplicate names ({len(dupes)}): the lookalike problem, measured")
    for n, c in sorted(dupes.items(), key=lambda kv: -kv[1])[:15]:
        cats = [s["category"] for s in skills if s["name"] == n]
        print(f"  {n:38s} x{c}  {', '.join(cats[:4])}")


if __name__ == "__main__":
    found = discover()
    OUT.write_text(json.dumps(found, indent=1), encoding="utf-8")
    print(f"wrote {OUT} ({len(found)} skills)")
    if "--stats" in sys.argv:
        print()
        stats(found)
