// ════════════════════════════════════════════════════════════════════════════
// PRODUCTION GUARD (prodguard) — SECTION B: HOOK GLUE.
//
// This file is the transport. It knows about `$`, `next`, tool.call, tool.check,
// ui.render and nothing about policy. Every verdict comes from ./policy-core.ts,
// which never mentions `$` or `next` (grep it — that is the whole point).
//
//   session.start  → resolve project + environment once, from <repo>/.offlocal/
//                    state.json or the shipped demo registry. Register /prodguard.
//   tool.call      → classify → capability → evaluatePolicy → allow / deny /
//                    $.ui.ask{Allow once, Deny, Contain}. Decides BEFORE the
//                    command runs; a blocked command never starts.
//   tool.check     → mirror the same verdict, so a block holds even if another
//                    plugin answered the tool.call itself.
//   ui.render      → PROJECT · ENV · live-mode band above the prompt, red in prod.
//   command.run    → /prodguard prints context, rules, last 10 decisions.
//
// Nothing here performs a real external action. The guard answers before next().
// ════════════════════════════════════════════════════════════════════════════

import {
  decide,
  resolveContextFrom,
  containedCommand,
  sanitizeDashclawText,
  capabilityLabel,
} from "./policy-core.ts";

const PLUGIN_DIR = "C:/Projects/claude-mods-rnd/prototypes/prodguard/";
const AUDIT_DIR = PLUGIN_DIR + "audit/";
const DEMO_STATE = PLUGIN_DIR + "demo-state.json";

const GOVERNED_TOOLS = ["Bash", "Write", "Edit", "NotebookEdit"];

const state = {
  sessionId: "",
  ctx: null,            // resolved {project, environment, mapping, rules, ...}
  source: "none",       // where the registry came from
  degraded: true,       // true until a registry resolves; the one fail-open path
  rows: [],             // audit rows, newest last
  dirty: false,
  counts: { allow: 0, block: 0, ask: 0, contained: 0, denied: 0 },
  last: "",
};

// ── helpers that take `$` must be TOP-LEVEL function declarations: the loader's
//    static scan only accepts `$` as a call-site receiver or as a top-level
//    function's parameter. ────────────────────────────────────────────────────

async function loadRegistry($) {
  let repoRoot = "";
  try {
    const repo = await $.session.repo();
    if (repo && repo.root) repoRoot = String(repo.root).replace(/\\/g, "/");
  } catch (err) { /* not a repo; fall through to the demo registry */ }

  if (repoRoot) {
    const repoState = repoRoot.replace(/\/+$/, "") + "/.offlocal/state.json";
    try {
      if (await $.fs.exists(repoState)) {
        const text = await $.fs.read(repoState);
        const parsed = JSON.parse(text);
        const ctx = resolveContextFrom(parsed);
        if (ctx) { state.ctx = ctx; state.source = repoState; state.degraded = false; return; }
        state.source = repoState + " (no project/environment registered — using the demo registry)";
      }
    } catch (err) {
      state.source = repoState + " (unreadable: " + String(err && err.message ? err.message : err) + ")";
    }
  }

  try {
    const text = await $.fs.read(DEMO_STATE);
    const ctx = resolveContextFrom(JSON.parse(text));
    if (ctx) {
      state.ctx = ctx;
      state.source = DEMO_STATE + " (demo registry: no .offlocal/state.json in this repo)";
      state.degraded = false;
      return;
    }
  } catch (err) {
    state.source = "demo registry unreadable: " + String(err && err.message ? err.message : err);
  }
  state.degraded = true;
}

async function flushAudit($) {
  if (!state.dirty || !state.sessionId) return;
  state.dirty = false;
  try {
    const text = state.rows.map(function (r) { return JSON.stringify(r); }).join("\n") + "\n";
    await $.fs.write(AUDIT_DIR + state.sessionId + ".jsonl", text);
  } catch (err) { /* never let the audit break the guard */ }
}

// One JSONL line per decision, in DashClaw's `guard_decisions` vocabulary
// (app/lib/guard/types.ts GuardDecisionInsert + app/lib/validate.js:289
// GUARD_INPUT_SCHEMA). Every free-text field has already been through
// sanitizeDashclawText, so no secret can reach this file.
async function audit($, row) {
  state.rows.push(row);
  state.dirty = true;
  await flushAudit($);
}

function bandColor() {
  if (state.degraded || !state.ctx) return "yellow";
  return state.ctx.environment.isProduction ? "red" : "green";
}

