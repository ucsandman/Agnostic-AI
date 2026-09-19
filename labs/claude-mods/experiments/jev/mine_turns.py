"""Mine labeled (user request -> skill the agent loaded) pairs from real transcripts.

Ground truth here is a past decision by Claude, not a human label. It is the best
signal available without hand-labeling, and it has a known bias: a turn where the
agent picked the wrong skill is recorded as if that skill were correct. The eval
reports agreement with past behavior, which is why `--review` exists to spot-check.

Positives: the user's text immediately before a direct Skill call, labeled with it.
Negatives: user turns in the same sessions where no skill was loaded at all, which
is what the "should anything load?" gate has to get right.

    python mine_turns.py                 # writes turns.json
    python mine_turns.py --review 20     # print a sample to eyeball the labels
"""

import json
import random
import sys
from pathlib import Path

ROOT = Path.home() / ".claude" / "projects"
OUT = Path(__file__).parent / "turns.json"
MIN_CHARS, MAX_CHARS = 15, 1500

# A user record whose text starts with one of these is machine-generated, not a request.
NOISE_PREFIXES = (
    "<system-reminder",
    "[OpenClaw",
    "Caveat:",
    "<command-name>",
    "<local-command",
    "<user-prompt-submit-hook",
    "[Request interrupted",
    "API Error",
    "<task-notification",
    "[Image:",  # image-only turn: no text for a text-only model to rank
    "Conversation info:",  # OpenClaw envelope, the request is elsewhere
)

# A turn opening this way answers something already on screen, so the skill the agent
# loaded came from conversation context the suggester never sees. Scoring these would
# punish the model for missing information it was not given.
CONTEXT_DEPENDENT = (
    "wait ",
    "no ",
    "yes ",
    "yeah ",
    "ok ",
    "okay ",
    "actually ",
    "also ",
    "and ",
    "but ",
    "that ",
    "it ",
    "this ",
    "why ",
    "keep going",
    "continue",
    "go ahead",
)


def user_text(rec):
    """The human's words in a user record, or None if it is tool output or noise."""
    msg = rec.get("message") or {}
    if msg.get("role") != "user" or rec.get("isSidechain"):
        return None
    content = msg.get("content")
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content if b.get("type") == "text"]
        # a list containing tool_result is the harness replying to itself
        if any(b.get("type") == "tool_result" for b in content):
            return None
        text = "\n".join(parts).strip()
    elif isinstance(content, str):
        text = content.strip()
    else:
        return None
    if not text or text.startswith(NOISE_PREFIXES):
        return None
    if "[Image: source:" in text[:200]:
        return None
    if text.lower().startswith(CONTEXT_DEPENDENT):
        return None
    # An explicit slash invocation names the skill in the request, so ranking it is
    # a string match, not a judgment. Keeping these would inflate every backend.
    if "<command-name>" in text or "<command-message>" in text:
        return None
    if not (MIN_CHARS <= len(text) <= MAX_CHARS):
        return None
    return text


def skill_calls(rec):
    """Skill names this assistant record invoked directly (not auto-triggered)."""
    msg = rec.get("message") or {}
    if msg.get("role") != "assistant":
        return []
    content = msg.get("content")
    if not isinstance(content, list):
        return []
    out = []
    for b in content:
        if b.get("type") == "tool_use" and b.get("name") == "Skill":
            caller = (b.get("caller") or {}).get("type")
            if caller and caller != "direct":
                continue  # auto-invoked, so it reflects no judgment to measure
            name = (b.get("input") or {}).get("skill")
            if name:
                out.append(name)
    return out


def mine():
    positives, negatives = [], []
    files = sorted(ROOT.glob("*/*.jsonl"))
    for f in files:
        try:
            records = [
                json.loads(line)
                for line in f.open(encoding="utf-8", errors="replace")
                if line.strip()
            ]
        except (OSError, json.JSONDecodeError):
            continue
        pending = None  # most recent human request not yet resolved
        for rec in records:
            if (
                rec.get("type") == "user"
                or (rec.get("message") or {}).get("role") == "user"
            ):
                t = user_text(rec)
                if t:
                    if pending:  # previous request ended with no skill loaded
                        negatives.append(
                            {"text": pending, "gold": None, "file": f.name}
                        )
                    pending = t
                continue
            names = skill_calls(rec)
            if names and pending:
                positives.append({"text": pending, "gold": names[0], "file": f.name})
                pending = None
            elif names:
                pending = None
        if pending:
            negatives.append({"text": pending, "gold": None, "file": f.name})
    return positives, negatives


if __name__ == "__main__":
    pos, neg = mine()
    # dedupe on request text: repeated prompts would let one phrasing dominate scoring
    seen, upos = set(), []
    for p in pos:
        if p["text"] not in seen:
            seen.add(p["text"])
            upos.append(p)
    uneg = []
    for n in neg:
        if n["text"] not in seen:
            seen.add(n["text"])
            uneg.append(n)

    random.seed(17)
    random.shuffle(uneg)
    # keep negatives near the cookbook's ratio (173 uncovered to 315 covered)
    uneg = uneg[: max(1, int(len(upos) * 0.55))]

    # Flag, but keep, requests that spell out the skill's own name. They are genuine
    # turns, and dropping them would bias the set toward hard cases only; the eval
    # reports scores with and without them so neither reading can hide.
    for p in upos:
        bare = p["gold"].split(":")[-1].replace("-", " ").lower()
        p["names_skill"] = (
            bare in p["text"].lower() or p["gold"].lower() in p["text"].lower()
        )

    data = {"positives": upos, "negatives": uneg}
    OUT.write_text(json.dumps(data, indent=1), encoding="utf-8")
    from collections import Counter

    c = Counter(p["gold"] for p in upos)
    print(f"wrote {OUT}")
    print(f"positives: {len(upos)} over {len(c)} distinct skills")
    print(f"negatives: {len(uneg)}")
    print("\nmost-loaded skills:")
    for name, n in c.most_common(12):
        print(f"  {n:4d}  {name}")

    if "--review" in sys.argv:
        k = int(sys.argv[sys.argv.index("--review") + 1])
        print(f"\n--- random {k} positives, check the labels ---")
        for p in random.sample(upos, min(k, len(upos))):
            print(f"\n[{p['gold']}]\n  {p['text'][:220]}")
