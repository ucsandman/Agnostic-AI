## What

## Why

## Checklist

- [ ] `npm test` passes (engine, sync, hook, wire-protocol and port regression suites)
- [ ] `npm run docs:check` passes (run `npm run docs:targets` if you touched `core/templates/targets.json`)
- [ ] Bug fix includes a regression test that failed before the fix
- [ ] A new client is a registry entry plus, if it has its own dialect, an adapter per `engine/harness/README.md`; every unported item lands in `dropped` with a reason
- [ ] Nothing machine-specific in code (paths, user names, hook names, model slugs come from the bundle, `core/port.json` or the registry)
- [ ] New env vars are in `.env.example`
- [ ] `CHANGELOG.md` updated under Unreleased
