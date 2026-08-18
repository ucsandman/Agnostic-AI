#!/usr/bin/env node
// Fills a repo's .env from the machine's credential stores WITHOUT ever printing a
// secret value. Match by key name, copy, then prove each value against a live API.
//
//   node fill-env.cjs [--dir <repo>] [--dry-run] [--force] [--source <path>]
//
// --force   also replace values that are already real (default: only placeholders)
// --dry-run report what would change, write nothing

const fs = require('fs');
const path = require('path');

const argv = process.argv.slice(2);
const flag = (n) => argv.includes(n);
const opt = (n, d) => { const i = argv.indexOf(n); return i < 0 ? d : argv[i + 1]; };

const ROOT = path.resolve(opt('--dir', process.cwd()));
const TARGET = path.join(ROOT, '.env');
const EXAMPLE = path.join(ROOT, '.env.example');
const DRY = flag('--dry-run');
const FORCE = flag('--force');

const HOME = process.env.USERPROFILE || process.env.HOME;
// First store holding a key wins, so an explicit --source overrides the defaults.
const SOURCES = [
  ...argv.reduce((a, v, i) => (v === '--source' ? [...a, ['extra', argv[i + 1]]] : a), []),
  ['secrets', path.join(HOME, '.claude', '.secrets.env')],
  ['offlocal', 'C:/Projects/offlocalai-mcp/.env'],
];

// A destination key can be spelled differently in a credential store.
const ALIASES = {
  NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY: ['CLERK_PUBLISHABLE_KEY'],
  DATABASE_URL: ['POSTGRES_URL', 'NEON_DATABASE_URL'],
  STRIPE_SECRET_KEY: ['STRIPE_TEST_SECRET_KEY', 'STRIPE_LIVE_SECRET_KEY'],
  STRIPE_PUBLISHABLE_KEY: ['STRIPE_TEST_PUBLISHABLE_KEY'],
  NEXT_PUBLIC_POSTHOG_KEY: ['POSTHOG_PERSONAL_API_KEY'],
  REDIS_URL: ['UPSTASH_REDIS_URL'],
};

// Live probe per key: [url, headersFn]. Anything absent falls back to a format check.
const PROBES = {
  ANTHROPIC_API_KEY: ['https://api.anthropic.com/v1/models?limit=1',
    (v) => ({ 'x-api-key': v, 'anthropic-version': '2023-06-01' })],
  OPENAI_API_KEY: ['https://api.openai.com/v1/models', (v) => ({ authorization: 'Bearer ' + v })],
  RESEND_API_KEY: ['https://api.resend.com/domains', (v) => ({ authorization: 'Bearer ' + v })],
  CLERK_SECRET_KEY: ['https://api.clerk.com/v1/users?limit=1', (v) => ({ authorization: 'Bearer ' + v })],
  STRIPE_SECRET_KEY: ['https://api.stripe.com/v1/customers?limit=1', (v) => ({ authorization: 'Bearer ' + v })],
  GITHUB_TOKEN: ['https://api.github.com/user', (v) => ({ authorization: 'Bearer ' + v, 'user-agent': 'fill-env' })],
  NEON_API_KEY: ['https://console.neon.tech/api/v2/projects', (v) => ({ authorization: 'Bearer ' + v })],
  VERCEL_TOKEN: ['https://api.vercel.com/v2/user', (v) => ({ authorization: 'Bearer ' + v })],
  SENTRY_AUTH_TOKEN: ['https://sentry.io/api/0/organizations/', (v) => ({ authorization: 'Bearer ' + v })],
};

// A Clerk publishable key is base64 of "<frontend-api-host>$": decode it and prove the
// host is a live Clerk instance. Returns a status string.
const probeClerkPublishable = async (v) => {
  const host = Buffer.from(v.replace(/^pk_(test|live)_/, ''), 'base64').toString('utf8').replace(/\$$/, '');
  if (!/^[a-z0-9.\-]+$/i.test(host)) return 'REJECTED not a decodable Clerk key';
  const r = await fetch(`https://${host}/.well-known/jwks.json`);
  return r.ok ? `valid (${host})` : `REJECTED host ${host} (HTTP ${r.status})`;
};

