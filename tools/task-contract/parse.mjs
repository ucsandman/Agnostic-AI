/**
 * Restricted YAML reader for TASK_CONTRACT.md.
 *
 * Deliberately NOT a YAML parser. It accepts exactly the subset the contract
 * schema uses — top-level scalars, top-level lists of flat maps, scalar and
 * inline-array values — and throws on anything else. A contract that needs a
 * feature outside the subset is a contract that has drifted from the schema,
 * and silently half-parsing it is the same class of failure the contract
 * exists to prevent: a green that means "I did not look."
 */

const SCALAR_TRUE = /^(true|yes)$/i;
const SCALAR_FALSE = /^(false|no)$/i;

function stripQuotes(raw) {
  const s = raw.trim();
  if (s.length >= 2 && ((s[0] === '"' && s.at(-1) === '"') || (s[0] === "'" && s.at(-1) === "'"))) {
    return s.slice(1, -1);
  }
  return s;
}

function coerce(raw) {
  const s = raw.trim();
  if (s === '') return '';
  if (s.startsWith('[') && s.endsWith(']')) {
    const inner = s.slice(1, -1).trim();
    if (inner === '') return [];
    return inner.split(',').map((p) => coerce(p));
  }
  if (SCALAR_TRUE.test(s)) return true;
  if (SCALAR_FALSE.test(s)) return false;
  if (/^-?\d+$/.test(s)) return Number(s);
  return stripQuotes(s);
}

/** Pull the first ```yaml fence out of a markdown document. */
export function extractYamlBlock(markdown) {
  const lines = markdown.split(/\r?\n/);
  const out = [];
  let inside = false;
  for (const line of lines) {
    const fence = line.trim();
    if (!inside && (fence === '```yaml' || fence === '```yml')) { inside = true; continue; }
    if (inside && fence === '```') break;
    if (inside) out.push(line);
  }
  if (!inside) throw new Error('no ```yaml block found in contract');
  return out.join('\n');
}

export function parseContract(yamlText) {
  const doc = {};
  const lines = yamlText.split(/\r?\n/);
  let currentKey = null;   // top-level list key being filled
  let currentItem = null;  // map inside that list
  let itemIndent = null;   // indent every continuation key of that item must sit at

  const flush = () => {
    if (currentKey && currentItem) doc[currentKey].push(currentItem);
    currentItem = null;
  };

  for (let i = 0; i < lines.length; i += 1) {
    const raw = lines[i];
    if (!raw.trim() || raw.trim().startsWith('#')) continue;
    const indent = raw.length - raw.trimStart().length;
    const line = raw.trim();

    if (indent === 0) {
      flush();
      currentKey = null;
      const m = line.match(/^([A-Za-z_][\w-]*):\s*(.*)$/);
      if (!m) throw new Error(`line ${i + 1}: expected "key:" at top level, got: ${line}`);
      const [, key, rest] = m;
      if (rest === '') { doc[key] = []; currentKey = key; }
      else doc[key] = coerce(rest);
      continue;
    }

    if (!currentKey) throw new Error(`line ${i + 1}: indented line outside a list: ${line}`);

    if (line.startsWith('- ')) {
      flush();
      currentItem = {};
      // Continuation keys of this item line up under the text after "- ".
      itemIndent = indent + 2;
      const m = line.slice(2).match(/^([A-Za-z_][\w-]*):\s*(.*)$/);
      if (!m) throw new Error(`line ${i + 1}: list item must start with "key: value", got: ${line}`);
      currentItem[m[1]] = coerce(m[2]);
      continue;
    }

    if (!currentItem) throw new Error(`line ${i + 1}: value outside a list item: ${line}`);
    // Anything deeper than the item's own keys is a nested structure. The subset
    // has none, and flattening it would let a malformed contract read as valid —
    // the same silent-acceptance failure this whole mechanism exists to stop.
    if (indent !== itemIndent) {
      throw new Error(`line ${i + 1}: expected "key: value" at indent ${itemIndent}, got indent ${indent}: ${line}`);
    }
    const m = line.match(/^([A-Za-z_][\w-]*):\s*(.*)$/);
    if (!m) throw new Error(`line ${i + 1}: expected "key: value", got: ${line}`);
    currentItem[m[1]] = coerce(m[2]);
  }
  flush();
  return doc;
}
