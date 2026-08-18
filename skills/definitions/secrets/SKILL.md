---
name: secrets
description: Fill a repo's .env from the machine's credential stores without ever reading or printing a secret value. Use when the user says "/secrets", "fill in the .env", "get the keys", "wire up the credentials", "pull the secrets from offlocal", or when launch.py / a dev server refuses to start because keys are still on example values.
---

# secrets

Copies real credentials into the current repo's `.env` by matching key names against
`~/.claude/.secrets.env` and the offlocal MCP's own env file, then proves each value
against a live API before writing it.

**You never read either source file.** The script matches names and moves values.
The only thing that reaches your context is the key name, a short non-private prefix,
a length, and a validation status.

## Run it

```
node ~/.claude/skills/secrets/fill-env.cjs
```

From the repo root. Flags: `--dir <repo>`, `--dry-run`, `--force` (also replace values
that already look real), `--source <path>` (extra store, takes precedence).

Exits non-zero if any candidate was rejected. Backs up to `.env.bak` before writing.

## What it does

1. Creates `.env` from `.env.example` if absent.
2. Picks the keys still on their example value (or matching a placeholder pattern).
3. Resolves each from the stores, first match wins, with an alias table for keys spelled
   differently in a store.
4. Derives the Clerk publishable key from the secret key when only the secret is stored.
5. **Validates before writing**: a live API probe where one exists, a format check
   otherwise. A rejected value never lands in `.env`.
6. Prints a table and lists the keys no store has.

Step 5 is the point. `offlocal doctor` reports a credential as "set" when the value is
literally `twilio_placeholder`; only a real request tells you it is junk.

## What a probe cannot tell you

A probe proves the key **works**. It cannot prove the key is **this product's**. A shared
credential store holds one `CLERK_SECRET_KEY`, one `STRIPE_SECRET_KEY`, one
`RESEND_API_KEY` — and they belong to whichever product got there first. In 2026-08 that
wired seentoit to callclaw's Clerk instance: valid key, HTTP 200, wrong tenant. Nobody
noticed until the hosted sign-in page rendered "Sign in to callclaw".

So for any credential that identifies a tenant rather than an account, check the identity
the provider reports back, not just the status code:

- Clerk: load the sign-in page, or `GET /v1/instance` — whose application is it?
- Stripe: `GET /v1/account` — which business name?
- Twilio: `GET /Accounts/{sid}.json` — which `friendly_name`?

Say which product a key belongs to in the report. "Valid" on its own is not the answer.

## Reporting back

Give the user the table, then the gaps split into two lists:

- **needs a decision** (which Neon project, which domain) — ask, don't guess
- **needs a dashboard visit** (webhook signing secrets, OAuth redirect allowlists) — say
  which dashboard

Values generated per-repo (encryption keys, cron secrets) are usually already handled by
the repo's own bootstrap script. Check before offering to generate them.

## Rules

- Never `Read` `.secrets.env` or the offlocal env file. Not once, not to "check the format".
- Never echo a secret into chat, a commit, a log, or a file the script did not write.
- `NEXT_PUBLIC_*` and `*_PUBLISHABLE_KEY` are public and safe to print in full.
- When writing scripts that touch `.env`, build lines with `k + '=' + v`. The secret-scan
  hook blocks a literal `NAME=${expr}` template as a hardcoded secret.
