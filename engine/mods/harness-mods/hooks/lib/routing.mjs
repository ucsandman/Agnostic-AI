// routing.mjs — the supervisor's routing policy as one pure function over the agent.spawn event.
//
// Replaces, in `mod` mode, the Agent/Task branch of agent-model-guard.cjs (explicit model + Fable
// cap), capability-graph-guard.cjs's PreToolUse verdict (downward-only graph, advisor one rung up,
// Haiku is a leaf) and subagent-budget-guard.cjs's pre-spawn check (# EST: break-even against a
// PRIOR the ledger learns). Rewrite over deny: a violation is corrected onto the graph and explained
// to the model; deny is reserved for what no rewrite fixes (a Haiku parent, an undeclared scope
// below break-even on its first attempt). Reason codes are stable strings for the audit log.

export const RUNG_NAME = ["?", "haiku", "sonnet", "opus", "fable"];
export const ADVISOR_TYPES = ["advisor"];
export const FORK_TYPES = ["fork"];
export const DEFAULT_FABLE_CAP = 3;
// Subagent types whose definition pins a non-Fable model; safe without an explicit model (agent-model-guard).
export const PINNED_SAFE_SUBAGENTS = ["codex:codex-rescue"];
// Never gated by the budget check (subagent-budget-guard EXEMPT_TYPES).
export const BUDGET_EXEMPT_TYPES = ["advisor", "statusline-setup"];
// Tools a subagent needs to EXIT; a per-agent cap must never deny these (DOGFOOD finding 4: denying
// SubagentHandback produced four retries of the exit tool). Audit 2026-09-16 of claude-code.d.ts:
// SubagentHandback is the only exit tool named; TaskStop/TaskOutput are parent-side. Keep the list
// data so a new build's exit tool is a one-line change.
export const EXIT_TOOLS = ["SubagentHandback"];

export function rungOf(model) {
  if (!model) return 0;
  const m = String(model).toLowerCase();
  if (m.indexOf("fable") >= 0 || m.indexOf("mythos") >= 0) return 4;
  if (m.indexOf("opus") >= 0) return 3;
  if (m.indexOf("sonnet") >= 0) return 2;
  if (m.indexOf("haiku") >= 0) return 1;
  return 0;
}

export function parseEst(text) {
  const tag = /#\s*EST\s*:?\s*([^\n]*)/i.exec(String(text || ""));
  if (!tag) return null;
  const body = tag[1];
  const calls = /(\d+)\s*(?:tool\s*)?calls?/i.exec(body);
  const files = /(\d+)\s*files?/i.exec(body);
  if (!calls && !files) return null;
  return { calls: calls ? parseInt(calls[1], 10) : 0, files: files ? parseInt(files[1], 10) : 0, raw: body.trim() };
}

export function spawnOk(text) {
  const m = /#\s*SPAWN_OK\s*:\s*(\S[^\n]*)/i.exec(String(text || ""));
  return m ? m[1].trim() : null;
}

/**
 * The capability-graph half. Pure over the event.
 * Returns { action: "pass"|"rewrite"|"deny", model, reason, reasons[], parentRung, reqRung, targetRung, fableCounted }.
 */
export function decideGraph(e, ctx) {
  const fableUsed = (ctx && ctx.fableUsed) || 0;
  const fableCap = ctx && typeof ctx.fableCap === "number" ? ctx.fableCap : DEFAULT_FABLE_CAP;
  const reasons = [];
  const type = e.subagentType || "general-purpose";
  const requested = e.model;
  const reqRung = rungOf(requested);
  let parentRung = rungOf(e.parentModel);
  const base = { model: requested, reason: "", reasons, parentRung, reqRung, fableCounted: false };

  if (PINNED_SAFE_SUBAGENTS.indexOf(String(type).toLowerCase()) >= 0) {
    reasons.push("pinned-safe-subagent");
    return { ...base, action: "pass", targetRung: reqRung };
  }
  if (e.fork || FORK_TYPES.indexOf(type) >= 0) {
    reasons.push("fork-inherits-parent", "model-field-ignored-by-engine");
    if (parentRung === 4) { reasons.push("fork-counts-against-fable-cap"); base.fableCounted = true; }
    return { ...base, action: "pass", targetRung: parentRung };
  }
  if (parentRung === 0) { reasons.push("parent-model-unrecognised-assumed-opus"); parentRung = 3; base.parentRung = 3; }
  if (parentRung === 1) {
    reasons.push("haiku-is-a-leaf", "no-rewrite-can-fix-a-leaf");
    return { ...base, action: "deny", targetRung: 0, reason: "harness-mods routing: Haiku spawns nobody (capability graph: Haiku -> nobody). Do the work in this agent or report back to your caller." };
  }
  if (ADVISOR_TYPES.indexOf(type) >= 0) {
    const target = Math.min(4, parentRung + 1);
    reasons.push("advisor-upward-edge", "advisor-uncapped");
    if (!reqRung) reasons.push(requested ? "model-unrecognised" : "model-undeclared");
    else if (reqRung !== target) reasons.push("advisor-model-overridden");
    reasons.push("set-one-rung-above-parent");
    return { ...base, action: reqRung === target ? "pass" : "rewrite", model: RUNG_NAME[target], targetRung: target };
  }

  let target = reqRung;
  if (!reqRung) {
    reasons.push(requested ? "model-unrecognised" : "model-undeclared");
    target = parentRung - 1;
  }
  if (target === 4 && fableUsed >= fableCap) {
    reasons.push("fable-cap-" + fableCap + "-per-session");
    target = 3;
  }
  if (target >= parentRung) {
    reasons.push(target === parentRung ? "peer-edge-not-in-graph" : "upward-edge-not-in-graph", "downgraded-to-highest-child-rung");
    target = parentRung - 1;
  }
  if (target === reqRung && reqRung > 0) reasons.push("edge-in-graph");
  if (target === 4) base.fableCounted = true;
  return { ...base, action: target === reqRung ? "pass" : "rewrite", model: RUNG_NAME[target], targetRung: target };
}

