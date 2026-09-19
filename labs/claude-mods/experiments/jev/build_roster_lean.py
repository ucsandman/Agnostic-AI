"""Build a lean roster from usage history, without peeking at the eval's labels.

The full 407-skill roster sank call-1 recall to 8%. The probe's 22-skill roster got
42%, but it was assembled FROM the eval labels, so it could never miss. That number is
an upper bound, not a result.

This builds the honest version: rank skills by how often they were loaded across all
transcripts, keep the top N, and deduplicate by name. A skill's own load history is
knowable at hook-install time without knowing what the next request will be.

The eval then splits its turns:
  in-roster  turns whose gold skill made the cut. The suggester can be right.
  orphan     turns whose gold skill did not. The suggester must stay quiet, and every
             suggestion is a needless load. Dropping these would hide the real cost.

    python build_roster_lean.py --top 40
"""

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
ROOT = Path.home() / ".claude" / "projects"


def load_counts():
    """How many times each skill was directly invoked, across every transcript."""
    counts = Counter()
    for f in ROOT.glob("*/*.jsonl"):
        try:
            for line in f.open(encoding="utf-8", errors="replace"):
                if '"Skill"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = rec.get("message") or {}
                if msg.get("role") != "assistant":
                    continue
                content = msg.get("content")
                if not isinstance(content, list):
                    continue
                for b in content:
                    if b.get("type") == "tool_use" and b.get("name") == "Skill":
                        caller = (b.get("caller") or {}).get("type")
                        if caller and caller != "direct":
                            continue
                        name = (b.get("input") or {}).get("skill")
                        if name:
                            counts[name] += 1
        except OSError:
            continue
    return counts


def main():
    top_n = 40
    if "--top" in sys.argv:
        top_n = int(sys.argv[sys.argv.index("--top") + 1])

    full = json.loads((HERE / "roster.json").read_text(encoding="utf-8"))
    counts = load_counts()

    # Deduplicate by name first: three skills called `launch` can only ever waste
    # shortlist slots, since the suggestion is delivered as a name.
    by_name = {}
    for s in full:
        prior = by_name.get(s["name"])
        if prior is None or len(s["description"]) > len(prior["description"]):
            by_name[s["name"]] = s
    print(f"{len(full)} skills -> {len(by_name)} after name dedupe")

    ranked = [(counts.get(n, 0), n) for n in by_name]
    ranked.sort(key=lambda kv: (-kv[0], kv[1]))
    used = [n for c, n in ranked if c > 0]
    print(f"{len(used)} skills were loaded at least once in the transcript history")

    keep = [by_name[n] for _, n in ranked[:top_n]]
    out = HERE / "roster-lean.json"
    out.write_text(json.dumps(keep, indent=1), encoding="utf-8")

    est = sum(len(s["name"]) + len(s["description"]) + 8 for s in keep) / 4
    print(f"\nwrote {out}: {len(keep)} skills, ~{est:,.0f} tokens per Choice")
    print("top of the roster, by loads:")
    for c, n in ranked[:12]:
        print(f"  {c:4d}  {n}")


if __name__ == "__main__":
    main()
