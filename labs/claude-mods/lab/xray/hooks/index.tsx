// CLAUDE RUNTIME X-RAY — makes the function-hooks runtime visible.
// Every event the engine raises passes through the on("*") hook below; the hook classifies it,
// prints one line into the transcript (filtered), keeps a ring buffer for the HUD above the prompt,
// and appends everything to a black-box timeline file.
const TIMELINE_DIR = "C:/Projects/claude-mods-rnd/lab/xray/timeline/";
const FILTERS = ["all", "tools", "subagents", "session", "usage", "ui", "errors", "unknown", "off"];

// Which class an event belongs to (for the filter) — built from MOD_CAPABILITY_MAP.md.
const KNOWN = {
  tools: ["tool.call", "tool.check", "tool.describe", "tool.register", "tool.list", "classic.PreToolUse", "classic.PostToolUse", "classic.PostToolUseFailure", "classic.PostToolBatch", "classic.PermissionRequest", "classic.PermissionDenied", "mcp.call"],
  subagents: ["agent.spawn", "agent.offer", "agent.list", "classic.SubagentStart", "classic.SubagentStop", "classic.TaskCreated", "classic.TaskCompleted", "classic.TeammateIdle"],
  session: ["session.start", "session.receive", "session.compact", "session.attach", "session.detach", "session.cwd", "session.model", "session.turns", "session.id", "session.messages", "session.repo", "session.surface", "session.surfaces", "session.authorize", "prompt.submit", "prompt.fill", "prompt.suggest", "prompt.section", "prompt.context", "turn.start", "turn.step", "turn.complete", "turn.abort", "engine.create", "plugin.register", "command.run", "command.describe", "command.list", "command.register", "config.set", "config.describe", "config.list", "skill.prompt", "attribution.text", "settings.read", "env.get", "env.set", "fs.read", "fs.write", "fs.list", "fs.exists", "fs.stat", "fs.ancestors", "store.get", "store.set", "store.delete", "store.keys", "clock.now", "clock.sleep", "clock.after", "clock.every", "http.fetch", "process.run", "classic.SessionStart", "classic.SessionEnd", "classic.UserPromptSubmit", "classic.UserPromptExpansion", "classic.Stop", "classic.StopFailure", "classic.PreCompact", "classic.PostCompact", "classic.Setup", "classic.ConfigChange", "classic.InstructionsLoaded", "classic.WorktreeCreate", "classic.WorktreeRemove", "classic.CwdChanged", "classic.FileChanged", "classic.DirectoryAdded", "classic.Notification", "classic.Elicitation", "classic.ElicitationResult"],
  usage: ["session.usage", "classic.PreModelSwitch", "classic.PostModelSwitch", "model.complete", "model.classify", "model.fork"],
  ui: ["ui.render", "ui.resolve", "ui.press", "ui.input", "ui.select", "ui.message", "ui.scroll", "ui.focus", "ui.toast", "ui.status", "ui.log", "ui.notice", "ui.invalidate", "ui.open", "ui.close", "ui.blit", "audio.play", "audio.speak", "classic.MessageDisplay"],
};
// What a hook can do at each event (only capabilities that actually exist; verified in MOD_CAPABILITY_MAP.md).
const CAPS = {
  "tool.call":     "observe✓ modify-args✓ block✓ delay✓ replace-result✓ hidden-context✓",
  "tool.check":    "observe✓ decide(allow/ask/deny)✓ block✓ delay✓",
  "tool.describe": "observe✓ rewrite-description✓",
  "agent.spawn":   "observe✓ rewrite(model/prompt/type/cwd)✓ block✓ delay✓",
  "agent.offer":   "observe✓ hide-agent✓",
  "prompt.submit": "observe✓ rewrite-text✓ hidden-context✓ drop✓ delay✓",
  "turn.step":     "observe(stream)✓ rewrite(model/effort)✓ rewrite/drop-chunks✓ own-response✓ usage✓",
  "turn.complete": "observe✓ usage✓ alt-text-beneath✓",
  "turn.start":    "observe✓",
  "session.start": "observe✓ register-tools/commands✓ start-timers✓",
  "session.compact": "observe✓ rewrite-messages✓ skip✓",
  "ui.render":     "observe✓ wrap✓ replace-tree✓ rewrite-props✓",
  "command.run":   "observe✓ rewrite-args✓ answer✓",
  "engine.create": "observe✓ add-noun✓ withhold-noun✓",
  "plugin.register": "observe✓ refuse✓",
};
const NOISY = new Set(["ui.render", "command.describe", "tool.describe", "agent.offer", "ui.invalidate", "clock.now", "store.get", "fs.write", "fs.read", "ui.status", "ui.log", "session.id", "session.usage"]);