/**
 * The budget half (subagent-budget-guard arithmetic with a learned prior).
 *   prior      tokens the spawn costs before its first tool call (measured median or the shipped constant)
 *   isWarm     a subagent request happened inside the warm window
 *   deniedOnce this exact signature was already denied this session (anti-thrash)
 * Returns { action: "pass"|"deny", reasons[], est, declared, inline, spawn, breakEvenCalls, reason }.
 */
export const BUDGET = { RESULT_TOKENS: 2000, FILE_TOKENS: 2000, TURNS_REMAINING: 20, CACHE_DISCOUNT: 0.1, WARM_DISCOUNT: 0.25 };

export function decideBudget(e, ctx) {
  const reasons = [];
  const type = String(e.subagentType || "general-purpose");
  const prompt = String(e.prompt || "");
  if (BUDGET_EXEMPT_TYPES.indexOf(type.toLowerCase()) >= 0) { reasons.push("budget-exempt-type"); return { action: "pass", reasons, est: null }; }
  const ok = spawnOk(prompt);
  const est = parseEst(prompt);
  const overhead = Math.round((ctx.prior || 0) * (ctx.isWarm ? BUDGET.WARM_DISCOUNT : 1));
  const amplification = 1 + BUDGET.TURNS_REMAINING * BUDGET.CACHE_DISCOUNT;
  const breakEvenCalls = Math.ceil(overhead / (BUDGET.RESULT_TOKENS * amplification - BUDGET.RESULT_TOKENS));
  if (ok) { reasons.push("spawn-ok-override"); return { action: "pass", reasons, est, why: ok, overhead, breakEvenCalls }; }
  if (!est) {
    if (ctx.deniedOnce) { reasons.push("no-est-tag", "anti-thrash-second-attempt"); return { action: "pass", reasons, est: null, overhead, breakEvenCalls }; }
    reasons.push("no-est-tag");
    return {
      action: "deny", reasons, est: null, overhead, breakEvenCalls,
      reason: "BLOCKED: this Agent dispatch declares no scope, so nothing checked it against the cost of doing the work inline. A \"" + type + "\" spawn costs ~" + Math.round(overhead / 1000) + "k tokens before its first tool call (" + (ctx.priorSource || "prior") + "); break-even is about " + breakEvenCalls + " tool calls. Add `# EST: <n> calls, <n> files` to the prompt and re-issue, or `# SPAWN_OK: <why>` if the scope genuinely cannot be known up front.",
    };
  }
  const spawn = Math.round(overhead + est.calls * BUDGET.RESULT_TOKENS);
  const inline = Math.round((est.calls * BUDGET.RESULT_TOKENS + est.files * BUDGET.FILE_TOKENS) * amplification);
  if (spawn <= inline) { reasons.push("declared-scope-clears-break-even"); return { action: "pass", reasons, est, spawn, inline, overhead, breakEvenCalls }; }
  if (ctx.deniedOnce) { reasons.push("below-break-even", "anti-thrash-second-attempt"); return { action: "pass", reasons, est, spawn, inline, overhead, breakEvenCalls }; }
  reasons.push("below-break-even");
  return {
    action: "deny", reasons, est, spawn, inline, overhead, breakEvenCalls,
    reason: "BLOCKED: the declared scope (" + est.raw + ") does not pay for a spawn. Spawning \"" + type + "\": ~" + overhead.toLocaleString() + " overhead (" + (ctx.priorSource || "prior") + ") + " + est.calls + " calls × " + BUDGET.RESULT_TOKENS.toLocaleString() + " = ~" + spawn.toLocaleString() + " tokens; inline: ~" + inline.toLocaleString() + " tokens. Do it directly, or re-issue with `# SPAWN_OK: <why>` if context isolation is the point.",
  };
}

/** The whole routing verdict: graph first (it may deny), then budget. */
export function decide(e, ctx) {
  const graph = decideGraph(e, ctx);
  if (graph.action === "deny") return { action: "deny", model: graph.model, reason: graph.reason, reasons: graph.reasons, graph, budget: null };
  const budget = decideBudget(e, ctx);
  if (budget.action === "deny") return { action: "deny", model: graph.model, reason: budget.reason, reasons: [...graph.reasons, ...budget.reasons], graph, budget };
  return { action: graph.action, model: graph.model, reason: "", reasons: [...graph.reasons, ...budget.reasons], graph, budget };
}

/** Same-session, same-type, same-prompt signature for anti-thrash (matches subagent-budget-guard's). */
export function signatureOf(sessionId, type, prompt, model) {
  // FNV-1a 32-bit over the string; no crypto in a hooks module. The requested model is part of the
  // key so two spawns of the same type+prompt with different models pair separately (seen 2026-09-16).
  const s = String(sessionId) + " " + String(type || "") + " " + String(model || "") + " " + String(prompt || "");
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; }
  return h.toString(16).padStart(8, "0");
}
