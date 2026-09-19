# Harness parity across clients

One harness, captured from Claude Code, applied to every other installed client (Codex CLI, Gemini CLI, Antigravity, Cursor and the rest of the registry in `core/templates/targets.json`). The port is the engine; nothing is hand-copied.

## The three commands

- `npm run status` shows every client against the source harness: which components are current, stale or deliberately absent.
- `npm run port` captures the Claude home and writes rules, hooks, skills, agents, commands, MCP servers and permissions to each client. The daily `HarnessParitySync` job (`jobs/port-daily.ps1`) runs it every morning after the nightly meditation promotes new rules.
- `node engine/harness/cli.cjs explain --to <target>` prints every item the port dropped for that client and why. An absence in a generated file is a config question, not a bug, until `explain` says otherwise.

## What is deliberately not ported

`core/port.json` is the policy. `rules.dropSectionsForTargets` removes the Claude-Code-specific sections (the model ladder, agent-model-guard, the Workflow tool) from every other client; hooks that only make sense under Claude Code's event model are listed there too. Change the policy, not the generated file.

## Hooks: dialect and trust

Codex runs the same guard scripts through the adapters in `engine/hooks/adapters/` (see `docs/codex-adapters.md`): the adapter translates the client's payload into the Claude hook protocol, runs the guard, and translates the verdict back. The trust list a client needs to run those hooks is written by the port inside marked regions of the client's config, so a hand edit outside the region survives.

## Verifying the port

```
npm run status                                      # every client, every component
node engine/hooks/tests/guard-probe.cjs             # the shared guards still block AND pass
node engine/hooks/tests/codex-delegate-guard-probe.cjs   # the Codex dialect still blocks AND pass
```

A guard that stopped firing is invisible otherwise: the daily job asserts the probe's positive result, not the absence of a failure line.

## History

The first port (September 2026) was a personal script with its own generated-file headers and a Gemini shim; the engine replaced both on 2026-09-06 and the shim was retired on 2026-09-19 when the harness moved into this repository. The design notes from that period (hook dialects, tool-name mapping, Windows gotchas) live on in `docs/codex-adapters.md` and `docs/windows-gotchas.md`.
