// redact.mjs — detection becomes redaction. Pure.
//
// Patterns are the harness's mature vendor-prefixed shapes, shared with output-secret-watch.cjs and
// tool-output-secret-watch.cjs so the three channels cannot drift apart. The two classic watches
// DETECT after the fact ("by the time PostToolUse fires the result is already in the transcript");
// this module produces the replacement text a `tool.call` hook returns INSTEAD, so the model never
// receives the value. Never returns or logs a secret: hits carry kind, head (8 chars) and length only.

import patterns from "./secret-patterns.mjs";

export const PATTERNS = patterns.PATTERNS;
export const PLACEHOLDER = patterns.PLACEHOLDER;

export function mask(kind, len) {
  return "<REDACTED:" + kind + ":" + len + ">";
}

/** Redact one string. Returns { text, hits } (hits: [{kind, head, len}]). */
export function redactText(text) {
  if (typeof text !== "string" || !text) return { text, hits: [] };
  const hits = [];
  let out = text;
  for (const [kind, re] of PATTERNS) {
    const g = new RegExp(re.source, re.flags.includes("g") ? re.flags : re.flags + "g");
    out = out.replace(g, (m) => {
      if (PLACEHOLDER.test(m)) return m;
      hits.push({ kind, head: m.slice(0, 8) + "…", len: m.length });
      return mask(kind, m.length);
    });
  }
  return { text: out, hits };
}

/** Deep-redact every string inside a tool result record (Bash {stdout,stderr}, Read {content…}, MCP content blocks…). */
export function redactValue(value, depth = 0) {
  if (depth > 12) return { value, hits: [] };
  if (typeof value === "string") {
    const r = redactText(value);
    return { value: r.text, hits: r.hits };
  }
  if (Array.isArray(value)) {
    const hits = [];
    const out = value.map((v) => { const r = redactValue(v, depth + 1); hits.push(...r.hits); return r.value; });
    return { value: out, hits };
  }
  if (value && typeof value === "object") {
    const hits = [];
    const out = {};
    for (const k of Object.keys(value)) { const r = redactValue(value[k], depth + 1); hits.push(...r.hits); out[k] = r.value; }
    return { value: out, hits };
  }
  return { value, hits: [] };
}

/**
 * Redact a tool.call result. `r` is what next(e) resolved to: { result, text?, isError?, context? }.
 * Returns null when nothing matched (return the original), else the replacement result object plus hits.
 * The engine re-maps the model-facing text from `result` with the tool's own mapper.
 */
export function redactToolResult(r) {
  if (!r || r.deny !== undefined) return null;
  const res = redactValue(r.result);
  const txt = typeof r.text === "string" ? redactText(r.text) : { text: r.text, hits: [] };
  const hits = [...res.hits, ...txt.hits];
  if (!hits.length) return null;
  const kinds = [...new Set(hits.map((h) => h.kind))];
  return { result: res.value, hits, kinds };
}

/** A summary line safe to log or show: never the value. */
export function summarize(hits) {
  const byKind = {};
  for (const h of hits) byKind[h.kind] = (byKind[h.kind] || 0) + 1;
  return Object.keys(byKind).map((k) => k + "×" + byKind[k]).join(", ");
}
