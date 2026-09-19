# Decision: wire-dark check and gate freeze

Status: implemented

## Problem

Two failure shapes had prose rules and no mechanism.

An agent adds a function and its unit test in one change. The test calls the
function directly, everything is green, and no real entrypoint ever reaches the
new code. Rule 5 of the working agreement (a feature nobody can reach is not
shipped) and the "wire it in the same change" dispatch prose only lower the
rate. ELAI's finish sweep hit this six times in one stretch after the prose was
added, then eliminated it with a deterministic checker over the changeset.

Every guard in this harness is a file under `~/.claude` that any session may
edit. The Fable delegate guard makes those writes free by design, so a session
working on a project that hits a guard can soften the guard in passing, and
nothing records that it happened. Guard-canary proves a guard fires. It does
not notice that the guard was changed first.

## Decision

**Wire-dark check.** `tools/wiredark/wiredark.cjs` reads the staged diff, finds
every exported symbol added by the change (JS/TS `export`, CommonJS
`exports.x`, Python top-level `def`/`class` without a leading underscore), and
searches the index for a production reference: a non-test, non-import line
outside the defining file. A name already declared in HEAD's version of the file
is an edit, not a new symbol. Verdicts: WIRED, REEXPORTED (only a barrel reaches
it), INTERNAL (same-file caller), REGISTERED-DARK (`// WIRE-DARK[<why>]` within
three lines above), DARK-TYPE, and DARK, which blocks. Framework entrypoints
(route handlers, `middleware`, `main`, config exports, files under `app/`,
`pages/`, `api/`) are skipped because the runtime, not the repo, calls them.
The global pre-commit runs it in every repo whenever a code file is staged. The
verdict line always carries the scanned volume. Exit 2 when the scan itself
cannot run. Off for one shell: `WIREDARK=off`.

Replayed over the last six commits of declick, DashClaw and creds before wiring:
thirteen new exports, twelve WIRED, one INTERNAL warn, zero false blocks.

**Gate freeze.** `tools/gates/gate-manifest.json` names the frozen fileset: the
hooks, the pre-commit chain, the gates runner, the wire-dark checker, the hooks
section of `settings.json`, and the agnostic-ai and DashClaw guard scripts.
`tools/gates/freeze.cjs` hashes them into `gate-manifest.lock.json`. Two
enforcement points:

- `hooks/gate-freeze.cjs` (PreToolUse on edits and shells) denies a write to a
  frozen file, and the relock itself, when the session's cwd is outside every
  harness root (`~/.claude`, agnostic-ai, DashClaw). Harness sessions edit
  guards freely; project sessions do not. `# GATE_OK: <why>` overrides one
  shell command, logged; `GATE_FREEZE=off` for a session.
- The `gate-freeze` check in `gates.cjs` fails on any hash drift. Guard-canary
  runs it at session start and the harness pre-commit runs it on every commit,
  so an edit the hook could not see (Codex, a hand edit, the guard off) surfaces
  the next session and blocks the next harness commit until someone reviews it
  and relocks with `node tools/gates/gates.cjs --lock`. Relocks are logged.

Probes: `hooks/tests/wiredark-probe.cjs` (14 cases in a scratch git repo) and
`hooks/tests/gate-freeze-probe.cjs` (20 cases, including a planted unlocked
guard file that the hash check must catch). Both were watched failing first.

## Alternatives considered

**Block guard edits from every session, harness roots included.** Rejected: the
harness is edited from `~/.claude` sessions daily, and a guard that fights its
own maintenance gets turned off. The cwd rule keeps the common path free and
puts the hash check behind it for everything the hook cannot see.

**Freeze the whole `settings.json`.** Rejected: permission allow-lists change in
ordinary sessions. Hashing only the `hooks` key means a permissions edit never
trips the gate and a hook edit always does.

**Sound reachability (an import graph, TypeScript program, or SCIP) for the
wire-dark check.** Rejected for now: a word-boundary grep over the index is
necessary-not-sufficient, which is the same honesty ELAI's checker carried, and
it ran clean on real history. The marker escape and the exit-2 fail-closed path
cost less than a resolver that has to understand five module systems.

**Take the rest of ELAI's `.claude/` (proof spine, traced-test assert, plan
gates, 40 agent files).** Rejected: the author's own postmortem names the
subsystem-per-problem accretion as what killed the project.

## Consequences

A commit that adds an export nobody calls stops at pre-commit in every repo, and
the fix is either the caller or a visible marker in the diff. A project session
that tries to edit a guard is told to open a harness session instead. A guard
changed by any other route is named at the next session start and blocks the
next harness commit until it is relocked. Editing a hook from `~/.claude` now
ends with `node tools/gates/gates.cjs --lock` and staging the lock file. The
freeze list is itself frozen, so removing a file from it is a drift finding.
