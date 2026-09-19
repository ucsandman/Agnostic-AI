#!/usr/bin/env node
// Global guard: make the main loop justify a subagent spawn against the cost of
// doing the work inline.
//
// Why this exists: a one-line edit delegated to a Claude Code subagent cost
// 77,000 tokens (2026-09-15). The "under ~10 tool calls, stay in the main loop"
// rule in agnostic-rules.md was judgment-enforced only, so nothing observed the
// dispatch before it happened. agent-model-guard checks WHICH model, the
// capability graph checks WHO may call WHOM; neither asks whether the spawn is
// worth its overhead at all.
//
// What it does NOT do: predict the real cost. A PreToolUse hook sees only
// tool_input (prompt, subagent_type, model) — never the files, never the
// result. So it does not guess; it makes the dispatch declare its own scope and
// checks that declaration against a break-even model, then logs declared-vs-
// actual so the model's constants get fitted from real data rather than vibes
// (tools/subagent-budget/calibrate.cjs).
//
// Contract: every Agent/Task dispatch carries a scope tag in its prompt:
//
//     # EST: 12 calls, 4 files
//
// Either field may be omitted ("# EST: 12 calls" is fine). Missing tag, or a
// declared scope below break-even, denies with the arithmetic shown.
// Override for one dispatch: put `# SPAWN_OK: <why>` in the prompt.
// Session off switch: SUBAGENT_BUDGET_GUARD=off
//
// Anti-thrash: the identical dispatch signature is denied at most once per
// session. A second attempt passes with the reason recorded. This is central to
// the design, not a leak — the fable-delegate-guard log showed a model
// treats a deny as a transient error and retries, producing 266 shell denials
// and edit denials retried five to seven times on one file. One correction
// informs the routing decision; a wall just burns tokens.

const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

if (String(process.env.SUBAGENT_BUDGET_GUARD || "").toLowerCase() === "off") process.exit(0);

// ─────────────────────────────────────────── cost model
//
// Every constant below is an observation with a date, and every one is an input
// the calibration script re-fits from CostClaw's measured subagent sessions.
// Override any of them with env so a bad constant is a config change, not an
// edit to a frozen guard.
const num = (envKey, fallback) => {
  const v = parseFloat(process.env[envKey] || "");
  return Number.isFinite(v) && v > 0 ? v : fallback;
};

// Spawn overhead: tokens burned before the subagent's first tool call.
// Measured 2026-09-02 on this machine: lean types ~17k, general-purpose ~60k.
const LEAN_SPAWN = num("SBG_LEAN_SPAWN", 17000);
const FULL_SPAWN = num("SBG_FULL_SPAWN", 60000);
// Average tokens a single tool result contributes to whichever context holds it.
const RESULT_TOKENS = num("SBG_RESULT_TOKENS", 2000);
// How many further turns the main loop runs after this work lands in its
// context. Every one of them re-sends it.
const TURNS_REMAINING = num("SBG_TURNS_REMAINING", 20);
// Re-sent context is usually a cache read, not a fresh input charge.
const CACHE_DISCOUNT = num("SBG_CACHE_DISCOUNT", 0.1);
// A file edited inline also lands in main context, roughly one result's worth.
const FILE_TOKENS = num("SBG_FILE_TOKENS", 2000);
// Warm prefix window: per Anthropic caching docs, cache TTL refreshes on each
// request that hits the cache (counted from start of request). Within 5 minutes
// of any earlier subagent request, a spawn hits cached prefix instead of paying
// full arrival write overhead. (Confirmed by PrimeLine's logs 2026-09-15).
const WARM_WINDOW_MS = num("SBG_WARM_WINDOW_MS", 5 * 60 * 1000);
// Effective multiplier on spawn overhead when warm (cache read discount on common prefix)
const WARM_DISCOUNT = num("SBG_WARM_DISCOUNT", 0.25);

// Lean subagent types carry no skills, MCP or Artifact tooling.
const LEAN_TYPES = new Set([
  "haiku-scout",
  "sonnet-implementer",
  "opus-owner",
  "explore",
  "advisor",
]);

// Types this guard does not gate at all:
// - advisor: upward consultation, explicitly never capped (agnostic-rules.md).
//   A blocked consultation becomes a guess, and a guess costs more than advice.
// - statusline-setup: harness plumbing, not work with a scope to declare.
const EXEMPT_TYPES = new Set(["advisor", "statusline-setup"]);

