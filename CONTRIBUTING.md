# Contributing

Thanks for taking the time. This page is the short version of how the repo is
laid out and what a change needs before it merges.

## Setup

```bash
git clone https://github.com/ucsandman/agnostic-harness.git
cd agnostic-harness
pip install -e ".[dev]"     # agent + pytest + ruff (Node 18+ is also required; no npm install step)
```

There are no npm dependencies. Every `.cjs` engine runs on Node's standard
library.

## Run everything

```bash
ruff check .                       # lint
python -m pytest tests/ -q         # agent tests
npm test                           # engine suite + sync + hook regression suites
npm run docs:check                 # generated docs are current
```

CI runs exactly these on Ubuntu (Python 3.9 and 3.12) and on Windows (3.12).
All four must pass on every leg.

## Where things live

| Area | Path | Notes |
|---|---|---|
| Rules (single source of truth) | `core/rules/global-rules.md` | Everything else is compiled from here. |
| Safety policy | `core/safety/guards.json` | The only place patterns live. Never hardcode a pattern in a guard, hook, or UI. |
| Client targets | `core/templates/targets.json` | Add a client here; never hardcode a client path elsewhere. Then `npm run docs:targets`. |
| Sync / hooks / distill engines | `engine/` | Zero-dependency Node. |
| Coding agent | `agent/` | Python. `agent/tui.py` is the default entry point, `agent/cli.py` the legacy shell. |
| Human surfaces | `tools/` | Local web UIs, `127.0.0.1` only. |
| Tests | `tests/` (pytest), `engine/tests/` (Node) | |

## Rules for a change

- Keep the diff to the request. Do not reformat or refactor adjacent code.
- A bug fix comes with a regression test that was seen failing before the fix.
- A new slash command gets a handler in `agent/tui_commands.py` (and `agent/cli.py` if
  it should work in the legacy shell), an entry in `SLASH_COMMANDS`
  (`agent/ui_common.py`), a line in `/help`, and a row in `docs/slash-commands.md`.
- A new env var goes in `.env.example` with a comment.
- A new mutating HTTP route must be `POST` and go through the server's
  `authorized()` check.
- Anything that changes what the guard allows needs a test in
  `engine/tests/reg-hooks.cjs` or `tests/test_guard_safety.py`.
- Update `CHANGELOG.md` under "Unreleased".

## Commit messages

Conventional commits: `feat(agent): ...`, `fix(sync): ...`, `docs: ...`,
`test: ...`, `chore: ...`.

## Platform note

The project is developed on Windows. Skill directories are linked with
`mklink /J` on Windows and symlinks elsewhere, and the scheduled jobs in `jobs/`
are PowerShell. If you hit a POSIX-only gap, a fix with a test is very welcome.
