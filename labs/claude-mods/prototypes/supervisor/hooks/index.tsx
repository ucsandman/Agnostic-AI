// SUBAGENT SUPERVISOR — routing and budget for subagents, as one hooks module.
//
// Replaces four classic PreToolUse guards (agent-model-guard, subagent-budget-guard,
// capability-graph-guard, fable-delegate-guard). All four reconstructed the same two invisible
// facts — who is calling, on what model — from transcript tails and registry files, and could
// only DENY. `agent.spawn` carries `parentModel` and a rewritable `model`, so this Mod corrects
// instead of refusing; per-agent `turn.step`/`turn.complete` usage turns the declared `# EST:`
// estimate into a measured one; `$.store` carries the fitted priors across sessions.
//
// Events hooked: session.start, agent.spawn, turn.step (streaming), turn.complete, tool.call,
// command.run{supervisor}, ui.render{AbovePrompt,terminal}.

const LOG_DIR = "C:/Projects/claude-mods-rnd/prototypes/supervisor/logs/";
const STORE_KEY = "supervisor.ledger";

// ---------------------------------------------------------------- capability graph
// Fable -> Opus/Sonnet/Haiku, Opus -> Sonnet/Haiku, Sonnet -> Haiku, Haiku -> nobody.
// Downward only; peers are not edges. The one upward edge is `advisor`, one rung ABOVE the parent.
const RUNG_NAME = ["?", "haiku", "sonnet", "opus", "fable"];
const ADVISOR_TYPES = ["advisor"];
const FORK_TYPES = ["fork"];
const FABLE_CAP = 3; // non-advisor fable spawns per session (advisor consultations are uncapped)

// ---------------------------------------------------------------- budget priors
// Constants inherited from subagent-budget-guard; they are only the PRIOR here — the ledger
// learns a running median per subagent type from observed usage and overrides them.
const LEAN_PRIOR = 17000;
const FULL_PRIOR = 60000;
const CALL_TOKENS = 2000;
const FILE_TOKENS = 2000;
const CACHE_DISCOUNT = 0.1;
const MAX_SAMPLES = 20;
// Never denied by the call cap: SubagentHandback is how a subagent returns its answer. Denying the
// exit door does not stop an over-budget agent, it makes it retry the handback (observed: 4 retries
// in evidence/03, the same "a deny reads as a transient error" pathology fable-delegate-guard logged).
const EXEMPT_TOOLS = ["SubagentHandback"];
const LEAN_TYPES = ["haiku-scout", "sonnet-implementer", "opus-owner", "advisor", "e2e-verifier", "Explore", "Plan", "statusline-setup", "security-reviewer", "fork"];

const state = {
  sessionId: "",
  maxCalls: 40,
  maxCallsSource: "default",
  agents: {},        // agentId -> ledger row
  order: [],         // agentIds in spawn order
  routes: [],        // routing decisions (the routing log)
  lastRoute: null,
  priors: {},        // subagentType -> { samples: number[], median: number }
  rows: [],          // JSONL rows
  dirty: false,
  t0: 0,
  usage: null,
  totals: { spawns: 0, rewrites: 0, denies: 0, passes: 0, fable: 0, overBudget: 0, mainTurns: 0, mainTokens: 0 },
};

