# Contributing

Thanks for taking the time. This page is the short version of how the repo is
laid out and what a change needs before it merges.

## Setup

```bash
git clone https://github.com/ucsandman/Agnostic-AI.git
cd Agnostic-AI
node --version     # 18 or newer; there is no npm install step
```

There are no npm dependencies. Every `.cjs` engine runs on Node's standard
library.

## Run everything

```bash
npm test                 # engine suite + sync, hook, wire-protocol and port regressions
npm run docs:check       # generated docs are current
```

CI runs exactly these on Ubuntu (Node 18 and 22) and on Windows (Node 22).
All must pass on every leg. Nothing in the test suite touches your home
directory: every test builds a throwaway home under the OS temp dir.

## Where things live

| Area | Path | Notes |
|---|---|---|
| Port engine | `engine/harness/` | `capture` reads a client, `apply` writes the others. Contract: `engine/harness/README.md`. |
| Source adapters | `engine/harness/sources/<client>.cjs` | One per client that can be the source of truth. |
| Target adapters | `engine/harness/targets/<client>.cjs` | One per client with its own hook, agent or MCP dialect; `generic.cjs` for the rest. |
| Client registry | `core/templates/targets.json` | Every client path lives here. Then `npm run docs:targets`. |
| Port policy | `core/port.json` | Source, targets, exclusions with reasons, model ladders. |
| Safety policy | `core/safety/guards.json` | The only place patterns live. Never hardcode a pattern in a guard, hook, or UI. |
| Authored rules (optional) | `core/rules/global-rules.md` | Compiled into the primary client by `npm run sync`. |
| Hooks and shims | `engine/hooks/` | Guards, the universal payload adapter, the dialect shim. |
| Harvest / distill | `engine/harvest/`, `engine/distill/`, `engine/ingest/` | The rule-learning loop. |
| Human surfaces | `tools/` | Local web UIs, `127.0.0.1` only. |
| Tests | `engine/tests/` | `run-all.cjs` plus one `reg-*.cjs` per regression area. |

## Rules for a change

- Keep the diff to the request. Do not reformat or refactor adjacent code.
- A bug fix comes with a regression test that was seen failing before the fix.
- A new client is a registry entry plus, if it has its own dialect, an adapter
  that follows `engine/harness/README.md`. Every item an adapter cannot port
  lands in `dropped` with a reason a stranger understands.
- Nothing machine-specific in code: paths, user names, hook names and model
  slugs come from the bundle, `core/port.json` or the registry.
- A new env var goes in `.env.example` with a comment.
- A new mutating HTTP route must be `POST` and go through the server's
  `authorized()` check.
- Anything that changes what the guard allows needs a test in
  `engine/tests/reg-hooks.cjs`.
- Update `CHANGELOG.md` under "Unreleased".

## Commit messages

Conventional commits: `feat(port): ...`, `fix(codex): ...`, `docs: ...`,
`test: ...`, `chore: ...`.

## Platform note

The project is developed on Windows. Skill directories are linked with
junctions on Windows and symlinks elsewhere, and the scheduled jobs in `jobs/`
are PowerShell. If you hit a POSIX-only gap, a fix with a test is very welcome.
