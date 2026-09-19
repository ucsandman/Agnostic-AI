/** @type {import('claude-code').Register} */
const LOG = "C:/Projects/claude-mods-rnd/lab/probe/probe.log";
const lines = [];
function safe(v) { try { const s = JSON.stringify(v); return s && s.length > 3000 ? s.slice(0, 3000) + "…" : JSON.parse(s ?? "null"); } catch { return String(v); } }
async function flush($) { try { await $.fs.write(LOG, lines.join("\n") + "\n"); } catch (e) {} }
export const register = (on, options) => {
  on("*", async ($, e, next) => {
    const t = Date.now();
    try {
      const r = await next(e);
      lines.push(JSON.stringify({ t, event: next.event, origin: next.origin, ms: Date.now() - t, e: safe(e), r: safe(r), trace: safe(next.trace) }));
      return r;
    } catch (err) {
      lines.push(JSON.stringify({ t, event: next.event, origin: next.origin, ms: Date.now() - t, e: safe(e), threw: String(err) }));
      throw err;
    } finally {
      if (next.event !== "fs.write" && next.event !== "engine.create") { await flush($); }
    }
  });
  on("session.start", async ($, e, next) => {
    const tools = await $.tool.list();
    lines.push(JSON.stringify({ marker: "session.start", e, options, cwd: await $.session.cwd(), model: await $.session.model(), usage: await $.session.usage(), toolCount: tools.length, tools: tools.map(t => t.name) }));
    return next(e);
  });
};
