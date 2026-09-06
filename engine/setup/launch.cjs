#!/usr/bin/env node
/**
 * engine/setup/launch.cjs — single-command entrypoint for the Agnostic harness.
 *
 * Checks the install, reports whether every client still carries the harness,
 * then opens the command center. Replaces the deleted launch.py; the Python
 * coding agent now lives at https://github.com/ucsandman/agnostic-agent.
 *
 * Usage: npm run launch
 */

const path = require('path');
const { spawn, spawnSync } = require('child_process');

const ROOT = path.resolve(__dirname, '..', '..');

function step(title, args, { advisory = false } = {}) {
  console.log(title);
  const result = spawnSync(process.execPath, args, { cwd: ROOT, stdio: 'inherit' });
  if (result.status !== 0 && advisory) {
    console.log(`\n[WARNING] ${args[0]} exited ${result.status}. Review the output above; continuing anyway.`);
  }
  return result.status;
}

function main() {
  console.log('==================================================');
  console.log('           AGNOSTIC AI AGENT HARNESS              ');
  console.log('==================================================');
  console.log(`Root: ${ROOT}\n`);

  // 0. First-run onboarding: harvest, skills, port, guards, DashClaw.
  step('[0/4] Checking harness installation & skill consolidation...', ['engine/setup/first-run.cjs']);

  // 1. Is every client still carrying the harness? Report only, writes nothing.
  //    A non-zero exit here means "something is out of date", not "broken".
  const stale = step('\n[1/4] Checking every client against your source harness...', ['engine/harness/cli.cjs', 'port', '--check']);
  if (stale !== 0) console.log('\n[NOTICE] Some clients are out of date. Run `npm run port` to write them.');

  // 2. Governed autonomy wiring.
  step('\n[2/4] Inspecting DashClaw integration & self-configuration...', ['engine/hooks/dashclaw-setup.cjs']);

  // 3. Self-tests are advisory: a failing check must not block the dashboard.
  step('\n[3/4] Running engine test suite...', ['engine/tests/run-all.cjs'], { advisory: true });

  // 4. Command center. The server prints its own URL: it may not be 7842 if
  //    another app holds the port.
  console.log('\n[4/4] Launching Agnostic AI Universal Command Center...');
  const server = spawn(process.execPath, ['tools/dashboard/dashboard.cjs', '--open'], { cwd: ROOT, stdio: 'inherit' });
  console.log('Press Ctrl+C to stop.');

  let stopping = false;
  const stop = () => {
    if (stopping) return;
    stopping = true;
    console.log('\nStopping server...');
    server.kill('SIGTERM');
  };
  process.on('SIGINT', stop);
  process.on('SIGTERM', stop);
  server.on('exit', (code) => { process.exitCode = code === null ? 0 : code; });
}

if (require.main === module) main();

module.exports = { main };
