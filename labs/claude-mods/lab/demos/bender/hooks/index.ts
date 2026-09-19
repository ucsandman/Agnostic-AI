// REALITY BENDER — the tool runs for real; the model is handed something else.
// After `await next(e)` a hook holds the real result; returning its own {result} replaces what Claude reads.
// Scope: only Bash commands containing the word "bend" (harmless demo), and Read of files named *.bend.txt.
function bend(text) { return text.split("").reverse().join("").toUpperCase(); }
export const register = (on, options) => {
  on("session.start", async ($, e, next) => { $.ui.log("⟦bender⟧ armed: Bash commands containing 'bend' get their stdout reversed+uppercased before Claude sees it"); return next(e); });
  on("tool.call", { tool: "Bash", command: /bend/i }, async ($, e, next) => {
    const real = await next(e);
    if (real.deny || real.isError) return real;
    const realText = String(real.text ?? real.result?.stdout ?? "");
    const bent = bend(realText);
    $.ui.log(`⟦bender⟧ REAL TOOL RESULT:  ${realText.slice(0, 100)}`);
    $.ui.log(`⟦bender⟧ CLAUDE RECEIVED:   ${bent.slice(0, 100)}`);
    return { result: { ...real.result, stdout: bent }, context: ["(reality bender: this output was altered by a function hook before you saw it)"] };
  });
};
