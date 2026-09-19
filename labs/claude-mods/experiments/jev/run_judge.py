"""Run the SAME typed judgments over the same runtime states through a chosen backend.

  python run_judge.py jev      # TypeSafe Jev (needs experiments/jev/.env with TYPESAFE_API_KEY; token cap enforced)
  python run_judge.py haiku    # Claude Haiku through the Claude Code CLI on the subscription (no API key; NO-API rule)
  python run_judge.py stub     # deterministic rules over the state (the fallback a runtime must always have)

Writes results-<backend>.jsonl and prints an accuracy table per question. The judgment interface is generic:
judge(state, questions) -> {id: answer}; Jev is one implementation.
"""

import json
import os
import sys
import time
import subprocess
import re

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from questions import ALL_QUESTIONS, score_answers  # noqa: E402  (sys.path set above)

TOKEN_CAP = int(os.environ.get("JEV_TOKEN_CAP", "60000"))


# ---------------- backend: Jev ----------------
def load_env():
    p = os.path.join(HERE, ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class JevBackend:
    name = "jev"

    def __init__(self):
        load_env()
        if not os.environ.get("TYPESAFE_API_KEY"):
            raise SystemExit(
                "TYPESAFE_API_KEY missing: run `creds mint typesafe --open`, paste the key into experiments/jev/.env"
            )
        from typesafe_sdk import TypeSafeClient, Choice, Noul, Score

        self.client = TypeSafeClient()
        self.C, self.N, self.S = Choice, Noul, Score
        self.tokens = 0

    def judge(self, state, questions):
        qs = {}
        for k, q in questions.items():
            if q["type"] == "noul":
                qs[k] = self.N(
                    instructions=q["instructions"], criteria=q.get("criteria")
                )
            elif q["type"] == "choice":
                qs[k] = self.C(instructions=q["instructions"], criteria=q["criteria"])
            else:
                qs[k] = self.S(instructions=q["instructions"], criteria=q["criteria"])
        if self.tokens > TOKEN_CAP:
            raise RuntimeError("token cap reached")
        resp = self.client.system_one(state=state, questions=qs)
        self.tokens += resp.usage.input_tokens + resp.usage.output_tokens
        out = {}
        for k, a in resp.nouls.items():
            out[k] = {"type": "noul", "p_yes": round(a.noul, 3)}
        for k, a in resp.choices.items():
            out[k] = {
                "type": "choice",
                "choice": a.choice,
                "confidence": round(a.confidence, 3),
                "probabilities": {o: round(p, 3) for o, p in a.probabilities.items()},
            }
        for k, a in resp.scores.items():
            out[k] = {
                "type": "score",
                "score": round(a.score, 3),
                "confidence": round(a.confidence, 3),
                "probabilities": {o: round(p, 3) for o, p in a.probabilities.items()},
            }
        return out, {
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
            "model": resp.model,
        }

    def close(self):
        self.client.close()


# ---------------- backend: Claude Haiku via the CLI (subscription) ----------------
class HaikuBackend:
    name = "haiku"

    def judge(self, state, questions):
        spec = {
            k: {
                "type": q["type"],
                "instructions": q["instructions"],
                "criteria": q["criteria"],
            }
            for k, q in questions.items()
        }
        prompt = (
            "You are a calibrated judgment engine. Evaluate STATE against every QUESTION independently and answer ONLY with one JSON object "
            'mapping each question id to an answer: for type noul -> {"p_yes": number 0..1}; for type choice -> {"choice": option, "probabilities": {option: number}} (probabilities sum to 1); '
            'for type score -> {"score": number between 0 and levels-1, "probabilities": {"0": p, ...}}. No prose.\n\nSTATE:\n'
            + json.dumps(state)
            + "\n\nQUESTIONS:\n"
            + json.dumps(spec)
        )
        env = {
            k: v
            for k, v in os.environ.items()
            if not (k.startswith("CLAUDE") or k.startswith("ANTHROPIC"))
        }
        r = subprocess.run(
            ["claude", "-p", "--model", "haiku", "--output-format", "json"],
            input=prompt,
            capture_output=True,
            text=True,
            env=env,
            timeout=180,
            shell=True,
        )
        body = json.loads(r.stdout)
        text = body.get("result", "")
        m = re.search(r"\{.*\}", text, re.S)
        raw = json.loads(m.group(0)) if m else {}
        out = {}
        for k, q in questions.items():
            a = raw.get(k, {})
            if q["type"] == "noul":
                out[k] = {"type": "noul", "p_yes": float(a.get("p_yes", 0.5))}
            elif q["type"] == "choice":
                probs = a.get("probabilities") or {}
                ch = a.get("choice") or (max(probs, key=probs.get) if probs else None)
                out[k] = {
                    "type": "choice",
                    "choice": ch,
                    "confidence": round(max(probs.values()) if probs else 0, 3),
                    "probabilities": probs,
                }
            else:
                out[k] = {
                    "type": "score",
                    "score": float(a.get("score", 0)),
                    "confidence": 0,
                    "probabilities": a.get("probabilities") or {},
                }
        u = body.get("usage", {})
        return out, {
            "input_tokens": u.get("input_tokens", 0)
            + u.get("cache_read_input_tokens", 0)
            + u.get("cache_creation_input_tokens", 0),
            "output_tokens": u.get("output_tokens", 0),
            "model": "claude-haiku-4-5 (cli)",
            "cost_usd": body.get("total_cost_usd"),
        }

    def close(self):
        pass


# ---------------- backend: deterministic stub ----------------
class StubBackend:
    name = "stub"

    def judge(self, state, questions):
        s = state
        calls = s.get("recent_tool_calls_oldest_first", [])
        turn_open = s.get("session", {}).get("turn_open", False)
        in_flight = any(c.get("in_flight") for c in calls) or bool(
            s.get("subagents_running")
        )
        reads = [c["args"] for c in calls if c.get("tool") == "Read"]
        reread = len(reads) != len(set(reads))
        denied = sum(1 for c in calls if c.get("denied") or c.get("error"))
        mech = (
            all(c.get("tool") in ("Edit", "Grep", "Glob") for c in calls[-4:])
            and len(calls) >= 4
        )
        model = s.get("session", {}).get("model", "")
        blocked = any(c.get("tool") == "AskUserQuestion" for c in calls[-1:])
        out = {
            "phase": {
                "type": "choice",
                "choice": "idle"
                if not turn_open
                else (
                    "recovery"
                    if denied >= 2
                    else (
                        "verification"
                        if any("test" in str(c.get("args", "")) for c in calls[-2:])
                        or s.get("subagents_running")
                        else "implementation"
                    )
                ),
                "confidence": 0.6,
                "probabilities": {},
            },
            "work_in_progress": {
                "type": "noul",
                "p_yes": 0.9 if (turn_open or in_flight) else 0.1,
            },
            "clean_boundary": {
                "type": "noul",
                "p_yes": 0.1 if (turn_open or in_flight) else 0.9,
            },
            "continuity_loss_risk": {
                "type": "score",
                "score": 3.0 if blocked else (2.0 if turn_open else 0.5),
                "confidence": 0.5,
                "probabilities": {},
            },
            "blocked_on_human": {"type": "noul", "p_yes": 0.9 if blocked else 0.1},
            "tool_thrashing": {"type": "noul", "p_yes": 0.9 if denied >= 2 else 0.1},
            "unnecessary_reread": {"type": "noul", "p_yes": 0.9 if reread else 0.1},
            "loop_state": {
                "type": "choice",
                "choice": "done"
                if not turn_open
                else ("stuck" if reread else "productive"),
                "confidence": 0.6,
                "probabilities": {},
            },
            "model_misroute": {
                "type": "noul",
                "p_yes": 0.9
                if (mech and ("opus" in model or "fable" in model))
                else 0.1,
            },
        }
        return out, {"input_tokens": 0, "output_tokens": 0, "model": "stub"}

    def close(self):
        pass


def main():
    backend_name = sys.argv[1] if len(sys.argv) > 1 else "stub"
    backend = {"jev": JevBackend, "haiku": HaikuBackend, "stub": StubBackend}[
        backend_name
    ]()
    states = json.load(open(os.path.join(HERE, "states.json"), encoding="utf-8"))
    out = open(
        os.path.join(HERE, f"results-{backend_name}.jsonl"), "w", encoding="utf-8"
    )
    totals = {"in": 0, "out": 0, "ms": 0, "n": 0}
    per_q = {}
    for s in states:
        t0 = time.perf_counter()
        try:
            answers, usage = backend.judge(s["state"], ALL_QUESTIONS)
        except Exception as err:
            print("ERR", s["id"], repr(err)[:200])
            out.write(json.dumps({"id": s["id"], "error": repr(err)}) + "\n")
            continue
        ms = round((time.perf_counter() - t0) * 1000)
        totals["in"] += usage["input_tokens"]
        totals["out"] += usage["output_tokens"]
        totals["ms"] += ms
        totals["n"] += 1
        scored = score_answers(s["truth"], answers)
        for k, (pred, exp, ok) in scored.items():
            per_q.setdefault(k, []).append(ok)
        row = {
            "id": s["id"],
            "backend": backend_name,
            "latency_ms": ms,
            "usage": usage,
            "answers": answers,
            "truth": s["truth"],
            "scored": scored,
            "notes": s["notes"],
        }
        out.write(json.dumps(row) + "\n")
        print(
            f"{s['id']:32s} {ms:6d}ms  "
            + "  ".join(
                f"{k}={'✓' if ok else '✗'}({pred}|{exp})"
                for k, (pred, exp, ok) in scored.items()
            )
        )
    out.close()
    backend.close()
    print(
        f"\n{backend_name}: {totals['n']} states, tokens in={totals['in']} out={totals['out']}, mean latency={totals['ms'] / max(1, totals['n']):.0f}ms"
    )
    for k, oks in per_q.items():
        print(f"  {k:22s} {sum(oks)}/{len(oks)} correct")
    json.dump(
        {
            "backend": backend_name,
            **totals,
            "per_question": {k: [sum(v), len(v)] for k, v in per_q.items()},
        },
        open(os.path.join(HERE, f"summary-{backend_name}.json"), "w"),
        indent=1,
    )


if __name__ == "__main__":
    main()