// ---------------------------------------------------------------- pure helpers
function rungOf(model) {
  if (!model) return 0;
  const m = String(model).toLowerCase();
  if (m.indexOf("fable") >= 0) return 4;
  if (m.indexOf("opus") >= 0) return 3;
  if (m.indexOf("sonnet") >= 0) return 2;
  if (m.indexOf("haiku") >= 0) return 1;
  return 0;
}
function num(n) { return String(Math.round(n || 0)).replace(/\B(?=(\d{3})+(?!\d))/g, ","); }
function k(n) { return (Math.round((n || 0) / 100) / 10).toFixed(1) + "k"; }
function shortId(id) { return id ? String(id).slice(0, 8) : "-"; }
function clip(v, n) {
  let s;
  try { s = typeof v === "string" ? v : JSON.stringify(v); } catch (err) { s = String(v); }
  s = (s || "").replace(/\s+/g, " ");
  return s.length > n ? s.slice(0, n - 1) + "\u2026" : s;
}
function parseEst(prompt) {
  const m = /#\s*EST:\s*(\d+)\s*calls?\s*,\s*(\d+)\s*files?/i.exec(prompt || "");
  if (!m) return null;
  return { calls: Number(m[1]), files: Number(m[2]) };
}
function medianOf(arr) {
  const s = (arr || []).slice().sort(function (a, b) { return a - b; });
  const n = s.length;
  if (!n) return 0;
  return n % 2 ? s[(n - 1) / 2] : Math.round((s[n / 2 - 1] + s[n / 2]) / 2);
}
function isLean(type) { return LEAN_TYPES.indexOf(type) >= 0; }
function priorFor(type) {
  const p = state.priors[type];
  if (p && p.median > 0) return p.median;
  return isLean(type) ? LEAN_PRIOR : FULL_PRIOR;
}
function priorSource(type) {
  const p = state.priors[type];
  if (p && p.median > 0) return "learned n=" + p.samples.length;
  return isLean(type) ? "prior lean" : "prior full";
}
function weigh(u) {
  if (!u) return 0;
  return (u.input_tokens || 0) + (u.output_tokens || 0) + (u.cache_creation_input_tokens || 0)
    + Math.round(CACHE_DISCOUNT * (u.cache_read_input_tokens || 0));
}
// The subagent-budget-guard arithmetic, evaluated ONCE at spawn time and frozen on the ledger row:
// recomputing it later would price the declaration against a prior the same agent just moved.
function declaredCost(type, est) {
  if (!est) return null;
  return priorFor(type) + est.calls * CALL_TOKENS + est.files * FILE_TOKENS;
}
function charged(a) { return a.settled ? a.measured : a.reserved; }

// The whole routing policy, as one pure function over the agent.spawn input.
// Returns { action: "pass" | "rewrite" | "deny", model, reason, reasons[], parentRung, reqRung, targetRung }.
function decide(e, fableUsed) {
  const reasons = [];
  const type = e.subagentType || "general-purpose";
  const requested = e.model;
  const reqRung = rungOf(requested);
  let parentRung = rungOf(e.parentModel);

  if (e.fork || FORK_TYPES.indexOf(type) >= 0) {
    reasons.push("fork-inherits-parent");
    reasons.push("model-field-ignored-by-engine");
    return { action: "pass", model: requested, reason: "", reasons: reasons, parentRung: parentRung, reqRung: reqRung, targetRung: parentRung };
  }
  if (parentRung === 0) {
    reasons.push("parent-model-unrecognised-assumed-opus");
    parentRung = 3;
  }
  if (parentRung === 1) {
    reasons.push("haiku-is-a-leaf");
    reasons.push("no-rewrite-can-fix-a-leaf");
    return {
      action: "deny",
      model: requested,
      reason: "supervisor: haiku is a leaf in the capability graph (Haiku -> nobody); this loop may not spawn subagents.",
      reasons: reasons, parentRung: parentRung, reqRung: reqRung, targetRung: 0,
    };
  }
  if (ADVISOR_TYPES.indexOf(type) >= 0) {
    const target = Math.min(4, parentRung + 1);
    reasons.push("advisor-upward-edge");
    reasons.push("advisor-uncapped");
    if (!reqRung) reasons.push(requested ? "model-unrecognised" : "model-undeclared");
    else if (reqRung !== target) reasons.push("advisor-model-overridden");
    reasons.push("set-one-rung-above-parent");
    return {
      action: reqRung === target ? "pass" : "rewrite",
      model: RUNG_NAME[target], reason: "", reasons: reasons,
      parentRung: parentRung, reqRung: reqRung, targetRung: target,
    };
  }

  let target = reqRung;
  if (!reqRung) {
    reasons.push(requested ? "model-unrecognised" : "model-undeclared");
    target = parentRung - 1;
  }
  if (target === 4 && fableUsed >= FABLE_CAP) {
    reasons.push("fable-cap-" + FABLE_CAP + "-per-session");
    target = 3;
  }
  if (target >= parentRung) {
    reasons.push(target === parentRung ? "peer-edge-not-in-graph" : "upward-edge-not-in-graph");
    reasons.push("downgraded-to-highest-child-rung");
    target = parentRung - 1;
  }
  if (target === reqRung && reqRung > 0) reasons.push("edge-in-graph");
  return {
    action: target === reqRung ? "pass" : "rewrite",
    model: RUNG_NAME[target], reason: "", reasons: reasons,
    parentRung: parentRung, reqRung: reqRung, targetRung: target,
  };
}

