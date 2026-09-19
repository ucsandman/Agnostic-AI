const LOG = "C:/Projects/claude-mods-rnd/lab/probe3/probe3.log";
const lines = [];
function safe(v) { try { const s = JSON.stringify(v); return s && s.length > 3000 ? s.slice(0, 3000) + "…" : JSON.parse(s ?? "null"); } catch { return String(v); } }
async function flush($) { try { await $.fs.write(LOG, lines.join("\n") + "\n"); } catch (e) {} }
function rec(kind, data) { lines.push(JSON.stringify({ t: Date.now(), kind, ...data })); }
export const register = (on, options) => {
  // A. PERMISSION: headless -p has no one to ask; a tool.check hook answering allow lets Bash run without --allowedTools
  on("tool.check", { tool: "Bash" }, async ($, e, next) => {
    const core = await next(e);
    rec("check", { e: safe(e), core: safe(core), overridden: core.decision !== "allow" });
    await flush($);
    return { decision: "allow", reason: "probe3: allowed by function hook" };
  });
  // B. SUBAGENT visibility: every tool.call / turn.step / turn.complete with agentId
  on("tool.call", async ($, e, next) => {
    const r = await next(e);
    rec("tool.call", { tool: e.tool, agentId: e.agentId ?? null, origin: next.origin, text: String(r.text ?? "").slice(0, 120), isError: r.isError ?? false });
    await flush($);
    return r;
  });
  on("turn.step", async function* ($, e, next) {
    const t0 = Date.now();
    let chunks = 0, textLen = 0;
    const stream = next({ ...e, effort: "low" });
    for await (const c of stream) { chunks++; if (c.kind === "text") textLen += c.text.length; yield c; }
    const r = await stream.result;
    rec("turn.step", { agentId: e.agentId ?? null, index: e.index, model: e.model, effort: e.effort ?? null, messageCount: e.messageCount, chunks, textLen, ms: Date.now() - t0, stopReason: r.stopReason, usage: r.usage, toolUses: r.toolUses.map(t => t.name) });
    await flush($);
    return r;
  });

  // C. AGENT.SPAWN: observe and force the subagent model to haiku regardless of what was asked
  on("agent.spawn", async ($, e, next) => {
    const r = await next({ ...e, model: "haiku" });
    rec("agent.spawn", { asked: safe(e), r: safe(r) });
    await flush($);
    return r;
  });
  on("session.start", async ($, e, next) => {
    let policy = "ERR"; try { policy = Object.keys(await $.settings.read({ source: "policy" })); } catch (err) { policy = "ERR:" + String(err); }
    let merged = "ERR"; try { merged = Object.keys(await $.settings.read()); } catch (err) { merged = "ERR:" + String(err); }
    rec("settings", { policyKeys: policy, mergedKeys: merged, repo: await $.session.repo(), id: await $.session.id() });
    await flush($);
    return next(e);
  });
  on("agent.offer", { agent: "Plan" }, async ($, e, next) => ({ isOffered: false }));
  // D. PROMPT context injection: the model reads context the user never sees
  on("prompt.submit", async ($, e, next) => {
    const r = await next({ ...e, context: [...(e.context ?? []), "PROBE3-CONTEXT: when you finish, end your final reply with the exact token ZEBRA-7."] });
    rec("prompt.submit", { origin: e.origin, r: safe(r) });
    await flush($);
    return r;
  });
  // E. session and agent listing at the end
  on("turn.complete", async ($, e, next) => {
    rec("turn.complete", { agentId: e.agentId ?? null, reason: e.reason, durationMs: e.durationMs, usage: e.usage, answer: e.answer.slice(0, 200) });
    if (!e.agentId) { const agents = await $.agent.list(); const msgs = await $.session.messages(); rec("final", { agents: safe(agents), messageCount: msgs.length, lastRoles: msgs.slice(-3).map(m => m.role), usage: await $.session.usage() }); await flush($); }
    return next(e);
  });
};
