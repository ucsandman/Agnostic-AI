"""Score skill suggestion on real transcript turns: Jev two-call vs a keyword baseline.

    python run_suggest.py keyword          # free, no API, the bar Jev must clear
    python run_suggest.py jev [--limit N]  # two TypeSafe calls per turn

Design follows TypeSafe's skill_suggestion cookbook: call 1 ranks the whole roster with
one Choice and asks three Nouls whether the turn needs a skill at all; call 2 re-reads
the top 3 with real detail and may reject all of them.

Two error rates, both lower-is-better, reported separately because a suggester that
never fires looks perfect on one and useless on the other:
  wrong_load    of turns that did load a skill, share where we name a different one
  needless_load of turns that loaded nothing, share where we suggest something anyway
"""

import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
SHORTLIST = 3
EXCERPT_CHARS = 700
GATE_THRESHOLD = 0.30
FITS_THRESHOLD = 0.30
TOKEN_CAP = 4_000_000  # ~$0.17 at $0.042/Mtok, a hard stop against a runaway loop


def load_env():
    env = HERE / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def load_data(roster_file="roster.json"):
    roster = json.loads((HERE / roster_file).read_text(encoding="utf-8"))
    turns = json.loads((HERE / "turns.json").read_text(encoding="utf-8"))
    # Only skills that appear as a label are reachable; the rest still compete as
    # distractors, which is the point: a real roster is mostly wrong answers.
    return roster, turns


# ---------------- backend: keyword baseline ----------------
class KeywordBackend:
    """Token overlap between the request and each skill's name + description.

    No model, no cost. If Jev cannot beat this, the API call is not buying anything.
    """

    name = "keyword"

    def __init__(self, roster):
        self.roster = roster
        self.index = []
        for s in roster:
            words = set(
                re.findall(r"[a-z]{3,}", f"{s['name']} {s['description']}".lower())
            )
            self.index.append((s["name"], words))
        self.tokens = 0

    def suggest(self, text):
        q = set(re.findall(r"[a-z]{3,}", text.lower()))
        if not q:
            return None
        scored = [(len(q & w) / (len(w) ** 0.5 + 1), n) for n, w in self.index]
        scored.sort(reverse=True)
        best, name = scored[0]
        # a weak best match means nothing really fits, so stay quiet
        return name if best > 0.45 else None

    def close(self):
        pass


# ---------------- backend: Jev, two calls ----------------
class JevBackend:
    name = "jev"
    CHUNK = 250  # API rejects a Choice with more than 255 options, __none__ included

    def __init__(self, roster):
        load_env()
        if not os.environ.get("TYPESAFE_API_KEY"):
            raise SystemExit("TYPESAFE_API_KEY missing: run `creds resolve .` here")
        from typesafe_sdk import Choice, Noul, TypeSafeClient

        self.client = TypeSafeClient()
        self.C, self.N = Choice, Noul
        self.roster = roster
        self.by_name = {s["name"]: s for s in roster}
        self.tokens = 0

    def _spend(self, resp):
        self.tokens += resp.usage.input_tokens + resp.usage.output_tokens
        if self.tokens > TOKEN_CAP:
            raise RuntimeError(f"token cap {TOKEN_CAP:,} reached")

    def suggest(self, text):
        # --- call 1: rank everything, and ask whether any skill is wanted at all
        #
        # A Choice takes at most 255 options (API returns 400 above that) and this
        # roster is 407, so it splits into chunks asked in the SAME request. They
        # evaluate in parallel, so this stays one round trip. Probabilities are only
        # comparable within a chunk, so each chunk carries its own __none__ and the
        # shortlist takes the best from each.
        chunks = [
            self.roster[i : i + self.CHUNK]
            for i in range(0, len(self.roster), self.CHUNK)
        ]
        q1 = {}
        for ci, chunk in enumerate(chunks):
            criteria = {s["name"]: s["description"][:200] for s in chunk}
            criteria["__none__"] = "No skill in this list fits what the user asked for."
            q1[f"which_{ci}"] = self.C(
                instructions=(
                    "The user sent this request to a coding agent that can load one "
                    "skill: a document of instructions for a specific kind of task. "
                    "Which skill best fits this request?"
                ),
                criteria=criteria,
            )
        r1 = self.client.system_one(
            state={"user_request": text},
            questions={
                **q1,
                "wants_action": self.N(
                    instructions="Is the user asking for work to be performed, rather than asking a question to be answered in prose?",
                ),
                "follows_procedure": self.N(
                    instructions="Would this request be done better by following a written, repeatable procedure than by improvising?",
                ),
                "prose_suffices": self.N(
                    instructions="Can this request be fully satisfied by a conversational reply, with no tools used and nothing built or changed?",
                ),
            },
        )
        self._spend(r1)
        gate = (
            r1.nouls["wants_action"].noul
            + r1.nouls["follows_procedure"].noul
            + (1 - r1.nouls["prose_suffices"].noul)
        ) / 3
        if gate < GATE_THRESHOLD:
            return None, {"stage": "gate", "gate": round(gate, 3)}

        # Merge the chunks. Each chunk's __none__ probability says how strongly that
        # chunk disclaims the request; a skill only survives if it beat its own chunk's
        # __none__, which keeps a chunk of pure distractors from promoting its least-bad
        # entry into the shortlist.
        pooled = []
        none_won_all = True
        for ci in range(len(chunks)):
            probs = r1.choices[f"which_{ci}"].probabilities
            none_p = probs.get("__none__", 0.0)
            best = [(p, n) for n, p in probs.items() if n != "__none__"]
            if not best:
                continue
            best.sort(reverse=True)
            if best[0][0] > none_p:
                none_won_all = False
            pooled.extend(best[:SHORTLIST])
        if none_won_all or not pooled:
            return None, {"stage": "none_won", "gate": round(gate, 3)}
        pooled.sort(reverse=True)
        top = [n for _, n in pooled[:SHORTLIST]]

        # --- call 2: read the finalists properly, and allow rejecting all of them
        detail = {
            n: {
                "name": n,
                "description": self.by_name[n]["description"],
                "instructions_excerpt": self.by_name[n]["body"][:EXCERPT_CHARS],
            }
            for n in top
        }
        q2 = {
            "which": self.C(
                instructions="Given the full descriptions, which of these skills should the agent load for this request?",
                criteria={
                    **{n: detail[n]["description"][:400] for n in top},
                    "__none__": "None of these three is right for this request.",
                },
            )
        }
        for i, n in enumerate(top):
            q2[f"fits_{i}"] = self.N(
                instructions={
                    "question": "Does this skill actually do what the user is asking for?",
                    "skill": detail[n],
                }
            )
        r2 = self.client.system_one(
            state={"user_request": text, "candidates": detail}, questions=q2
        )
        self._spend(r2)
        pick = r2.choices["which"].choice
        if pick == "__none__":
            return None, {"stage": "rejected", "gate": round(gate, 3)}
        best_fit = max(r2.nouls[f"fits_{i}"].noul for i in range(len(top)))
        if best_fit < FITS_THRESHOLD:
            return None, {"stage": "low_fit", "fit": round(best_fit, 3)}
        return pick, {
            "stage": "picked",
            "gate": round(gate, 3),
            "fit": round(best_fit, 3),
            "conf": round(r2.choices["which"].confidence, 3),
            "top3": top,
        }

    def close(self):
        self.client.close()


