"""Jev (TypeSafe System One) experiment: narrow typed judgments over REAL Claude Code runtime states.

Reads states.json (see build_states.py), asks Jev a fixed set of independent questions per state in ONE
request (speculative fan-out), records answers, probabilities, confidence, latency and token usage to
results.jsonl, scores them against the ground-truth labels, and writes REPORT.md.

Budget guard: aborts once cumulative input+output tokens exceed TOKEN_CAP (default 60,000). The key is read
from experiments/jev/.env by this program only (never printed).
"""

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN_CAP = int(os.environ.get("JEV_TOKEN_CAP", "60000"))


def load_env():
    p = os.path.join(HERE, ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()
if not os.environ.get("TYPESAFE_API_KEY"):
    print("TYPESAFE_API_KEY missing (experiments/jev/.env)")
    sys.exit(2)

from typesafe_sdk import TypeSafeClient, Choice, Noul, Score  # noqa: E402  (env must load first)

# ---- The judgments. Question ids are for code; the meaning is in instructions/criteria. ----
LEG_QUESTIONS = {
    "phase": Choice(
        instructions="Look at `last_user_prompt`, `recent_tool_calls_oldest_first` and `last_model_step`. Which phase of coding-agent work is the session in right now?",
        criteria={
            "planning": "Reading, searching or exploring; no files changed yet; deciding what to do",
            "implementation": "Editing files or running commands that change things; a task is actively being carried out",
            "verification": "Running tests, checking results, a subagent reporting back, confirming that work succeeded",
            "recovery": "Handling a failure, a denial or an error: retrying, working around a refusal, fixing a broken attempt",
            "idle": "No turn is open (`session.turn_open` is false); the last turn finished and nothing is in flight",
        },
    ),
    "work_in_progress": Noul(
        instructions="Is important work still in progress right now: an open turn, a tool call in flight, a subagent running, or an edit started but not finished?",
        criteria={
            "true": "Something is mid-flight and interrupting now would cut it off",
            "false": "Nothing is in flight; the last action completed and the model has stopped",
        },
    ),
    "clean_boundary": Noul(
        instructions="Would handing this session over to a different coding agent RIGHT NOW be a clean boundary, with no half-done action and no pending answer the current agent still owes?",
        criteria={
            "true": "The turn is closed, no tool call or subagent is running, the working tree is coherent enough to describe",
            "false": "A turn is open, a call or subagent is running, or a dialog is waiting",
        },
    ),
    "continuity_loss_risk": Score(
        instructions="If the session were handed off at this instant with only the information visible in this state, how much continuity would the next agent lose?",
        criteria=[
            "Nothing: the state is self-describing and complete",
            "A little: minor context such as why the last command was run",
            "A lot: a multi-step task is half done and its plan lives only in the current agent's context",
            "Severe: an action is mid-flight or a human answer is pending; the next agent could not know what to do",
        ],
    ),
    "blocked_on_human": Noul(
        instructions="Is the session currently waiting on a human (a dialog, a permission prompt, an approval) rather than on the model or a tool?",
        criteria={
            "true": "A question or approval dialog is open and the human has not answered",
            "false": "No human input is being awaited",
        },
    ),
}
COST_QUESTIONS = {
    "tool_thrashing": Noul(
        instructions="Looking at `recent_tool_calls_oldest_first` and `permission_denials_so_far` if present: is the agent thrashing, i.e. issuing repeated tool calls that keep failing, being denied, or not advancing the task?",
        criteria={
            "true": "Repeated failures or denials with the same approach; little or no progress between calls",
            "false": "Calls succeed and each advances the task",
        },
    ),
    "unnecessary_reread": Noul(
        instructions="In `recent_tool_calls_oldest_first`, is the same file being read again without an intervening edit to it, so that the re-read adds no new information?",
        criteria={
            "true": "The same file_path was Read two or more times with no Edit or Write of that file in between",
            "false": "Each Read is of a new file or follows a change to that file",
        },
    ),
    "loop_state": Choice(
        instructions="Overall, is this session's recent activity productive iteration, a stuck loop, or finished?",
        criteria={
            "productive": "Each step changes something or learns something new",
            "stuck": "The same actions repeat without new information or progress",
            "done": "The task appears complete and the model has stopped",
        },
    ),
    "model_misroute": Noul(
        instructions="Given `session.model` and the nature of `recent_tool_calls_oldest_first` and `last_user_prompt`: is an expensive frontier model (opus/fable) being used for purely mechanical work that a small model could do (bulk renames, formatting, boilerplate, copying)?",
        criteria={
            "true": "The work is mechanical and repetitive and the model is a top-tier expensive one",
            "false": "The work needs judgment, or the model is already a small/cheap one",
        },
    ),
}


def ask(client, state, questions):
    t0 = time.perf_counter()
    resp = client.system_one(state=state, questions=questions)
    ms = (time.perf_counter() - t0) * 1000
    answers = {}
    for k, a in resp.nouls.items():
        answers[k] = {"type": "noul", "p_yes": round(a.noul, 3)}
    for k, a in resp.choices.items():
        answers[k] = {
            "type": "choice",
            "choice": a.choice,
            "confidence": round(a.confidence, 3),
            "probabilities": {o: round(p, 3) for o, p in a.probabilities.items()},
        }
    for k, a in resp.scores.items():
        answers[k] = {
            "type": "score",
            "score": round(a.score, 3),
            "confidence": round(a.confidence, 3),
            "probabilities": {o: round(p, 3) for o, p in a.probabilities.items()},
        }
    return (
        answers,
        ms,
        {
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
        },
        resp.model,
    )


def main():
    states = json.load(open(os.path.join(HERE, "states.json"), encoding="utf-8"))
    out = open(os.path.join(HERE, "results.jsonl"), "w", encoding="utf-8")
    total_in = total_out = 0
    results = []
    with TypeSafeClient() as client:
        for s in states:
            if total_in + total_out > TOKEN_CAP:
                print("TOKEN CAP reached; stopping")
                break
            qs = dict(LEG_QUESTIONS)
            qs.update(COST_QUESTIONS)  # one request, speculative fan-out: 9 questions
            try:
                answers, ms, usage, model = ask(client, s["state"], qs)
            except Exception as err:
                row = {"id": s["id"], "error": repr(err)}
                print("ERR", s["id"], err)
                out.write(json.dumps(row) + "\n")
                results.append(row)
                continue
            total_in += usage["input_tokens"]
            total_out += usage["output_tokens"]
            row = {
                "id": s["id"],
                "source": s["source"],
                "model": model,
                "latency_ms": round(ms),
                "usage": usage,
                "truth": s["truth"],
                "answers": answers,
                "notes": s["notes"],
            }
            out.write(json.dumps(row) + "\n")
            results.append(row)
            print(
                f"{s['id']:34s} {round(ms):5d}ms in={usage['input_tokens']} out={usage['output_tokens']}  phase={answers['phase']['choice']}({answers['phase']['confidence']}) wip={answers['work_in_progress']['p_yes']} boundary={answers['clean_boundary']['p_yes']} risk={answers['continuity_loss_risk']['score']} human={answers['blocked_on_human']['p_yes']} thrash={answers['tool_thrashing']['p_yes']} reread={answers['unnecessary_reread']['p_yes']} loop={answers['loop_state']['choice']} misroute={answers['model_misroute']['p_yes']}"
            )
    out.close()
    json.dump(
        {
            "total_input_tokens": total_in,
            "total_output_tokens": total_out,
            "requests": len(results),
        },
        open(os.path.join(HERE, "usage.json"), "w"),
        indent=1,
    )
    print(f"TOTAL tokens in={total_in} out={total_out} requests={len(results)}")


if __name__ == "__main__":
    main()
