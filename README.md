# 🛡️ Agnostic AI Harness & Autonomous Coding Agent

<div align="center">

[![Template Repository](https://img.shields.io/badge/Template-GitHub%20Template-blueviolet.svg?style=flat-square)](#-using-this-template)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square)](LICENSE)
[![Targets: 18 Synced](https://img.shields.io/badge/Targets-18%20AI%20Clients-success.svg?style=flat-square)](#-supported-clients--runtimes)
[![Native Agent](https://img.shields.io/badge/CLI%20Agent-Open--Source%20Claude%20Code%20Parity-brightgreen.svg?style=flat-square)](#-native-autonomous-coding-agent)
[![Local First](https://img.shields.io/badge/Architecture-Local--First-9cf.svg?style=flat-square)](#-core-pillars)
[![Governed Autonomy](https://img.shields.io/badge/Governance-DashClaw%20%7C%20Opt--Out%20Ready-purple.svg?style=flat-square)](https://github.com/ucsandman/DashClaw)

**The unified open-source ecosystem combining an 18-target cross-agent SSOT harness with a native, autonomous terminal coding agent (Claude Code parity for local LLMs).**

*Run an autonomous coding agent powered by LM Studio, Ollama, or OpenAI with subagent swarms, AST symbol indexers, live diffs, test-and-repair loops, and instant harness distillation.*

---

[Native Coding Agent](#-native-autonomous-coding-agent) • [Harness Features](#-harness-key-features) • [Supported Clients](#-supported-clients--runtimes) • [Quick Start](#-quick-start) • [Command Center](#-local-command-center-port-7842)

</div>

---

## ⚡ What is Agnostic AI?

Agnostic AI is a two-in-one system designed for developers who want complete autonomy and zero vendor lock-in:

1. **The Native Autonomous Coding Agent (`agnostic` CLI)**: An open-source, terminal coding agent that brings frontier capabilities (parallel subagents, AST symbol slicing, autonomous test-and-fix loops, `/swarm`, `/diagram`, visual diffs, atomic checkpoints, and live context meters) to any endpoint — whether running frontier flagships (**Google Antigravity Gemini 3.7**, **Claude 5**, **OpenAI GPT-5.6 Sol**, **DeepSeek V4-Pro**) or open-weight models (Qwen 3.8/2.5 Coder, DeepSeek V4, Llama 3) via LM Studio and Ollama.
2. **The 18-Target Universal SSOT Harness**: A single source of truth that keeps your rules, custom skills, safety guards, and learned lessons synchronized across Claude Code, Cursor, Codex, Windsurf, Copilot, Cline, and 12 other AI tools.

---

## 🤖 Native Autonomous Coding Agent

`agnostic` launches a Textual-based TUI (Claude Code-style, with a fixed input box
pinned to the bottom and streaming output above). Prefer the older prompt_toolkit
readline shell? Run `agnostic-legacy` instead — both entry points share the same
agent loop, tools, and slash commands below.

Run the autonomous coding agent in any directory or project:

```bash
# Global interactive coding agent
agnostic

# Switch to frontier models with interactive arrow-key picker
agnostic > /model

# Direct prompt execution with fuzzy @file or #symbol reference
agnostic -p "refactor #CodebaseIndexer in @agent/tools/indexer.py"

# Run tests and auto-repair until green
agnostic
agnostic > /test
agnostic > /fix
```

### 🏆 Built-in Agent Capabilities & Slash Shortcuts

| Command / Trigger | Capability | What It Does |
|---|---|---|
| `@<filename>` / `#<symbol>` | **AST Context Injection** | Dynamic fuzzy auto-completion in terminal; injects exact file content or AST class/function slice directly into prompt. |
| `/model` | **Interactive Model & Effort Picker** | Arrow-key navigation across **Native Monthly Subscriptions** (Google Antigravity `agy`, Claude Code `claude`, OpenAI `codex` with zero API keys required), **Developer API Presets** (Gemini 3.7, Claude 5, GPT-5.6 Sol, DeepSeek V4-Pro), and **Local Offline** with reasoning effort control (`low`, `medium`, `high`). |
| `/fix [cmd]` | **One-Click Quick Fix** | Runs tests or inspects stack traces, diagnoses root cause, and executes a surgical fix in a single turn. |
| `/compact` | **Smart Context Compaction** | Manually condenses older turns into structured distillation preserving touched files, test results, and symbol anchors. |
| `/checkpoint save\|restore\|list` | **Atomic Multi-File Checkpoints** | Creates named checkpoints to atomically roll back multi-file transactions across refactors. |
| `/session save\|load\|list` | **Session Bookmarking** | Saves and restores conversation snapshots and whiteboard state across tasks and branches. |
| `/trust [reads\|tests\|all]` | **Smart Trust Tiers** | Sets permission mode (`strict`, `trust-reads`, `trust-tests`, `trust-all`) while keeping secrets strictly protected. |
| `/audit` / `/retro` | **Session Retro & Audit** | Compiles and exports an end-of-session Markdown report of all tool calls, hard stops, and file modifications. |
| `/web` | **Live Web Companion** | Starts real-time browser companion on `http://localhost:7843` with telemetry, visual diffs, and REST API. |
| `/swarm <task>` | **Parallel Worker Swarm** | Spawns 3 background subagents (Researcher, Implementer, Reviewer) with Git worktree isolation and synthesizes a unified diff. |
| `/test [cmd]` | **Auto Test-and-Fix Loop** | Detects test runners (`npm test`, `pytest`, `cargo test`), catches failures, and loops surgical fixes until tests pass. |
| `/diagram` / `/map` | **Mermaid Architecture** | Scans imports across the project and outputs clean Mermaid architecture dependency charts. |
| `/learn <lesson>` | **Instant SSOT Learning** | Records candidate rules directly into the harness 4-Tier Promotion Ladder (`candidates.jsonl`). |
| `/grill-me <task>` | **Design Interview Mode** | Interrogates the developer with 3 lead architect trade-off questions to eliminate wrong assumptions before coding. |
| `/pr` | **PR & Branch Auto-Pilot** | Analyzes git diffs and drafts a conventional GitHub Pull Request summary. |
| `/undo` | **Snapshot Rollback** | Instantly reverts the most recent file edit or deletes newly generated files. |
| `/commit` | **Conventional Git Commit** | Inspects `git status` + `git diff` and generates conventional commits with one-click approval. |
| `/state` | **Persistent Whiteboard** | Displays active objectives, completed milestones, and scratchpad notes from `.agnostic/state.md`. |
| `/doctor` | **Endpoint Auto-Detector** | Queries local LM Studio / Ollama endpoints, reporting model name, context length, and latency. |
| `/multiline` | **Multi-line Paste Mode** | Paste massive error logs and specs without premature execution (`Ctrl+Z` + `Enter` to submit). |
| `/clear` | **Viewport Reset** | Clears the terminal screen while preserving working session memory. |

---

## 🌟 Harness Key Features

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

### 2. 🧩 Cross-Agent Skill Consolidation & Project-Specific Stack Recommender
- **Automatic Multi-Language & Monorepo Inspection:** Analyzes projects recursively (including `package.json` workspaces, Python `requirements.txt`/`pyproject.toml`, Rust `Cargo.toml`, Go `go.mod`, Three.js, React, TailwindCSS v4, Vite, and WebSocket stacks).
- **Intelligent Tech-Stack Matching:** Automatically maps and activates specialized skills for matching languages and frameworks (e.g. 3D WebGL/Three.js suites for game projects like `husky-raid`).
- **Interactive Project-Scoped Overrides:** Activating any skill in the Global Skills Inventory while a project is selected scopes it directly to that repository and moves it into the project's active skills matrix with instant UI reactivity.

### 3. 🔄 Multi-Source Rule & Lesson Ingestion
Did Claude Code or Codex learn a new repo fact in a local `CLAUDE.md`? The `merge` engine sweeps project and global files, deduplicates sections, and propagates the lessons everywhere.

### 4. 🧬 4-Tier Automated Distillation Ladder
A daily distillation pass analyzes errors, deviations, and human corrections across sessions:
- **Tier 0 · Observation:** Raw error log or corrected deviation.
- **Tier 1 · Repo Fact:** Persistent repo-specific fact or nuance.
- **Tier 2 · Universal Rule:** Sighted on 3+ distinct days; promoted to the universal rule set.
- **Tier 3 · Core Trait:** Foundational agent disposition guiding decisions under ambiguity.

### 5. ⚡ High-Performance Execution & Zero-Latency Engine
- **Parallel Multi-Tool Calling:** Read-only inspection tools (`read_file`, `grep_search`, `find_files`) run concurrently across background threads to minimize LLM tool turnaround latency.
- **mtime AST Symbol & Codebase Caching:** Tracks filesystem timestamps so incremental codebase indexing and symbol lookups (@file, #symbol) are instantaneous without re-parsing unchanged files.
- **Smart Token-Aware Output Truncation:** Large command output streams and test results (>120 lines) are automatically condensed, preserving context window tokens and head/tail exit diagnostics.
- **Zero-Latency Pre-Compiled Security Guardrails:** Safety patterns and secret boundary regexes are pre-compiled in memory for real-time validation with zero runtime overhead.
- **Concurrent Subagent Swarm Worker Dispatch:** Multi-task subagent routines execute asynchronously via threaded workers.

### 6. 🛡️ Optional Governed Autonomy & 100% Local Fallback
Optional integration with DashClaw for remote approval of high-risk actions (force pushes, DB migrations, secret access). **Never forced:** users can opt out with a single click in the dashboard or CLI for pure local execution.

---

## 💻 Supported Clients & Runtimes

| Client / Agent | Synchronized File Target | Hook Dialect | Skill Linking |
|---|---|---|---|
| **Claude Code** | `~/.claude/CLAUDE.md` + `SOUL.md` | `settings.json` (PascalCase events, array form) | Junction (`~/.claude/skills`) |
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

> **Current wiring status:** every client above gets its rules file compiled and synced (18/18).
> Hook proxies (`engine/hooks/dashclaw-guard.cjs`) are actually wired for 10 of the 18 clients today
> (Copilot, Aider, Zed, Amazon Q, Cody, OpenClaw, Hermes, and Generic fall back to declarative
> guards only). Skill-directory junctions are wired for 14 of 18 (Aider, Amazon Q, Cody, and
> Generic have no `skillsDir`). See `core/templates/targets.json` for the exact per-target config.

## 📦 Using This Template
 
 You can use this repository as a clean template to establish your own personalized cross-agent harness:
 
 1. Click **"Use this template"** on GitHub to create your personal harness repository (e.g. `yourname/agnostic-harness`).
 2. Clone your repo locally onto your development machine.
 3. Customize [`core/rules/global-rules.md`](core/rules/global-rules.md) with your preferred working style, rules, non-negotiables, and tool preferences.
 4. Run `npm run setup:default` (or `python launch.py`) to automatically consolidate existing skills, harvest local logs, and link all 18 agent target configurations.
 
 ---
 
 ## 🚀 Quick Start
 
 ### Prerequisites
 - Node.js (v18+)
 - Python (3.10+, optional for `launch.py` and `agnostic` CLI)
 
 ### Installation & First Run
 
 ```bash
 # 1. Clone your harness repository
 git clone https://github.com/<your-username>/agnostic-harness.git
 cd agnostic-harness
 
 # 2. Install dependencies
 npm install
 pip install -e .
 
 # 3. Run the interactive single-command launcher
 python launch.py
 # or launch the agent directly:
 agnostic
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
pytest
```

---

## 🖥️ Local Command Center (Port 7842 & Port 7843)

- **Port 7842 (`npm run dashboard`):** Master configuration, error explorer, skills matrix, and 18-target parity synchronization.
- **Port 7843 (`agnostic --web` / `/web`):** Real-time agent companion dashboard with telemetry, visual diff inspection, context token progress meters, and REST API controls.

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

## 🧹 Uninstall / Restore

The harness only writes inside this repo's own `storage/` and `skills/definitions/`
folders, plus one rules/hooks/skills file per AI client under your home directory
(`~`) — the same 18 targets listed in [Supported Clients](#-supported-clients--runtimes),
each backed up automatically before every overwrite:

1. **Restore a client's previous rules file:** `node engine/sync/sync.cjs` copies a
   timestamped backup to `storage/backups/<client-id>-<filename>-<timestamp>.bak` before
   every overwrite (and before skipping a hand-edited target). Copy the newest `.bak`
   for that client back over the target listed in its row above.
2. **Remove a client's rules file entirely:** delete the path in the "Synchronized
   File Target" column (e.g. `~/.claude/CLAUDE.md`) and, if present, the skill
   junction/directory in the "Skill Linking" column.
3. **Remove hook wiring:** delete the `PreToolUse` entry pointing at
   `engine/hooks/dashclaw-guard.cjs` from `~/.claude/settings.json`, or delete
   `~/.codex/hooks.json` / `~/.gemini/config/hooks.json` for Codex/Antigravity.
4. **Remove harness-local state:** delete this repo's `storage/` directory
   (candidates, digests, backups, DashClaw config) and `skills/definitions/`
   (consolidated skill copies). Neither is required by any other client.
5. **Uninstall the Python package:** `pip uninstall agnostic-agent`.

There is no destructive uninstall script — every write above is additive/backed-up,
so undoing it is copy-back-the-backup or delete-the-file, never a data migration.

---

## 📁 Repository Structure

```
agnostic-harness/
├── agent/                              # Native Autonomous Coding Agent
│   ├── cli.py                          # Interactive shell with @file / #symbol autocomplete
│   ├── loop.py                         # Agent loop & tool execution engine
│   ├── governance/                     # SafetyGuard, AuditManager, SessionManager, ContextManager
│   ├── tools/                          # CodebaseIndexer, DiffViewer, Subagents, MCP Bridge
│   ├── workflows/                      # Swarm, Tester (/fix, /test), Planner, Grill, PR Pilot
│   └── web/                            # Real-time visual companion (port 7843)
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
├── tests/                              # Pytest test suites (Agent & QoL features)
├── skills/                             # Shared agent skills definitions
├── storage/                            # Candidate error records & digests
├── launch.py                           # Single-command launcher
└── package.json
```

---

## 📄 License

MIT License. Free for personal and commercial use. Contributions welcome!