function push(row) {
  state.rows.push(Object.assign({ at: Date.now() - state.t0 }, row));
  state.dirty = true;
}
function bumpAgent(agentId, usage) {
  const a = state.agents[agentId];
  if (!a) return;
  a.steps++;
  a.tokens += weigh(usage);
  state.dirty = true;
}
function settleAgent(e) {
  const a = state.agents[e.agentId];
  if (!a) return null;
  a.turns++;
  a.measured += weigh(e.usage);
  a.durationMs += e.durationMs || 0;
  a.settled = true;
  a.reason = e.reason;
  const p = state.priors[a.type] || { samples: [], median: 0 };
  p.samples.push(a.measured);
  if (p.samples.length > MAX_SAMPLES) p.samples.shift();
  p.median = medianOf(p.samples);
  state.priors[a.type] = p;
  state.dirty = true;
  return a;
}
function liveAgents() {
  return state.order.map(function (id) { return state.agents[id]; }).filter(function (a) { return a && !a.settled; });
}
function totalsLine() {
  let reserved = 0, measured = 0;
  state.order.forEach(function (id) {
    const a = state.agents[id];
    if (!a) return;
    reserved += a.reserved;
    measured += charged(a);
  });
  return { reserved: reserved, measured: measured };
}
function usageBits() {
  const u = state.usage;
  if (!u) return { five: "?", cost: "?", ctx: "?" };
  const five = (u.rateLimits || []).filter(function (x) { return x.kind === "five_hour"; })[0];
  return {
    five: five ? Math.round(five.percentUsed) + "%" : "?",
    cost: u.cost ? "$" + u.cost.usd.toFixed(3) : "?",
    ctx: u.context && u.context.percent !== undefined ? u.context.percent + "%" : "?",
  };
}
function routeLine(r) {
  return (r.ms / 1000).toFixed(1).padStart(7) + "s  " + String(r.type).padEnd(20)
    + " parent=" + String(r.parent).padEnd(7)
    + " requested=" + String(r.requested === undefined ? "inherit" : r.requested).padEnd(8)
    + " -> " + String(r.action === "deny" ? "DENIED" : r.model).padEnd(8)
    + " [" + r.reasons.join(", ") + "]"
    + (r.agentId ? "  agent=" + shortId(r.agentId) : "");
}
function ledgerLine(a) {
  const dec = a.declared;
  const ch = charged(a);
  return "  " + shortId(a.agentId).padEnd(9) + String(a.type).padEnd(20) + String(a.model).padEnd(26)
    + (a.calls + "/" + state.maxCalls).padEnd(8)
    + (dec === null ? "no # EST:" : num(dec)).padStart(11)
    + num(a.reserved).padStart(11)
    + (a.settled ? num(a.measured) : num(a.tokens) + "*").padStart(11)
    + (dec === null ? "" : "  delta=" + (ch - dec > 0 ? "+" : "") + num(ch - dec))
    + (a.settled ? "" : "  LIVE")
    + (a.overBudget ? "  OVER-BUDGET" : "");
}
function statusText() {
  const t = totalsLine();
  return "supervisor \u00b7 " + state.totals.spawns + " spawns \u00b7 " + state.totals.rewrites + " rewritten \u00b7 "
    + state.totals.denies + " denied \u00b7 " + liveAgents().length + " live \u00b7 reserved " + k(t.reserved) + " / charged " + k(t.measured);
}

