# Decision: Repeat-tool-call guard

Status: implemented

## Problem

A model stuck in a loop re-issues the same tool call with identical arguments —
re-running a failing test, re-reading an unchanged file, polling a command that
already answered. Each round trip costs tokens and wall clock and adds no
information. Nothing in the harness noticed.

`CLAUDE.md` carried the rule as prose: *"Guard against no-op retries. Before
retrying, check the state delta. If the last action changed nothing, force a
different approach."* That is exactly the kind of rule a model reads at session
start and does not apply at turn forty, because the loop it is in is the
condition that stops it noticing.

## Decision

`hooks/repeat-tool-guard.cjs` runs on `PostToolUse` and `PostToolUseFailure`.
It counts consecutive calls to the same tool with identical canonical arguments
and injects an escalating reminder as `additionalContext` at thresholds 3, 5,
and 8. It never blocks, delays, or rewrites a call.

Detection rules:

- The chain key is `(tool name, canonical arguments)`. Canonicalisation is a
  deep key sort then stringify, so argument order cannot hide a repeat.
- **Transparent tools** (`TodoWrite`, `TaskUpdate`, `TaskCreate`,
  `ScheduleWakeup`) neither increment nor reset the chain. Without this,
  `grep X → TodoWrite → grep X` reads as two unrelated calls and a real loop
  launders itself through its own note-taking.
- **Exempt tools** (`TaskOutput`, `TaskGet`, `TaskList`, `Monitor`,
  `AskUserQuestion`) are ignored outright — repeating them identically is what
  they are for.
- A `UserPromptSubmit` registration passes `--reset` and clears the chain: a
  user interjection changes the context, so repetition across it is not a loop.

The first threshold gets a short nudge. Later thresholds get the detailed form
naming the tool, the count, and the arguments, and demanding the model state
what it expects to be different before calling again.

State is one JSON file per session under the OS temp directory, expiring after
six hours. `REPEAT_GUARD_OFF=1` disables it; `REPEAT_GUARD_THRESHOLDS` overrides
the thresholds.

Eleven probes in `hooks/tests/repeat-guard-probe.cjs` cover counting, reset,
canonicalisation, transparency, exemption, escalation, the off switch, and
session isolation.

## Alternatives considered

**Register on `PreToolUse` and block at a high threshold.** Rejected. A blocked
call punishes legitimate identical repeats — polling a long-running process,
re-reading a file the agent expects to have changed — and the guard cannot tell
those apart. An advisory reminder leaves the model in control, which is the
right default for a heuristic. Revisit with evidence.

**Count in `PreToolUse` instead of `PostToolUse`.** Rejected: post-execute also
fires for calls that failed, and a model hammering a failing command is exactly
the loop worth breaking. Registering on `PostToolUseFailure` as well as
`PostToolUse` covers strictly more attempts than the pre-execute seam.

**Fuzzy matching on near-identical arguments** (normalised paths, similar
commands). Rejected: exact match after canonicalisation is cheap, deterministic,
and explainable in the reminder text. Similarity thresholds invite false
positives and need evidence before earning the complexity.

**Leave it as a prose rule in `CLAUDE.md` and rely on the model.** Rejected —
this is the status quo that failed. It also costs words in the highest-priced
document in the harness for a rule nothing enforced.

**In-memory state.** Rejected: hooks are separate short-lived processes, so
there is no memory to hold. A temp file keyed by session is the cheapest thing
that survives between calls.

## Consequences

- Idempotent polling patterns not on the exempt list still get nudged past
  threshold 3. The pressure valves are the exempt set and `REPEAT_GUARD_OFF`.
- Each trigger costs reminder tokens on the next request. Thresholds bound how
  often that happens to at most three times per chain.
- Chain state is per session and expires after six hours. A loop spanning a
  resume starts counting fresh — accepted; this is a nudge, not an audit trail.
- The `CLAUDE.md` prose rule stays, shortened to one line pointing here. The
  hook is the enforcement; the line is the explanation for a model that hits a
  reminder and wants to know what produced it.
