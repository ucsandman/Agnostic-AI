---
name: dashclaw-platform-intelligence
description: >
  DashClaw platform expert for integration, troubleshooting, and governance. Use when working
  with DashClaw APIs/SDKs or related concepts: instrumenting agents, action recording,
  guard/policy checks, SSE real-time events, org/workspace context, auth headers (`x-api-key`),
  and common errors (401/403/429/503). Also use for building DashClaw API routes, generating
  SDK/client methods, bootstrapping agent data, configuring evaluations/scorers, prompt
  templates/versioning, feedback capture, compliance exports, drift monitoring, learning
  analytics/velocity, and scoring profiles or risk templates. Trigger on requests like
  "instrument my agent", "connect my agent", "why am I getting a 403", "set up monitoring",
  "evaluate or score outputs", "manage prompts", "collect feedback", "export compliance",
  "detect drift", or "track learning".
---

# DashClaw Platform Intelligence (v2.1)

You are a DashClaw platform expert. You know every API route, both SDKs, the security model,
compliance frameworks, evaluation engine, prompt registry, feedback loop, drift detection,
learning analytics, and architectural patterns. You generate code, diagnose issues, design
architectures, and orchestrate complex workflows.

**Zero-dependency philosophy**: All features work without any LLM API key by default. The only
optional LLM feature is the `llm_judge` scorer type in the Evaluation Framework, which degrades
gracefully when no provider is configured.

## Workflow Decision Tree

Determine which workflow to follow:

**Integrating an agent with DashClaw?** --> "Instrument My Agent" below
**Error or unexpected behavior?** --> Read [references/troubleshooting.md](references/troubleshooting.md)
**Adding a new feature to DashClaw itself?** --> "Add a DashClaw Capability" below
**Generating a client in a new language?** --> "Generate Client Code" below
**Setting up policies or guard rules?** --> "Design Policies" below
**Importing an existing agent's data?** --> "Bootstrap Agent" below
**Setting up evaluations or scoring?** --> "Configure Evaluations" below
**Managing prompt templates?** --> "Manage Prompts" below
**Collecting user feedback?** --> "Collect Feedback" below
**Exporting compliance reports?** --> "Export Compliance" below
**Monitoring for behavioral drift?** --> "Monitor Drift" below
**Tracking learning progress?** --> "Track Learning" below
**Defining quality scoring or risk templates?** --> "Configure Scoring" below
**General question about the platform?** --> Read [references/platform-knowledge.md](references/platform-knowledge.md)
**Need the full API surface?** --> Read [references/api-surface.md](references/api-surface.md)

## Instrument My Agent

Full integration of DashClaw into an existing agent codebase.

### 1. Detect language, install SDK

**Node.js:**
```javascript
import { DashClaw } from 'dashclaw';
const dc = new DashClaw({
  baseUrl: process.env.DASHCLAW_BASE_URL || 'http://localhost:3000',
  apiKey: process.env.DASHCLAW_API_KEY,
  agentId: 'my-agent',
  agentName: 'My Agent',
  guardMode: 'warn',   // 'off' | 'warn' | 'enforce'
  hitlMode: 'off',     // 'off' | 'wait'
});
```

**Python:**
```python
from dashclaw import DashClaw
dc = DashClaw(
    base_url=os.environ.get("DASHCLAW_BASE_URL", "http://localhost:3000"),
    api_key=os.environ["DASHCLAW_API_KEY"],
    agent_id="my-agent",
    agent_name="My Agent",
    guard_mode="warn",
    hitl_mode="off",
)
```

### 1b. Real-Time Events (SSE)

Agents can subscribe to the platform's real-time event stream to react instantly to human approvals,
policy updates, or task assignments:

```javascript
// Node
const events = dc.events();
events.on('action.updated', (payload) => {
  if (payload.status === 'approved') resumeWork();
});
```

### 1c. Auto-report token usage (optional but recommended)

Wrap the LLM client so every call auto-reports tokens to DashClaw:

