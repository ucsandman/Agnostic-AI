// MATRIX — "stop time" before a tool runs.
// A tool.call hook can hold the call for as long as it wants (the dispatch stays open), show the person
// exactly what Claude intended, and only then call next(e) — or refuse. Classic hooks can only exit 0/2.
const state = { armed: true, frozen: 0 };
function summarize(e) {
  const { tool, tool_use_id, agentId, ...args } = e;
  const s = JSON.stringify(args); return `${tool} ${s.length > 160 ? s.slice(0, 159) + "…" : s}`;
}
export const register = (on, options) => {
  on("session.start", async ($, e, next) => {
    await $.command.register({ name: "matrix", description: "MATRIX: freeze harmless Bash/Write calls before they run (on|off)", argumentHint: "on|off", immediate: true });
    $.ui.log("⟦matrix⟧ armed: every Bash whose command contains the word matrix is frozen before it runs");
    return next(e);
  });
  on("command.run", { command: "matrix" }, async ($, e, next) => {
    state.armed = (e.args || "").trim() !== "off";
    return { text: `matrix ${state.armed ? "ON" : "OFF"}` };
  });
  on("tool.call", { tool: "Bash", command: /matrix/i }, async ($, e, next) => {
    if (!state.armed) return next(e);
    state.frozen++;
    const t0 = Date.now();
    $.ui.log(`⟦matrix⟧ ⏸ FROZEN #${state.frozen}: Claude intends → ${summarize(e)}`);
    $.ui.status(`matrix: holding ${e.tool} (${e.tool_use_id.slice(-6)})`);
    $.ui.notice(e.tool_use_id, "MATRIX holds this call until you answer");
    let answer = "Continue";
    try {
      answer = await $.ui.ask(`MATRIX froze a tool call. Claude intends: ${summarize(e)}. Let it run?`, ["Continue", "Deny", "Rewrite to echo MATRIX-REWROTE-THIS"]);
    } catch (err) {
      // headless (-p) has no one to ask: hold 3 s so the freeze is still visible in the timeline, then continue
      await $.clock.sleep(3000, { signal: next.signal });
      answer = "Continue (no one to ask)";
    }
    $.ui.status(undefined);
    const held = Date.now() - t0;
    if (answer.startsWith("Deny")) { $.ui.log(`⟦matrix⟧ ✖ denied after ${held}ms`); return { deny: `MATRIX: the person refused this call after seeing it (${summarize(e)})` }; }
    if (answer.startsWith("Rewrite")) { $.ui.log(`⟦matrix⟧ ✎ rewritten after ${held}ms`); return next({ ...e, command: "echo MATRIX-REWROTE-THIS" }); }
    $.ui.log(`⟦matrix⟧ ▶ released after ${held}ms (${answer})`);
    return next(e);
  });
};