// ---------------------------------------------------------------- $-using helpers (top level)
async function flush($) {
  if (!state.dirty || !state.sessionId) return;
  state.dirty = false;
  try {
    await $.fs.write(LOG_DIR + state.sessionId + ".jsonl", state.rows.map(function (r) { return JSON.stringify(r); }).join("\n") + "\n");
  } catch (err) { /* a hooks module never blocks the engine */ }
}
async function persist($) {
  try {
    await $.store.set(STORE_KEY, { priors: state.priors, updatedAt: Date.now(), sessionId: state.sessionId });
  } catch (err) { /* store is best-effort */ }
}
function tick($) {
  void flush($);
  $.ui.status(statusText());
  $.ui.invalidate("ui.render");
}
async function refreshUsage($) {
  try { state.usage = await $.session.usage(); } catch (err) { /* usage is advisory */ }
}

// ---------------------------------------------------------------- module
export const register = (on, options) => {
  const configured = options && options.maxSubagentCalls;
  if (typeof configured === "number" && configured > 0) { state.maxCalls = configured; state.maxCallsSource = "userConfig"; }

  on("session.start", async ($, e, next) => {
    state.sessionId = await $.session.id();
    state.t0 = Date.now();
    const stored = await $.store.get(STORE_KEY);
    if (stored && typeof stored === "object" && stored.priors) state.priors = stored.priors;
    await $.command.register({
      name: "supervisor",
      description: "SUBAGENT SUPERVISOR: routing log + measured budget ledger (log | ledger | priors | all)",
      argumentHint: "[log|ledger|priors|all]",
      immediate: true,
    });
    push({ kind: "session", sessionId: state.sessionId, maxCalls: state.maxCalls, maxCallsSource: state.maxCallsSource, priorTypes: Object.keys(state.priors) });
    $.ui.status(statusText());
    $.clock.every(2000, () => tick($));
    $.ui.log("\u27e6supervisor\u27e7 armed \u00b7 capability graph fable>opus>sonnet>haiku \u00b7 maxSubagentCalls=" + state.maxCalls
      + " (" + state.maxCallsSource + ") \u00b7 log \u2192 " + LOG_DIR + state.sessionId + ".jsonl");
    await refreshUsage($);
    return next(e);
  });

  // ---- 1. routing: rewrite onto the capability graph, deny only a leaf ----
  on("agent.spawn", async ($, e, next) => {
    const d = decide(e, state.totals.fable);
    const est = parseEst(e.prompt);
    const type = e.subagentType || "general-purpose";
    const route = {
      ms: Date.now() - state.t0,
      type: type,
      parent: e.parentModel,
      parentRung: RUNG_NAME[d.parentRung] || String(e.parentModel),
      requested: e.model,
      model: d.model,
      action: d.action,
      reasons: d.reasons,
      est: est,
      agentId: null,
    };
    state.totals.spawns++;

    if (d.action === "deny") {
      state.totals.denies++;
      state.routes.push(route);
      state.lastRoute = route;
      push({ kind: "route", route: route, denied: d.reason });
      $.ui.log("\u27e6supervisor\u27e7 DENY " + type + " parent=" + e.parentModel + " [" + d.reasons.join(", ") + "]");
      await flush($);
      return { deny: d.reason };
    }

    const sent = d.action === "rewrite" ? Object.assign({}, e, { model: d.model }) : e;
    if (d.action === "rewrite") state.totals.rewrites++; else state.totals.passes++;
    // Advisor consultations land on fable but are explicitly uncapped, so they do not feed the counter.
    if (d.targetRung === 4 && ADVISOR_TYPES.indexOf(type) < 0) state.totals.fable++;

    // Priced before the spawn, against the prior in force now.
    const reserved = priorFor(type);
    const reservedFrom = priorSource(type);
    const declared = declaredCost(type, est);
    route.reserved = reserved;
    route.declared = declared;

    const r = await next(sent);
    const agentId = r && r.agentId ? r.agentId : null;
    route.agentId = agentId;
    route.resolvedModel = r ? r.model : null;
    state.routes.push(route);
    state.lastRoute = route;

    if (agentId) {
      state.agents[agentId] = {
        agentId: agentId, type: type, model: r.model, requested: e.model, rewritten: d.action === "rewrite",
        reasons: d.reasons, est: est, declared: declared, reserved: reserved, reservedFrom: reservedFrom,
        calls: 0, steps: 0, turns: 0, tokens: 0, measured: 0, durationMs: 0,
        settled: false, overBudget: false, reason: "", startedAt: Date.now() - state.t0,
        description: clip(e.description, 60),
      };
      state.order.push(agentId);
    }
    push({ kind: "route", route: route, reserved: reserved, reservedFrom: reservedFrom, declared: declared });
    $.ui.log("\u27e6supervisor\u27e7 " + (d.action === "rewrite" ? "REWRITE" : "PASS") + " " + type
      + " " + (e.model === undefined ? "inherit" : e.model) + " \u2192 " + d.model
      + " (parent " + e.parentModel + ") [" + d.reasons.join(", ") + "]"
      + (agentId ? " agent=" + shortId(agentId) + " reserve=" + num(state.agents[agentId].reserved) : ""));
    await flush($);
    return r;
  });

  // ---- 2. live token accounting per subagent ----
  on("turn.step", async function* ($, e, next) {
    const r = yield* next(e);
    if (e.agentId) bumpAgent(e.agentId, r ? r.usage : null);
    return r;
  });

  // ---- 3. settle the ledger; maintain session totals from the main loop ----
  on("turn.complete", async ($, e, next) => {
    if (e.agentId) {
      const a = settleAgent(e);
      if (a) {
        const dec = a.declared;
        push({
          kind: "settle", agentId: a.agentId, type: a.type, model: a.model, calls: a.calls,
          declared: dec, reserved: a.reserved, measured: a.measured, delta: dec === null ? null : a.measured - dec,
          durationMs: a.durationMs, reason: a.reason, newMedian: state.priors[a.type].median,
        });
        $.ui.log("\u27e6supervisor\u27e7 SETTLE " + shortId(a.agentId) + " " + a.type + " " + a.model
          + " calls=" + a.calls + " declared=" + (dec === null ? "n/a" : num(dec))
          + " reserved=" + num(a.reserved) + " measured=" + num(a.measured)
          + " \u00b7 median(" + a.type + ")=" + num(state.priors[a.type].median));
        await persist($);
      }
    } else {
      state.totals.mainTurns++;
      state.totals.mainTokens += weigh(e.usage);
      await refreshUsage($);
    }
    await flush($);
    return next(e);
  });

  // ---- 4. per-subagent tool-call budget ----
  on("tool.call", async ($, e, next) => {
    const a = e && e.agentId ? state.agents[e.agentId] : null;
    if (!a) return next(e);
    a.calls++;
    state.dirty = true;
    if (EXEMPT_TOOLS.indexOf(e.tool) >= 0) return next(e);
    if (a.calls > state.maxCalls) {
      if (!a.overBudget) {
        a.overBudget = true;
        state.totals.overBudget++;
        $.ui.log("\u27e6supervisor\u27e7 OVER BUDGET " + shortId(a.agentId) + " " + a.type + " at call " + a.calls + "/" + state.maxCalls);
      }
      push({ kind: "budget-deny", agentId: a.agentId, type: a.type, tool: e.tool, call: a.calls, max: state.maxCalls });
      await flush($);
      return { deny: "supervisor: subagent over budget" };
    }
    return next(e);
  });

  // ---- 5. /supervisor ----
  on("command.run", { command: "supervisor" }, async ($, e, next) => {
    await flush($);
    await refreshUsage($);
    const arg = (e.args || "").trim().toLowerCase() || "all";
    const t = totalsLine();
    const u = usageBits();
    const head = "SUBAGENT SUPERVISOR \u00b7 session " + state.sessionId
      + "\n  spawns=" + state.totals.spawns + "  rewritten=" + state.totals.rewrites + "  passed=" + state.totals.passes
      + "  denied=" + state.totals.denies + "  over-budget=" + state.totals.overBudget
      + "  live=" + liveAgents().length
      + "\n  reserved=" + num(t.reserved) + " tok  charged=" + num(t.measured) + " tok"
      + "  (an agent that never completes is charged its full reservation)"
      + "\n  main loop: " + state.totals.mainTurns + " turns, " + num(state.totals.mainTokens) + " weighted tok"
      + "  \u00b7 context " + u.ctx + " \u00b7 five-hour " + u.five + " \u00b7 cost " + u.cost;
    const log = "\nROUTING LOG (" + state.routes.length + " decisions)\n"
      + (state.routes.length ? state.routes.slice(-25).map(routeLine).join("\n") : "  none");
    const cols = "  " + "agent".padEnd(9) + "type".padEnd(20) + "model".padEnd(26) + "calls".padEnd(8)
      + "declared".padStart(11) + "reserved".padStart(11) + "measured".padStart(11);
    const ledger = "\nLEDGER (* = live, still accruing)\n" + cols + "\n"
      + (state.order.length ? state.order.map(function (id) { return ledgerLine(state.agents[id]); }).join("\n") : "  none");
    const priors = "\nPRIORS ($.store " + STORE_KEY + ", learned medians across sessions)\n"
      + (Object.keys(state.priors).length
        ? Object.keys(state.priors).map(function (ty) {
          const p = state.priors[ty];
          return "  " + ty.padEnd(22) + "n=" + String(p.samples.length).padEnd(4) + "median=" + num(p.median).padStart(9)
            + "   default=" + num(isLean(ty) ? LEAN_PRIOR : FULL_PRIOR);
        }).join("\n")
        : "  none yet \u2014 defaults: lean " + num(LEAN_PRIOR) + ", full " + num(FULL_PRIOR));
    const tail = "\nlog file: " + LOG_DIR + state.sessionId + ".jsonl";
    if (arg === "log") return { text: head + log + tail };
    if (arg === "ledger") return { text: head + ledger + tail };
    if (arg === "priors") return { text: head + priors + tail };
    return { text: head + log + ledger + priors + tail };
  });

  // ---- 6. HUD ----
  on("ui.render", { component: "AbovePrompt", surface: "terminal" }, async ($, e, next) => {
    const { Box, Text } = $.ui.resolve(e);
    const width = Math.max(40, (e.props && e.props.bodyColumns ? e.props.bodyColumns : 100) - 4);
    const u = usageBits();
    const t = totalsLine();
    const r = state.lastRoute;
    const routeText = r
      ? "ROUTE " + r.type + "  " + (r.requested === undefined ? "inherit" : r.requested) + " \u2192 "
        + (r.action === "deny" ? "DENIED" : r.model) + "  [" + r.reasons.join(", ") + "]"
      : "ROUTE none yet \u00b7 capability graph fable>opus>sonnet>haiku, advisor = +1 rung";
    const live = liveAgents().slice(-4).map(function (a, i) {
      return (
        <Text key={"l" + i} color="green" wrap="truncate-end">
          {("LIVE  " + shortId(a.agentId) + " " + a.type + " " + a.model + " calls=" + a.calls + "/" + state.maxCalls
            + " tok=" + k(a.tokens) + " (reserved " + k(a.reserved) + ")").slice(0, width)}
        </Text>
      );
    });
    const done = state.order.map(function (id) { return state.agents[id]; })
      .filter(function (a) { return a && a.settled; }).slice(-3).map(function (a, i) {
        const dec = a.declared;
        return (
          <Text key={"d" + i} dimColor wrap="truncate-end">
            {("DONE  " + shortId(a.agentId) + " " + a.type + " " + a.model + " calls=" + a.calls
              + " measured=" + k(a.measured) + (dec === null ? " (no # EST:)" : " vs declared " + k(dec))).slice(0, width)}
          </Text>
        );
      });
    return (
      <Box flexDirection="column" borderStyle="round" borderColor="cyan" paddingX={1}>
        <Text bold color="cyan">
          {("SUBAGENT SUPERVISOR  spawns=" + state.totals.spawns + " rewritten=" + state.totals.rewrites
            + " denied=" + state.totals.denies + " live=" + liveAgents().length
            + "  \u00b7 reserved " + k(t.reserved) + " / charged " + k(t.measured)
            + "  \u00b7 5h " + u.five + "  \u00b7 " + u.cost).slice(0, width)}
        </Text>
        <Text color={r && r.action === "deny" ? "red" : r && r.action === "rewrite" ? "yellow" : "gray"} wrap="truncate-end">
          {routeText.slice(0, width)}
        </Text>
        {live}
        {done}
      </Box>
    );
  });
};
