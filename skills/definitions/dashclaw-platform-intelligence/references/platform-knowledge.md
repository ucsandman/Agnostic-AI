# DashClaw Platform Knowledge

## Table of Contents

- [What DashClaw Is](#what-dashclaw-is)
- [Deployment Modes](#deployment-modes)
- [Tech Stack](#tech-stack)
- [Auth Chain](#auth-chain)
- [ID Prefixes](#id-prefixes)
- [Architectural Guardrails](#architectural-guardrails)
- [Product Surfaces](#product-surfaces)
- [Key Reference Files](#key-reference-files)

## What DashClaw Is

AI agent decision infrastructure. A control plane for policy enforcement, decision recording,
assumption tracking, compliance mapping, security signals, messaging, evaluation scoring,
prompt management, user feedback, behavioral drift detection, learning analytics, scoring profiles, and operator
workflows. The governance layer for AI agent fleets.

**Zero-dependency philosophy**: All features work without any LLM API key by default. The only
optional LLM feature is the `llm_judge` scorer type in the Evaluation Framework.

## Deployment Modes

- **Marketing site** (`DASHCLAW_MODE=demo` + `NEXT_PUBLIC_DASHCLAW_MODE=demo`): dashclaw.io, fake data, no login. All writes return 403.
- **Self-hosted** (`DASHCLAW_MODE=self_host`, the default): real database, GitHub/Google OAuth, API key auth.

Both modes serve the same landing page. `/demo` sets a cookie and redirects to `/dashboard` with fixture data. `/dashboard` in self-host requires login.

## Tech Stack

- Next.js 15 (App Router), JavaScript, Tailwind CSS 3
- Postgres (TCP via `postgres`, serverless via `@neondatabase/serverless`)
- Auth: NextAuth v4 for UI (GitHub, Google, or OIDC), `x-api-key` header for agents/tools
- SDKs: Node (`sdk/dashclaw.js`, 177+ methods), Python (`sdk-python/dashclaw/client.py`, 177+ methods)
- Node SDK naming: camelCase. Python SDK naming: snake_case.

## Auth Chain

This is the full middleware pipeline -- critical for troubleshooting:

```
Client request hits middleware.js
  |
  +--> Strip x-org-id, x-org-role, x-user-id from inbound headers (ALWAYS)
  |
  +--> Rate limit check (local in-memory or Upstash Redis)
  |     Default: 100 req/min (prod), 1000 req/min (dev)
  |     Override: DASHCLAW_RATE_LIMIT_MAX, DASHCLAW_RATE_LIMIT_WINDOW_MS
  |     Dev bypass: DASHCLAW_DISABLE_RATE_LIMIT=true
  |
  +--> Body size check: 2MB max for POST/PUT/PATCH
  |
  +--> PUBLIC_ROUTES check:
  |     /api/health, /api/setup/status, /api/auth, /api/cron, /api/docs/raw, /api/prompts
  |     These skip auth entirely (but still rate-limited)
  |
  +--> Protected route auth:
        |
        +--> x-api-key header present?
        |     |
        |     +--> Fast path: timing-safe compare against DASHCLAW_API_KEY env var
        |     |     Success: inject x-org-id from DASHCLAW_API_KEY_ORG (default: org_default)
        |     |
        |     +--> Slow path: SHA-256 hash lookup in api_keys table
        |           Success: inject x-org-id + x-org-role from resolved key
        |           Failure: 401 Unauthorized
        |
        +--> No API key?
              |
              +--> Same-origin request (Sec-Fetch-Site: same-origin)?
              |     Resolve NextAuth session token --> orgId + role
              |     Supported: GitHub, Google, OIDC (Authentik, Keycloak, etc.)
              |     org_default users blocked from all APIs except onboarding
              |
              +--> Cross-origin without key --> 401 Unauthorized
```

## ID Prefixes

| Prefix | Entity |
|---|---|
| `sn_` | Snippets |
| `mt_` | Message threads |
| `ct_` | Context threads |
| `oc_live_` / `oc_test_` | API keys |
| `pi_` | Prompt injection scans |
| `org_` | Organizations |
| `gp_` | Guard policies |
| `es_` | Evaluation scorers |
| `sc_` | Evaluation scores |
| `er_` | Evaluation runs |
| `pt_` | Prompt templates |
| `pv_` | Prompt versions |
| `fb_` | Feedback entries |
| `ce_` | Compliance exports |
| `cs_` | Compliance schedules |
| `da_` | Drift alerts |
| `db_` | Drift baselines |
| `ds_` | Drift snapshots |
| `lv_` | Learning velocity records |
| `lc_` | Learning curve records |
| `sp_` | Scoring profiles |
| `sd_` | Scoring dimensions |
| `ps_` | Profile scores |
| `rt_` | Risk templates |

## Architectural Guardrails

1. **Route SQL guardrail**: No direct SQL in `app/api/**/route.js`. Use repositories in `app/lib/repositories/*.repository.js`. CI enforces via `npm run route-sql:check`.

2. **Real-time first**: DashClaw uses Server-Sent Events (SSE) via `/api/stream` to push updates instantly. Dashboard components use the `useRealtime` hook instead of polling.

3. **Default-deny**: All `/api/*` routes require auth unless listed in `PUBLIC_ROUTES` in middleware.js. New endpoints are protected by default.

4. **Org context injection**: Never accept `x-org-id`, `x-org-role`, `x-user-id` from clients. Middleware strips them and injects trusted values from API key resolution.

5. **Two separate thread systems**:
   - Context threads (`ct_*` via `/api/context/threads`) -- track reasoning and context
   - Message threads (`mt_*` via `/api/messages/threads`) -- inter-agent communication
   - These are NOT interchangeable.

6. **Zero-LLM default**: All features must work without any LLM API key. The only exception is the `llm_judge` scorer type, which gracefully degrades when no provider is configured.

7. **DB patterns**: TEXT primary keys with crypto-random prefixed IDs. `getSql()` for connection, `getOrgId()` for org scoping. Tagged template SQL via Neon's `postgres` driver.

## Product Surfaces

| Path | Purpose |
|---|---|
| `/` | Public landing site |
| `/demo` | Demo sandbox (fake data, read-only, no login) |
| `/mission-control` | Strategic fleet overview (reactive timeline + live log) |
| `/dashboard` | Draggable widget dashboard (real-time reactive cards) |
| `/workspace` | Per-agent workspace (digest, context, handoffs, snippets, preferences, memory) |
| `/security` | Security dashboard (signals, guard decisions, findings) |
| `/routing` | Task routing (agent registry, task queue, health) |
| `/compliance` | Compliance mapping (framework controls, gap analysis, evidence, reports) |
| `/compliance/exports` | Compliance export generation, scheduling, downloads |
| `/evaluations` | Evaluation framework (scorers, scores, runs, quality tracking) |
| `/prompts` | Prompt registry (templates, versions, rendering, usage stats) |
| `/feedback` | User feedback (ratings, sentiment, auto-tagging, resolution) |
| `/drift` | Drift detection (baselines, alerts, severity, trends) |
| `/learning` | Learning loop (episodes, recommendations) |
| `/learning/analytics` |
| `/scoring` | Learning analytics (velocity, maturity, curves, summary) |

## Key Reference Files

When you need current data from the codebase, read these:

| What | File |
|---|---|
| Full route inventory | `docs/api-inventory.json` |
| OpenAPI spec (stable) | `docs/openapi/critical-stable.openapi.json` |
| SDK parity matrix | `docs/sdk-parity.md` |
| Node SDK source | `sdk/dashclaw.js` |
| Python SDK source | `sdk-python/dashclaw/client.py` |
| Middleware (auth chain) | `middleware.js` |
| Demo fixtures | `app/lib/demo/demoFixtures.js` |
| Repository modules | `app/lib/repositories/*.repository.js` |
| Client setup guide | `docs/client-setup-guide.md` |
| Agent bootstrap guide | `docs/agent-bootstrap.md` |
| Project architecture | `PROJECT_DETAILS.md` |
| Cross-SDK test harness | `docs/sdk-critical-contract-harness.json` |
| Eval engine | `app/lib/eval.js` |
| Prompt engine | `app/lib/prompt.js` |
| Feedback engine | `app/lib/feedback.js` |
| Compliance exporter | `app/lib/compliance/exporter.js` |
| Drift engine | `app/lib/drift.js` |
| Learning analytics | `app/lib/learningAnalytics.js` |
| Scoring profiles engine | `app/lib/scoringProfiles.js` |
| LLM abstraction (optional) | `app/lib/llm.js` |