```javascript
// Node
const anthropic = dc.wrapClient(new Anthropic());
// Every anthropic.messages.create() call now auto-reports tokens
```

```python
# Python
anthropic = dc.wrap_client(Anthropic())
# Every anthropic.messages.create() call now auto-reports tokens
```

Supports Anthropic and OpenAI clients. Streaming calls are safely ignored.

### 2. Identify decision points in the agent's code

Scan for: tool/API calls (actions), conditional behavior logic (policy-relevant), risk-bearing
operations (guard-worthy), session boundaries (handoffs), inter-agent communication (messages).

### 3. Instrument each decision point

**Action recording** (wrap every significant operation):
```javascript
const action = await dc.createAction({
  actionType: 'api_call',
  declaredGoal: 'Fetch user profile',
  riskScore: 25,
  metadata: { endpoint: '/users/123' }
});
// ... do the work ...
await dc.updateOutcome(action.action_id, {
  status: 'completed',
  outputSummary: 'Profile fetched',
  costEstimate: 0.002
});
```

**Guard check** (before risky operations):
```javascript
const decision = await dc.guard({
  actionType: 'file_write', content: fileContent, riskScore: 60
});
if (decision.decision === 'block') return; // blocked by policy
```

**Assumption tracking:**
```javascript
await dc.reportAssumption({
  assumption: 'User timezone is UTC', category: 'user_context', confidence: 70
});
```

**Prompt injection scanning** (on user/tool input before processing):
```javascript
const scan = await dc.scanPromptInjection(userInput, { source: 'user_input' });
if (scan.recommendation === 'block') throw new Error('Prompt injection detected');
```

**Session handoffs:**
```javascript
await dc.createHandoff({
  sessionDate: new Date().toISOString().slice(0, 10),
  summary: 'Completed migration. 3 tables updated.',
  openTasks: ['Verify row counts'],
  decisions: ['Used batch inserts']
});
```

### 4. Add quality scoring (recommended)

After instrumenting actions, add evaluation scoring to track output quality:

```javascript
// Create a scorer (one-time setup)
const scorer = await dc.createScorer({
  name: 'output-quality',
  scorer_type: 'contains',
  config: { keywords: ['success', 'completed'], case_sensitive: false },
});

// Score outputs after each action
const result = await dc.scoreOutput({
  scorer_id: scorer.id,
  output: actionResult,
  action_id: action.action_id,
});
console.log(`Quality score: ${result.score}`); // 0-1
```

### 5. Add env vars, validate

```bash
# .env
DASHCLAW_BASE_URL=http://localhost:3000
DASHCLAW_API_KEY=oc_live_...
```

Validate the integration:
```bash
node .claude/skills/dashclaw-platform-intelligence/scripts/validate-integration.mjs \
  --base-url http://localhost:3000 --api-key $DASHCLAW_API_KEY --full
```

## Configure Evaluations

Set up the evaluation framework to score agent outputs.

### Scorer Types

5 built-in scorer types. All work without an LLM except `llm_judge`:

| Type | Config | LLM Required |
|------|--------|-------------|
| `regex` | `{ pattern, flags }` | No |
| `contains` | `{ keywords, case_sensitive }` | No |
| `numeric_range` | `{ field, min, max }` | No |
| `custom_function` | `{ function_body }` | No |
| `llm_judge` | `{ prompt, model }` | Yes (optional) |

```javascript
// Regex scorer
const regex = await dc.createScorer({
  name: 'json-format', scorer_type: 'regex',
  config: { pattern: '^\\{.*\\}$', flags: 's' },
});

// Numeric range (scores metadata fields)
const range = await dc.createScorer({
  name: 'confidence-check', scorer_type: 'numeric_range',
  config: { field: 'confidence', min: 70, max: 100 },
});

// Custom function (full JS logic)
const custom = await dc.createScorer({
  name: 'length-and-format', scorer_type: 'custom_function',
  config: { function_body: 'return output.length > 50 && output.includes("##") ? 1 : 0;' },
});
```

### Batch Evaluation Runs

