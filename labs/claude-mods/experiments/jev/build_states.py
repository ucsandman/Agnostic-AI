"""Build reproducible runtime-state snapshots for the Jev experiment from REAL captured function-hook timelines.

Sources (captured 2026-09-16, see ../../snapshot/2.1.273/payloads/):
  - xray-timeline-demo-session.jsonl   : 1,254 events of an interactive Haiku session (4 prompts, denials, a dialog)
  - probe3-subagent-permission.jsonl    : Sonnet main loop spawning a Haiku subagent
  - probe2-interception.jsonl           : Haiku running 7 tool steps incl. hook denials / rewrites

A "state" is what a LegCLI / CostClaw runtime supervisor would hold at one instant: the last prompt, the
recent tool calls (tool, args, result summary, ms, denied?), the last model step, whether a turn is open,
subagents in flight, and usage. Each state carries GROUND-TRUTH labels derived from what actually happened
next in the timeline (not from opinion) so Jev's judgments can be scored.

Output: states.json (list of {id, source, state, truth, notes}).
"""

import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
PAY = os.path.join(HERE, "..", "..", "snapshot", "2.1.273", "payloads")


def short(v, n=140):
    s = v if isinstance(v, str) else json.dumps(v)
    s = re.sub(r"\s+", " ", s or "")
    return s if len(s) <= n else s[: n - 1] + "…"


def load(name):
    return [
        json.loads(line)
        for line in open(os.path.join(PAY, name), encoding="utf-8")
        if line.strip()
    ]


# ---------- source 1: xray demo session (events carry event/e/r/ms/agentId) ----------
def xray_states():
    rows = load("xray-timeline-demo-session.jsonl")
    keep = [
        r
        for r in rows
        if r["event"]
        in (
            "prompt.submit",
            "tool.call",
            "turn.step",
            "turn.complete",
            "agent.spawn",
            "tool.check",
        )
    ]
    states = []

    def snapshot(upto, sid, truth, notes):
        window = keep[:upto]
        prompts = [w for w in window if w["event"] == "prompt.submit"]
        tools = [w for w in window if w["event"] == "tool.call"]
        steps = [w for w in window if w["event"] == "turn.step"]
        completes = [w for w in window if w["event"] == "turn.complete"]
        last_prompt = prompts[-1]["e"]["text"] if prompts else ""
        turn_open = len(completes) < len(prompts) if prompts else False
        recent = []
        for t in tools[-8:]:
            e, r = t["e"], t["r"] or {}
            args = {
                k: v
                for k, v in e.items()
                if k not in ("tool", "tool_use_id", "agentId")
            }
            recent.append(
                {
                    "tool": e.get("tool"),
                    "args": short(args, 120),
                    "ms": t["ms"],
                    "denied": bool(r.get("deny")),
                    "error": bool(r.get("isError")),
                    "result": short(
                        r.get("deny") or r.get("text") or r.get("result") or "", 100
                    ),
                }
            )
        last_step = steps[-1] if steps else None
        st = {
            "session": {
                "model": "claude-haiku-4-5",
                "surface": "terminal",
                "turn_open": turn_open,
                "prompts_so_far": len(prompts),
                "tool_calls_so_far": len(tools),
            },
            "last_user_prompt": short(last_prompt, 200),
            "recent_tool_calls_oldest_first": recent,
            "last_model_step": None
            if not last_step
            else {
                "stop_reason": (last_step["r"] or {}).get("stopReason"),
                "tools_requested": [
                    t["name"] for t in (last_step["r"] or {}).get("toolUses", [])
                ],
                "messages_in_context": last_step["e"].get("messageCount"),
            },
            "subagents_running": [],
            "usage": {
                "context_percent": 27,
                "five_hour_percent": 26,
                "seven_day_percent": 6,
            },
            "git": {
                "uncommitted_changes": True,
                "note": "lab/ files edited earlier this session; no commit yet",
            },
        }
        states.append(
            {
                "id": sid,
                "source": "xray-demo",
                "state": st,
                "truth": truth,
                "notes": notes,
            }
        )

    # locate indices
    prompt_idx = [i for i, w in enumerate(keep) if w["event"] == "prompt.submit"]
    complete_idx = [i for i, w in enumerate(keep) if w["event"] == "turn.complete"]
    tool_idx = [i for i, w in enumerate(keep) if w["event"] == "tool.call"]
    # S1: right after prompt 2 submitted, before any tool ran -> work about to start, not a boundary
    snapshot(
        prompt_idx[1] + 1,
        "xray-after-prompt2",
        {
            "work_in_progress": True,
            "clean_boundary": False,
            "phase": "implementation",
            "next_event": "tool.call Read",
        },
        "prompt 2 (edit protected file) just submitted; the model has not acted yet",
    )
    # S2: mid-turn after the Read, before the Edit (which will be denied)
    snapshot(
        tool_idx[1] + 1,
        "xray-mid-turn2-after-read",
        {
            "work_in_progress": True,
            "clean_boundary": False,
            "phase": "implementation",
            "next_event": "tool.call Edit (denied by guardian)",
        },
        "turn 2 open; Read done; Edit attempt is next",
    )
    # S3: after turn 2 complete (edit refused, model reported) -> boundary, recovery-ish
    snapshot(
        complete_idx[1] + 1,
        "xray-after-turn2-complete",
        {
            "work_in_progress": False,
            "clean_boundary": True,
            "phase": "idle",
            "next_event": "prompt.submit (user)",
        },
        "turn 2 ended with the model quoting the refusal; nothing in flight",
    )
    # S4: during the MATRIX freeze: AskUserQuestion open (tool.call in flight 28 s) -> waiting on human, not a boundary
    ask_i = [i for i in tool_idx if keep[i]["e"].get("tool") == "AskUserQuestion"]
    snapshot(
        ask_i[0] + 1,
        "xray-during-dialog",
        {
            "work_in_progress": True,
            "clean_boundary": False,
            "phase": "implementation",
            "next_event": "tool.call Bash",
        },
        "a dialog held the Bash call for 28 s; turn 4 open",
    )
    # S5: after the last turn complete -> boundary
    snapshot(
        complete_idx[-1] + 1,
        "xray-session-end",
        {
            "work_in_progress": False,
            "clean_boundary": True,
            "phase": "idle",
            "next_event": "command.run /blackbox",
        },
        "all four turns complete",
    )
    return states