const STATE_FILE = path.join(__dirname, ".subagent-budget-denials.json");
const SPAWNS_FILE = path.join(__dirname, ".subagent-budget-spawns.json");
const LOG_FILE = path.join(__dirname, ".subagent-budget-log.jsonl");

// ─────────────────────────────────────────── input

let data;
try {
  data = JSON.parse(fs.readFileSync(0, "utf8"));
} catch {
  process.exit(0);
}

const toolName = data.tool_name || "";
if (toolName !== "Agent" && toolName !== "Task") process.exit(0);

const ti = data.tool_input || {};
const sessionId = String(data.session_id || "unknown");
const subagentType = String(ti.subagent_type || "").toLowerCase();
const model = String(ti.model || "").toLowerCase();
const prompt = String(ti.prompt || "");

if (EXEMPT_TYPES.has(subagentType)) process.exit(0);

// PostToolUse / completion handling:
// When a subagent completes, its final turn made a request. Record this completion
// as the latest active cache-hit time so subsequent spawns recognize a warm prefix.
const isPost =
  process.argv.includes("--post") ||
  data.hook_event_name === "PostToolUse" ||
  data.tool_result !== undefined ||
  data.tool_response !== undefined;

if (isPost) {
  recordActivity(subagentType, "complete");
  log({ decision: "complete", type: subagentType || "(default)", model });
  process.exit(0);
}

// Mods migration (2026-09-16): when ~/.claude/mods/harness-mods owns routing for this session it
// prices the spawn against a MEASURED prior and applies the same break-even + anti-thrash rule
// itself; this pre-spawn check yields. --post above keeps feeding the calibration log either way.
// In shadow_mod this guard enforces and records its verdict beside the Mod's.
let shadowBudget = null;
try {
  const mm = require("./lib/mods-mode.cjs");
  const v = mm.standsDown("routing", sessionId);
  mm.log("subagent-budget-guard", sessionId, v);
  if (v.standDown) process.exit(0);
  if (v.mode === "shadow_mod") {
    const key = mm.signatureOf(sessionId, String(ti.subagent_type || "general-purpose"), prompt, ti.model);
    shadowBudget = (decision, reasons) => mm.recordShadow(sessionId, { subsystem: "routing", action: "Agent " + String(ti.subagent_type || "general-purpose"), key, mode: v.mode, decision, requestedValue: model || null, reasonCodes: ["subagent-budget-guard", ...reasons], enforced: true });
  }
} catch {}

// ─────────────────────────────────────────── helpers

function emit(obj) {
  process.stdout.write(JSON.stringify(obj));
}

function log(entry) {
  try {
    fs.appendFileSync(
      LOG_FILE,
      JSON.stringify({ ts: new Date().toISOString(), session: sessionId, ...entry }) + "\n"
    );
  } catch {}
}

function allow(entry) {
  recordActivity(subagentType, "spawn");
  if (shadowBudget) shadowBudget("allow", [String(entry.reason || "")]);
  log({ decision: "allow", ...entry });
  process.exit(0);
}

function deny(reason, entry) {
  if (shadowBudget) shadowBudget("deny", [entry && entry.est ? "below-break-even" : "no-est-tag"]);
  log({ decision: "deny", ...entry });
  emit({
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: reason,
    },
  });
  process.exit(0);
}

// Dispatch signature: same session, same type, same prompt => same attempt.
// Used only for the one-deny-per-signature anti-thrash rule.
function signature() {
  return crypto
    .createHash("sha1")
    .update(sessionId + " " + subagentType + " " + prompt)
    .digest("hex")
    .slice(0, 16);
}

function readDenials() {
  try {
    const d = JSON.parse(fs.readFileSync(STATE_FILE, "utf8"));
    return d && typeof d === "object" ? d : {};
  } catch {
    return {};
  }
}

function alreadyDenied(sig) {
  return Boolean(readDenials()[sig]);
}

function recordDenial(sig) {
  const d = readDenials();
  const now = Date.now();
  for (const k of Object.keys(d)) {
    if (now - (d[k] || 0) > 24 * 3600 * 1000) delete d[k]; // prune
  }
  d[sig] = now;
  try {
    fs.writeFileSync(STATE_FILE, JSON.stringify(d));
  } catch {}
}

