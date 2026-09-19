// spike-handoff — two questions LegCli needs answered before it can become a runtime-aware supervisor:
//  1. Can a plugin end a turn cleanly ($.turn.abort) instead of Leg's killTree()? What does turn.complete report?
//  2. Can a handoff bundle be written at a SAFE boundary (turn.complete) from the runtime bus, with no help from the model?
const OUT = "C:/Projects/claude-mods-rnd/lab/spike-handoff/out/";
const state = { turnId: "", calls: 0, abortAfter: 0, handoffAt: 0, aborted: false, log: [] };
function rec(kind, data) { state.log.push(JSON.stringify({ t: Date.now(), kind, ...data })); }
async function flush($) { try { await $.fs.write(OUT + "spike.log", state.log.join("\n") + "\n"); } catch (err) {} }
async function writeBundle($, e) {
  const events = await $.runtime.snapshot({ limit: 200 });
  const msgs = await $.session.messages();
  const usage = await $.session.usage();
  let git = { exitCode: -1, stdout: "", stderr: "" }; try { git = await $.process.run(["git", "status", "--porcelain=v1", "-b"], { timeoutMs: 8000 }); } catch (err) {}
  const files = {}; for (const ev of events) if (ev.kind === "FileObserved" || ev.kind === "FileModified") { const p = String(ev.data.path); files[p] = files[p] || { reads: 0, writes: 0 }; if (ev.kind === "FileObserved") files[p].reads++; else files[p].writes++; }
  const tools = events.filter(x => x.kind === "ToolCompleted").map(x => `${x.data.tool} ${x.data.denied ? "DENIED" : x.data.isError ? "ERROR" : "ok"} ${x.data.ms}ms ${String(x.data.preview).slice(0, 60)}`);
  const lastUser = [...msgs].reverse().find(m => m.role === "user");
  const md = [
    `# HANDOFF (written by a function hook at turn.complete, no model involved)`,
    `session: ${await $.session.id()}  turn: ${e.turnId}  reason: ${e.reason}  duration: ${e.durationMs}ms`,
    `## Boundary`, `- turn closed: yes (this file is written inside turn.complete)`, `- five_hour: ${(usage.rateLimits.find(r => r.kind === "five_hour") || {}).percentUsed ?? "?"}%  context: ${usage.context.percent ?? "?"}%  cost: $${usage.cost ? usage.cost.usd.toFixed(3) : "?"}`,
    `- git (${git.exitCode === 0 ? "ok" : "unavailable"}):\n\`\`\`\n${git.stdout.trim().slice(0, 1500)}\n\`\`\``,
    `## Last user prompt`, "> " + (lastUser ? lastUser.text.slice(0, 500) : "(none)"),
    `## Last answer`, e.answer.slice(0, 800),
    `## Files touched (from the runtime bus)`, ...Object.entries(files).map(([p, c]) => `- ${p}  reads=${c.reads} writes=${c.writes}`),
    `## Tool calls this session (from the runtime bus)`, ...tools.map(t => "- " + t),
    `## Evidence anchors`, ...Object.keys(files).filter(p => files[p].writes > 0).map(p => `- ${p} — modified this session`),
  ].join("\n");
  await $.fs.write(OUT + "HANDOFF-" + e.turnId.slice(0, 8) + ".md", md);
  return md.length;
}
export const register = (on, options) => {
  state.abortAfter = Number(options.abortAfterCalls) || 0; state.handoffAt = Number(options.handoffAtPercent) || 0;
  on("turn.start", async ($, e, next) => { state.turnId = e.turnId; state.calls = 0; state.aborted = false; rec("turn.start", { turnId: e.turnId }); return next(e); });
  on("tool.call", async ($, e, next) => {
    if (e.agentId) return next(e);
    state.calls++;
    if (state.abortAfter > 0 && state.calls === state.abortAfter && !state.aborted) {
      state.aborted = true; rec("abort.request", { turnId: state.turnId, afterCalls: state.calls, tool: e.tool });
      try { await $.turn.abort({ turnId: state.turnId }); rec("abort.ok", {}); } catch (err) { rec("abort.error", { err: String(err) }); }
      await flush($);
    }
    return next(e);
  });
  on("turn.complete", async ($, e, next) => {
    if (e.agentId) return next(e);
    rec("turn.complete", { turnId: e.turnId, reason: e.reason, isAborted: e.isAborted, durationMs: e.durationMs, answer: e.answer.slice(0, 120) });
    const usage = await $.session.usage(); const fh = (usage.rateLimits.find(r => r.kind === "five_hour") || {}).percentUsed ?? 0;
    if (fh >= state.handoffAt) { try { const n = await writeBundle($, e); rec("handoff.written", { bytes: n, five_hour: fh }); $.ui.toast("spike-handoff: bundle written at a clean boundary"); } catch (err) { rec("handoff.error", { err: String(err) }); } }
    await flush($);
    return next(e);
  });
};