# ---------- source 2: probe3 (Sonnet + Haiku subagent) ----------
def probe3_states():
    rows = load("probe3-subagent-permission.jsonl")
    # rows have kind: tool.call / turn.step / agent.spawn / turn.complete / check / final
    spawn = next(r for r in rows if r["kind"] == "agent.spawn")
    main_done = [
        r for r in rows if r["kind"] == "turn.complete" and not r.get("agentId")
    ]

    def base():
        return {
            "session": {
                "model": "claude-sonnet-5",
                "surface": "headless -p",
                "turn_open": True,
                "prompts_so_far": 1,
                "tool_calls_so_far": 1,
            },
            "last_user_prompt": "Use the Agent tool exactly once with subagent_type haiku-scout and model haiku to run one Bash command and report its output verbatim.",
            "usage": {
                "context_percent": 6,
                "five_hour_percent": 11,
                "seven_day_percent": 3,
            },
            "git": {"uncommitted_changes": False},
        }

    s_a = base()
    s_a["recent_tool_calls_oldest_first"] = [
        {
            "tool": "Agent",
            "args": short(spawn["asked"]["prompt"], 120),
            "ms": None,
            "in_flight": True,
        }
    ]
    s_a["subagents_running"] = [
        {
            "id": spawn["r"]["agentId"][:8],
            "type": spawn["asked"]["subagentType"],
            "model": spawn["r"]["model"],
            "tool_calls": 0,
        }
    ]
    s_a["last_model_step"] = {
        "stop_reason": "tool_use",
        "tools_requested": ["Agent"],
        "messages_in_context": 37,
    }
    s_b = base()
    s_b["recent_tool_calls_oldest_first"] = [
        {
            "tool": "Agent",
            "args": short(spawn["asked"]["prompt"], 120),
            "ms": None,
            "in_flight": True,
        },
        {
            "tool": "Bash",
            "agent": spawn["r"]["agentId"][:8],
            "args": "node -e console.log(...)",
            "ms": 4000,
            "result": "FROM-SUB",
        },
    ]
    s_b["subagents_running"] = [
        {
            "id": spawn["r"]["agentId"][:8],
            "type": "haiku-scout",
            "model": spawn["r"]["model"],
            "tool_calls": 1,
            "status": "running (handing back)",
        }
    ]
    s_b["last_model_step"] = {
        "stop_reason": "tool_use",
        "tools_requested": ["SubagentHandback"],
        "messages_in_context": 35,
        "agent": spawn["r"]["agentId"][:8],
    }
    s_c = base()
    s_c["session"]["turn_open"] = False
    s_c["recent_tool_calls_oldest_first"] = [
        {
            "tool": "Agent",
            "args": "haiku-scout: run one Bash command",
            "ms": 19000,
            "result": short(main_done[0]["answer"], 100),
        }
    ]
    s_c["subagents_running"] = []
    s_c["last_model_step"] = {
        "stop_reason": "end_turn",
        "tools_requested": [],
        "messages_in_context": 55,
    }
    return [
        {
            "id": "probe3-subagent-just-spawned",
            "source": "probe3",
            "state": s_a,
            "truth": {
                "work_in_progress": True,
                "clean_boundary": False,
                "phase": "implementation",
                "next_event": "subagent tool.call",
            },
            "notes": "subagent started, no calls yet",
        },
        {
            "id": "probe3-subagent-handing-back",
            "source": "probe3",
            "state": s_b,
            "truth": {
                "work_in_progress": True,
                "clean_boundary": False,
                "phase": "verification",
                "next_event": "subagent turn.complete then parent step",
            },
            "notes": "subagent finished its command, handing back",
        },
        {
            "id": "probe3-main-complete",
            "source": "probe3",
            "state": s_c,
            "truth": {
                "work_in_progress": False,
                "clean_boundary": True,
                "phase": "idle",
                "next_event": "session end",
            },
            "notes": "parent reported; nothing in flight",
        },
    ]