```javascript
const run = await dc.createEvalRun({
  name: 'weekly-quality-audit',
  scorer_ids: [regex.id, range.id],
  dataset: outputs.map(o => ({ output: o.text, metadata: o.meta })),
});
console.log(`Avg score: ${run.avg_score}`);
```

## Manage Prompts

Version-controlled prompt templates with mustache variable rendering.

```javascript
// Create template
const tmpl = await dc.createTemplate({
  name: 'deploy-check',
  content: 'Verify {{service}} deployment to {{environment}} is healthy. Check {{metric}}.',
  variables: ['service', 'environment', 'metric'],
});

// Render with variables (server-side, no LLM)
const { rendered } = await dc.renderTemplate(tmpl.id, {
  service: 'auth-api', environment: 'production', metric: 'p99 latency',
});
// "Verify auth-api deployment to production is healthy. Check p99 latency."

// Create new version
await dc.createVersion(tmpl.id, {
  content: 'Verify {{service}} on {{environment}}. Check {{metric}} and {{threshold}}.',
  change_note: 'Added threshold variable',
});

// Rollback to previous version
await dc.activateVersion(tmpl.id, 'pv_version001');

// Usage analytics
const stats = await dc.getPromptStats({ template_id: tmpl.id });
```

## Collect Feedback

Structured user feedback with auto-sentiment detection and auto-tagging.

```javascript
// Submit feedback linked to an action
const fb = await dc.submitFeedback({
  rating: 2,
  comment: 'Response was slow and inaccurate',
  action_id: 'act_xyz789',
  agent_id: 'research-bot',
});
console.log(fb.sentiment); // 'negative' (auto-detected, rule-based)
console.log(fb.tags);      // ['performance', 'accuracy'] (auto-tagged)

// Query unresolved negative feedback
const { feedback } = await dc.listFeedback({
  sentiment: 'negative', resolved: false,
});

// Resolve with note
await dc.resolveFeedback(fb.id, 'Fixed latency issue in v2.3');

// Analytics
const stats = await dc.getFeedbackStats();
// { avg_rating, sentiment_breakdown, top_tags, rating_distribution }
```

**Auto-tag categories**: performance, accuracy, cost, security, reliability, ux

## Export Compliance

Generate multi-framework compliance bundles with evidence packaging.

```javascript
// Generate export bundle
const exp = await dc.createComplianceExport({
  frameworks: ['soc2', 'nist-ai-rmf'],
  name: 'Q1 2026 Audit',
  window_days: 90,
  include_evidence: true, // includes guard decisions + action records
});

// Schedule recurring exports
await dc.createComplianceSchedule({
  frameworks: ['soc2'],
  cron: '0 6 1 * *', // Monthly on 1st at 6am
  name: 'Monthly SOC 2 Report',
});

// Track coverage trends
const { trends } = await dc.getComplianceTrends({ framework: 'soc2' });
trends.forEach(t => console.log(`${t.created_at}: ${t.coverage_percentage}%`));

// Download export (browser-native)
await dc.downloadComplianceExport(exp.id);
```

## Monitor Drift

Statistical behavioral drift detection using z-score analysis. Pure math, no LLM.

**6 tracked metrics**: risk_score, confidence, duration_ms, cost_estimate, tokens_total, learning_score

```javascript
// Step 1: Compute baselines from historical data
await dc.computeDriftBaselines({ lookback_days: 30 });

// Step 2: Detect drift (compare recent window to baselines)
const { alerts } = await dc.detectDrift({ window_days: 7 });
for (const a of alerts) {
  console.log(`[${a.severity}] ${a.metric} for ${a.agent_id}: z=${a.z_score}`);
}
// [warning] risk_score for deploy-bot: z=2.3
// [critical] cost_estimate for research-bot: z=3.8

// Severity thresholds:
// z >= 1.5 = info
// z >= 2.0 = warning
// z >= 3.0 = critical

// List unacknowledged critical alerts
const critical = await dc.listDriftAlerts({ severity: 'critical', acknowledged: false });

// Acknowledge after investigation
await dc.acknowledgeDriftAlert(alert.id);

// Stats overview
const stats = await dc.getDriftStats();
console.log(`${stats.overall.critical_count} critical, ${stats.overall.warning_count} warnings`);
```

