// MIDDLEWARE TUNNEL stage 2/4 — "cost". Load all four with --plugin-dir in order; each Bash call containing
// the word "tunnel" walks down observer → cost → policy → telemetry → next() → tool, then back up.
const STAGE = "2/4 cost";
export const register = (on, options) => {
  on("tool.call", { tool: "Bash", command: /tunnel/i }, async ($, e, next) => {
    const t0 = Date.now();
    $.ui.log(`⟦tunnel ${STAGE}⟧ ↓ enter  ${e.tool} ${String(e.command).slice(0, 60)}`);
    const size = JSON.stringify(e).length;
    $.ui.log(`⟦tunnel ${STAGE}⟧   ↓ estimate: args=${size} chars ≈ ${Math.ceil(size / 4)} tokens in; result cost known only after next()`);
    const r = await next(e);
    $.ui.log(`⟦tunnel ${STAGE}⟧   ↑ result ≈ ${Math.ceil(String(r.text || "").length / 4)} tokens back to the model`);
    $.ui.log(`⟦tunnel ${STAGE}⟧ ↑ leave  after ${Date.now() - t0}ms`);
    return r;
  });
};
