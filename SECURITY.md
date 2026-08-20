# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 1.2.x | Yes |
| < 1.2 | No |

## Reporting a vulnerability

Please do not open a public issue for security problems. Use GitHub's private
vulnerability reporting on this repository ("Security" tab, "Report a
vulnerability"). You will get an acknowledgement within 7 days and a fix or a
written plan within 30 days for confirmed reports.

## What is in scope

- The safety guard: `core/safety/guards.json`, `agent/governance/guard.py`,
  `engine/hooks/secret-guard.cjs`, `engine/hooks/dashclaw-guard.cjs`. A way to
  read a secret path, run a hard-stop command without approval, or turn a
  fail-closed path into an allow is a vulnerability.
- The hook protocol shims in `engine/hooks/universal-adapter.cjs` (payload
  injection that changes a verdict).
- The local web servers: `tools/dashboard/dashboard.cjs`, `tools/sync/parity.cjs`,
  `tools/recall/recall.cjs`, `agent/web/server.py`. They bind `127.0.0.1` only;
  mutating routes require a per-process token and a loopback `Origin`. Anything
  that lets another origin, or another local user, trigger a write is in scope.
- The sync engine writing outside the targets declared in
  `core/templates/targets.json`.

## What the guard is and is not

The guard is defense in depth for an LLM that is allowed to run shell commands.
It blocks known-dangerous patterns and secret paths and routes hard stops to a
human. It is **not** a sandbox: a model that is given `trust-all` and an
unrestricted shell can still do damage the pattern list does not describe. Run
the agent in a workspace you can restore from git, and keep credentials out of
the working tree.

## Secrets

No secret is ever read by the harness. `.env` is gitignored and is never loaded
automatically. If you believe a credential was committed to this repository's
history, rotate it first, then report it.
