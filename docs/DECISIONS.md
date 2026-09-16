# Decisions

Durable architecture and product decisions, newest first. One entry per
decision: what, why, what it rules out.

## 2026-09-16 — The port engine is a library first; the repo's CLI is one caller

`engine/harness/index.cjs` is the entry a host product requires. Everything the
engine used to read from this repo (the ownership mark, the secret patterns,
the hook shim path, the import roots, the target registry, the port policy) is
an option with the repo's file as its default, so the same bytes run inside a
zero-dependency ESM host (Leg, github.com/ucsandman/legcli, vendors them
verbatim and pins their hashes). Why: a host that patched a copy would drift
from this repo forever; a host that can pass options needs no patch. Rules
out: converting the engine to ESM for style (the dynamic adapter loading and
every regression would have been rewritten for nothing), and a package
dependency (the host ships zero). Secret scanning now covers the whole
bundle, not the two env maps: free text is redacted, an unsafe handler or
server is dropped with a warning, and `save()` refuses what remains; a prune
takes the same backup an overwrite takes; the Windows junction fallback
refuses a path with a cmd metacharacter instead of quoting it.

## 2026-09-06 — The client you use is the source of truth; the port is the only writer of every other client

A harness lives in the client the operator actually works in (Claude Code
today, Codex CLI tomorrow). `capture` reads it into a client-neutral bundle;
`apply` renders that bundle into every other installed client. Each generated
file has exactly one writer: a header marks the port's own files, a marked
region or per-key ownership marks its entries inside user-owned files, and
everything else is preserved byte for byte. Two writers for one file (the old
rules-only sync and a personal harness-sync script) ping-ponged the Codex
agreement in September 2026; that shape is ruled out. Authoring rules inside
this repo stays supported as a way to feed the primary client, never as a
second writer of the targets.

## 2026-09-06 — Hooks are ported by reference, never by copy

The same guard scripts run in every client. Where a client speaks another hook
dialect (Cursor, Gemini CLI, Antigravity) the port wraps the call in
`engine/hooks/shim.cjs`, which translates payload and decision. A second copy of
a guard per client drifts within weeks (the hand-written Codex files of June
2026 ran a three-month-old agreement); a shim is one file to fix.

## 2026-09-06 — Every drop is explained, in data

What is not ported is policy, not code: `core/port.json` lists each excluded
hook, skill and MCP server with a reason, and every run prints what it dropped.
A silent omission is indistinguishable from a bug; a hardcoded exclusion list is
one machine's opinion shipped as everyone's.

## 2026-09-06 — The coding agent is a separate product

The Python terminal agent moved to its own repository (agnostic-agent) with its
history. One repo carried two products with one README, one CI matrix and two
toolchains; a harness porter that needs `pip install` to run its tests is
harder to adopt than one that needs Node alone.

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

## 2026-08-20 — Generated runtime state is not tracked

`storage/` holds only `.gitkeep`. Manifests, prune reports and tombstones are
rebuilt by the engines on each machine; tracking them made a clean clone
describe files that did not exist there.

