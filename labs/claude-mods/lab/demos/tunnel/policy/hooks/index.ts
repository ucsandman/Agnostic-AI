// MIDDLEWARE TUNNEL stage 3/4 — "policy". Load all four with --plugin-dir in order; each Bash call containing
// the word "tunnel" walks down observer → cost → policy → telemetry → next() → tool, then back up.
const STAGE = "3/4 policy";
export const register = (on, options) => {
  on("tool.call", { tool: "Bash", command: /tunnel/i }, async ($, e, next) => {
    const t0 = Date.now();
    $.ui.log(`⟦tunnel ${STAGE}⟧ ↓ enter  ${e.tool} ${String(e.command).slice(0, 60)}`);
    if (/format c:/i.test(String(e.command))) { $.ui.log(`⟦tunnel ${STAGE}⟧   ✖ DENY`); return { deny: "tunnel policy: no" }; }
    $.ui.log(`⟦tunnel ${STAGE}⟧   ↓ verdict: allow (no rule matched)`);
    const r = await next(e);
    $.ui.log(`⟦tunnel ${STAGE}⟧ ↑ leave  after ${Date.now() - t0}ms`);
    return r;
  });
};
