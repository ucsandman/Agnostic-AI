---
name: secrets-non-negotiable
description: The secrets rule at the moment it matters: a command or edit that names an env file, a secrets file or a key. Loads before the call.
context:
  triggers:
    commands: [.env, secrets, .credentials, api_key, apikey, token=]
    paths: ["**/.env", "**/.env.*", "**/*secrets*", "**/.credentials.json", "**/keys/**"]
  priority: 90
  stale_after: 365d
---
# Secrets (loaded on demand)

Never open or read a secret env file (`.secrets.env`, `.env`). Wire tools to read them: on this machine Bash gets them through `BASH_ENV` (`~/.claude/load-secrets.sh`); the PowerShell tool runs `-NoProfile` and does not. Every new env var goes in `.env.example` with a placeholder; `.env` stays gitignored. Verify a credential by presence and length only (`[ -n "$VAR" ]`, `${#VAR}`) and by a read-only authenticated call that prints the HTTP status, never the value. Nothing that leaves the repo or this machine carries a key, a token or a local path.
