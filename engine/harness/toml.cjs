/**
 * engine/harness/toml.cjs — a small TOML reader for the subset client configs use.
 *
 * Handles: top-level key/value, [table], [table."quoted key"], [[array.of.tables]],
 * basic/literal/multiline strings, integers, floats, booleans, arrays (multi-line),
 * inline tables, comments. Unknown constructs are recorded in `warnings`, never
 * thrown, because a config we cannot fully read must still be readable in part.
 *
 * Writing is done by the adapters through managed regions (common.replaceRegion)
 * with common.tomlStr / tomlMultiline for values; there is no serializer here.
 */

function parse(text) {
  const root = {};
  const warnings = [];
  let current = root;
  const lines = String(text).split(/\r?\n/);
  let i = 0;

  const unescape = (s) => s.replace(/\\(u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8}|.)/g, (m, e) => {
    switch (e[0]) {
      case 'n': return '\n'; case 't': return '\t'; case 'r': return '\r'; case '"': return '"'; case '\\': return '\\';
      case 'b': return '\b'; case 'f': return '\f';
      case 'u': case 'U': return String.fromCodePoint(parseInt(e.slice(1), 16));
      default: return m;
    }
  });

  // Parse a value starting at `s`; returns [value, rest]. `more()` pulls the next
  // physical line for multi-line arrays and strings.
  function parseValue(s, more) {
    s = s.trimStart();
    if (s.startsWith('"""')) {
      let body = s.slice(3);
      if (body.startsWith('\n')) body = body.slice(1);
      let acc = '';
      for (;;) {
        const end = body.indexOf('"""');
        if (end !== -1 && !/\\$/.test(body.slice(0, end))) { acc += body.slice(0, end); return [unescape(acc.replace(/^\n/, '')), body.slice(end + 3)]; }
        acc += body + '\n';
        const next = more();
        if (next == null) return [unescape(acc), ''];
        body = next;
      }
    }
    if (s.startsWith("'''")) {
      let body = s.slice(3).replace(/^\n/, '');
      let acc = '';
      for (;;) {
        const end = body.indexOf("'''");
        if (end !== -1) { acc += body.slice(0, end); return [acc, body.slice(end + 3)]; }
        acc += body + '\n';
        const next = more();
        if (next == null) return [acc, ''];
        body = next;
      }
    }
    if (s[0] === '"') {
      let j = 1; let out = '';
      while (j < s.length && s[j] !== '"') { if (s[j] === '\\') { out += s[j] + s[j + 1]; j += 2; } else out += s[j++]; }
      return [unescape(out), s.slice(j + 1)];
    }
    if (s[0] === "'") { const j = s.indexOf("'", 1); return [s.slice(1, j), s.slice(j + 1)]; }
    if (s[0] === '[') {
      const arr = []; let rest = s.slice(1);
      for (;;) {
        rest = rest.replace(/^\s*(#[^\n]*)?/, '');
        if (!rest) { const next = more(); if (next == null) return [arr, '']; rest = next; continue; }
        if (rest[0] === ']') return [arr, rest.slice(1)];
        if (rest[0] === ',') { rest = rest.slice(1); continue; }
        const [v, r] = parseValue(rest, more); arr.push(v); rest = r;
      }
    }
    if (s[0] === '{') {
      const obj = {}; let rest = s.slice(1);
      for (;;) {
        rest = rest.trimStart();
        if (rest[0] === '}') return [obj, rest.slice(1)];
        if (rest[0] === ',') { rest = rest.slice(1); continue; }
        const km = rest.match(/^("(?:[^"\\]|\\.)*"|'[^']*'|[A-Za-z0-9_.-]+)\s*=\s*/);
        if (!km) { warnings.push(`unparseable inline table near: ${rest.slice(0, 40)}`); return [obj, '']; }
        const key = km[1].replace(/^["'](.*)["']$/, '$1');
        const [v, r] = parseValue(rest.slice(km[0].length), more); obj[key] = v; rest = r;
      }
    }
    const m = s.match(/^(true|false|[+-]?(?:inf|nan)|[+-]?\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d+)?|0x[0-9a-fA-F_]+|0o[0-7_]+|0b[01_]+|\d{4}-\d{2}-\d{2}[^\s,\]}]*)/);
    if (m) {
      const raw = m[1]; const rest = s.slice(raw.length);
      if (raw === 'true') return [true, rest];
      if (raw === 'false') return [false, rest];
      if (/^\d{4}-\d{2}-\d{2}/.test(raw)) return [raw, rest];
      const num = Number(raw.replace(/_/g, ''));
      return [Number.isNaN(num) ? raw : num, rest];
    }
    warnings.push(`unparseable value: ${s.slice(0, 40)}`);
    return [s, ''];
  }

  const splitKey = (k) => {
    const parts = []; let rest = k.trim();
    while (rest) {
      const m = rest.match(/^("(?:[^"\\]|\\.)*"|'[^']*'|[A-Za-z0-9_-]+)\s*(\.\s*)?/);
      if (!m) { warnings.push(`unparseable key: ${k}`); return parts; }
      parts.push(m[1].startsWith('"') ? unescape(m[1].slice(1, -1)) : m[1].replace(/^'(.*)'$/, '$1'));
      rest = rest.slice(m[0].length);
    }
    return parts;
  };

  const descend = (obj, parts, arrayLeaf) => {
    let node = obj;
    parts.forEach((p, idx) => {
      const last = idx === parts.length - 1;
      if (last && arrayLeaf) {
        if (!Array.isArray(node[p])) node[p] = [];
        const entry = {}; node[p].push(entry); node = entry;
        return;
      }
      if (node[p] === undefined) node[p] = {};
      if (Array.isArray(node[p])) {
        // [[a]] then [a.b]: the sub-table belongs to the LAST element of the array.
        if (!node[p].length) node[p].push({});
        node = node[p][node[p].length - 1];
      } else {
        node = node[p];
      }
    });
    return node;
  };

  while (i < lines.length) {
    let line = lines[i++];
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    let m;
    if ((m = trimmed.match(/^\[\[(.+)\]\]\s*(#.*)?$/))) { current = descend(root, splitKey(m[1]), true); continue; }
    if ((m = trimmed.match(/^\[(.+)\]\s*(#.*)?$/))) { current = descend(root, splitKey(m[1]), false); continue; }
    m = line.match(/^\s*("(?:[^"\\]|\\.)*"|'[^']*'|[A-Za-z0-9_.-]+(?:\s*\.\s*[A-Za-z0-9_.-]+)*)\s*=\s*(.*)$/);
    if (!m) { warnings.push(`line ${i}: ${trimmed.slice(0, 60)}`); continue; }
    const keyParts = splitKey(m[1]);
    const [value] = parseValue(m[2], () => (i < lines.length ? lines[i++] : null));
    const leaf = keyParts.pop();
    const holder = keyParts.length ? descend(current, keyParts, false) : current;
    holder[leaf] = value;
  }
  return { data: root, warnings };
}

module.exports = { parse };
