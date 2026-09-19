'use strict';
/**
 * engine/context/frontmatter.cjs — the YAML subset a context module's
 * frontmatter is written in, parsed without a dependency.
 *
 * Supported: nested maps (indent-based), block lists (`- item`), flow lists
 * (`[a, b]`), quoted and bare scalars, `true`/`false`/numbers, `#` comment
 * lines. Enough for `name`, `description`, `metadata:` and the `context:`
 * block below. Anchors, `|` block scalars and nested flow maps are out of
 * scope on purpose: a module that needs them should be simpler.
 *
 *   context:
 *     requires: [company, architecture]
 *     suggests: [customer-model]
 *     triggers:
 *       keywords: [billing, invoice, "price hike"]
 *       paths: ["C:/Projects/billing/**"]
 *       repos: [billing]
 *       tools: [Bash]
 *       agents: [opus-owner]
 *     scope: user
 *     clients: [claude, codex]
 *     priority: 60
 *     stale_after: 90d
 *     sensitivity: private
 *     section: "## Rules"
 */

const FENCE = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/;

function split(md) {
  const m = String(md).match(FENCE);
  if (!m) return { raw: null, body: String(md) };
  return { raw: m[1], body: m[2] };
}

function scalar(s) {
  const v = String(s).trim();
  if (v === '') return '';
  const q = v.match(/^"(.*)"$/) || v.match(/^'(.*)'$/);
  if (q) return q[1];
  if (v === 'true') return true;
  if (v === 'false') return false;
  if (v === 'null' || v === '~') return null;
  if (/^-?\d+(\.\d+)?$/.test(v)) return Number(v);
  return v;
}

function flowList(s) {
  const inner = s.trim().slice(1, -1).trim();
  if (!inner) return [];
  const out = [];
  let cur = '', quote = null;
  for (const ch of inner) {
    if (quote) { if (ch === quote) quote = null; else cur += ch; continue; }
    if (ch === '"' || ch === "'") { quote = ch; continue; }
    if (ch === ',') { out.push(scalar(cur)); cur = ''; continue; }
    cur += ch;
  }
  if (cur.trim() !== '' || out.length) out.push(scalar(cur));
  return out;
}

function value(s) {
  const v = String(s).trim();
  if (/^\[.*\]$/.test(v)) return flowList(v);
  return scalar(v);
}

/** Parse the YAML subset into a plain object. Never throws; lines it cannot read are skipped. */
function parseYaml(raw) {
  const lines = String(raw || '').split(/\r?\n/)
    .map((l) => ({ indent: l.match(/^ */)[0].length, text: l.trim() }))
    .filter((l) => l.text && !l.text.startsWith('#'));
  let i = 0;
  const isItem = (t) => t === '-' || t.startsWith('- ');

  function block(indent) {
    if (i >= lines.length) return {};
    return isItem(lines[i].text) ? list(indent) : map(indent);
  }
  function map(indent) {
    const out = {};
    while (i < lines.length && lines[i].indent === indent && !isItem(lines[i].text)) {
      const kv = lines[i].text.match(/^([A-Za-z_][A-Za-z0-9_-]*):(?:\s+(.*)|)$/);
      i++;
      if (!kv) continue;
      const key = kv[1];
      const rest = (kv[2] || '').replace(/\s+#.*$/, '').trim();
      if (rest === '') {
        out[key] = (i < lines.length && lines[i].indent > indent) ? block(lines[i].indent) : null;
      } else {
        out[key] = value(rest);
      }
    }
    return out;
  }
  function list(indent) {
    const out = [];
    while (i < lines.length && lines[i].indent === indent && isItem(lines[i].text)) {
      const rest = lines[i].text.replace(/^-\s*/, '').trim();
      i++;
      if (rest === '') {
        out.push((i < lines.length && lines[i].indent > indent) ? block(lines[i].indent) : null);
      } else {
        out.push(value(rest));
      }
    }
    return out;
  }
  return lines.length ? map(lines[0].indent) : {};
}

/**
 * parse(md) -> { meta, body, hasFrontmatter }
 * meta is the parsed frontmatter object; body is the markdown after it.
 */
function parse(md) {
  const { raw, body } = split(md);
  if (raw === null) return { meta: {}, body, hasFrontmatter: false };
  return { meta: parseYaml(raw), body, hasFrontmatter: true };
}

module.exports = { parse, parseYaml, split, scalar, flowList };
