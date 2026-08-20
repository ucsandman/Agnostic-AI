# Decisions

Durable architecture and product decisions, newest first. One entry per
decision: what, why, what it rules out.

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

`setup.py` removed. Dependencies live in `pyproject.toml` (mirrored in
`requirements.txt` for plain `pip install -r`), dev tools in the `dev` extra,
ruff and pytest config alongside. The npm package is `private`; it exists for
scripts only and is never published.

## 2026-08-20 — Generated runtime state is not tracked

`storage/` holds only `.gitkeep`. Manifests, prune reports and tombstones are
rebuilt by the engines on each machine; tracking them made a clean clone
describe files that did not exist there.
