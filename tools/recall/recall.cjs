#!/usr/bin/env node
/**
 * tools/recall/recall.cjs — Memory & Fact Retrieval Tool.
 *
 * Scans memory directories, global rules, and decisions for matching facts.
 *
 * Usage:
 *   node tools/recall/recall.cjs <query>
 *   node tools/recall/recall.cjs --open
 */

const fs = require('fs');
const path = require('path');
const http = require('http');
const { exec } = require('child_process');

const ROOT = path.resolve(__dirname, '..', '..');
const MEMORY_DIR = path.join(ROOT, 'storage', 'memory');
const RULES_FILE = path.join(ROOT, 'core', 'rules', 'global-rules.md');
const HTML_FILE = path.join(__dirname, 'recall.html');

const QUERY = process.argv.slice(2).filter(a => !a.startsWith('--')).join(' ');
const OPEN_FLAG = process.argv.includes('--open');
const PORT = process.env.RECALL_PORT || 7844;

function searchMemory(query = '') {
  const results = [];
  const q = query.toLowerCase();

  // Search Core Rules
  if (fs.existsSync(RULES_FILE)) {
    const rulesContent = fs.readFileSync(RULES_FILE, 'utf8');
    const sections = rulesContent.split(/^##\s+/m).slice(1);
    for (const sec of sections) {
      const lines = sec.trim().split('\n');
      const title = lines[0];
      const body = lines.slice(1).join('\n');
      if (!q || title.toLowerCase().includes(q) || body.toLowerCase().includes(q)) {
        results.push({
          source: 'Core Rules',
          title,
          content: body.trim(),
          type: 'rule'
        });
      }
    }
  }

  // Search Storage Memory
  if (fs.existsSync(MEMORY_DIR)) {
    function walk(dir) {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) {
          walk(full);
        } else if (entry.name.endsWith('.md') || entry.name.endsWith('.json')) {
          const content = fs.readFileSync(full, 'utf8');
          if (!q || content.toLowerCase().includes(q)) {
            results.push({
              source: path.relative(ROOT, full),
              title: entry.name,
              content: content.trim(),
              type: 'fact'
            });
          }
        }
      }
    }
    walk(MEMORY_DIR);
  }

  return results;
}

function serve() {
  const server = http.createServer((req, res) => {
    const parsedUrl = new URL(req.url, `http://localhost:${PORT}`);
    if (parsedUrl.pathname === '/api/search') {
      const q = parsedUrl.searchParams.get('q') || '';
      res.writeHead(200, { 'Content-Type': 'application/json' });
      return res.end(JSON.stringify({ query: q, results: searchMemory(q) }));
    }

    if (parsedUrl.pathname === '/' || parsedUrl.pathname === '/index.html') {
      if (fs.existsSync(HTML_FILE)) {
        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(fs.readFileSync(HTML_FILE, 'utf8'));
      }
    }

    res.writeHead(404);
    res.end('Not Found');
  });

  server.listen(PORT, '127.0.0.1', () => {
    const url = `http://127.0.0.1:${PORT}`;
    console.log(`[Recall] Memory explorer live at ${url}`);
    if (OPEN_FLAG) {
      const openCmd = process.platform === 'win32' ? `start ${url}` : `open ${url}`;
      exec(openCmd);
    }
  });
}

if (OPEN_FLAG || process.argv.includes('--serve')) {
  serve();
} else {
  const res = searchMemory(QUERY);
  console.log(`[Recall] Found ${res.length} result(s) for "${QUERY}":\n`);
  for (const item of res) {
    console.log(`[${item.source}] ${item.title}`);
    console.log(item.content.slice(0, 150) + (item.content.length > 150 ? '...' : ''));
    console.log('---');
  }
}

module.exports = { searchMemory };
