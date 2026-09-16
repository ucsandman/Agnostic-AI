/**
 * engine/harness/status.cjs — what every client actually looks like right now.
 *
 * Reads the targets from disk (an apply run in check mode: nothing is written)
 * and reports per component whether it is in sync. Nothing is asserted from
 * memory; a claim here always came from a file this process just read.
 *
 * `renderHtml(report)` is the human surface: one standalone page, no assets.
 */

const fs = require('fs');
const os = require('os');
const path = require('path');

const bundleMod = require('./bundle.cjs');
const { apply, DEFAULT_STORAGE } = require('./apply.cjs');

const NO_BUNDLE = 'no bundle captured yet; run npm run capture';

/**
 * status({ home, port, storageDir, json, explain, bundleDir, html, quiet })
 *   -> { syncState, targets, report }
 * syncState is 'synced' | 'stale' | 'error' | 'no-bundle'.
 */
function status(options = {}) {
  const {
    home = os.homedir(), port, to, bundleDir, json = false, explain = false,
    html = false, quiet = false, adapters, registry,
  } = options;
  const storageDir = options.storageDir || DEFAULT_STORAGE;
  const log = options.log || ((line) => { if (!quiet && !json) console.log(line); });

  const bundle = options.bundle || bundleMod.load(bundleDir || bundleMod.DEFAULT_DIR);
  if (!bundle) {
    log(NO_BUNDLE);
    return { syncState: 'no-bundle', targets: {}, report: null, message: NO_BUNDLE };
  }

  const report = apply({ bundle, home, port, to, check: true, storageDir, adapters, registry, log });
  const anyError = Object.values(report.targets).some((t) => t.status === 'error');
  const syncState = anyError ? 'error' : report.stale ? 'stale' : 'synced';
  report.syncState = syncState;

  if (explain) log(formatDropped(report));
  if (html) {
    const file = path.join(storageDir, 'harness-status.html');
    fs.mkdirSync(storageDir, { recursive: true });
    fs.writeFileSync(file, renderHtml(report), 'utf8');
    report.htmlFile = file;
    log(`status page: ${file}`);
  }
  if (json) console.log(JSON.stringify(report, null, 2));

  return { syncState, targets: report.targets, report };
}