const state = { filter: "tools", count: 0, byEvent: {}, ring: [], timeline: [], sessionId: "", unknown: {}, errors: 0, dirty: false, subagents: {}, lastUsage: null };

function classOf(event) {
  for (const k of Object.keys(KNOWN)) if (KNOWN[k].includes(event)) return k;
  return "unknown";
}
function passes(event, cls, isError) {
  const f = state.filter;
  if (f === "off") return false;
  if (f === "errors") return isError;
  if (f === "all") return !NOISY.has(event);
  if (f === "unknown") return cls === "unknown";
  return cls === f;
}
function short(v, n) { let s; try { s = typeof v === "string" ? v : JSON.stringify(v); } catch { s = String(v); } s = (s ?? "").replace(/\s+/g, " "); return s.length > n ? s.slice(0, n - 1) + "…" : s; }
function describe(event, e) {
  if (!e || typeof e !== "object") return "";
  if (event === "tool.call") { const { tool, tool_use_id, agentId, ...args } = e; return `${tool} ${short(args, 70)}${agentId ? "  agent=" + String(agentId).slice(0, 8) : ""}`; }
  if (event === "tool.check") return `${e.tool} ${short(e.input, 60)}`;
  if (event === "agent.spawn") return `${e.subagentType} model=${e.model ?? "inherit"} parent=${e.parentModel} bg=${e.background} "${short(e.description, 40)}"`;
  if (event === "turn.step") return `#${e.index} ${e.model} effort=${e.effort ?? "-"} msgs=${e.messageCount}${e.agentId ? " agent=" + String(e.agentId).slice(0, 8) : ""}`;
  if (event === "turn.complete") return `${e.reason} ${e.durationMs}ms ${e.usage ? `in=${e.usage.input_tokens} out=${e.usage.output_tokens} cacheR=${e.usage.cache_read_input_tokens} cacheW=${e.usage.cache_creation_input_tokens}` : ""}${e.agentId ? " agent=" + String(e.agentId).slice(0, 8) : ""}`;
  if (event === "prompt.submit") return `${e.origin ? e.origin.kind : "?"} "${short(e.text, 60)}"`;
  if (event === "ui.render") return `${e.component}@${e.surface} ${short(e.requestId, 24)}`;
  if (event === "command.run") return `/${e.command} ${short(e.args, 40)}`;
  if (event === "session.usage") return "";
  return short(e, 90);
}
function resultLine(event, r) {
  if (!r || typeof r !== "object") return "";
  if (r.deny) return `DENIED: ${short(r.deny, 60)}`;
  if (event === "tool.call") return r.isError ? `ERROR: ${short(r.text, 60)}` : `→ ${short(r.text ?? r.result, 60)}`;
  if (event === "tool.check") return `→ ${r.decision}${r.rule ? " by " + r.rule : ""}${r.reason ? " (" + short(r.reason, 40) + ")" : ""}`;
  if (event === "agent.spawn") return `→ ${r.model} agentId=${r.agentId}`;
  if (event === "session.usage" && r.value) { const v = r.value; return `ctx ${v.context && v.context.percent !== undefined ? v.context.percent : "?"}% of ${v.context ? v.context.window : "?"} · ${(v.rateLimits || []).map(x => x.kind + " " + x.percentUsed + "%").join(" ")} · $${v.cost ? v.cost.usd.toFixed(3) : "?"}`; }
  return "";
}
function pipeline(trace) {
  // Claude → [xray] → plugin links beneath → core
  const links = (trace || []).map(t => `${t.plugin}${t.tier === "core" ? "" : "/" + t.tier}${t.outcome !== "returned" && t.outcome !== "passed" ? "(" + t.outcome + ")" : ""} ${Math.round(t.ms)}ms`);
  return ["Claude", "[xray]", ...links].join(" → ");
}
function record(entry) {
  state.count++; state.byEvent[entry.event] = (state.byEvent[entry.event] || 0) + 1;
  state.ring.push(entry); if (state.ring.length > 8) state.ring.shift();
  state.timeline.push(entry); if (state.timeline.length > 3000) state.timeline.shift();
  state.dirty = true;
}
async function flushTimeline($) {
  if (!state.dirty || !state.sessionId) return;
  state.dirty = false;
  try { await $.fs.write(TIMELINE_DIR + state.sessionId + ".jsonl", state.timeline.map(x => JSON.stringify(x)).join("\n") + "\n"); } catch (err) {}
}
function safeJson(v, n) { try { const s = JSON.stringify(v); if (s === undefined) return null; return s.length > n ? s.slice(0, n) + "…" : JSON.parse(s); } catch { return String(v); } }
function usageSummary() {
  const u = state.lastUsage; if (!u) return "";
  return ` · ctx ${u.context && u.context.percent !== undefined ? u.context.percent : "?"}% · ${(u.rateLimits || []).map(x => x.kind + " " + Math.round(x.percentUsed) + "%").join(" ")} · $${u.cost ? u.cost.usd.toFixed(3) : "?"}`;
}
function statusText() { return `x-ray ${state.filter} · ${state.count} events · ${state.errors} errors`; }
function tick($) { void flushTimeline($); if (state.dirty) { $.ui.invalidate("ui.render"); } $.ui.status(statusText()); }