function bandText() {
  if (state.degraded || !state.ctx) return "PRODGUARD  NO REGISTRY — passing every call through (fail-open, see README)";
  const c = state.ctx;
  const live = c.mapping && c.mapping.resource && c.mapping.resource.mode === "live";
  const parts = [
    c.project.slug,
    c.environment.name.toUpperCase() + (c.environment.isProduction ? " (production)" : ""),
    "live-mode " + (live ? "ON" : "off"),
    c.mappedProvider + (c.resourceLabel ? ":" + c.resourceLabel : ""),
  ];
  const tally = "allow " + state.counts.allow + " · block " + state.counts.block +
    " · asked " + state.counts.ask + " · contained " + state.counts.contained +
    " · denied " + state.counts.denied;
  return "PRODGUARD  " + parts.join("  ·  ") + "   [" + tally + "]";
}

function short(v, n) {
  let s;
  try { s = typeof v === "string" ? v : JSON.stringify(v); } catch (err) { s = String(v); }
  s = (s || "").replace(/\s+/g, " ");
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

// The verdict → a DashClaw five-value decision word.
function dashclawDecision(effect) {
  if (effect === "allow") return "allow";
  if (effect === "block") return "block";
  return "require_approval";
}

function denialText(v) {
  return "PRODGUARD " + v.effect.toUpperCase() + ": " + v.reason +
    "\n  project=" + state.ctx.project.slug +
    " environment=" + state.ctx.environment.name +
    " capability=" + capabilityLabel(v.capability) +
    " provider=" + v.provider +
    "\n  evidence: " + v.evidence.derived_action_type +
    " base_risk=" + v.evidence.base_risk +
    " flags=[" + v.evidence.flags.join(",") + "]" +
    " risk_score=" + v.risk_score +
    "\n  rule: " + v.source +
    "\n  This is enforced by a function hook before the command runs, not by instructions." +
    " Do not retry it through another tool or another phrasing.";
}

export const register = (on, options) => {

  on("session.start", async ($, e, next) => {
    state.sessionId = await $.session.id();
    await loadRegistry($);
    await $.command.register({
      name: "prodguard",
      description: "PRODUCTION GUARD: resolved project/environment, the policy rules in force, and the last 10 decisions",
      immediate: true,
    });
    if (state.degraded) {
      $.ui.log("⟦prodguard⟧ NO REGISTRY (" + state.source + ") — every call passes through ungoverned");
    } else {
      const c = state.ctx;
      $.ui.log("⟦prodguard⟧ armed · " + c.project.slug + " · " + c.environment.name +
        (c.environment.isProduction ? " (PRODUCTION)" : "") +
        " · provider=" + c.mappedProvider +
        " · " + c.rules.length + " explicit rules + offlocal defaults · registry: " + state.source);
      if (c.fellBackToProduction) {
        $.ui.log("⟦prodguard⟧ the registry names no current environment; failing closed to the production one");
      }
      $.ui.status("prodguard: " + c.project.slug + "/" + c.environment.name);
    }
    return next(e);
  });

  // ── THE ENFORCEMENT POINT ────────────────────────────────────────────────
  // Every governed tool call is decided here, before the tool runs. `vercel
  // deploy --prod`, `git push --force`, `psql … DELETE` never start.
  on("tool.call", { tool: GOVERNED_TOOLS }, async ($, e, next) => {
    if (state.degraded || !state.ctx) return next(e);

    let verdict = null;
    try {
      const { tool, tool_use_id, agentId, ...input } = e;
      verdict = decide(state.ctx, e.tool, input);
    } catch (err) {
      $.ui.log("⟦prodguard⟧ classifier threw, failing closed: " + String(err && err.message ? err.message : err));
      return { deny: "PRODGUARD: the policy core threw while classifying this call, so it was refused (fail closed)." };
    }
    if (!verdict) return next(e);

    const base = {
      ts: new Date().toISOString(),
      session_id: state.sessionId,
      agent_id: e.agentId ? String(e.agentId) : "main",
      tool: e.tool,
      tool_use_id: e.tool_use_id,
      action_type: verdict.action_type,
      derived_action_type: verdict.evidence.derived_action_type,
      risk_score: verdict.risk_score,
      evidence_total: verdict.evidence.evidence_total,
      evidence_flags: verdict.evidence.flags,
      evidence_modifiers: verdict.evidence.modifiers,
      decision: dashclawDecision(verdict.effect),
      policy_effect: verdict.effect,
      reason: verdict.reason,
      matched_policy: verdict.source,
      capability: verdict.capability,
      provider: verdict.provider,
      live: verdict.live,
      project: state.ctx.project.slug,
      environment: state.ctx.environment.name,
      environment_kind: state.ctx.environment.kind,
      systems_touched: verdict.systems_touched,
      reversible: verdict.reversible,
      command: verdict.subject,           // already sanitized in the core
    };

    if (verdict.effect === "allow") {
      state.counts.allow++;
      state.last = "allow " + short(verdict.subject, 50);
      await audit($, { ...base, outcome: "allowed" });
      return next(e);
    }

    if (verdict.effect === "block") {
      state.counts.block++;
      state.last = "BLOCK " + short(verdict.subject, 50);
      $.ui.log("⟦prodguard⟧ ✖ BLOCK " + verdict.action_type + " risk=" + verdict.risk_score + " · " + short(verdict.subject, 70));
      $.ui.toast("prodguard blocked a " + capabilityLabel(verdict.capability) + " in " + state.ctx.environment.name);
      $.ui.invalidate("ui.render");
      await audit($, { ...base, outcome: "blocked" });
      return { deny: denialText(verdict) };
    }

    // approval_required — the engine's own dialog, three ways out.
    state.counts.ask++;
    $.ui.log("⟦prodguard⟧ ⏸ APPROVAL REQUIRED " + verdict.action_type + " risk=" + verdict.risk_score + " · " + short(verdict.subject, 70));
    $.ui.status("prodguard: holding a " + capabilityLabel(verdict.capability) + " in " + state.ctx.environment.name);
    let answer = null;
    try {
      answer = await $.ui.ask(
        "PRODGUARD — " + state.ctx.project.slug + " / " + state.ctx.environment.name +
          ": " + capabilityLabel(verdict.capability) + " via " + e.tool + " — " + short(verdict.subject, 90) +
          ". " + verdict.reason + " Allow it?",
        ["Allow once", "Deny", "Contain (dry-run)"],
      );
    } catch (err) {
      // Headless (-p): $.ui.ask rejects because there is no one to ask. Fail closed.
      state.counts.denied++;
      state.last = "DENY(fail-closed) " + short(verdict.subject, 40);
      $.ui.status(undefined);
      $.ui.log("⟦prodguard⟧ ✖ no one to ask (headless) — failing closed");
      await audit($, {
        ...base,
        outcome: "denied_fail_closed",
        approval_channel: "unavailable",
        approval_error: String(err && err.message ? err.message : err),
      });
      return {
        deny: denialText(verdict) +
          "\n  Approval was required and there is no one to ask in this run (headless), so it was refused. Fail closed.",
      };
    }
    $.ui.status(undefined);

    if (answer.indexOf("Contain") === 0) {
      const rewritten = containedCommand(e.tool === "Bash" ? e.command : verdict.subject);
      state.counts.contained++;
      state.last = "CONTAIN " + short(verdict.subject, 40);
      $.ui.log("⟦prodguard⟧ ⇄ CONTAINED → " + rewritten);
      $.ui.invalidate("ui.render");
      await audit($, { ...base, decision: "allow_contained", outcome: "contained", contained_command: sanitizeDashclawText(rewritten) });
      if (e.tool === "Bash") return next({ ...e, command: rewritten });
      // A non-Bash act has no command to rewrite; containment degrades to a refusal.
      return { deny: denialText(verdict) + "\n  Containment is only wired for Bash in this prototype, so the call was refused." };
    }

    if (answer.indexOf("Deny") === 0) {
      state.counts.denied++;
      state.last = "DENY " + short(verdict.subject, 45);
      $.ui.log("⟦prodguard⟧ ✖ DENIED by the person");
      $.ui.invalidate("ui.render");
      await audit($, { ...base, decision: "block", outcome: "denied", approved_by: "person" });
      return { deny: denialText(verdict) + "\n  A person saw this call and refused it." };
    }

    state.counts.allow++;
    state.last = "allow-once " + short(verdict.subject, 40);
    $.ui.log("⟦prodguard⟧ ▶ allowed once by the person");
    $.ui.invalidate("ui.render");
    await audit($, { ...base, outcome: "allowed_once", approved_by: "person", answer: answer });
    return next(e);
  });

  // ── BELT AND BRACES ──────────────────────────────────────────────────────
  // tool.check is the engine's permission verdict as an event, and the last word
  // up the chain wins. Mirroring the block here means enforcement holds even if
  // another plugin answered the tool.call without calling next.
  on("tool.check", { tool: GOVERNED_TOOLS }, async ($, e, next) => {
    if (state.degraded || !state.ctx) return next(e);
    let verdict = null;
    try {
      verdict = decide(state.ctx, e.tool, e.input || {});
    } catch (err) {
      return next(e);
    }
    if (verdict && verdict.effect === "block") {
      return { decision: "deny", reason: "PRODGUARD: " + verdict.reason + " (" + verdict.source + ")" };
    }
    return next(e);
  });

  on("command.run", { command: "prodguard" }, async ($, e, next) => {
    await flushAudit($);
    if (state.degraded || !state.ctx) {
      return { text: "PRODGUARD — degraded.\nregistry: " + state.source + "\nEvery call is passing through ungoverned." };
    }
    const c = state.ctx;
    const live = c.mapping && c.mapping.resource && c.mapping.resource.mode === "live";
    const head = [
      "PRODGUARD — resolved ambient context",
      "  registry      " + state.source,
      "  project       " + c.project.name + " (" + c.project.slug + ", " + c.project.id + ")",
      "  environment   " + c.environment.name + "  kind=" + c.environment.kind +
        "  isProduction=" + c.environment.isProduction + (c.fellBackToProduction ? "   [failed closed: registry named none]" : ""),
      "  known envs    " + c.environments.map(function (x) { return x.name + "/" + x.kind; }).join(", "),
      "  provider      " + c.mappedProvider + (c.resourceLabel ? " → " + c.resourceLabel : "") + "   live-mode " + (live ? "ON" : "off"),
      "  audit         " + AUDIT_DIR + state.sessionId + ".jsonl",
      "",
      "POLICY RULES IN FORCE (explicit rules first, highest priority wins; then offlocal defaults)",
    ].join("\n");

    const rules = c.rules.length
      ? c.rules.slice().sort(function (a, b) { return b.priority - a.priority; }).map(function (r) {
          const m = r.match || {};
          const scope = Object.keys(m).map(function (k) { return k + "=" + m[k]; }).join(" ") || "*";
          return "  [" + String(r.priority).padStart(3) + "] " + r.effect.padEnd(17) + " " + scope + "\n        " + (r.description || r.id);
        }).join("\n")
      : "  (none — defaults only)";

    const defaults = [
      "",
      "DEFAULTS (offlocalai-mcp/src/policy.ts defaultDecision, ported verbatim)",
      "  destructive_sql  block everywhere      delete  block everywhere",
      "  purchase         approval_required always, and clamped so an allow rule cannot lower it",
      "  read             allow                 live write  approval_required",
      "  production write/deploy/env_change  approval_required   ·  non-production  allow",
      "",
      "LAST 10 DECISIONS",
    ].join("\n");

    const rows = state.rows.slice(-10).map(function (r) {
      return "  " + r.ts.slice(11, 19) + "  " + String(r.decision).padEnd(17) +
        " " + String(r.outcome).padEnd(19) +
        " risk=" + String(r.risk_score).padStart(3) +
        " " + r.capability.padEnd(16) +
        " " + short(r.command, 54) + "\n        " + r.matched_policy + " — " + short(r.reason, 96);
    }).join("\n");

    return {
      text: head + "\n" + rules + defaults + "\n" +
        (rows || "  (none yet)") +
        "\n\n  totals: allow=" + state.counts.allow + " block=" + state.counts.block +
        " asked=" + state.counts.ask + " contained=" + state.counts.contained +
        " denied=" + state.counts.denied + "  (" + state.rows.length + " audit rows)",
    };
  });

  on("ui.render", { component: "AbovePrompt", surface: "terminal" }, async ($, e, next) => {
    const { Box, Text } = $.ui.resolve(e);
    const color = bandColor();
    const width = Math.max(40, (e.props && e.props.bodyColumns ? e.props.bodyColumns : 80) - 4);
    return (
      <Box flexDirection="column" borderStyle="round" borderColor={color} paddingX={1}>
        <Text bold color={color} wrap="truncate-end">{bandText().slice(0, width)}</Text>
        {state.last ? <Text dimColor wrap="truncate-end">{("last: " + state.last).slice(0, width)}</Text> : null}
      </Box>
    );
  });

  on("turn.complete", async ($, e, next) => {
    await flushAudit($);
    return next(e);
  });
};
