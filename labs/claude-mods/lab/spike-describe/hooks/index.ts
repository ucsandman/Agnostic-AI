// spike-describe — three EXPERIMENTAL entries in the capability map, exercised:
//  tool.describe rewrite (does the model read the rewritten description?), agent.offer hide (is the type gone
//  from the model's listing and refused at dispatch?), and the $.prompt.suggest / prompt.suggest pair.
const OUT = "C:/Projects/claude-mods-rnd/lab/spike-describe/out/spike.log";
const log = [];
function rec(kind, data) { log.push(JSON.stringify({ t: Date.now(), kind, ...data })); }
async function flush($) { try { await $.fs.write(OUT, log.join("\n") + "\n"); } catch (err) {} }
export const register = (on, options) => {
  on("tool.describe", { tool: "Bash" }, async ($, e, next) => {
    const r = await next(e);
    rec("tool.describe", { tool: e.tool, provider: e.provider, originalChars: e.description.length });
    return { description: "MARKER-ZQX-77: Executes a shell command on the host. (Description rewritten by spike-describe.)\n\n" + r.description };
  });
  on("agent.offer", { agent: "Plan" }, async ($, e, next) => { rec("agent.offer.hidden", { agent: e.agent, source: e.source }); return { isOffered: false }; });
  on("agent.offer", async ($, e, next) => { const r = await next(e); if (e.agent !== "Plan") rec("agent.offer", { agent: e.agent, isOffered: r.isOffered }); return r; });
  on("prompt.suggest", async ($, e, next) => { const r = await next(e); rec("prompt.suggest", { origin: e.origin, text: e.text.slice(0, 80), isShown: r.isShown }); await flush($); return r; });
  on("turn.complete", async ($, e, next) => {
    if (!e.agentId) { try { const r = await $.prompt.suggest({ text: "run the tests you just wrote" }); rec("prompt.suggest.call", r); } catch (err) { rec("prompt.suggest.error", { err: String(err) }); } await flush($); }
    return next(e);
  });
};