def main():
    backend_name = sys.argv[1] if len(sys.argv) > 1 else "keyword"
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    roster_file = "roster.json"
    if "--roster" in sys.argv:
        roster_file = sys.argv[sys.argv.index("--roster") + 1]
    roster, turns = load_data(roster_file)
    pos, neg = turns["positives"], turns["negatives"]
    if limit:
        pos, neg = pos[:limit], neg[: max(1, limit // 2)]
    # A turn whose gold skill is not in this roster can never be answered correctly.
    # It is kept and counted as an orphan so a smaller roster cannot buy its score by
    # quietly discarding the turns it made unanswerable.
    in_roster = {s["name"] for s in roster}

    backend = {"keyword": KeywordBackend, "jev": JevBackend}[backend_name](roster)
    rows, t0 = [], time.time()

    for i, p in enumerate(pos + neg, 1):
        try:
            out = backend.suggest(p["text"])
            pick, meta = out if isinstance(out, tuple) else (out, {})
        except RuntimeError as e:
            print(f"stopped at {i}: {e}")
            break
        rows.append(
            {
                "text": p["text"][:160],
                "gold": p.get("gold"),
                "pick": pick,
                "names_skill": p.get("names_skill", False),
                "meta": meta,
            }
        )
        if i % 25 == 0:
            print(f"  {i}/{len(pos) + len(neg)}  {time.time() - t0:.0f}s", flush=True)

    backend.close()
    (HERE / f"suggest-{backend_name}-{Path(roster_file).stem}.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows), encoding="utf-8"
    )

    covered = [r for r in rows if r["gold"]]
    uncovered = [r for r in rows if not r["gold"]]
    answerable = [r for r in covered if r["gold"] in in_roster]
    orphans = [r for r in covered if r["gold"] not in in_roster]
    wrong = [r for r in answerable if r["pick"] != r["gold"]]
    needless = [r for r in uncovered if r["pick"]]
    hard = [r for r in answerable if not r["names_skill"]]
    hard_wrong = [r for r in hard if r["pick"] != r["gold"]]
    orphan_noise = [r for r in orphans if r["pick"]]

    summary = {
        "backend": backend_name,
        "roster": roster_file,
        "roster_size": len(roster),
        "n_answerable": len(answerable),
        "n_orphan": len(orphans),
        "n_uncovered": len(uncovered),
        "wrong_load": round(len(wrong) / max(1, len(answerable)), 4),
        "needless_load": round(len(needless) / max(1, len(uncovered)), 4),
        "orphan_wrong_suggestion": round(len(orphan_noise) / max(1, len(orphans)), 4),
        "wrong_load_hard_subset": round(len(hard_wrong) / max(1, len(hard)), 4),
        "n_hard": len(hard),
        "tokens": backend.tokens,
        "cost_usd": round(backend.tokens * 0.042 / 1e6, 4),
        "seconds": round(time.time() - t0, 1),
    }
    (HERE / f"suggest-summary-{backend_name}-{Path(roster_file).stem}.json").write_text(
        json.dumps(summary, indent=1), encoding="utf-8"
    )
    print(f"\n=== {backend_name} ===")
    for k, v in summary.items():
        print(f"  {k:24s} {v}")
    print("\n  most-missed skills:")
    for name, n in Counter(r["gold"] for r in wrong).most_common(6):
        print(f"    {n:3d}  {name}")


if __name__ == "__main__":
    main()
