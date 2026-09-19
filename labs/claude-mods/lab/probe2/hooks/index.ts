const LOG = "C:/Projects/claude-mods-rnd/lab/probe2/probe2.log";
const lines = [];
function safe(v) { try { const s = JSON.stringify(v); return s && s.length > 4000 ? s.slice(0, 4000) + "…" : JSON.parse(s ?? "null"); } catch { return String(v); } }
async function flush($) { try { await $.fs.write(LOG, lines.join("\n") + "\n"); } catch (e) {} }
function rec(kind, data) { lines.push(JSON.stringify({ t: Date.now(), kind, ...data })); }
export const register = (on, options) => {
  // 1. observe every tool-ish event with trace
  on("tool.*", async ($, e, next) => {
    const t = Date.now();
    const r = await next(e);
    rec("observe", { event: next.event, ms: Date.now() - t, e: safe(e), r: safe(r), trace: safe(next.trace) });
    await flush($);
    return r;
  });
  on("classic.*", async ($, e, next) => {
    const t = Date.now();
    const r = await next(e);
    rec("classic", { event: next.event, ms: Date.now() - t, e: safe(e), r: safe(r), trace: safe(next.trace) });
    await flush($);
    return r;
  });
  // 2. DENY: Bash whose command contains DENYME
  on("tool.call", { tool: "Bash", command: /DENYME/ }, async ($, e, next) => {
    rec("deny", { e: safe(e) });
    return { deny: "probe2 policy: commands containing DENYME are refused (function hook)" };
  });
  // 3. REWRITE INPUT: Bash 'echo ORIGINAL' -> 'echo REWRITTEN'
  on("tool.call", { tool: "Bash", command: /echo ORIGINAL/ }, async ($, e, next) => {
    const r = await next({ ...e, command: e.command.replace("ORIGINAL", "REWRITTEN-BY-HOOK") });
    rec("rewrite-input", { before: e.command, r: safe(r) });
    return r;
  });
  // 4. REPLACE RESULT: Read of secret.txt returns redacted content
  on("tool.call", { tool: "Read", file_path: /secret\.txt$/ }, async ($, e, next) => {
    const real = await next(e);
    rec("replace-result", { real: safe(real) });
    return { result: { type: "text", file: { filePath: e.file_path, content: "REDACTED-BY-PROBE2 (real file had " + String(real.text ?? "").length + " chars)", numLines: 1, startLine: 1, totalLines: 1 } } };
  });
  // 5. DELAY: Bash 'echo SLOW' waits 1500ms before continuing
  on("tool.call", { tool: "Bash", command: /echo SLOW/ }, async ($, e, next) => {
    const t = Date.now();
    await $.clock.sleep(1500, { signal: next.signal });
    const r = await next(e);
    rec("delay", { waitedMs: Date.now() - t });
    return r;
  });
  // 6. THROW: Bash 'echo BOOM' throws in the hook; .catch handler answers
  on("tool.call", { tool: "Bash", command: /echo BOOM/ }, async ($, e, next) => {
    throw new Error("probe2 deliberate throw");
  }).catch(async ($, e, next) => {
    rec("caught", { error: safe(next.error), called: next.called });
    return next(e);
  });
  // 7. THROW without catch: Bash 'echo CRASH' -> hook is skipped, chain continues
  on("tool.call", { tool: "Bash", command: /echo CRASH/ }, async ($, e, next) => {
    throw new Error("probe2 uncaught throw");
  });
  // 8. register a tool and serve it
  on("session.start", async ($, e, next) => {
    const reg = await $.tool.register({ name: "probe_echo", description: "Echoes its input back with a PROBE2 stamp. Call it with { text }.", inputSchema: { type: "object", properties: { text: { type: "string" } }, required: ["text"] } });
    rec("registered", { reg });
    await flush($);
    return next(e);
  });
  on("tool.call", { tool: "mcp__probe2__probe_echo" }, async ($, e, next) => {
    let label;
    try { label = await $.model.classify(String(e.text), ["greeting", "question", "command"]); } catch (err) { label = "ERR:" + String(err); }
    rec("served-tool", { e: safe(e), label });
    return { result: { content: [{ type: "text", text: "PROBE2 says: " + e.text + " (classified as " + label + ")" }] } };
  });
  // 9. tool.check observer for the ask/allow verdict
  on("tool.check", async ($, e, next) => {
    const r = await next(e);
    rec("check", { e: safe(e), r: safe(r) });
    return r;
  });
  on("turn.complete", async ($, e, next) => { rec("turn.complete", { e: safe(e) }); await flush($); return next(e); });
};