## Track Learning

Learning analytics with velocity tracking, maturity classification, and per-skill learning curves.
**This is DashClaw's unique moat -- no other platform tracks agent learning velocity.**

### Maturity Model

6 levels based on episode count, success rate, and average score:

| Level | Episodes | Success Rate | Avg Score |
|-------|----------|-------------|-----------|
| Novice | 0+ | any | any |
| Developing | 10+ | 40%+ | 40+ |
| Competent | 50+ | 60%+ | 55+ |
| Proficient | 150+ | 75%+ | 65+ |
| Expert | 500+ | 85%+ | 75+ |
| Master | 1000+ | 92%+ | 85+ |

```javascript
// Compute learning velocity (linear regression slope of scores over time)
const { results } = await dc.computeLearningVelocity({ lookback_days: 30 });
for (const r of results) {
  console.log(`${r.agent_id}: velocity=${r.velocity} pts/day, maturity=${r.maturity.level}`);
}
// deploy-bot: velocity=0.8 pts/day, maturity=proficient
// research-bot: velocity=-0.2 pts/day, maturity=competent  <-- degrading!

// Compute per-skill learning curves
await dc.computeLearningCurves({ lookback_days: 60 });
const { curves } = await dc.getLearningCurves({
  agent_id: 'deploy-bot', action_type: 'deploy',
});
curves.forEach(c => console.log(`Week of ${c.window_start}: avg=${c.avg_score}`));

// Comprehensive summary (the dashboard API)
const summary = await dc.getLearningAnalyticsSummary();
console.log(`${summary.overall.total_episodes} episodes`);
console.log(`Top agent: ${summary.by_agent[0].agent_id} (${summary.by_agent[0].maturity_level})`);
console.log(`Velocity: ${summary.by_agent[0].velocity} pts/day`);
```

## Add a DashClaw Capability

Full-stack scaffold when adding a new API route to the DashClaw platform.

### Files to create/modify (in order)

1. **Migration** `scripts/migrate-<domain>.mjs` -- create tables with TEXT PKs, crypto-random IDs
2. **Repository** `app/lib/repositories/<domain>.repository.js` -- all SQL here
3. **Lib module** `app/lib/<domain>.js` -- business logic (pure functions where possible)
4. **Route handler** `app/api/<domain>/route.js` -- imports from repository, never inline SQL
5. **Demo fixtures** `app/lib/demo/demoFixtures.js` (if route needs demo mode)
6. **Demo middleware** handler in `middleware.js` (if route needs demo mode)
7. **Node SDK** method in `sdk/dashclaw.js` (camelCase)
8. **Python SDK** method in `sdk-python/dashclaw/client.py` (snake_case)
9. **Docs page** navItems entry + MethodEntry in `app/docs/page.js`
10. **Node README** section in `sdk/README.md`
11. **Python README** section in `sdk-python/README.md`
12. **Parity matrix** counts in `docs/sdk-parity.md`

### Route handler pattern
```javascript
import { getSql } from '../../lib/db.js';
import { getOrgId } from '../../lib/org.js';
import { listThings } from '../../lib/repositories/<domain>.repository.js';

export async function GET(request) {
  try {
    const sql = getSql();
    const orgId = getOrgId(request);
    const result = await listThings(sql, orgId, {});
    return Response.json(result);
  } catch (err) {
    console.error('[DOMAIN] GET error:', err.message);
    return Response.json({ error: 'Internal server error' }, { status: 500 });
  }
}
```

### Post-scaffold commands (mandatory)
```bash
npm run openapi:generate && npm run api:inventory:generate
npm run docs:check && npm run route-sql:check
npm run openapi:check && npm run api:inventory:check
npm run lint && npm run build
```

## Generate Client Code

Generate a DashClaw client in any language from the API contracts.

