// MIDDLEWARE TUNNEL stage 1/4 — "observer". Load all four with --plugin-dir in order; each Bash call containing
// the word "tunnel" walks down observer → cost → policy → telemetry → next() → tool, then back up.
const STAGE = "1/4 observer";
export const register = (on, options) => {
  on("tool.call", { tool: "Bash", command: /tunnel/i }, async ($, e, next) => {
    const t0 = Date.now();
    $.ui.log(`⟦tunnel ${STAGE}⟧ ↓ enter  ${e.tool} ${String(e.command).slice(0, 60)}`);
    const r = await next(e);
    const links = (next.trace || []).map(t => `${t.plugin}${t.tier === "core" ? "" : "/" + t.tier} ${Math.round(t.ms)}ms`).join(" → ");
    $.ui.log(`⟦tunnel ${STAGE}⟧   ↑ pipeline beneath me: ${links}`);
    $.ui.log(`⟦tunnel ${STAGE}⟧ ↑ leave  after ${Date.now() - t0}ms`);
    return r;
  });
};
