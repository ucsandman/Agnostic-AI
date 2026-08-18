# DashClaw Troubleshooting Guide

## Table of Contents

- [Error: 401 Unauthorized](#error-401-unauthorized)
- [Error: 403 Forbidden](#error-403-forbidden)
- [Error: 429 Rate Limited](#error-429-rate-limited)
- [Error: 503 Server Misconfigured](#error-503-server-misconfigured)
- [Error: redirect_uri Not Associated](#error-redirect_uri-not-associated)
- [Actions Not Appearing in Dashboard](#actions-not-appearing-in-dashboard)
- [Agent Pairing Fails](#agent-pairing-fails)
- [Guard Blocks Unexpectedly](#guard-blocks-unexpectedly)
- [Common Gotchas](#common-gotchas)
- [General Diagnostic Approach](#general-diagnostic-approach)
- [Companion Diagnostic Scripts](#companion-diagnostic-scripts)

## Error: 401 Unauthorized

**"Unauthorized - Invalid or missing API key"**

1. Check `x-api-key` header is being sent (not query params -- those leak in logs)
2. Check `DASHCLAW_API_KEY` is set in the server's `.env`
3. If using multi-org keys, verify the key hash exists in `api_keys` table and is not revoked
4. If using session auth (dashboard), check `Sec-Fetch-Site` is `same-origin`
5. Cross-origin requests without an API key always get 401

## Error: 403 Forbidden

Multiple causes -- check the error message:

**"Demo mode: write APIs are disabled"**
- You are hitting the demo instance (`DASHCLAW_MODE=demo`)
- Writes are blocked in demo mode by design
- Fix: Use your self-hosted instance URL instead

**"Forbidden - readonly API key"**
- The API key has `role=readonly` in the `api_keys` table
- Fix: Use an admin-role API key for write operations

**"Forbidden - Complete onboarding to access this resource"**
- User is on `org_default`, which is blocked from all APIs except onboarding
- Fix: Complete workspace setup at `/setup` on the dashboard
- Response includes `{ needsOnboarding: true }` for programmatic detection

**"Guard blocked action"**
- Behavior guard policy matched and returned `decision: block`
- Check `decision.reasons` and `decision.matched_policies` in the response
- Fix: Adjust the policy, lower the risk score, or change the action type

## Error: 429 Rate Limited

**"Rate limit exceeded. Please slow down."**

Defaults:
- Production: 100 requests per minute
- Development: 1000 requests per minute

Fixes:
- Wait 60 seconds (Retry-After header is set)
- Increase: `DASHCLAW_RATE_LIMIT_MAX=500` in server `.env`
- Adjust window: `DASHCLAW_RATE_LIMIT_WINDOW_MS=120000` (2 minutes)
- Dev bypass: `DASHCLAW_DISABLE_RATE_LIMIT=true`

For agents that batch operations, implement client-side rate limiting or increase the server limit.

## Error: 503 Server Misconfigured

**"Server misconfigured: set DASHCLAW_API_KEY to protect /api/* endpoints"**
- Production mode but no `DASHCLAW_API_KEY` env var set
- Fix: Set `DASHCLAW_API_KEY` in server `.env`

**"DASHCLAW_API_KEY_ORG references org that does not exist"**
- The configured org ID doesn't exist in the `organizations` table
- Fix: Run migrations:
  ```bash
  node scripts/_run-with-env.mjs scripts/migrate-multi-tenant.mjs
  ```
- Or create the org: `POST /api/orgs` with admin key

## Error: redirect_uri Not Associated

OAuth callback URL missing from your provider app settings.

Add these callback URLs:
- **GitHub:** `http://localhost:3000/api/auth/callback/github`
- **Google:** `http://localhost:3000/api/auth/callback/google`

For production, replace `http://localhost:3000` with your deployed URL.

## Actions Not Appearing in Dashboard

1. **Org mismatch**: The agent's API key must resolve to the same org as the dashboard user. Check which org the key maps to.
2. **Route handler check**: Verify `const orgId = request.headers.get('x-org-id')` is being used to scope queries.
3. **Demo mode confusion**: If `DASHCLAW_MODE=demo`, the dashboard shows fixture data, not real data.
4. Run the diagnostic script:
   ```bash
   node .claude/skills/dashclaw-platform-intelligence/scripts/diagnose.mjs \
     --base-url http://localhost:3000 --api-key $DASHCLAW_API_KEY
   ```

## Agent Pairing Fails

The agent pairing flow has several gotchas:

1. **Canonical JSON ordering matters** for signature verification. Use `JSON.stringify` with sorted keys.
2. **Middleware strips client-sent org headers.** The pairing request goes through without org context initially; an admin must approve.
3. **Full flow:**
   - Generate RSA keypair
   - `POST /api/pairings` with public key PEM
   - Operator approves at the approval URL (returned in response)
   - Agent polls `GET /api/pairings/{id}` or uses `waitForPairing()`
4. If the admin key is wrong, the approval POST will 401.

## Guard Blocks Unexpectedly

1. Check which policies matched: look at `decision.matched_policies` in the guard response
2. Test the policy in isolation:
   ```javascript
   const result = await dc.testPolicy({
     policyId: 'pol_xxx',
     testInput: { actionType: 'your_type', riskScore: 50 }
   });
   ```
3. Check if `guardMode` is set to `enforce` vs `warn` in the SDK constructor
4. If using `DASHCLAW_GUARD_FALLBACK=block`, the guard fails closed when the LLM is unavailable

## Common Gotchas

1. **Client-sent org headers are stripped.** Middleware always removes `x-org-id`, `x-org-role`, `x-user-id` from inbound requests. Org context comes from API key resolution only.

2. **Two thread systems exist.** Context threads (`ct_*` via `/api/context/threads`) track reasoning. Message threads (`mt_*` via `/api/messages/threads`) are for communication. Not interchangeable.

3. **org_default trap.** New users land on `org_default` which is blocked from all APIs except onboarding. Must complete workspace setup first.

4. **API key shown once.** The onboarding key is displayed exactly once. If lost, generate a new one via `POST /api/keys` or the dashboard.

5. **Body size limit.** 2MB max for POST/PUT/PATCH. Large sync payloads should be chunked.

6. **HTTPS in production.** SDK warns if `baseUrl` is not HTTPS. API keys sent over HTTP are visible to network observers.

7. **Repository pattern enforced.** Never put SQL in route files. CI catches it via `npm run route-sql:check`.

8. **Demo writes always 403.** Even if you have a valid API key, `DASHCLAW_MODE=demo` blocks all writes.

9. **Agent signatures need canonical JSON.** Key ordering matters when signing payloads.

10. **Rate limiting is per-IP.** Multiple agents on the same machine share a rate limit bucket.

## General Diagnostic Approach

```
1. Check the HTTP status code and full error message
2. Map it to a section above
3. Check middleware.js for the exact condition producing that error
4. Check the route handler: app/api/<path>/route.js
5. Check the repository: app/lib/repositories/<domain>.repository.js
6. Check if migrations are needed (missing tables/columns)
7. Run the diagnose script for automated checks
```

## Companion Diagnostic Scripts

**Full validation:**
```bash
node .claude/skills/dashclaw-platform-intelligence/scripts/validate-integration.mjs \
  --base-url http://localhost:3000 --api-key $DASHCLAW_API_KEY --full
```

**Targeted diagnosis:**
```bash
node .claude/skills/dashclaw-platform-intelligence/scripts/diagnose.mjs \
  --base-url http://localhost:3000 --api-key $DASHCLAW_API_KEY \
  --error "403 Forbidden" --endpoint "/api/actions"
```

Both scripts support `--json` for machine-readable output.