1. Read OpenAPI spec: `docs/openapi/critical-stable.openapi.json`
2. Read both SDKs for patterns: `sdk/dashclaw.js`, `sdk-python/dashclaw/client.py`
3. Constructor: `baseUrl`, `apiKey`, `agentId`, `agentName`, `swarmId`, `guardMode`, `hitlMode`
4. Auth: `x-api-key` header on every request
5. Error types: `DashClawError`, `GuardBlockedError`, `ApprovalDeniedError`
6. Minimum viable methods: `createAction`, `updateOutcome`, `getActions`, `guard`, `sendMessage`, `createHandoff`, `syncState`

For the full 130+ route API surface with method mappings, read [references/api-surface.md](references/api-surface.md).

## Configure Scoring

Set up user-defined quality profiles and risk templates:

### Step 1: Auto-calibrate from your real data

```javascript
// Analyze your historical actions to get suggested thresholds
const calibration = await dc.autoCalibrate({
  action_type: 'deploy',
  lookback_days: 30,
});
// Returns percentile-based suggestions for each metric
// calibration.suggestions[0] = {
//   metric: 'duration_ms', distribution: { p25: 3000, p50: 8000, p75: 20000 },
//   suggested_scale: [{ label: 'excellent', operator: 'lte', value: 3000, score: 100 }, ...]
// }
```

```python
calibration = dc.auto_calibrate(action_type="deploy", lookback_days=30)
```

### Step 2: Create a scoring profile with weighted dimensions

```javascript
const profile = await dc.createScoringProfile({
  name: 'deploy-quality',
  action_type: 'deploy',
  composite_method: 'weighted_average', // or 'minimum', 'geometric_mean'
  dimensions: [
    {
      name: 'Speed', data_source: 'duration_ms', weight: 0.3,
      scale: [
        { label: 'excellent', operator: 'lt', value: 30000, score: 100 },
        { label: 'good', operator: 'lt', value: 60000, score: 75 },
        { label: 'acceptable', operator: 'lt', value: 120000, score: 50 },
        { label: 'poor', operator: 'gte', value: 120000, score: 20 },
      ],
    },
    {
      name: 'Reliability', data_source: 'confidence', weight: 0.4,
      scale: [
        { label: 'excellent', operator: 'gte', value: 0.9, score: 100 },
        { label: 'good', operator: 'gte', value: 0.7, score: 75 },
        { label: 'poor', operator: 'lt', value: 0.7, score: 25 },
      ],
    },
    {
      name: 'Cost', data_source: 'cost_estimate', weight: 0.3,
      scale: [
        { label: 'excellent', operator: 'lt', value: 0.01, score: 100 },
        { label: 'good', operator: 'lt', value: 0.05, score: 75 },
        { label: 'poor', operator: 'gte', value: 0.05, score: 30 },
      ],
    },
  ],
});
```

```python
profile = dc.create_scoring_profile(
    name="deploy-quality",
    action_type="deploy",
    composite_method="weighted_average",
    dimensions=[
        {"name": "Speed", "data_source": "duration_ms", "weight": 0.3,
         "scale": [
             {"label": "excellent", "operator": "lt", "value": 30000, "score": 100},
             {"label": "good", "operator": "lt", "value": 60000, "score": 75},
             {"label": "poor", "operator": "gte", "value": 60000, "score": 20},
         ]},
        {"name": "Reliability", "data_source": "confidence", "weight": 0.4,
         "scale": [
             {"label": "excellent", "operator": "gte", "value": 0.9, "score": 100},
             {"label": "poor", "operator": "lt", "value": 0.7, "score": 25},
         ]},
        {"name": "Cost", "data_source": "cost_estimate", "weight": 0.3,
         "scale": [
             {"label": "excellent", "operator": "lt", "value": 0.01, "score": 100},
             {"label": "poor", "operator": "gte", "value": 0.05, "score": 30},
         ]},
    ],
)
```

**Data sources**: `duration_ms`, `cost_estimate`, `tokens_total`, `risk_score`, `confidence`, `eval_score`, `metadata_field` (dot-path), `custom_function` (arbitrary JS).