const FORMATS = {
  GOOGLE_CLIENT_ID: [/\.apps\.googleusercontent\.com$/, 'must end .apps.googleusercontent.com'],
  GOOGLE_CLIENT_SECRET: [/^GOCSPX-/, 'must start GOCSPX-'],
  TWILIO_ACCOUNT_SID: [/^AC[0-9a-f]{32}$/i, 'must be AC + 32 hex'],
  TWILIO_AUTH_TOKEN: [/^[0-9a-f]{32}$/i, 'must be 32 hex'],
  DATABASE_URL: [/^postgres(ql)?:\/\//, 'must be a postgres:// URI'],
};

const PLACEHOLDER = /placeholder|changeme|change[-_]me|your[-_]|^xxx|dummy|^<.*>$|example\.com/i;

const parse = (p) => {
  const out = {};
  if (!fs.existsSync(p)) return out;
  for (const line of fs.readFileSync(p, 'utf8').split(/\r?\n/)) {
    const m = line.match(/^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/);
    if (m) out[m[1]] = m[2].trim().replace(/^["']|["']$/g, '');
  }
  return out;
};

// Enough to identify which credential landed, never enough to use it.
const shape = (v) => {
  const pre = v.match(/^([A-Za-z]{2,8}[-_](?:test|live|prod)?[-_]?)/);
  return (pre ? pre[1] : v.slice(0, 3)) + '\u2026(' + v.length + ')';
};
const isPublic = (k) => k.startsWith('NEXT_PUBLIC_') || k.endsWith('_PUBLISHABLE_KEY');

const setLine = (k, v) => k + '=' + v;

(async () => {
  if (!fs.existsSync(EXAMPLE)) { console.error('no .env.example in ' + ROOT); process.exit(1); }
  const example = parse(EXAMPLE);
  if (!fs.existsSync(TARGET)) {
    fs.writeFileSync(TARGET, Object.entries(example).map(([k, v]) => setLine(k, v)).join('\n') + '\n');
    console.log('created .env from .env.example');
  }
  const current = parse(TARGET);

  const stores = SOURCES.map(([label, p]) => [label, p, parse(p)])
    .filter(([label, p, kv]) => {
      if (!Object.keys(kv).length) { console.log(`source ${label}: missing or empty (${p})`); return false; }
      return true;
    });
  console.log('sources: ' + stores.map(([l, , kv]) => `${l} (${Object.keys(kv).length} keys)`).join(', '));

  const needs = Object.keys(example).filter((k) =>
    FORCE || !current[k] || current[k] === example[k] || PLACEHOLDER.test(current[k]));

  const resolved = {};
  for (const k of needs) {
    for (const name of [k, ...(ALIASES[k] || [])]) {
      const hit = stores.find(([, , kv]) => kv[name] && kv[name].length);
      if (hit) { resolved[k] = { value: hit[2][name], from: hit[0], as: name }; break; }
    }
  }

  // Clerk's publishable key is a public encoding of the instance's frontend host.
  if (needs.includes('NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY') && !resolved.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY) {
    const sk = resolved.CLERK_SECRET_KEY?.value || current.CLERK_SECRET_KEY;
    if (sk && !PLACEHOLDER.test(sk)) {
      try {
        const r = await fetch('https://api.clerk.com/v1/domains', { headers: { authorization: 'Bearer ' + sk } });
        if (r.ok) {
          const body = await r.json();
          const list = Array.isArray(body) ? body : body.data || [];
          const primary = list.find((d) => d.is_satellite === false) || list[0];
          const host = ((primary && primary.frontend_api_url) || '').replace(/^https?:\/\//, '');
          if (host) {
            const kind = sk.startsWith(['sk', 'live', ''].join('_')) ? 'live' : 'test';
            resolved.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY = {
              value: ['pk', kind, ''].join('_') + Buffer.from(host + '$').toString('base64'),
              from: 'derived', as: 'clerk /v1/domains',
            };
          }
        }
      } catch { /* leave it unresolved */ }
    }
  }

  // Verify before writing, so a placeholder in a credential store never lands in .env.
  const rows = [];
  for (const [k, r] of Object.entries(resolved)) {
    let status = 'unchecked';
    if (PLACEHOLDER.test(r.value)) status = 'REJECTED placeholder';
    else if (FORMATS[k] && !FORMATS[k][0].test(r.value)) status = 'REJECTED ' + FORMATS[k][1];
    else if (k === 'TWILIO_AUTH_TOKEN') {
      // Twilio needs the SID and the token together to authenticate at all.
      const sid = resolved.TWILIO_ACCOUNT_SID?.value || current.TWILIO_ACCOUNT_SID;
      if (!sid || PLACEHOLDER.test(sid)) status = 'format ok (no SID yet, cannot probe)';
      else {
        const auth = Buffer.from(sid + ':' + r.value).toString('base64');
        const res = await fetch(`https://api.twilio.com/2010-04-01/Accounts/${sid}.json`,
          { headers: { authorization: 'Basic ' + auth } });
        status = res.ok ? `valid (HTTP ${res.status})` : `REJECTED by API (HTTP ${res.status})`;
      }
    } else if (/CLERK_PUBLISHABLE_KEY$/.test(k)) {
      try { status = await probeClerkPublishable(r.value); }
      catch (e) { status = 'probe failed: ' + e.message; }
    } else if (PROBES[k]) {
      const [url, hdr] = PROBES[k];
      try {
        const res = await fetch(url, { headers: hdr(r.value) });
        status = res.ok ? `valid (HTTP ${res.status})` : `REJECTED by API (HTTP ${res.status})`;
      } catch (e) { status = 'probe failed: ' + e.message; }
    } else if (FORMATS[k]) status = 'format ok';
    rows.push({ k, ...r, status });
  }

  const good = rows.filter((r) => !r.status.startsWith('REJECTED'));
  if (!DRY && good.length) {
    fs.copyFileSync(TARGET, TARGET + '.bak');
    const byKey = Object.fromEntries(good.map((r) => [r.k, r.value]));
    const out = fs.readFileSync(TARGET, 'utf8').split(/\r?\n/).map((line) => {
      const m = line.match(/^([A-Za-z_][A-Za-z0-9_]*)=/);
      return m && byKey[m[1]] ? setLine(m[1], byKey[m[1]]) : line;
    });
    fs.writeFileSync(TARGET, out.join('\n'));
  }

  const w = Math.max(4, ...rows.map((r) => r.k.length));
  console.log('\n' + (DRY ? 'would fill' : 'filled') + ':');
  for (const r of rows) {
    const val = isPublic(r.k) ? r.value : shape(r.value);
    console.log(`  ${r.k.padEnd(w)}  ${r.from.padEnd(8)}  ${val}  ${r.status}`);
  }
  const unresolved = needs.filter((k) => !resolved[k]);
  if (unresolved.length) console.log('\nno source has: ' + unresolved.join(', '));
  if (!DRY && good.length) console.log('\nbackup at .env.bak');
  process.exit(rows.some((r) => r.status.startsWith('REJECTED')) ? 1 : 0);
})();