# ---------- source 3: probe2 (7 sequential tool steps, several denied) for CostClaw-style judgments ----------
def probe2_states():
    rows = load("probe2-interception.jsonl")
    checks = [r for r in rows if r["kind"] == "check"]
    calls = [r for r in rows if r["kind"] == "observe" and r["event"] == "tool.call"]
    recent = []
    for c in calls:
        e, r = c["e"], c["r"] or {}
        recent.append(
            {
                "tool": e.get("tool"),
                "args": short(
                    {k: v for k, v in e.items() if k not in ("tool", "tool_use_id")},
                    100,
                ),
                "ms": c["ms"],
                "denied": bool(r.get("deny")),
                "error": bool(r.get("isError")),
                "result": short(r.get("deny") or r.get("text") or "", 90),
            }
        )
    denied = [c for c in checks if c["r"]["decision"] == "deny"]
    st = {
        "session": {
            "model": "claude-haiku-4-5",
            "surface": "headless -p",
            "turn_open": True,
            "prompts_so_far": 1,
            "tool_calls_so_far": len(calls),
        },
        "last_user_prompt": "Do these 7 steps IN ORDER, one tool call each... Do not skip a step because an earlier one failed.",
        "recent_tool_calls_oldest_first": recent,
        "permission_denials_so_far": [short(d["r"]["reason"], 120) for d in denied],
        "last_model_step": {
            "stop_reason": "tool_use",
            "tools_requested": ["Bash"],
            "messages_in_context": 60,
        },
        "subagents_running": [],
        "usage": {
            "context_percent": 9,
            "five_hour_percent": 10,
            "seven_day_percent": 2,
        },
    }
    truth = {
        "tool_thrashing": True,
        "loop_state": "productive",
        "unnecessary_reread": False,
        "model_misroute": False,
        "note": "3 consecutive Bash calls were denied by the harness batch-guard (one-at-a-time calls); the model kept issuing single calls because the user demanded it; it was still making progress",
    }
    # A second, contrasting state: repeated identical Read of the same file (synthetic from real rows, labelled synthetic)
    reread = [
        {
            "tool": "Read",
            "args": '{"file_path":"C:/Projects/app/src/auth.ts"}',
            "ms": 120,
            "result": "1 export function verifyToken(...)",
        }
    ] * 4
    st2 = {
        "session": {
            "model": "claude-opus-5",
            "surface": "terminal",
            "turn_open": True,
            "prompts_so_far": 3,
            "tool_calls_so_far": 19,
        },
        "last_user_prompt": "fix the failing auth test",
        "recent_tool_calls_oldest_first": reread
        + [
            {
                "tool": "Bash",
                "args": "npm test -- auth.spec.ts",
                "ms": 4100,
                "result": "1 failing: expected 200, got 401",
            },
            {
                "tool": "Read",
                "args": '{"file_path":"C:/Projects/app/src/auth.ts"}',
                "ms": 110,
                "result": "1 export function verifyToken(...)",
            },
        ],
        "last_model_step": {
            "stop_reason": "tool_use",
            "tools_requested": ["Read"],
            "messages_in_context": 140,
        },
        "subagents_running": [],
        "usage": {
            "context_percent": 61,
            "five_hour_percent": 70,
            "seven_day_percent": 40,
        },
    }
    truth2 = {
        "tool_thrashing": False,
        "loop_state": "stuck",
        "unnecessary_reread": True,
        "model_misroute": False,
        "note": "SYNTHETIC (built from real event shapes): the same file read 5 times without an edit between reads",
    }
    st3 = {
        "session": {
            "model": "claude-opus-5",
            "surface": "terminal",
            "turn_open": True,
            "prompts_so_far": 1,
            "tool_calls_so_far": 6,
        },
        "last_user_prompt": "rename every occurrence of fooBar to fooBaz across src/",
        "recent_tool_calls_oldest_first": [
            {"tool": "Grep", "args": "fooBar src/", "ms": 90, "result": "14 files"}
        ]
        + [
            {
                "tool": "Edit",
                "args": f'{{"file_path":"src/f{i}.ts","old_string":"fooBar","new_string":"fooBaz","replace_all":true}}',
                "ms": 60,
                "result": "ok",
            }
            for i in range(5)
        ],
        "last_model_step": {
            "stop_reason": "tool_use",
            "tools_requested": ["Edit"],
            "messages_in_context": 40,
        },
        "subagents_running": [],
        "usage": {
            "context_percent": 12,
            "five_hour_percent": 70,
            "seven_day_percent": 40,
        },
    }
    truth3 = {
        "tool_thrashing": False,
        "loop_state": "productive",
        "unnecessary_reread": False,
        "model_misroute": True,
        "note": "SYNTHETIC: purely mechanical replace-all edits running on the most expensive model",
    }
    return [
        {
            "id": "probe2-denied-single-calls",
            "source": "probe2",
            "state": st,
            "truth": truth,
            "notes": truth["note"],
        },
        {
            "id": "synthetic-reread-loop",
            "source": "synthetic",
            "state": st2,
            "truth": truth2,
            "notes": truth2["note"],
        },
        {
            "id": "synthetic-mechanical-on-opus",
            "source": "synthetic",
            "state": st3,
            "truth": truth3,
            "notes": truth3["note"],
        },
    ]


if __name__ == "__main__":
    states = xray_states() + probe3_states() + probe2_states()
    out = os.path.join(HERE, "states.json")
    json.dump(states, open(out, "w", encoding="utf-8"), indent=1)
    print(f"wrote {len(states)} states to {out}")
    for s in states:
        print(" ", s["id"], "->", {k: v for k, v in s["truth"].items() if k != "note"})
