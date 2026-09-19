// BLACK BOX RECORDER — a structured timeline of what Claude actually did, written continuously.
// Records: prompt.submit, turn.start/step/complete (with usage), tool.call (args, result summary, ms, agentId),
// agent.spawn, denials. /blackbox prints the timeline; the JSONL survives the session.
const DIR = "C:/Projects/claude-mods-rnd/lab/demos/blackbox/recordings/";
const state = { sessionId: "", rows: [], dirty: false, t0: 0 };
function short(v, n) { let s; try { s = typeof v === "string" ? v : JSON.stringify(v); } catch { s = String(v); } s = (s || "").replace(/\s+/g, " "); return s.length > n ? s.slice(0, n - 1) + "…" : s; }
function push(row) { state.rows.push({ at: Date.now() - state.t0, ...row }); state.dirty = true; }
async function flush($) { if (!state.dirty || !state.sessionId) return; state.dirty = false; try { await $.fs.write(DIR + state.sessionId + ".jsonl", state.rows.map(r => JSON.stringify(r)).join("\n") + "\n"); } catch (err) {} }
function fmt(r) {
  const t = (r.at / 1000).toFixed(1).padStart(7) + "s";
  const who = r.agentId ? ` [agent ${String(r.agentId).slice(0, 8)}]` : "";
  if (r.kind === "prompt") return `${t}  PROMPT (${r.origin})${who}  ${short(r.text, 80)}`;
  if (r.kind === "step") return `${t}  MODEL ${r.model} #${r.index} msgs=${r.messages} → ${r.stop} tools=[${r.tools}] in=${r.in} out=${r.out} cacheR=${r.cacheR}${who}`;
  if (r.kind === "tool") return `${t}  TOOL ${r.tool} ${short(r.args, 60)} → ${r.deny ? "DENIED " + short(r.deny, 40) : r.isError ? "ERROR " + short(r.text, 40) : short(r.text, 50)} (${r.ms}ms)${who}`;
  if (r.kind === "spawn") return `${t}  SPAWN ${r.type} model=${r.model} → ${r.agentId ? r.agentId.slice(0, 8) : "denied"}${who}`;
  if (r.kind === "turn") return `${t}  TURN ${r.reason} ${r.durationMs}ms in=${r.in} out=${r.out} cacheR=${r.cacheR} cacheW=${r.cacheW}${who}`;
  return `${t}  ${r.kind} ${short(r, 80)}`;
}
export const register = (on, options) => {
  on("session.start", async ($, e, next) => {
    state.sessionId = await $.session.id(); state.t0 = Date.now();
    await $.command.register({ name: "blackbox", description: "BLACK BOX: print this session's recorded timeline", immediate: true });
    $.ui.log(`⟦blackbox⟧ recording → ${DIR}${state.sessionId}.jsonl · /blackbox to print`);
    $.clock.every(2000, () => { void flush($); });
    return next(e);
  });
  on("prompt.submit", async ($, e, next) => { push({ kind: "prompt", origin: e.origin ? e.origin.kind : "?", text: e.text }); return next(e); });
  on("turn.step", async function* ($, e, next) {
    const r = yield* next(e);
    push({ kind: "step", agentId: e.agentId, model: r.usage ? r.usage.model : e.model, index: e.index, messages: e.messageCount, stop: r.stopReason, tools: r.toolUses.map(t => t.name).join(","), in: r.usage ? r.usage.input_tokens : 0, out: r.usage ? r.usage.output_tokens : 0, cacheR: r.usage ? r.usage.cache_read_input_tokens : 0 });
    return r;
  });
  on("tool.call", async ($, e, next) => {
    const t0 = Date.now(); const { tool, tool_use_id, agentId, ...args } = e;
    const r = await next(e);
    push({ kind: "tool", tool, args, agentId, ms: Date.now() - t0, deny: r.deny, isError: r.isError, text: r.text });
    return r;
  });
  on("agent.spawn", async ($, e, next) => { const r = await next(e); push({ kind: "spawn", type: e.subagentType, model: r.model, agentId: r.agentId, deny: r.deny }); return r; });
  on("turn.complete", async ($, e, next) => {
    const u = e.usage || {};
    push({ kind: "turn", agentId: e.agentId, reason: e.reason, durationMs: e.durationMs, in: u.input_tokens, out: u.output_tokens, cacheR: u.cache_read_input_tokens, cacheW: u.cache_creation_input_tokens });
    await flush($);
    return next(e);
  });
  on("command.run", { command: "blackbox" }, async ($, e, next) => {
    await flush($);
    const tools = state.rows.filter(r => r.kind === "tool"); const denied = tools.filter(r => r.deny).length;
    const steps = state.rows.filter(r => r.kind === "step");
    const tokens = steps.reduce((a, r) => a + (r.in || 0) + (r.out || 0), 0);
    const head = `BLACK BOX ${state.sessionId}: ${state.rows.filter(r => r.kind === "prompt").length} prompts · ${steps.length} model steps · ${tools.length} tool calls (${denied} denied) · ${state.rows.filter(r => r.kind === "spawn").length} spawns · ${tokens} uncached+output tokens`;
    return { text: head + "\n" + state.rows.slice(-40).map(fmt).join("\n") + `\nfile: ${DIR}${state.sessionId}.jsonl` };
  });
};
