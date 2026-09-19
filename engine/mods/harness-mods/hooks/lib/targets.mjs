// targets.mjs — the (tool, target) grain, shared with CostClaw. Pure.
//
// commandTarget / targetFor are ported verbatim from costclaw packages/engine/src/parser.ts:65-100
// (CostClaw now exports them: see costclaw packages/engine/src/targets.ts). Keep the two in
// lockstep; the drift test in tests/targets.test.mjs compares against the CostClaw copy when present.
//
// observation() is the addition the 2026-09-16 dogfood asked for (DOGFOOD.md finding 1): a logical
// file observation may happen through Read, Grep, Glob, or a safe shell inspection (cat, head, tail,
// wc, type, Get-Content). It resolves the FILE the call observes, so a repeated-read rule keys on
// the file, not the tool name. Serving from cache stays stricter (see readcache in index.tsx).

export function commandTarget(command) {
  let s = String(command || "").trim();
  const hop = /^(?:cd|Set-Location|pushd)\s+(?:"[^"]*"|'[^']*'|\S+)\s*(?:&&|;)\s*/i;
  const env = /^[A-Za-z_][A-Za-z0-9_]*=(?:"[^"]*"|'[^']*'|\S*)\s+/;
  for (;;) {
    const next2 = s.replace(hop, "").replace(env, "");
    if (next2 === s) break;
    s = next2;
  }
  const words = s.split(/\s+/).filter(Boolean);
  if (words.length === 0) return null;
  return words.slice(0, 2).join(" ").slice(0, 60);
}

export function targetFor(name, input) {
  const s = (v, n) => (typeof v === "string" && v.length ? v.slice(0, n) : null);
  input = input || {};
  if (["Read", "Edit", "Write", "NotebookEdit"].includes(name)) return s(input.file_path || input.notebook_path, 200);
  if (["Grep", "Glob"].includes(name)) return s(input.path || input.glob || input.pattern, 160);
  if (["Bash", "PowerShell"].includes(name)) return typeof input.command === "string" ? commandTarget(input.command) : null;
  if (String(name).indexOf("Task") === 0) return s(input.subject || input.description, 80);
  if (["WebFetch", "WebSearch"].includes(name)) return s(input.url || input.query, 60);
  if (name === "Agent") return s(input.subagent_type || input.description, 60);
  return null;
}

// ---- file observations across mechanisms ---------------------------------------------------

const INSPECT_VERBS = new Set(["cat", "head", "tail", "wc", "type", "less", "more", "get-content", "gc"]);
// One simple command: no pipes, no redirects, no chaining, no substitution. Flags allowed only in
// the numeric/short forms these verbs take. Anything else is not a safe inspection.
const SIMPLE = /^(?:cd\s+(?:"[^"]*"|'[^']*'|\S+)\s*(?:&&|;)\s*)?([A-Za-z-]+)((?:\s+-{1,2}[A-Za-z]+(?:\s+\d+|=\d+|\d+)?)*)\s+("[^"]+"|'[^']+'|[^\s"'|&;<>$`]+)\s*(?:#.*)?$/;

function normPath(p) {
  return String(p || "").replace(/^["']|["']$/g, "").replace(/\\/g, "/");
}

/**
 * Resolve the file a call OBSERVES (reads without changing), or null.
 * Returns { path, via, exact } where `exact` is true when the observation is a whole-file read
 * whose result would be byte-identical to a repeat (Read with no offset/limit; plain `cat file`).
 */
export function observation(tool, input) {
  input = input || {};
  if (tool === "Read" && typeof input.file_path === "string") {
    return { path: normPath(input.file_path), via: "Read", exact: input.offset === undefined && input.limit === undefined };
  }
  if ((tool === "Grep" || tool === "Glob") && typeof input.path === "string") {
    return { path: normPath(input.path), via: tool, exact: false };
  }
  if ((tool === "Bash" || tool === "PowerShell") && typeof input.command === "string") {
    const m = SIMPLE.exec(input.command.trim());
    if (!m) return null;
    const verb = m[1].toLowerCase();
    if (!INSPECT_VERBS.has(verb)) return null;
    const flags = (m[2] || "").trim();
    const path = normPath(m[3]);
    if (!path || path.startsWith("-")) return null;
    return { path, via: tool + " " + verb, exact: verb === "cat" && flags === "" };
  }
  return null;
}

/** Paths a call MUTATES (invalidates any cached observation of them). */
export function mutations(tool, input) {
  input = input || {};
  if (["Write", "Edit", "MultiEdit", "NotebookEdit"].includes(tool)) {
    const p = input.file_path || input.notebook_path;
    return p ? [normPath(p)] : [];
  }
  if ((tool === "Bash" || tool === "PowerShell") && typeof input.command === "string") {
    // Shell writes cannot be resolved to exact paths safely; report the mutation as "unknown" so the
    // cache is flushed whole. A plain inspection command is not a mutation.
    if (observation(tool, input)) return [];
    if (/(^|[^&|<>])>>?|\bsed\s+-\w*i|\btee\b|\b(?:Set-Content|Out-File|Add-Content|Copy-Item|Move-Item|Remove-Item|Rename-Item|New-Item)\b|\b(?:cp|mv|rm|truncate|touch|mkdir|rmdir|git\s+(?:checkout|reset|stash|pull|merge|rebase|apply|clean)|npm\s+(?:i|install|ci)|pip\s+install)\b/i.test(input.command)) return ["*"];
    return [];
  }
  return [];
}
