---
name: team
description: Fan a task out to the Claude Code + OpenClaw (MoltFire) team. Use when the user types /team <task> or asks to "have both agents" / "the team" handle something. Classifies who leads, delegates over CLI, logs every exchange to the team ledger, reports back here.
---

# /team — two-agent task execution

Read `~/clawd/agent-comms/team/PROTOCOL.md` FIRST and follow it
exactly, then `~/clawd/agent-comms/team/LESSONS.md`. This skill
is the Claude Code entry point; the protocol file is the source of truth for
classifier, transport, ledger, tiers, and failure rules.

Paths here are home-anchored (`~/…`) on purpose. `agent-comms/team/...` is
relative and does not resolve from the usual cwd, and `~/agent-comms` is a
DIFFERENT repo with no `team/` dir. A relative path silently skips the
protocol and the lessons file.

## Procedure

0. **Recon before you design.** Before proposing any adapter, wrapper, bot, or
   browser automation, enumerate what the target already exposes — list its
   API routes, CLI commands, and exported functions FROM SOURCE. Never accept
   "there is no X" from a README, a report, or the other agent; a negative
   capability claim rules out whole designs, so verify it directly. Two agents
   agreeing on an inherited premise is one check, not two. (See LESSONS.md
   2026-08-10.)

1. **Classify** the task with the PROTOCOL.md Classifier. Announce the lead
   in one sentence.
2. **Create the task** (you are the receiving agent):
   `node ~/clawd/agent-comms/team/bin/team-ledger.mjs create --slug <slug> --instruction "<task>" --origin claude-code --lead <claude|openclaw>`
   then `update --task <id> --status in_progress`.
3. **If YOU lead:**
   - `dashclaw_session_start` for the task.
   - Decompose. For each piece that belongs to OpenClaw's domain, send a
     DELEGATION envelope (PROTOCOL.md Transport) via Bash:
     `openclaw agent --agent main --message "<envelope>" --timeout 300`
     Send the delegation, then log a `delegation` event (send first, then
     log). Log the returned answer as received context; MoltFire logs its
     own `reply` event itself.
   - Do your own share of the work. Apply the Tier rules from PROTOCOL.md
     (guard/record/approval) to every consequential action.
   - Integrate, verify, write artifacts to
     `agent-comms/team/tasks/<id>/artifacts/`.
   - Log a `result` event, report to the user in this session, log `done`,
     `update --status done`, `dashclaw_session_end`.
4. **If OPENCLAW leads:** send the LEAD_HANDOFF envelope (PROTOCOL.md
   Transport) via `openclaw agent --agent main --message ... --timeout 1800`
   (the whole task runs inside that call — LEAD_HANDOFF window, not the
   300s delegation window), log a `lead_assigned` event, then act as
   specialist: answer any DELEGATION envelopes MoltFire sends back during
   the task, and relay MoltFire's final report to the user verbatim when it
   arrives in the command output.
5. **Failure handling:** PROTOCOL.md Failure rules verbatim. Delegation
   timeout (300s) → log `error`, retry once, degrade to solo with a note.
   LEAD_HANDOFF timeout (1800s) → check the task's `events-openclaw.jsonl`
   first; fresh events mean the lead is alive — poll the ledger, never
   spawn a second lead. Cap 10 exchanges.

## Hard rules

- You log events ONLY with `--from claude`.
- Specialists (either direction) answer once and stop. No sub-delegation.
- Never approve anything on Wes's behalf; Tier 2/3 waits for his approval
  via DashClaw. Fail closed if DashClaw is unreachable.
- No secrets in envelopes, events, or artifacts.
