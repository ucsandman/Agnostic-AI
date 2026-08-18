# 🛡️ Agnostic AI Harness

<div align="center">

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Targets: 18 Synced](https://img.shields.io/badge/Targets-18%20AI%20Clients-success.svg)](#-supported-clients--runtimes)
[![Local First](https://img.shields.io/badge/Architecture-Local--First-9cf.svg)](#-core-pillars)
[![Zero Bloat](https://img.shields.io/badge/Dependencies-Zero%20Bloat-orange.svg)](#-quick-start)
[![Governed Autonomy](https://img.shields.io/badge/Governance-DashClaw%20%7C%20Opt--Out%20Ready-purple.svg)](https://github.com/ucsandman/DashClaw)

**The single-source harness for developers juggling Claude Code, Cursor, Codex, Windsurf, Copilot, and CLI coding agents.**

*Keep your rules, custom skills, safety guards, and learned lessons synchronized across every AI tool on your machine — with zero config drift and zero bloat.*

---

[Features](#-key-features) • [Supported Clients](#-supported-clients--runtimes) • [Quick Start](#-quick-start) • [Command Center](#-local-command-center-port-7842) • [Governance & Opt-Out](#-optional-governed-autonomy-dashclaw)

</div>

---

## ⚡ The Problem: Context & Rules Drift

If you bounce between multiple AI coding assistants, you've likely hit these friction points:
1. **Rule Drift:** You patch a critical instruction in `CLAUDE.md`, forget to update `.cursorrules` or `AGENTS.md`, and an IDE agent touches `.secrets.env` or executes an unsafe command.
2. **Skill Fragmentation:** Custom skills and MCP tools must be manually copied, configured, and updated across 5+ tool config paths.
3. **Forgotten Corrections:** When you correct an agent's repeated hallucination, the lesson is lost across subsequent sessions or other tools.

**Agnostic AI Harness** provides a single source of truth on your machine with automated polyglot compilation, bidirectional lesson ingestion, cross-agent skill consolidation, and deterministic safety guardrails.

---

## 🌟 Key Features

```
                               ┌───────────────────────────┐
                               │     Single Source of      │
                               │   Truth (SSOT) Rules      │
                               │  core/rules/global-rules  │
                               └─────────────┬─────────────┘
                                             │
                      ┌──────────────────────┼──────────────────────┐
                      ▼                      ▼                      ▼
            ┌───────────────────┐  ┌───────────────────┐  ┌───────────────────┐
            │    Claude Code    │  │    Cursor IDE     │  │     Codex CLI     │
            │  ~/.claude/CLAUDE │  │ ~/.cursor/rules   │  │ ~/.codex/AGENTS   │
            └───────────────────┘  └───────────────────┘  └───────────────────┘
                      │                      │                      │
                      └──────────────────────┼──────────────────────┘
                                             ▼
                               ┌───────────────────────────┐
                               │ Cross-Agent Skill & Error │
                               │        Harvester          │
                               │  (Daily Distill Pass)     │
                               └───────────────────────────┘
```

### 1. 🎯 18-Target Polyglot Parity Engine
Edit your master working agreement and core traits once in markdown (`core/rules/global-rules.md`). The sync engine compiles and delivers them into the exact dialects, frontmatters, and locations required by 18 AI coding agents.

### 2. 🧩 Cross-Agent Skill Consolidation
Automatically scans all agent configurations on your machine (`~/.claude/skills`, `~/.cursor/skills`, `~/.gemini/skills`, etc.), deduplicates skills into a central repository, and symlinks/junctions them back so all agents share the same capabilities.

### 3. 🔄 Multi-Source Rule & Lesson Ingestion
Did Claude Code or Codex learn a new repo fact in a local `CLAUDE.md`? The `merge` engine sweeps project and global files, deduplicates sections, and propagates the lessons everywhere.

### 4. 🧬 4-Tier Automated Distillation Ladder
A daily distillation pass analyzes errors, deviations, and human corrections across sessions:
- **Tier 0 · Observation:** Raw error log or corrected deviation.
- **Tier 1 · Repo Fact:** Persistent repo-specific fact or nuance.
- **Tier 2 · Universal Rule:** Sighted on 3+ distinct days; promoted to the universal rule set.
- **Tier 3 · Core Trait:** Foundational agent disposition guiding decisions under ambiguity.

### 5. 🛡️ Optional Governed Autonomy & 100% Local Fallback
Optional integration with DashClaw for remote approval of high-risk actions (force pushes, DB migrations, secret access). **Never forced:** users can opt out with a single click in the dashboard or CLI for pure local execution.

---

## 💻 Supported Clients & Runtimes

| Client / Agent | Synchronized File Target | Hook Dialect | Skill Linking |
|---|---|---|---|
| **Claude Code** | `~/.claude/CLAUDE.md` + `SOUL.md` | `settings.json` (camelCase) | Junction (`~/.claude/skills`) |
| **Codex CLI** | `~/.codex/AGENTS.md` | `hooks.json` (snake_case) | Junction (`~/.codex/skills`) |
| **Antigravity CLI (`agy`)** | `~/.gemini/GEMINI.md` | `config/hooks.json` (protojson) | Junction (`~/.gemini/config/skills`) |
| **Cursor IDE** | `~/.cursor/rules/global-rules.mdc` | `~/.cursor/mcp.json` (MCP) | Junction (`~/.cursor/rules`) |
| **Windsurf (Cascade)** | `~/.windsurf/rules/global-rules.md` | `mcp_config.json` (Cascade MCP) | Junction (`~/.windsurf/rules`) |
| **GitHub Copilot** | `~/.github/copilot-instructions.md` | VS Code Tasks / Pre-commit | Directory export (`.github/instructions`) |
| **Cline** | `~/.cline/prompts/global-rules.md` | `cline_mcp_settings.json` | Junction (`~/.cline/skills`) |
| **Aider** | `~/.aider.conventions.md` | `.aider.conf.yml` (auto-lint) | Config file reference |
| **OpenHands** | `~/.openhands/AGENTS.md` | `.openhands/hooks.json` | Junction (`~/.agents/skills`) |
| **Goose (Block)** | `~/.config/goose/.goosehints` | `config.yaml` (MCP allowlist) | Junction (`~/.config/goose/extensions`) |
| **Continue.dev** | `~/.continue/rules/global-rules.md` | `.continue/prompts` (Slash cmd) | Junction (`~/.continue/prompts`) |
| **Zed AI** | `~/.config/zed/AGENTS.md` | `settings.json` (Commit hooks) | Junction (`~/.config/zed/prompts`) |
| **Trae (ByteDance)** | `~/.trae/user_rules/user_rules.md` | `.trae/config.json` | Junction (`~/.trae/skills`) |
| **Amazon Q Developer** | `~/.amazonq/rules/global-rules.md` | Amazon Q CLI policies | Junction (`~/.amazonq/rules`) |
| **Sourcegraph Cody** | `~/.sourcegraph/rules/global-rules.rule.md` | Cody MCP Engine | Web Prompt Library / MCP mount |
| **OpenClaw** | `~/.openclaw/SYSTEM.md` | Generic Hook Proxy | Custom link |
| **Hermes** | `~/.hermes/agent_system.md` | JSON Hook Proxy | Custom link |
| **Generic / Local LLMs** | `storage/compiled/system_prompt.md` | HTTP / CLI wrapper | Directory export |

---

## 🚀 Quick Start

### Prerequisites
- Node.js (v18+)
- Python (3.10+, optional for `launch.py`)

### Installation & First Run

```bash
# 1. Clone the repository
git clone https://github.com/ucsandman/agnostic-harness.git
cd agnostic-harness

# 2. Run the interactive single-command launcher
python launch.py
# or directly with Node:
npm run dashboard
```

### Essential CLI Commands

```bash
# Verify sync status across all 18 targets:
npm run sync:check

# Compile & push rules to all AI client directories:
npm run sync

# Ingest & merge learned rules across all local CLAUDE.md / AGENTS.md / GEMINI.md:
npm run merge

# Consolidate skills from all installed agent directories:
npm run skills:consolidate

# Run the daily error distillation & rule promotion pass:
npm run distill

# Run all test suites:
npm test
```

---

## 🖥️ Local Command Center (Port 7842)

Launch the visual command center via `npm run dashboard`:

- **Overview:** Real-time metrics on harvested candidate errors, active skills, and target client health.
- **Rule Explorer:** Inspect the master Single Source of Truth, Tier 3 Core Traits, and safety policy JSON.
- **Skill Matrix:** 1-click stack analyzer and skill recommendation engine for any repository on your disk.
- **Error Explorer:** Filter and browse 800+ harvested real-world error traces to identify friction hotspots.
- **Governance & Approvals:** Configure safety thresholds, simulate guard verdicts, or opt out completely.

---

## 🛡️ Optional Governed Autonomy (DashClaw)

Agnostic AI Harness includes native support for [DashClaw](https://github.com/ucsandman/DashClaw) for human-in-the-loop runtime verification on high-risk operations (e.g. `git push --force`, DB drops, production deploys).

```
                      [ Agent Proposes Action ]
                                  │
                                  ▼
                    ┌───────────────────────────┐
                    │ DashClaw Risk Evaluator   │
                    └─────────────┬─────────────┘
                                  │
                    ┌─────────────┴─────────────┐
                    ▼                           ▼
            [ Low Risk (<50) ]          [ High Risk (>=50) ]
                    │                           │
                    ▼                           ▼
            ( Execute Locally )       ( Held for Mobile / Web Approval )
```

### Opt-Out & Standalone Mode
Governance is **100% optional**. You can opt out at any time:
1. **Via Web Dashboard:** Open `http://localhost:7842` -> **Governed Decisions** -> **Settings & Auth** -> Toggle **"Opt Out"**.
2. **Via Config File:** Set `"active": false` in `storage/dashclaw-config.json`.

When opted out, the harness operates with zero external network requests, enforcing all safety boundaries through local declarative guards.

---

## 📁 Repository Structure

```
agnostic-harness/
├── core/                               # Single Source of Truth (SSOT)
│   ├── rules/global-rules.md           # Universal working agreement & rules
│   ├── traits/traits.md                # Tier 3 ladder traits
│   ├── safety/guards.json              # Declarative security & process policies
│   └── templates/targets.json          # Target client mappings & preambles
├── engine/                             # Execution engines
│   ├── sync/sync.cjs                   # Polyglot rules compiler & skills linker
│   ├── ingest/merge.cjs                # Cross-agent rule & lesson merger
│   ├── skills/                         # Skill consolidation & recommendation
│   ├── hooks/                          # Protocol translation shims & safety guards
│   ├── distill/distill.cjs             # Daily self-maintenance & ladder evaluator
│   └── tests/run-all.cjs               # Automated test suites
├── tools/                              # Human-first web command center & tools
│   ├── dashboard/                      # Command center UI (port 7842)
│   ├── errorlog/                       # Error harvester explorer
│   ├── sync/                           # Harness parity monitor
│   └── recall/                         # Rule and memory recall search
├── skills/                             # Shared agent skills definitions
├── storage/                            # Candidate error records & digests
├── launch.py                           # Single-command launcher
└── package.json
```

---

## 📄 License

MIT License. Free for personal and commercial use. Contributions welcome!