/** Every dropped item from a report, grouped per target, with its reason. */
function formatDropped(report) {
  const lines = [];
  let total = 0;
  for (const target of Object.values(report.targets)) {
    const items = [];
    for (const [component, result] of Object.entries(target.components || {})) {
      for (const drop of result.dropped || []) items.push(`    ${component}: ${drop.item} — ${drop.reason}`);
    }
    if (!items.length) continue;
    total += items.length;
    lines.push(`  ${target.name} (${items.length})`);
    lines.push(...items);
  }
  lines.unshift(`Dropped items: ${total} across ${Object.keys(report.targets).length} targets`);
  if (!total) lines.push('  (nothing was dropped)');
  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// HTML status page — standalone, no external assets, light and dark.
// ---------------------------------------------------------------------------
const esc = (s) => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

const STATUS_CLASS = { synced: 'ok', written: 'ok', source: 'src', stale: 'bad', skipped: 'warn', unsupported: 'muted', error: 'bad' };
const CELL = { synced: '✓', written: '●', stale: '✗', skipped: '!', unsupported: '–', error: 'E', source: '=' };

const PAGE_CSS = `
:root { color-scheme: light dark; --bg:#ffffff; --surface:#f6f8fa; --border:#d0d7de; --text:#1f2328; --muted:#656d76; --ok:#1a7f37; --bad:#cf222e; --warn:#9a6700; --accent:#0969da; }
@media (prefers-color-scheme: dark) { :root { --bg:#0d1117; --surface:#161b22; --border:#30363d; --text:#e6edf3; --muted:#8b949e; --ok:#3fb950; --bad:#f85149; --warn:#d29922; --accent:#58a6ff; } }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: var(--bg); color: var(--text); line-height: 1.5; padding: 28px 24px; }
.wrap { max-width: 1100px; margin: 0 auto; }
h1 { font-size: 22px; font-weight: 650; }
h2 { font-size: 15px; font-weight: 650; margin: 28px 0 10px; }
.lede { color: var(--muted); margin-top: 6px; font-size: 14px; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: 12px; margin-top: 20px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; }
.card .n { font-weight: 650; }
.card .d { font-size: 12px; color: var(--muted); margin-top: 4px; font-family: ui-monospace, Consolas, monospace; word-break: break-all; }
.pill { float: right; font-size: 11px; font-weight: 650; text-transform: uppercase; letter-spacing: .4px; padding: 1px 8px; border-radius: 10px; border: 1px solid currentColor; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { border-bottom: 1px solid var(--border); padding: 6px 8px; text-align: left; }
th { color: var(--muted); font-weight: 550; font-size: 11px; text-transform: uppercase; letter-spacing: .4px; }
td.c { text-align: center; font-size: 15px; }
.ok { color: var(--ok); } .bad { color: var(--bad); } .warn { color: var(--warn); } .muted { color: var(--muted); } .src { color: var(--accent); }
.legend, .foot { color: var(--muted); font-size: 12px; margin-top: 10px; }
code, pre { font-family: ui-monospace, Consolas, monospace; font-size: 12px; }
pre { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; overflow-x: auto; }
ul { margin-left: 18px; font-size: 13px; }
li { margin: 2px 0; }
`;

function renderHtml(report) {
  const targets = Object.values(report.targets || {});
  const totals = report.totals || {};
  const supported = (t) => Object.values(t.components || {}).filter((r) => r.status !== 'unsupported');
  const syncedOf = (t) => supported(t).filter((r) => r.status === 'synced').length;

  const cards = targets.map((t) => {
    const cls = STATUS_CLASS[t.status] || 'muted';
    const detail = t.status === 'source'
      ? 'source of truth — never written to'
      : `${syncedOf(t)}/${supported(t).length} components synced · ${t.dropped || 0} dropped`;
    return `<div class="card"><span class="pill ${cls}">${esc(t.status)}</span><div class="n">${esc(t.name)}</div>` +
      `<div class="d">${esc(t.home || t.adapter)}</div>` +
      `<div class="d">${t.installed ? 'installed' : 'not installed'} · ${detail}</div></div>`;
  }).join('\n');

  const rows = targets.map((t) => {
    const cells = bundleMod.COMPONENTS.map((c) => {
      if (t.status === 'source') return `<td class="c src" title="source of truth">${CELL.source}</td>`;
      const r = (t.components || {})[c] || { status: 'unsupported' };
      const title = [r.note, r.error, `${(r.files || []).length} files`].filter(Boolean).join(' — ');
      return `<td class="c ${STATUS_CLASS[r.status] || 'muted'}" title="${esc(r.status)}${title ? ': ' + esc(title) : ''}">${CELL[r.status] || '?'}</td>`;
    }).join('');
    return `<tr><td>${esc(t.name)}</td>${cells}<td>${t.dropped || 0}</td></tr>`;
  }).join('\n');

  const droppedBlocks = targets.map((t) => {
    const items = [];
    for (const [component, r] of Object.entries(t.components || {})) {
      for (const d of r.dropped || []) items.push(`<li><code>${esc(component)}</code> ${esc(d.item)} — ${esc(d.reason)}</li>`);
    }
    return items.length ? `<h2>${esc(t.name)} — ${items.length} dropped</h2><ul>${items.join('')}</ul>` : '';
  }).filter(Boolean).join('\n') || '<p class="foot">Nothing was dropped.</p>';

  const b = report.bundle || {};
  const counts = Object.entries(b.components || {}).map(([k, v]) => `${k} ${v}`).join(' · ') || 'none';

  return `<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agnostic harness — port status</title><style>${PAGE_CSS}</style></head>
<body><div class="wrap">
<h1>Harness port status</h1>
<p class="lede">Your <strong>${esc(b.source || 'unknown')}</strong> harness, copied into every other AI coding client on this machine. Each cell says whether that client's rules, hooks, skills, agents, commands, MCP servers and permissions match it.</p>
<p class="foot">${targets.length} targets · ${totals.wouldWrite || 0} files out of date · ${totals.unchanged || 0} already in sync · ${totals.dropped || 0} dropped · checked ${esc(report.appliedAt)}</p>
<div class="cards">${cards}</div>
<h2>Component matrix</h2>
<table><thead><tr><th>Client</th>${bundleMod.COMPONENTS.map((c) => `<th>${esc(c)}</th>`).join('')}<th>dropped</th></tr></thead><tbody>${rows}</tbody></table>
<p class="legend">✓ in sync · ● written · ✗ out of date · ! skipped (hand-edited, needs --force) · – client has no such surface · E error · = the source client</p>
<h2>What was not ported</h2>
${droppedBlocks}
<h2>Bundle</h2>
<p class="foot">source <code>${esc(b.source || '?')}</code> · captured ${esc(b.capturedAt || 'never')} · ${esc(counts)}</p>
<h2>Regenerate</h2>
<pre>npm run capture   # re-read the source client
npm run port      # capture, then write every target
npm run port:check # report only, write nothing
npm run explain   # every dropped item and why</pre>
</div></body></html>
`;
}

module.exports = { status, renderHtml, formatDropped, NO_BUNDLE };
