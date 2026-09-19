// spike-compact — exercise the context-management primitives the map lists as EXPERIMENTAL:
// session.compact (observe: trigger, messages with handles) and $.session.compact({instructions}) from a plugin.
const OUT = "C:/Projects/claude-mods-rnd/lab/spike-compact/out/spike.log";
const log = [];
function rec(kind, data) { log.push(JSON.stringify({ t: Date.now(), kind, ...data })); }
async function flush($) { try { await $.fs.write(OUT, log.join("\n") + "\n"); } catch (err) {} }
export const register = (on, options) => {
  on("session.compact", async ($, e, next) => {
    rec("session.compact.in", { trigger: e.trigger, agentId: e.agentId || null, instructions: e.instructions || null, messages: e.messages.length, withHandles: e.messages.filter(m => m.handle).length, roles: e.messages.map(m => m.role).join("") });
    const r = await next(e);
    rec("session.compact.out", { skip: r.skip || null, messages: r.messages ? r.messages.length : null, tokensBefore: r.tokensBefore ?? null, tokensAfter: r.tokensAfter ?? null, firstText: r.messages && r.messages[0] ? String(r.messages[0].text).slice(0, 200) : null });
    await flush($);
    return r;
  });
  on("turn.complete", async ($, e, next) => {
    if (e.agentId) return next(e);
    const turns = await $.session.turns();
    rec("turn.complete", { turns, reason: e.reason });
    if (turns >= 2) {
      const t0 = Date.now();
      try { const r = await $.session.compact({ instructions: "Keep every echo output verbatim; drop everything else." }); rec("compact.call", { ms: Date.now() - t0, skip: r.skip || null, messages: r.messages ? r.messages.length : null, tokensBefore: r.tokensBefore ?? null, tokensAfter: r.tokensAfter ?? null }); }
      catch (err) { rec("compact.error", { ms: Date.now() - t0, err: String(err) }); }
      try { const u = await $.session.usage(); rec("usage.after", { context: u.context }); } catch (err) {}
    }
    await flush($);
    return next(e);
  });
};