function readSpawns() {
  try {
    const s = JSON.parse(fs.readFileSync(SPAWNS_FILE, "utf8"));
    return s && typeof s === "object" ? s : {};
  } catch {
    return {};
  }
}

function recordActivity(type, action) {
  const s = readSpawns();
  const now = Date.now();
  const key = type || "(default)";
  for (const k of Object.keys(s)) {
    const val = s[k];
    const ts = typeof val === "number" ? val : (val && (val.active || val.spawn)) || 0;
    if (now - ts > 24 * 3600 * 1000) delete s[k]; // prune
  }
  const entry =
    s[key] && typeof s[key] === "object"
      ? s[key]
      : { spawn: typeof s[key] === "number" ? s[key] : 0, active: 0 };
  if (action === "spawn") entry.spawn = now;
  entry.active = now;
  s[key] = entry;

  const star =
    s["*"] && typeof s["*"] === "object"
      ? s["*"]
      : { spawn: typeof s["*"] === "number" ? s["*"] : 0, active: 0 };
  if (action === "spawn") star.spawn = now;
  star.active = now;
  s["*"] = star;

  try {
    fs.writeFileSync(SPAWNS_FILE, JSON.stringify(s));
  } catch {}
}

function getLatestSubagentMtime(transcriptPath) {
  if (!transcriptPath || typeof transcriptPath !== "string") return 0;
  try {
    const sessionDir = path.dirname(transcriptPath);
    const sessionBase = path.basename(transcriptPath, ".jsonl");
    const subagentsDir = path.join(sessionDir, sessionBase, "subagents");
    if (!fs.existsSync(subagentsDir)) return 0;
    const files = fs.readdirSync(subagentsDir);
    let max = 0;
    for (const f of files) {
      if (!f.endsWith(".jsonl")) continue;
      const st = fs.statSync(path.join(subagentsDir, f));
      if (st.mtimeMs > max) max = st.mtimeMs;
    }
    return max;
  } catch {
    return 0;
  }
}

function getLastActive(type, transcriptPath) {
  const s = readSpawns();
  const key = type || "(default)";
  const getTs = (entry) => {
    if (!entry) return 0;
    if (typeof entry === "number") return entry;
    return Math.max(entry.active || 0, entry.spawn || 0);
  };
  const typeTs = getTs(s[key]);
  const starTs = getTs(s["*"]);
  const transcriptTs = getLatestSubagentMtime(transcriptPath);
  return Math.max(typeTs, starTs, transcriptTs);
}

// ─────────────────────────────────────────── scope declaration
//
// Lenient on purpose: "# EST: 12 calls, 4 files", "#EST 12 calls", "# EST: 3
// files" and "# EST: 12 tool calls / 4 files" all parse. A tag that names
// neither calls nor files is treated as absent — an unparseable declaration is
// not a declaration.
function parseEst(text) {
  const tag = /#\s*EST\s*:?\s*([^\n]*)/i.exec(text);
  if (!tag) return null;
  const body = tag[1];
  const calls = /(\d+)\s*(?:tool\s*)?calls?/i.exec(body);
  const files = /(\d+)\s*files?/i.exec(body);
  if (!calls && !files) return null;
  return {
    calls: calls ? parseInt(calls[1], 10) : 0,
    files: files ? parseInt(files[1], 10) : 0,
    raw: body.trim(),
  };
}

const override = /#\s*SPAWN_OK\s*:\s*(\S[^\n]*)/i.exec(prompt);
const sig = signature();
const base = { type: subagentType || "(default)", model, sig };

if (override) {
  allow({ ...base, reason: "SPAWN_OK override", why: override[1].trim() });
}

// ─────────────────────────────────────────── the arithmetic
//
// Spawning costs its overhead up front, and the subagent pays for its own tool
// results in its own context.
//   spawn  = OVERHEAD + calls * RESULT_TOKENS
// Working inline costs nothing up front, but every result lands in main context
// and is re-sent for the rest of the session.
//   inline = (calls * RESULT_TOKENS + files * FILE_TOKENS)
//            * (1 + TURNS_REMAINING * CACHE_DISCOUNT)
// Spawn wins once inline's re-send tail exceeds the spawn overhead.

const isLean = LEAN_TYPES.has(subagentType);
const baseOverhead = isLean ? LEAN_SPAWN : FULL_SPAWN;

