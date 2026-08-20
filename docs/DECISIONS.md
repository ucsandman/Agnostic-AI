# Decisions

Durable architecture and product decisions, newest first. One entry per
decision: what, why, what it rules out.

## 2026-08-20 — A tool the model cannot use successfully is removed, not kept

`ask_question` (no input channel), `generate_artifact` (a `write_file` with a
worse path) and `manage_subagents` (`kill` unimplemented) were re-sent as JSON
schemas on every completion and could never succeed. The rule: every tool in
`ToolRegistry` must be able to return a real result in the default UI, or it
goes. Half-built capabilities live behind a slash command or not at all — the
model's tool list is not a roadmap. Same rule for modules: the MCP stub, the
fake `TaskManager`, `planner.py` and the Python harvester were deleted rather
than whitelisted.

## 2026-08-20 — A turn can always be cancelled and history stays well-formed

`AgentLoop.cancel_event` is the one cancellation primitive: checked between
steps and before each dispatch, handed to `ToolRegistry` so `run_command` can
kill its child. Whatever ends a turn early — Esc, an exception, Ctrl+C — every
pending `tool_call` gets a synthetic result (`[cancelled by user]` /
`[aborted]`) before the lock is released, because an OpenAI-style backend
rejects a transcript with an unanswered tool call forever after. New
background work in the loop must honour the event and must not append an
assistant tool-call message it cannot answer.

## 2026-08-20 — Compact prompt mode shortens the rules; it never replaces them

Small-context local models get the compiled `global-rules.md` clipped at a
line boundary (~4 KB) under the harness badge, followed by the workspace's own
`AGENTS.md`/`CLAUDE.md` if it fits. A hand-written summary beside the real
rules drifted silently and made the repo's headline claim false by default;
that shape is ruled out.

## 2026-08-20 — Default ports are a starting guess, never an assumption

Every local server here (`tools/dashboard` 7842, `agent/web/server.py` 7843,
`tools/recall` 7844, `tools/sync/parity` 7845) shares a developer machine with
other projects. So a default port is where a server starts looking, not where
it must land: on collision it walks up to the next free port (10 tries) and
reports the URL it actually bound. Reusing an occupied port is allowed only
after confirming the occupant is the same program — the dashboard identifies
itself with an `x-agnostic-dashboard` response header. Callers print the
returned URL; no launcher, doc, or test hardcodes one it did not bind.

## 2026-08-20 — Mutating HTTP routes need a token and a loopback origin

All local UIs (`tools/dashboard`, `tools/sync/parity`, `agent/web/server.py`)
bind `127.0.0.1`, but loopback binding does not stop a page in another tab from
POSTing to them (a `text/plain` body is a CORS simple request). Every mutating
route is therefore `POST`, requires a per-process random token injected into
the served page, and rejects a non-loopback `Origin`/`Referer`. GET routes stay
open; they are read-only and the data is local. A new route that writes
anything goes behind `authorized()` or it does not merge.

## 2026-08-20 — Dashboard shows only real data

The governance view once seeded itself with fabricated events ("zero secret
leaks detected") to look alive. Removed, and not coming back: a human-facing
safety surface may show an empty state, never an invented result. Every
verdict carries the count of things it processed.

## 2026-08-20 — One guard, read from `core/safety/guards.json`

The Python guard, the Node hooks and the dashboard simulator all evaluate the
same file. No pattern list lives anywhere else; the simulator calls
`calculateLocalRisk` from `engine/hooks/dashclaw-guard.cjs` rather than
reimplementing it.

## 2026-08-20 — Generated docs for generated facts

`docs/targets.md` is rendered from `core/templates/targets.json` by
`engine/docs/targets-doc.cjs` and CI fails if it is stale. The hand-written
client table in the old README drifted within days; anything that is a
projection of config gets generated.

## 2026-08-20 — `pyproject.toml` is the Python source of truth

`setup.py` removed. Dependencies live in `pyproject.toml` (`requirements.txt`
is a one-line `-e .` shim so `pip install -r` still works), dev tools in the
`dev` extra,
ruff and pytest config alongside. The npm package is `private`; it exists for
scripts only and is never published.

## 2026-08-20 — Generated runtime state is not tracked

`storage/` holds only `.gitkeep`. Manifests, prune reports and tombstones are
rebuilt by the engines on each machine; tracking them made a clean clone
describe files that did not exist there.