export const register = (on, options) => {
  on("*", async ($, e, next) => {
    const event = next.event;
    if (event === "engine.create") return next(e);
    const cls = classOf(event);
    if (cls === "unknown") state.unknown[event] = (state.unknown[event] || 0) + 1;
    const t0 = Date.now();
    let r, threw;
    try { r = await next(e); } catch (err) { threw = String(err); }
    const ms = Date.now() - t0;
    const isError = !!threw || !!(r && typeof r === "object" && (r.deny || r.isError || r.drop || r.refuse || r.skip));
    if (isError) state.errors++;
    if (event === "agent.spawn" && r && r.agentId) state.subagents[r.agentId] = { type: e.subagentType, model: r.model, calls: 0 };
    if (event === "tool.call" && e && e.agentId && state.subagents[e.agentId]) state.subagents[e.agentId].calls++;
    if (event === "session.usage" && r && r.value) state.lastUsage = r.value;
    const entry = { t: t0, ms, event, cls, origin: next.origin, agentId: e && typeof e === "object" && e.agentId ? e.agentId : null, e: event === "ui.render" ? { component: e.component, surface: e.surface, requestId: e.requestId } : safeJson(e, 1500), r: safeJson(r, 1500), threw: threw || null, trace: (next.trace || []).map(t => ({ plugin: t.plugin, tier: t.tier, outcome: t.outcome, ms: t.ms })) };
    record(entry);
    if (passes(event, cls, isError) && event !== "ui.render") {
      const caps = CAPS[event] ? "   [" + CAPS[event] + "]" : "";
      const line = `⟦xray⟧ ${event} ${describe(event, e)} ${resultLine(event, r)}  ·${ms}ms · from ${next.origin.plugin}/${next.origin.tier}${threw ? "  THREW " + short(threw, 60) : ""}`;
      $.ui.log(line);
      if (state.filter !== "all" || event === "tool.call" || event === "turn.step") $.ui.log(`        ${pipeline(next.trace)}${caps}`);
    }
    if (threw) throw new Error(threw);
    return r;
  });

  on("session.start", async ($, e, next) => {
    state.sessionId = await $.session.id();
    const stored = await $.store.get("filter");
    if (typeof stored === "string" && FILTERS.includes(stored)) state.filter = stored;
    await $.command.register({ name: "xray", description: "X-RAY filter: all | tools | subagents | session | usage | ui | errors | unknown | off | status", argumentHint: "[filter]", immediate: true });
    $.ui.status(statusText());
    $.clock.every(1000, () => tick($));
    $.ui.log(`⟦xray⟧ armed · filter=${state.filter} · timeline → ${TIMELINE_DIR}${state.sessionId}.jsonl · /xray <filter> to switch`);
    return next(e);
  });

  on("command.run", { command: "xray" }, async ($, e, next) => {
    const arg = (e.args || "").trim().toLowerCase();
    if (arg === "status" || arg === "") {
      const top = Object.entries(state.byEvent).sort((a, b) => b[1] - a[1]).slice(0, 12).map(([k, v]) => `${k}=${v}`).join("  ");
      const unk = Object.keys(state.unknown).length ? "\nUNKNOWN EVENTS: " + Object.entries(state.unknown).map(([k, v]) => `${k}=${v}`).join("  ") : "\nUNKNOWN EVENTS: none";
      const subs = Object.entries(state.subagents).map(([id, s]) => `${id.slice(0, 8)} ${s.type} ${s.model} calls=${s.calls}`).join("\n  ");
      return { text: `X-RAY filter=${state.filter} · ${state.count} events · ${state.errors} errors\nTOP: ${top}${unk}\nSUBAGENTS: ${subs || "none"}${usageSummary()}\nTIMELINE: ${TIMELINE_DIR}${state.sessionId}.jsonl` };
    }
    if (!FILTERS.includes(arg)) return { text: `x-ray: unknown filter "${arg}". One of: ${FILTERS.join(" ")}` };
    state.filter = arg; await $.store.set("filter", arg); $.ui.invalidate("ui.render");
    return { text: `x-ray filter → ${arg}` };
  });

  on("ui.render", { component: "AbovePrompt", surface: "terminal" }, async ($, e, next) => {
    if (state.filter === "off") return next(e);
    const { Box, Text } = $.ui.resolve(e);
    const width = Math.max(40, e.props.bodyColumns - 4);
    const rows = state.ring.slice(-5).map((x, i) => {
      const bad = !!x.threw || !!(x.r && x.r.deny);
      const text = `${x.event.padEnd(16)} ${describe(x.event, x.e)} ${resultLine(x.event, x.r)} ${x.ms}ms`.slice(0, width);
      return bad ? <Text key={"r" + i} color="red" wrap="truncate-end">{text}</Text> : <Text key={"r" + i} dimColor wrap="truncate-end">{text}</Text>;
    });
    const subs = Object.keys(state.subagents).length;
    return (
      <Box flexDirection="column" borderStyle="round" borderColor="magenta" paddingX={1}>
        <Text bold color="magenta">{`CLAUDE RUNTIME X-RAY  filter=${state.filter}  events=${state.count}  errors=${state.errors}  subagents=${subs}  unknown=${Object.keys(state.unknown).length}${usageSummary()}`}</Text>
        {rows}
      </Box>
    );
  });

  on("turn.complete", async ($, e, next) => {
    if (!e.agentId) { try { state.lastUsage = await $.session.usage(); } catch (err) {} }
    await flushTimeline($);
    return next(e);
  });
};