// Check warm cache prefix state: was any subagent active within WARM_WINDOW_MS?
// Anthropic cache TTL refreshes on each request that hits cache (counted from request start).
const lastActive = getLastActive(subagentType, data.transcript_path);
const deltaMs = lastActive > 0 ? Date.now() - lastActive : Infinity;
const isWarm = deltaMs < WARM_WINDOW_MS;
const overhead = isWarm ? Math.round(baseOverhead * WARM_DISCOUNT) : baseOverhead;
const deltaMin = Number.isFinite(deltaMs) ? (deltaMs / 60000).toFixed(1) : null;
const warmHint = isWarm
  ? ` (warm cache: last subagent request was ${deltaMin}m ago, overhead discounted from ~${Math.round(baseOverhead / 1000)}k to ~${Math.round(overhead / 1000)}k)`
  : (lastActive > 0 ? ` (cold cache: last subagent request was ${deltaMin}m ago, outside the 5m window)` : "");

const amplification = 1 + TURNS_REMAINING * CACHE_DISCOUNT;

function costs(calls, files) {
  const spawn = overhead + calls * RESULT_TOKENS;
  const inline = (calls * RESULT_TOKENS + files * FILE_TOKENS) * amplification;
  return { spawn: Math.round(spawn), inline: Math.round(inline) };
}

// Smallest call count that pays for the spawn with zero files touched.
const breakEvenCalls = Math.ceil(
  overhead / (RESULT_TOKENS * amplification - RESULT_TOKENS)
);

const typeLabel = subagentType ? `"${subagentType}"` : "the default type";
const leanHint = isLean
  ? ""
  : ` ${typeLabel} is not a lean type, so it carries the ~${Math.round(
      baseOverhead / 1000
    )}k base spawn overhead rather than ~${Math.round(
      LEAN_SPAWN / 1000
    )}k. A lean type (haiku-scout, sonnet-implementer, opus-owner) breaks even sooner.`;

const est = parseEst(prompt);

if (!est) {
  if (alreadyDenied(sig)) {
    allow({ ...base, isWarm, deltaMs, reason: "no EST tag, second attempt (anti-thrash)" });
  }
  recordDenial(sig);
  deny(
    "BLOCKED: this Agent dispatch declares no scope, so nothing checked it against the cost of doing the work inline. " +
      `A ${typeLabel} spawn burns ~${Math.round(
        overhead / 1000
      )}k tokens before its first tool call${warmHint}; on this machine a one-line edit delegated to a subagent cost 77,000 tokens. ` +
      `Break-even for ${typeLabel} is about ${breakEvenCalls} tool calls.` +
      leanHint +
      " Add a scope tag to the prompt and re-issue, e.g. `# EST: 12 calls, 4 files`. " +
      "If the work genuinely cannot be scoped ahead of time, say so with `# SPAWN_OK: <why>` instead.",
    { ...base, est: null, isWarm, deltaMs }
  );
}

const { spawn, inline } = costs(est.calls, est.files);

if (spawn <= inline) {
  allow({
    ...base,
    est,
    isWarm,
    deltaMs,
    spawn,
    inline,
    reason: "declared scope clears break-even",
  });
}

if (alreadyDenied(sig)) {
  allow({ ...base, est, isWarm, deltaMs, spawn, inline, reason: "below break-even, second attempt (anti-thrash)" });
}
recordDenial(sig);
deny(
  `BLOCKED: the declared scope (${est.raw}) does not pay for a spawn. ` +
    `Spawning ${typeLabel}: ~${overhead.toLocaleString()} overhead${warmHint} + ${est.calls} calls x ${RESULT_TOKENS.toLocaleString()} = ~${spawn.toLocaleString()} tokens. ` +
    `Doing it in the main loop: (${est.calls} calls x ${RESULT_TOKENS.toLocaleString()} + ${est.files} files x ${FILE_TOKENS.toLocaleString()}) x ${amplification} re-send = ~${inline.toLocaleString()} tokens. ` +
    `Inline is cheaper by ~${(spawn - inline).toLocaleString()} tokens.` +
    leanHint +
    ` Do this work directly with your own tools. Break-even for ${typeLabel} is about ${breakEvenCalls} tool calls — ` +
    "re-issue as a spawn only if the real scope is bigger than declared, or use `# SPAWN_OK: <why>` if context isolation is the point rather than token count.",
  { ...base, est, isWarm, deltaMs, spawn, inline }
);
