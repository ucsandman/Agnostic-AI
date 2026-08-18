# Agnostic AI Harness

> A model- and client-agnostic agent harness designed for continuous self-maintenance, polyglot synchronization, deterministic error harvesting, and safety guardrails across any LLM or AI agent runtime.

---

## Supported Clients & Runtimes

| Client / Agent | Agreement Target | Hook Dialect | Skill Linking |
|---|---|---|---|
| **Claude Code** | `~/.claude/CLAUDE.md` + `SOUL.md` | `settings.json` (camelCase) | Windows Junction (`~/.claude/skills`) |
| **Codex CLI** | `~/.codex/AGENTS.md` | `hooks.json` (snake_case) | Windows Junction (`~/.codex/skills`) |
| **Antigravity CLI (`agy`)** | `~/.gemini/GEMINI.md` | `config/hooks.json` (protojson) | Windows Junction (`~/.gemini/config/skills`) |
| **OpenClaw** | `~/.openclaw/SYSTEM.md` | Generic Hook Proxy | Custom link |
| **Hermes** | `~/.hermes/agent_system.md` | JSON Hook Proxy | Custom link |
| **Generic / Local LLMs** | `storage/compiled/system_prompt.md` | HTTP / CLI wrapper | Directory export |

---

## Core Pillars

### 1. Single Source of Truth (SSOT) & Polyglot Sync
Rules and traits are maintained in canonical markdown files under `core/rules/` and `core/traits/`. Running `node engine/sync/sync.cjs` compiles these into target formats without manual duplication.

### 2. Universal Hook Adapter & Security Guards
Standardizes security hooks across disparate agent JSON formats. Intercepts file reads, token leaks, process termination, and destructive commands before execution.

### 3. The 4-Tier Self-Maintenance & Distillation Ladder
A scheduled daily distillation routine clusters mistakes, tracks recurring candidate counts, and evaluates candidates through strict graduation gates:
- **Tier 0 · Observation**: Raw error or deviation sighting.
- **Tier 1 · Repo Fact**: Single sighting affecting a specific repository.
- **Tier 2 · Universal Rule**: Sighted on **3+ distinct days**; imperative constraint preventing repeat failures.
- **Tier 3 · Trait**: Guiding philosophy when no explicit rule covers the case.

**The Refusal Rule**: Measures health by the *refusal-to-promotion ratio* (max 2 rule promotions per run) to prevent context window bloat.

### 4. Multi-Source Rule Ingestion & Merging (`engine/ingest/merge.cjs`)
Claude Code only reads `CLAUDE.md`, Codex only reads `AGENTS.md`, and Antigravity only reads `GEMINI.md`. When different agents are used on the same codebase or across sessions, lessons and rules written to one file are missed by the others.
- `node engine/ingest/merge.cjs` automatically discovers all `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, and `SYSTEM.md` files in a repository or global home directory.
- Deduplicates sections, aggregates all **Learned Rules** and lessons, and writes back the complete unified ruleset to all files so every agent shares 100% parity.

### 5. Governed Autonomy with DashClaw (`engine/hooks/dashclaw-guard.cjs`)
For long-running unattended runs (nightly background tasks, CI pipelines, multi-agent swarms), `agnostic-harness` seamlessly integrates with **[DashClaw](https://github.com/ucsandman/DashClaw)** ([dashclaw.io](https://dashclaw.io)):
- **Fail-Closed Seam**: Intercepts high-risk destructive actions (`git push --force`, `rmdir /s`, database drops, credential exfiltration) at the hook level before execution.
- **Remote & Async Approvals**: Resolves pending approvals from anywhere via phone PWA, Telegram, Discord, or the web Approvals inbox without stalling unattended runs.
- **Signed Audit Trail**: Cryptographically logs every granted or denied decision with Ed25519 signatures.
- **Zero Configuration**: Automatically discovers local DashClaw instances (`npx dashclaw up`) and falls back cleanly to local guard policies if inactive.

### 6. Human-First Tooling Suite
Includes fast interactive CLI + Web UI surfaces:
- **ErrorLog (`tools/errorlog/`)**: Interactive error explorer and ladder candidate viewer.
- **Parity Monitor (`tools/sync/`)**: Multi-harness sync checker with one-click re-sync.
- **Recall (`tools/recall/`)**: Instant full-text search across memory facts, rules, and decisions.

---

## Directory Structure

```
agnostic-harness/
├── core/                               # Single Source of Truth (SSOT)
│   ├── rules/global-rules.md           # Universal working agreement & rules
│   ├── traits/traits.md                # Tier 3 ladder traits
│   ├── safety/guards.json              # Declarative security & process policies
│   └── templates/targets.json          # Target client mappings & preambles
├── engine/                             # Core execution engines
│   ├── sync/sync.cjs                   # Polyglot rules compiler & skills linker
│   ├── ingest/merge.cjs                # Rule & lesson merger across CLAUDE/AGENTS/GEMINI
│   ├── hooks/                          # Protocol translation shims & guards
│   │   ├── universal-adapter.cjs       # Hook dialect normalizer
│   │   ├── secret-guard.cjs            # Secret scanning & file blocker
│   │   ├── dashclaw-guard.cjs          # Governed autonomy & remote approval seam
│   │   └── correction-tracker.cjs      # User correction harvester
│   ├── distill/distill.cjs             # Daily self-maintenance & ladder evaluator
│   └── tests/run-all.cjs               # Test runner
├── tools/                              # Human-first UI and CLI tools
│   ├── errorlog/                       # Error harvester & dashboard (errorlog.html)
│   ├── sync/                           # Harness parity status (parity.html)
│   └── recall/                         # Fact & rule memory search (recall.html)
├── skills/                             # Shared agent skills
│   └── definitions/                    # Canonical skill markdown files
├── storage/                            # Operational persistence
│   ├── candidates.jsonl                # Sighting counts & ladder candidate states
│   ├── corrections.jsonl               # Real-time human interventions
│   ├── distill-PROPOSAL.md             # Reviewable daily promotion proposal
│   └── distill-digest.json             # Structured digest for UI dashboards
├── jobs/                               # Headless automation scripts
│   ├── daily-distill.ps1               # Scheduled daily maintenance runner
│   └── sync-targets.ps1                # Re-sync helper
├── launch.py                           # Single-command launcher
└── package.json
```

---

## Quick Start

### 1. Run the Launch Entrypoint
```bash
python launch.py
```

### 2. Check or Apply Target Sync
```bash
# Check if target configs are in sync:
node engine/sync/sync.cjs --check

# Compile and update all targets:
node engine/sync/sync.cjs
```

### 3. Ingest & Merge Rules Across All Agents
```bash
# Merge rules and lessons in the current repository:
npm run merge

# Merge global rules (~/.claude, ~/.codex, ~/.gemini):
npm run merge:global
```

### 4. Enable Governed Autonomy with DashClaw
```bash
# Start local DashClaw instance:
npm run dashclaw:up

# Verify connection health:
npm run dashclaw:doctor
```

### 5. Run Self-Maintenance Distillation
```bash
node engine/distill/distill.cjs
```

### 6. Open Human-First Dashboards
```bash
# Error & Distillation Explorer:
node tools/errorlog/errorlog.cjs --open

# Multi-Harness Parity Monitor:
node tools/sync/parity.cjs --open

# Memory & Rule Recall:
node tools/recall/recall.cjs --open
```

### 7. Run Engine Tests
```bash
npm test
```
