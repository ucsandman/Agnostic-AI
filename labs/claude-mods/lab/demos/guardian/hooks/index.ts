// GUARDIAN — policy as code, not as prose. CLAUDE.md can say "never edit X"; the model usually obeys.
// A tool.call hook makes it a property of the runtime: the write never reaches the tool.
const PROTECTED = /lab[\\/]+demos[\\/]+protected[\\/]/i;
const state = { blocked: 0 };
function touches(e) {
  if (e.tool === "Write" || e.tool === "Edit" || e.tool === "NotebookEdit") return PROTECTED.test(String(e.file_path ?? e.notebook_path ?? ""));
  if (e.tool === "Bash") return PROTECTED.test(String(e.command ?? "")) && /(>|>>|rm |del |mv |cp |sed |tee |echo )/i.test(String(e.command ?? ""));
  return false;
}
export const register = (on, options) => {
  on("session.start", async ($, e, next) => { $.ui.log("⟦guardian⟧ armed: lab/demos/protected/** is read-only for Write/Edit/NotebookEdit and for Bash redirections"); return next(e); });
  on("tool.call", { tool: ["Write", "Edit", "NotebookEdit", "Bash"] }, async ($, e, next) => {
    if (!touches(e)) return next(e);
    state.blocked++;
    const what = e.tool === "Bash" ? e.command : e.file_path ?? e.notebook_path;
    $.ui.log(`⟦guardian⟧ ✖ BLOCKED #${state.blocked}: ${e.tool} on ${what}`);
    $.ui.toast(`guardian blocked ${e.tool} on a protected file`);
    return { deny: `GUARDIAN policy: ${what} is protected (lab/demos/protected/**). This is enforced by a function hook, not by instructions; do not retry with another tool.` };
  });
  // Belt and braces: the permission verdict is also a hook. Even if a later plugin answered the call itself,
  // the engine's tool.check sees the same input and we deny there too.
  on("tool.check", { tool: ["Write", "Edit", "NotebookEdit", "Bash"] }, async ($, e, next) => {
    const input = e.input || {};
    const fake = { tool: e.tool, ...input };
    if (touches(fake)) return { decision: "deny", reason: "GUARDIAN: protected path" };
    return next(e);
  });
};
