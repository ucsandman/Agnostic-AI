## What

## Why

## Checklist

- [ ] `ruff check .` passes
- [ ] `python -m pytest tests/ -q` passes
- [ ] `npm test` passes (engine, sync, hook regression suites)
- [ ] `npm run docs:check` passes (run `npm run docs:targets` if you touched `core/templates/targets.json`)
- [ ] Bug fix includes a regression test that failed before the fix
- [ ] New env vars are in `.env.example`; new slash commands are in `docs/slash-commands.md`
- [ ] `CHANGELOG.md` updated under Unreleased
