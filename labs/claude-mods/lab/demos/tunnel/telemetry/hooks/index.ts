// MIDDLEWARE TUNNEL stage 4/4 — "telemetry". Load all four with --plugin-dir in order; each Bash call containing
// the word "tunnel" walks down observer → cost → policy → telemetry → next() → tool, then back up.
const STAGE = "4/4 telemetry";
export const register = (on, options) => {
  on("tool.call", { tool: "Bash", command: /tunnel/i }, async ($, e, next) => {
    const t0 = Date.now();
    $.ui.log(`⟦tunnel ${STAGE}⟧ ↓ enter  ${e.tool} ${String(e.command).slice(0, 60)}`);
    const r = await next(e);
    $.ui.log(`⟦tunnel ${STAGE}⟧   ↑ recorded: ${e.tool} ${r.deny ? "DENIED" : r.isError ? "ERROR" : "ok"} text=${String(r.text || "").length} chars`);
    $.ui.log(`⟦tunnel ${STAGE}⟧ ↑ leave  after ${Date.now() - t0}ms`);
    return r;
  });
};
