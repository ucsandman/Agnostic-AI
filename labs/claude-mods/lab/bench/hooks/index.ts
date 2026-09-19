const LOG = "C:/Projects/claude-mods-rnd/lab/bench/bench.log";
const lines = [];
async function flush($) { try { await $.fs.write(LOG, lines.join("\n") + "\n"); } catch (e) {} }
function rec(kind, data) { lines.push(JSON.stringify({ t: Date.now(), kind, ...data })); }
function traceMs(trace) { return trace.map(x => ({ plugin: x.plugin, tier: x.tier, outcome: x.outcome, ms: x.ms })); }
export const register = (on, options) => {
  on("session.start", async ($, e, next) => {
    const spawn = [];
    for (let i = 0; i < 5; i++) { const t0 = performance.now(); await $.process.run(["node", "-e", "0"]); spawn.push(performance.now() - t0); }
    const noop = [];
    for (let i = 0; i < 5; i++) { const t0 = performance.now(); await $.session.model(); noop.push(performance.now() - t0); }
    rec("baseline", { subprocess_node_noop_ms: spawn, host_roundtrip_session_model_ms: noop });
    await flush($);
    return next(e);
  });
  on("classic.PreToolUse", async ($, e, next) => {
    const t0 = performance.now();
    const r = await next(e);
    rec("classic.PreToolUse", { tool: e.tool, wall_ms: performance.now() - t0, trace: traceMs(next.trace) });
    return r;
  });
  on("classic.PostToolUse", async ($, e, next) => {
    const t0 = performance.now();
    const r = await next(e);
    rec("classic.PostToolUse", { tool: e.tool_name, wall_ms: performance.now() - t0, trace: traceMs(next.trace) });
    return r;
  });
  on("tool.call", async ($, e, next) => {
    const t0 = performance.now();
    const r = await next(e);
    rec("tool.call", { tool: e.tool, wall_ms: performance.now() - t0, trace: traceMs(next.trace) });
    await flush($);
    return r;
  });
  on("tool.check", async ($, e, next) => {
    const t0 = performance.now();
    const r = await next(e);
    rec("tool.check", { tool: e.tool, wall_ms: performance.now() - t0, decision: r.decision, trace: traceMs(next.trace) });
    return r;
  });
  on("turn.complete", async ($, e, next) => { rec("turn.complete", { usage: e.usage, durationMs: e.durationMs }); await flush($); return next(e); });
};
