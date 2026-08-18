# DashClaw API Surface

140+ routes across 29 categories. Node SDK uses camelCase, Python SDK uses snake_case.

## Table of Contents

- [Action Recording](#action-recording)
- [Loops and Assumptions](#loops-and-assumptions)
- [Signals](#signals)
- [Behavior Guard](#behavior-guard)
- [Policies](#policies)
- [Context Manager](#context-manager)
- [Agent Messaging](#agent-messaging)
- [Automation Snippets](#automation-snippets)
- [Session Handoffs](#session-handoffs)
- [Memory](#memory)
- [User Preferences](#user-preferences)
- [Daily Digest](#daily-digest)
- [Security Scanning](#security-scanning)
- [Webhooks](#webhooks)
- [Agent Pairing](#agent-pairing)
- [Identity Binding](#identity-binding)
- [Organization Management](#organization-management)
- [Activity Logs](#activity-logs)
- [Compliance Engine](#compliance-engine)
- [Compliance Exports](#compliance-exports)
- [Task Routing](#task-routing)
- [Bulk Sync](#bulk-sync)
- [Evaluation Framework](#evaluation-framework)
- [Prompt Management](#prompt-management)
- [User Feedback](#user-feedback)
- [Drift Detection](#drift-detection)
- [Learning Analytics](#learning-analytics)
- [Scoring Profiles](#scoring-profiles)
- [Risk Templates](#risk-templates)
- [Dashboard Data and Other Routes](#dashboard-data-and-other-routes)

## Action Recording

**Maturity:** Stable

| Endpoint | Methods | Node SDK | Python SDK |
|---|---|---|---|
| `/api/actions` | GET, POST, DELETE | `createAction`, `getActions` | `create_action`, `get_actions` |
| `/api/actions/{actionId}` | GET, PATCH | `getAction`, `updateOutcome` | `get_action`, `update_outcome` |
| `/api/actions/{actionId}/approve` | POST | `approveAction` | `approve_action` |
| `/api/actions/{actionId}/trace` | GET | `getActionTrace` | `get_action_trace` |

`getPendingApprovals` / `get_pending_approvals` -- queries actions with status=pending_approval.

## Loops and Assumptions

**Maturity:** Stable

| Endpoint | Methods | Node SDK | Python SDK |
|---|---|---|---|
| `/api/actions/loops` | GET, POST | `reportLoop`, `getLoops` | `report_loop`, `get_loops` |
| `/api/actions/loops/{loopId}` | GET, PATCH | `closeLoop` | `close_loop` |
| `/api/actions/assumptions` | GET, POST | `reportAssumption`, `getAssumptions` | `report_assumption`, `get_assumptions` |
| `/api/actions/assumptions/{assumptionId}` | GET, PATCH | `getAssumption`, `updateAssumption` | `get_assumption`, `update_assumption` |

## Signals

**Maturity:** Stable

| Endpoint | Methods | Node SDK | Python SDK |
|---|---|---|---|
| `/api/actions/signals` | GET | `getSignals` | `get_signals` |

## Behavior Guard

**Maturity:** Stable

| Endpoint | Methods | Node SDK | Python SDK |
|---|---|---|---|
| `/api/guard` | GET, POST | `guard`, `getGuardDecisions` | `guard`, `get_guard_decisions` |

POST sends an action for policy evaluation. Returns `{ decision, reasons, warnings, matched_policies, risk_score }`.
Decisions: `allow`, `block`, `warn`, `require_approval`.

## Policies

**Maturity:** Stable

| Endpoint | Methods | Node SDK | Python SDK |
|---|---|---|---|
| `/api/policies` | GET, POST, PATCH, DELETE | `importPolicies` | `import_policies` |
| `/api/policies/import` | POST | `importPolicies` | `import_policies` |
| `/api/policies/test` | POST | `testPolicy` | `test_policy` |
| `/api/policies/proof` | GET | `getProofReport` | `get_proof_report` |

## Context Manager

**Maturity:** Stable

| Endpoint | Methods | Node SDK | Python SDK |
|---|---|---|---|
| `/api/context/points` | GET, POST | `saveContextPoint`, `getContextPoints` | `save_context_point`, `get_context_points` |
| `/api/context/threads` | GET, POST | `createThread`, `getThreads` | `create_thread`, `get_threads` |
| `/api/context/threads/{threadId}` | GET, PATCH | `getThread`, `closeThread` | `get_thread`, `close_thread` |
| `/api/context/threads/{threadId}/entries` | POST | `addThreadEntry` | `add_thread_entry` |

Context thread IDs use `ct_` prefix.

## Agent Messaging

**Maturity:** Stable

| Endpoint | Methods | Node SDK | Python SDK |
|---|---|---|---|
| `/api/messages` | GET, POST, PATCH | `sendMessage`, `getMessages`, `markRead`, `archiveMessages`, `broadcast` | `send_message`, `get_messages`, `mark_read`, `archive_messages`, `broadcast` |
| `/api/messages/threads` | GET, POST, PATCH | `createMessageThread`, `getMessageThreads`, `resolveMessageThread` | `create_message_thread`, `get_message_threads`, `resolve_message_thread` |
| `/api/messages/docs` | GET, POST | `getSharedDocs`, `saveSharedDoc` | `get_shared_docs`, `save_shared_doc` |
| `/api/messages/attachments` | GET | `getMessageAttachments` | `get_message_attachments` |

Message thread IDs use `mt_` prefix.

## Automation Snippets

**Maturity:** Stable

| Endpoint | Methods | Node SDK | Python SDK |
|---|---|---|---|
| `/api/snippets` | GET, POST, DELETE | `saveSnippet`, `getSnippets`, `deleteSnippet` | `save_snippet`, `get_snippets`, `delete_snippet` |
| `/api/snippets/{snippetId}` | GET | `getSnippet` | `get_snippet` |
| `/api/snippets/{snippetId}/use` | POST | `useSnippet` | `use_snippet` |

Snippet IDs use `sn_` prefix.

## Session Handoffs

**Maturity:** Stable

| Endpoint | Methods | Node SDK | Python SDK |
|---|---|---|---|
| `/api/handoffs` | GET, POST | `createHandoff`, `getHandoffs`, `getLatestHandoff` | `create_handoff`, `get_handoffs`, `get_latest_handoff` |

## Memory

**Maturity:** Stable

| Endpoint | Methods | Node SDK | Python SDK |
|---|---|---|---|
| `/api/memory` | GET, POST | `reportMemoryHealth` | `report_memory_health` |

## User Preferences

**Maturity:** Experimental

| Endpoint | Methods | Node SDK | Python SDK |
|---|---|---|---|
| `/api/preferences` | GET, POST | `logObservation`, `setPreference`, `logMood`, `trackApproach`, `getPreferenceSummary`, `getApproaches` | `log_observation`, `set_preference`, `log_mood`, `track_approach`, `get_preference_summary`, `get_approaches` |

GET accepts `?type=summary|observations|preferences|moods|approaches`.

## Daily Digest

**Maturity:** Experimental

| Endpoint | Methods | Node SDK | Python SDK |
|---|---|---|---|
| `/api/digest` | GET | `getDailyDigest` | `get_daily_digest` |

## Security Scanning

**Maturity:** Beta

| Endpoint | Methods | Node SDK | Python SDK |
|---|---|---|---|
| `/api/security/scan` | POST | `scanContent` | `scan_content` |
| `/api/security/status` | GET | `reportSecurityFinding` | `report_security_finding` |
| `/api/security/prompt-injection` | GET, POST | `scanPromptInjection` | `scan_prompt_injection` |

POST scans text for prompt injection attacks. Returns `{ clean, risk_level, recommendation, findings_count, categories, findings }`. Recommendation: `allow`, `warn`, or `block`. Scan metadata stored with `pi_` prefixed IDs.

## Webhooks

**Maturity:** Stable

| Endpoint | Methods | Node SDK | Python SDK |
|---|---|---|---|
| `/api/webhooks` | GET, POST, DELETE | `getWebhooks`, `createWebhook`, `deleteWebhook` | `get_webhooks`, `create_webhook`, `delete_webhook` |
| `/api/webhooks/{webhookId}/test` | POST | `testWebhook` | `test_webhook` |
| `/api/webhooks/{webhookId}/deliveries` | GET | `getWebhookDeliveries` | `get_webhook_deliveries` |

## Agent Pairing

**Maturity:** Experimental

| Endpoint | Methods | Node SDK | Python SDK |
|---|---|---|---|
| `/api/pairings` | GET, POST | `createPairing` | `create_pairing` |
| `/api/pairings/{pairingId}` | GET | `getPairing` | `get_pairing` |
| `/api/pairings/{pairingId}/approve` | POST | `waitForPairing` | `wait_for_pairing` |

## Identity Binding

**Maturity:** Experimental

| Endpoint | Methods | Node SDK | Python SDK |
|---|---|---|---|
| `/api/identities` | GET, POST | `registerIdentity`, `getIdentities` | `register_identity`, `get_identities` |

## Organization Management

**Maturity:** Stable

| Endpoint | Methods | Node SDK | Python SDK |
|---|---|---|---|
| `/api/orgs` | GET, POST | `getOrg`, `createOrg` | `get_org`, `create_org` |
| `/api/orgs/{orgId}` | GET, PATCH | `getOrgById`, `updateOrg` | `get_org_by_id`, `update_org` |
| `/api/orgs/{orgId}/keys` | GET | `getOrgKeys` | `get_org_keys` |

## Activity Logs

**Maturity:** Stable

| Endpoint | Methods | Node SDK | Python SDK |
|---|---|---|---|
| `/api/activity` | GET | `getActivityLogs` | `get_activity_logs` |

## Compliance Engine

**Maturity:** Stable

| Endpoint | Methods | Node SDK | Python SDK |
|---|---|---|---|
| `/api/compliance/map` | POST | `mapCompliance` | `map_compliance` |
| `/api/compliance/gaps` | POST | `analyzeGaps` | `analyze_gaps` |
| `/api/compliance/report` | GET | `getComplianceReport` | `get_compliance_report` |
| `/api/compliance/frameworks` | GET | `listFrameworks` | `list_frameworks` |
| `/api/compliance/evidence` | GET | `getComplianceEvidence` | `get_compliance_evidence` |

Supports frameworks: SOC 2 (`soc2`), NIST AI RMF (`nist-ai-rmf`), EU AI Act (`eu-ai-act`), ISO 42001 (`iso-42001`).

## Compliance Exports

**Maturity:** Stable

| Endpoint | Methods | Node SDK | Python SDK |
|---|---|---|---|
| `/api/compliance/exports` | GET, POST | `createComplianceExport`, `listComplianceExports` | `create_compliance_export`, `list_compliance_exports` |
| `/api/compliance/exports/{exportId}` | GET, DELETE | `getComplianceExport`, `deleteComplianceExport` | `get_compliance_export`, `delete_compliance_export` |
| `/api/compliance/exports/{exportId}/download` | GET | `downloadComplianceExport` | `download_compliance_export` |
| `/api/compliance/exports/{exportId}/status` | GET | `getComplianceExportStatus` | `get_compliance_export_status` |
| `/api/compliance/schedules` | GET, POST | `createComplianceSchedule`, `listComplianceSchedules` | `create_compliance_schedule`, `list_compliance_schedules` |
| `/api/compliance/schedules/{scheduleId}` | PATCH, DELETE | `toggleComplianceSchedule`, `deleteComplianceSchedule` | `toggle_compliance_schedule`, `delete_compliance_schedule` |
| `/api/compliance/trends` | GET | `getComplianceTrends` | `get_compliance_trends` |

Export IDs use `ce_` prefix. Schedule IDs use `cs_` prefix.

## Task Routing

**Maturity:** Stable

| Endpoint | Methods | Node SDK | Python SDK |
|---|---|---|---|
| `/api/routing/agents` | GET, POST | `listRoutingAgents`, `registerRoutingAgent` | `list_routing_agents`, `register_routing_agent` |
| `/api/routing/agents/{agentId}` | GET, PATCH, DELETE | `getRoutingAgent`, `updateRoutingAgentStatus`, `deleteRoutingAgent` | `get_routing_agent`, `update_routing_agent_status`, `delete_routing_agent` |
| `/api/routing/tasks` | GET, POST | `listRoutingTasks`, `submitRoutingTask` | `list_routing_tasks`, `submit_routing_task` |
| `/api/routing/tasks/{taskId}/complete` | POST | `completeRoutingTask` | `complete_routing_task` |
| `/api/routing/stats` | GET | `getRoutingStats` | `get_routing_stats` |
| `/api/routing/health` | GET | `getRoutingHealth` | `get_routing_health` |

## Bulk Sync

**Maturity:** Stable

| Endpoint | Methods | Node SDK | Python SDK |
|---|---|---|---|
| `/api/sync` | POST | `syncState` | `sync_state` |

Accepts a bulk payload with decisions, lessons, goals, context, relationships, memory, preferences. Used by bootstrap scripts and periodic agent syncs.

## Evaluation Framework

**Maturity:** Stable

| Endpoint | Methods | Node SDK | Python SDK |
|---|---|---|---|
| `/api/evaluations/scorers` | GET, POST | `createScorer`, `listScorers` | `create_scorer`, `list_scorers` |
| `/api/evaluations/scorers/{scorerId}` | GET, PATCH, DELETE | `getScorer`, `updateScorer`, `deleteScorer` | `get_scorer`, `update_scorer`, `delete_scorer` |
| `/api/evaluations/scores` | GET, POST | `scoreOutput`, `listScores` | `score_output`, `list_scores` |
| `/api/evaluations/runs` | GET, POST | `createEvalRun`, `listEvalRuns` | `create_eval_run`, `list_eval_runs` |
| `/api/evaluations/types` | GET | `getScorerTypes` | `get_scorer_types` |

Scorer IDs use `es_` prefix. Score IDs use `sc_` prefix. Run IDs use `er_` prefix.

**5 scorer types**: `regex`, `contains`, `numeric_range`, `custom_function`, `llm_judge` (optional, requires LLM provider).

## Prompt Management

**Maturity:** Stable

| Endpoint | Methods | Node SDK | Python SDK |
|---|---|---|---|
| `/api/prompts/templates` | GET, POST | `createTemplate`, `listTemplates` | `create_template`, `list_templates` |
| `/api/prompts/templates/{templateId}` | GET, PATCH, DELETE | `getTemplate`, `updateTemplate`, `deleteTemplate` | `get_template`, `update_template`, `delete_template` |
| `/api/prompts/templates/{templateId}/duplicate` | POST | `duplicateTemplate` | `duplicate_template` |
| `/api/prompts/versions` | GET | `listVersions` | `list_versions` |
| `/api/prompts/versions/{templateId}` | POST | `createVersion` | `create_version` |
| `/api/prompts/versions/{templateId}/activate/{versionId}` | POST | `activateVersion` | `activate_version` |
| `/api/prompts/versions/{templateId}/rollback/{versionId}` | POST | `rollbackVersion` | `rollback_version` |
| `/api/prompts/render` | POST | `renderTemplate` | `render_template` |
| `/api/prompts/runs` | GET | `listPromptRuns` | `list_prompt_runs` |
| `/api/prompts/stats` | GET | `getPromptStats` | `get_prompt_stats` |
| `/api/prompts/variables` | GET | `listPromptVariables` | `list_prompt_variables` |

Template IDs use `pt_` prefix. Version IDs use `pv_` prefix.

## User Feedback

**Maturity:** Stable

| Endpoint | Methods | Node SDK | Python SDK |
|---|---|---|---|
| `/api/feedback` | GET, POST | `submitFeedback`, `listFeedback` | `submit_feedback`, `list_feedback` |
| `/api/feedback/{feedbackId}` | GET, PATCH, DELETE | `getFeedback`, `resolveFeedback`, `deleteFeedback` | `get_feedback`, `resolve_feedback`, `delete_feedback` |
| `/api/feedback/stats` | GET | `getFeedbackStats` | `get_feedback_stats` |

Feedback IDs use `fb_` prefix. Auto-detects sentiment (positive/negative/neutral) and auto-tags into 6 categories: performance, accuracy, cost, security, reliability, ux.

## Drift Detection

**Maturity:** Stable

| Endpoint | Methods | Node SDK | Python SDK |
|---|---|---|---|
| `/api/drift/alerts` | GET, POST | `listDriftAlerts`, `detectDrift`, `computeDriftBaselines`, `recordDriftSnapshots` | `list_drift_alerts`, `detect_drift`, `compute_drift_baselines`, `record_drift_snapshots` |
| `/api/drift/alerts/{alertId}` | PATCH, DELETE | `acknowledgeDriftAlert`, `deleteDriftAlert` | `acknowledge_drift_alert`, `delete_drift_alert` |
| `/api/drift/stats` | GET | `getDriftStats` | `get_drift_stats` |
| `/api/drift/snapshots` | GET | `getDriftSnapshots` | `get_drift_snapshots` |
| `/api/drift/metrics` | GET | `getDriftMetrics` | `get_drift_metrics` |

Alert IDs use `da_` prefix. Baseline IDs use `db_` prefix. Snapshot IDs use `ds_` prefix.

**6 tracked metrics**: risk_score, confidence, duration_ms, cost_estimate, tokens_total, learning_score.
**Severity thresholds**: z >= 1.5 (info), z >= 2.0 (warning), z >= 3.0 (critical).

POST `/api/drift/alerts` accepts `action` field: `detect` (default), `compute_baselines`, `record_snapshots`.

## Learning Analytics

**Maturity:** Stable

| Endpoint | Methods | Node SDK | Python SDK |
|---|---|---|---|
| `/api/learning/analytics/velocity` | GET, POST | `computeLearningVelocity`, `getLearningVelocity` | `compute_learning_velocity`, `get_learning_velocity` |
| `/api/learning/analytics/curves` | GET, POST | `computeLearningCurves`, `getLearningCurves` | `compute_learning_curves`, `get_learning_curves` |
| `/api/learning/analytics/summary` | GET | `getLearningAnalyticsSummary` | `get_learning_analytics_summary` |
| `/api/learning/analytics/maturity` | GET | `getMaturityLevels` | `get_maturity_levels` |

Velocity computed via linear regression slope. Acceleration is the change in velocity. Maturity classification uses 6 levels (novice through master) based on episode count, success rate, and average score.

## Scoring Profiles

**Maturity:** New (Phase 7)

| Endpoint | Methods | Node SDK | Python SDK |
|---|---|---|---|
| `/api/scoring/profiles` | GET, POST | `createScoringProfile`, `listScoringProfiles` | `create_scoring_profile`, `list_scoring_profiles` |
| `/api/scoring/profiles/{profileId}` | GET, PATCH, DELETE | `getScoringProfile`, `updateScoringProfile`, `deleteScoringProfile` | `get_scoring_profile`, `update_scoring_profile`, `delete_scoring_profile` |
| `/api/scoring/profiles/{profileId}/dimensions` | POST | `addScoringDimension` | `add_scoring_dimension` |
| `/api/scoring/profiles/{profileId}/dimensions/{dimensionId}` | PATCH, DELETE | `updateScoringDimension`, `deleteScoringDimension` | `update_scoring_dimension`, `delete_scoring_dimension` |
| `/api/scoring/score` | GET, POST | `scoreWithProfile`, `batchScoreWithProfile`, `getProfileScores`, `getProfileScoreStats` | `score_with_profile`, `batch_score_with_profile`, `get_profile_scores`, `get_profile_score_stats` |
| `/api/scoring/calibrate` | POST | `autoCalibrate` | `auto_calibrate` |

POST `/api/scoring/profiles` supports inline dimension creation (pass `dimensions` array in body).
POST `/api/scoring/score` accepts either `action` (single) or `actions` (batch array).
GET `/api/scoring/score?view=stats` returns aggregate statistics.

**Composite methods**: `weighted_average`, `minimum`, `geometric_mean`.
**Data sources**: `duration_ms`, `cost_estimate`, `tokens_total`, `risk_score`, `confidence`, `eval_score`, `metadata_field`, `custom_function`.
**ID prefixes**: `sp_` (profiles), `sd_` (dimensions), `ps_` (scores).

## Risk Templates

**Maturity:** New (Phase 7)

| Endpoint | Methods | Node SDK | Python SDK |
|---|---|---|---|
| `/api/scoring/risk-templates` | GET, POST | `createRiskTemplate`, `listRiskTemplates` | `create_risk_template`, `list_risk_templates` |
| `/api/scoring/risk-templates/{templateId}` | PATCH, DELETE | `updateRiskTemplate`, `deleteRiskTemplate` | `update_risk_template`, `delete_risk_template` |

Risk templates define rule-based risk scoring: `base_risk` + conditional `rules` (array of `{ condition, add }`).
Condition operators: `==`, `!=`, `>`, `>=`, `<`, `<=`, `contains`. Supports nested paths.
**ID prefix**: `rt_`.

## Dashboard Data and Other Routes

| Endpoint | Methods | Node SDK | Python SDK |
|---|---|---|---|
| `/api/health` | GET | -- | -- |
| `/api/stream` | GET (SSE) | `events()` | -- |
| `/api/tokens` | POST | `reportTokenUsage` | `report_token_usage` |
| `/api/dashboard/data` | GET | -- | -- |
| `/api/decisions` | GET, POST | `recordDecision` | `record_decision` |
| `/api/goals` | GET, POST | `createGoal` | `create_goal` |
| `/api/content` | GET, POST | `recordContent` | `record_content` |
| `/api/interactions` | GET, POST | `recordInteraction` | `record_interaction` |
| `/api/integrations` | GET, POST | `reportConnections` | `report_connections` |
| `/api/calendar` | GET, POST | `createCalendarEvent` | `create_calendar_event` |
| `/api/ideas` | GET, POST | `recordIdea` | `record_idea` |
| `/api/onboarding/api-key` | POST | -- | -- |
| `/api/setup/status` | GET | -- | -- |
| `/api/settings/llm-status` | GET | `getLLMStatus` | `get_llm_status` |
| `/api/cron/*` | POST | -- | -- |
| `/api/schedules` | GET, POST | `listAgentSchedules`, `createAgentSchedule` | `list_agent_schedules`, `create_agent_schedule` |