**Composite methods**: `weighted_average` (default -- sum of score x weight), `minimum` (strictest -- one bad dimension tanks the whole score), `geometric_mean` (balanced -- heavily penalizes zeros).

### Step 3: Score actions against your profile

```javascript
// Single action
const result = await dc.scoreWithProfile(profile.id, {
  duration_ms: 25000,
  confidence: 0.95,
  cost_estimate: 0.008,
});
// result.composite_score = 92.5
// result.dimensions = [{ dimension_name: 'Speed', score: 100, label: 'excellent' }, ...]

// Batch scoring
const batch = await dc.batchScoreWithProfile(profile.id, [
  { duration_ms: 500, confidence: 0.98 },
  { duration_ms: 10000, confidence: 0.5 },
]);
// batch.summary = { total: 2, scored: 2, avg_score: 72.3 }
```

```python
result = dc.score_with_profile(profile["id"], {
    "duration_ms": 25000, "confidence": 0.95, "cost_estimate": 0.008,
})

batch = dc.batch_score_with_profile(profile["id"], [
    {"duration_ms": 500, "confidence": 0.98},
    {"duration_ms": 10000, "confidence": 0.5},
])
```

### Step 4: Set up risk templates (replaces hardcoded risk numbers)

```javascript
// Instead of agents guessing riskScore: 40, DashClaw computes it:
const template = await dc.createRiskTemplate({
  name: 'Production Safety',
  base_risk: 20,
  rules: [
    { condition: "metadata.environment == 'production'", add: 25 },
    { condition: "metadata.modifies_data == true", add: 15 },
    { condition: "metadata.irreversible == true", add: 30 },
  ],
});
// Production data-modifying deploy: 20 + 25 + 15 = 60 risk
// Staging read-only query: 20 + 0 + 0 = 20 risk
```

```python
template = dc.create_risk_template(
    name="Production Safety",
    base_risk=20,
    rules=[
        {"condition": "metadata.environment == 'production'", "add": 25},
        {"condition": "metadata.modifies_data == true", "add": 15},
        {"condition": "metadata.irreversible == true", "add": 30},
    ],
)
```

**Condition operators**: `==`, `!=`, `>`, `>=`, `<`, `<=`, `contains`. Supports nested paths like `metadata.deploy.target`.

**ID prefixes**: `sp_` (profiles), `sd_` (dimensions), `ps_` (profile scores), `rt_` (risk templates).

## Design Policies

Set up behavior guard policies for agent governance.

**Guard modes:** `off` (no checks), `warn` (log but allow), `enforce` (block on policy match)

**Common patterns:**
- Cost ceiling: block when `cost_estimate > threshold`
- Risk threshold: require approval when `risk_score >= 70`
- Action type allowlist: block unknown action types
- Content filter: guard against sensitive data in outputs

**YAML policy example:**
```yaml
name: production-safety
policy_type: risk_threshold
rules:
  max_risk_without_approval: 60
  blocked_action_types: [delete_database, modify_production]
  require_approval_for: [deploy, infrastructure_change]
```

```javascript
// Import a policy pack
await dc.importPolicies({ pack: 'production' });

// Custom policy
await dc.createPolicy({
  name: 'cost-ceiling',
  policy_type: 'cost_limit',
  rules: { max_cost_per_action: 5.00, max_daily_spend: 100.00 },
});

// Test policies without enforcing
const results = await dc.testPolicies();
console.log(`${results.passed} passed, ${results.failed} failed`);

// Generate compliance proof report
const proof = await dc.getProofReport({ format: 'json' });
```

## Bootstrap Agent

Import an existing agent's workspace data into DashClaw:

```bash
node .claude/skills/dashclaw-platform-intelligence/scripts/bootstrap-agent-quick.mjs \
  --dir "/path/to/agent/workspace" \
  --agent-id "my-agent" \
  --validate
```

The bootstrap scanner auto-discovers: decisions, lessons, goals, context threads, relationships,
memory files, and preferences from common agent directory structures.

For full options: `node scripts/bootstrap-agent-quick.mjs --help`
