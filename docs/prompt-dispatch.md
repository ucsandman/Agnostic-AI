---
name: prompt-dispatch
description: "UserPromptSubmit is one process (prompt-dispatch.cjs) running the prompt hooks in-process; wakeup-guard.cjs stops a session from answering every Monitor wake-up with Waiting."
context:
  triggers:
    keywords: ["prompt-dispatch", "wakeup-guard", "hook timed out", "UserPromptSubmit", "Waiting.", "task-notification", "Monitor wake-up"]
  priority: 40
---
# prompt-dispatch.cjs and wakeup-guard.cjs (2026-09-19)

UserPromptSubmit is ONE registered command, `prompt-dispatch.cjs`, timeout 30 s.
It reads the payload once and runs every prompt hook in-process (its `CHAIN`:
wakeup-guard, context-nudge, scope-lock, opus-handoff-inject, correction-tracker,
repeat-tool-guard --reset, fable-delegate-guard, mods-liveness, context-graph),
intercepting fd 0, stdout and `process.exit` around each require, then merges
the answers: additionalContext joined in chain order, the first `decision: block`
wins, systemMessages concatenated. Per-hook ms go to
`~/.claude/state/prompt-dispatch.jsonl` (`--report` prints medians; `--list` the
chain). A hook that throws is skipped and logged, never fatal. Why: eight spawns
per prompt at 5 s each timed out on every prompt once a bare node start cost
2.6 s under load, and every machine wake-up repeated the set. Add a prompt hook
by adding it to `CHAIN`, never as a second settings.json entry: the doctor's
`prompt-hooks` check fails on more than one command or a timeout under 20 s,
and `first-run.cjs` installs the dispatcher, not the individual guards.
`context-nudge.py` is retired; `context-nudge.cjs` is the same nudge in Node.

`wakeup-guard.cjs` counts consecutive machine wake-ups per session (a prompt
starting with `<task-notification>`, or any `source` outside user/sdk; a human
prompt resets the streak, state in `~/.claude/state/wakeups/`). From the third
one it injects: no "Waiting." text, end the turn silently if nothing changed,
TaskStop the Monitor and the stalled task if nothing progressed, re-arm only at
>= 1200 s. Why: a Monitor on "screenshots landing" fired once per PNG, 17
wake-ups in 45 min, each answered "Waiting.", 1.4M tokens on a workflow at 0 of
12. No override marker: it only speaks, it never blocks. `context-graph.cjs`
also skips `<task-notification>` prompts now. Probe:
`engine/hooks/tests/prompt-dispatch-probe.cjs`.

