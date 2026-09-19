const LOG = "C:/Projects/claude-mods-rnd/lab/probe-ui/probe-ui.log";
const lines = [];
const seen = {};
function safe(v) { try { const s = JSON.stringify(v); return s && s.length > 1500 ? s.slice(0, 1500) + "…" : JSON.parse(s ?? "null"); } catch { return String(v); } }
async function flush($) { try { await $.fs.write(LOG, lines.join("\n") + "\n"); } catch (e) {} }
function rec(kind, data) { lines.push(JSON.stringify({ t: Date.now(), kind, ...data })); }
export const register = (on, options) => {
  on("session.start", async ($, e, next) => {
    rec("session.start", { e, surfaces: await $.session.surfaces() });
    $.ui.log("probe-ui: hooks module loaded (this line is $.ui.log)");
    $.ui.status("probe-ui status line");
    $.ui.toast("probe-ui toast: hello from a function hook", { timeoutMs: 8000 });
    await $.command.register({ name: "probeui", description: "probe-ui: opens the probe pane", immediate: true });
    try { await $.ui.open({ id: "probe-pane", title: "PROBE PANE", rows: 6 }); rec("pane", { opened: true }); } catch (err) { rec("pane", { error: String(err) }); }
    await flush($);
    return next(e);
  });
  on("command.run", { command: "probeui" }, async ($, e, next) => {
    rec("command.run", { e: safe(e) });
    await $.ui.open({ id: "probe-pane", title: "PROBE PANE (via /probeui)", focus: true, closeOnEscape: true, rows: 6 });
    await flush($);
    return { text: "probe-ui: pane opened" };
  });
  on("ui.render", async ($, e, next) => {
    const key = e.surface + ":" + e.component;
    seen[key] = (seen[key] ?? 0) + 1;
    if (seen[key] <= 2) rec("ui.render", { surface: e.surface, component: e.component, requestId: e.requestId, viewport: e.viewport ?? null, props: safe(e.props) });
    if (e.component === "Pane" && e.requestId === "probe-pane") {
      const { Box, Text, Button } = $.ui.resolve(e);
      return <Box flexDirection="column"><Text bold color="green">PROBE PANE BODY</Text><Text dimColor>components seen: {Object.keys(seen).length}</Text><Button key="ping" label="ping" hotkey="p" onPress={() => { rec("press", { key: "ping" }); }} /></Box>;
    }
    if (e.component === "AbovePrompt" && e.surface === "terminal") {
      const { Box, Text } = $.ui.resolve(e);
      return <Box borderStyle="round" borderColor="cyan"><Text color="cyan">PROBE-UI ABOVE PROMPT: {Object.keys(seen).length} component kinds rendered</Text></Box>;
    }
    if (e.component === "ToolUse") {
      const { Box, Text } = $.ui.resolve(e);
      const inner = await next(e);
      return <Box flexDirection="column"><Text dimColor>[probe-ui wrapped ToolUse {e.props.tool}]</Text>{inner}</Box>;
    }
    await flush($);
    return next(e);
  });
  on("ui.press", async ($, e, next) => { rec("ui.press", { e: safe(e) }); await flush($); return next(e); });
  on("ui.close", async ($, e, next) => { rec("ui.close", { e: safe(e) }); await flush($); return next(e); });
  on("turn.complete", async ($, e, next) => { rec("turn.complete", { answer: e.answer.slice(0, 100), seen }); $.ui.toast("turn done in " + Math.round(e.durationMs / 1000) + "s"); await flush($); return next(e); });
};
