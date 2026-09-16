// lib.test.mjs — the pure policy of harness-mods, under node --test. Every deny/redact/serve case
// has its allow twin (a green run proves the rule, not that it blocks everything), and the L1
// negative controls make each check fail on purpose once.
//   node --test C:/Users/sandm/.claude/mods/harness-mods/tests/
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { modeFor, allModes, parseConfig, classicStandsDown, DEFAULT_CONFIG } from "../hooks/lib/modes.mjs";
import { explain, withContext, explainRoute } from "../hooks/lib/explain.mjs";
import { commandTarget, targetFor, observation, mutations } from "../hooks/lib/targets.mjs";
import { redactText, redactToolResult, PATTERNS } from "../hooks/lib/redact.mjs";
import { decideGraph, decideBudget, decide, parseEst, signatureOf, EXIT_TOOLS } from "../hooks/lib/routing.mjs";
import * as budget from "../hooks/lib/budget.mjs";
import { row, pair, report } from "../hooks/lib/shadow.mjs";
import { newNudgeState, onUsage, summary } from "../hooks/lib/usage.mjs";
import { newStatus, judge } from "../hooks/lib/canary.mjs";

const require = createRequire(import.meta.url);

// ---------------------------------------------------------------- modes
test("modes: config, env override, broken file → classic, stand-down needs mode+heartbeat+arm+fresh", () => {
  const cfg = parseConfig(JSON.stringify({ version: 1, guards: { routing: "mod", contextNudge: "classic" } }));
  assert.equal(modeFor("routing", cfg, {}), "mod");
  assert.equal(modeFor("contextNudge", cfg, {}), "classic");
  assert.equal(modeFor("secretRedaction", cfg, {}), DEFAULT_CONFIG.guards.secretRedaction, "unset guard takes the default");
  assert.equal(modeFor("routing", cfg, { HARNESS_MOD_ROUTING: "classic" }), "classic", "env override wins");
  assert.equal(modeFor("routing", cfg, { HARNESS_MODS: "off" }), "classic", "HARNESS_MODS=off forces classic");
  assert.equal(modeFor("routing", cfg, { HARNESS_MOD_ROUTING: "bogus" }), "classic", "an unknown mode value is classic, never open");
  const broken = parseConfig("{not json");
  assert.equal(broken.broken, true);
  assert.equal(modeFor("routing", broken, {}), DEFAULT_CONFIG.guards.routing);
  assert.deepEqual(Object.keys(allModes(cfg, {})).sort(), ["contextNudge", "readCache", "routing", "secretRedaction", "subagentAccounting"]);
  const now = Date.now();
  const hb = { ts: now - 1000, armed: { routing: true } };
  assert.equal(classicStandsDown("routing", cfg, {}, hb, now).standDown, true);
  assert.equal(classicStandsDown("routing", cfg, {}, null, now).standDown, false, "L1: no heartbeat → classic enforces");
  assert.equal(classicStandsDown("routing", cfg, {}, { ts: now, armed: { routing: false } }, now).standDown, false, "not armed → classic enforces");
  assert.equal(classicStandsDown("routing", cfg, {}, { ts: now - 7 * 3600 * 1000, armed: { routing: true } }, now).standDown, false, "stale → classic enforces");
  assert.equal(classicStandsDown("contextNudge", cfg, {}, hb, now).standDown, false, "mode classic → classic enforces");
  assert.equal(classicStandsDown("routing", cfg, { HARNESS_MODS: "off" }, hb, now).standDown, false, "off switch → classic enforces");
});

// ---------------------------------------------------------------- explain
test("explain: one line, kind + what + why + actual, clipped; withContext appends", () => {
  const s = explain({ kind: "model-rewrite", what: "haiku-scout model opus -> haiku", why: ["upward-edge-not-in-graph", "downgraded-to-highest-child-rung"], actual: "the subagent ran on haiku" });
  assert.match(s, /^\[harness-mods\] subagent model rewritten: haiku-scout model opus -> haiku · why: upward-edge-not-in-graph, downgraded/);
  assert.match(s, /actual: the subagent ran on haiku$/);
  assert.ok(!s.includes("\n"));
  assert.ok(explain({ kind: "redaction", what: "x".repeat(900) }).length <= 320);
  assert.deepEqual(withContext({ result: 1, context: ["a"] }, "b").context, ["a", "b"]);
  assert.deepEqual(withContext({ result: 1 }, "b").context, ["b"]);
  assert.equal(withContext({ result: 1 }, null).context, undefined);
  assert.equal(explainRoute({ action: "pass" }), null, "a pass needs no explanation");
  assert.match(explainRoute({ action: "rewrite", type: "advisor", requested: "haiku", model: "opus", reasons: ["advisor-upward-edge"], resolvedModel: "claude-opus-5" }), /advisor model haiku -> opus[\s\S]*claude-opus-5/);
});

// ---------------------------------------------------------------- targets
test("targets: costclaw grain unchanged; observation resolves the FILE across Read/Grep/Bash cat|wc; unsafe shells are not observations", () => {
  assert.equal(commandTarget("cd C:/x && npm test"), "npm test");
  assert.equal(commandTarget('FOO=1 cd "C:/a b" ; git status'), "git status");
  assert.equal(targetFor("Read", { file_path: "a.md" }), "a.md");
  assert.equal(targetFor("Bash", { command: "cat a.md" }), "cat a.md");
  const r = observation("Read", { file_path: "C:\\p\\a.md" });
  assert.deepEqual(r, { path: "C:/p/a.md", via: "Read", exact: true });
  assert.equal(observation("Read", { file_path: "a.md", offset: 10 }).exact, false);
  assert.deepEqual(observation("Bash", { command: "cat C:/p/a.md" }), { path: "C:/p/a.md", via: "Bash cat", exact: true });
  assert.deepEqual(observation("Bash", { command: "wc -l C:/p/a.md" }), { path: "C:/p/a.md", via: "Bash wc", exact: false });
  assert.deepEqual(observation("Bash", { command: "head -n 20 'C:/p/a.md'" }), { path: "C:/p/a.md", via: "Bash head", exact: false });
  assert.deepEqual(observation("Bash", { command: "cd C:/p && cat a.md" }), { path: "a.md", via: "Bash cat", exact: true });
  assert.equal(observation("Grep", { pattern: "x", path: "C:/p/a.md" }).via, "Grep");
  assert.equal(observation("Bash", { command: "cat a.md | grep x" }), null, "a pipe is not a plain observation");
  assert.equal(observation("Bash", { command: "cat a.md > b.md" }), null, "a redirect is not an observation");
  assert.equal(observation("Bash", { command: "cat a.md; rm b" }), null);
  assert.equal(observation("Bash", { command: "cat $(ls)" }), null);
  assert.equal(observation("Bash", { command: "rm -rf a.md" }), null, "L1: rm is never an observation");
  assert.deepEqual(mutations("Edit", { file_path: "C:\\p\\a.md" }), ["C:/p/a.md"]);
  assert.deepEqual(mutations("Bash", { command: "sed -i s/a/b/ a.md" }), ["*"]);
  assert.deepEqual(mutations("Bash", { command: "echo hi > out.txt" }), ["*"]);
  assert.deepEqual(mutations("Bash", { command: "git status" }), []);
  assert.deepEqual(mutations("Bash", { command: "cat a.md" }), []);
});

// ---------------------------------------------------------------- redact
test("redact: fixtures only; values never survive; placeholders untouched; drift against the harness patterns", () => {
  // assembled at runtime so no key-shaped literal sits in this file
  const fakeAnthropic = "sk-ant-" + "api03-" + "Q".repeat(40);
  const fakeStripe = "sk_live_" + "b7Xk9".repeat(6);
  const fakeGh = "ghp_" + "Ab1".repeat(14);
  const text = "KEY=" + fakeAnthropic + "\nSTRIPE=" + fakeStripe + "\nok=YOUR_KEY_HERE\ngh=" + fakeGh;
  const r = redactText(text);
  assert.equal(r.hits.length, 3);
  assert.ok(!r.text.includes(fakeAnthropic) && !r.text.includes(fakeStripe) && !r.text.includes(fakeGh), "no value survives");
  assert.ok(r.text.includes("<REDACTED:anthropic:") && r.text.includes("<REDACTED:stripe-live:") && r.text.includes("<REDACTED:github-pat:"));
  assert.ok(r.text.includes("ok=YOUR_KEY_HERE"), "placeholders are not secrets");
  for (const h of r.hits) { assert.ok(!JSON.stringify(h).includes(fakeAnthropic.slice(10, 30)), "a hit never carries the value"); }
  assert.deepEqual(redactText("plain text with sk-ant-short").hits, [], "allow twin: short shapes are not keys");
  assert.equal(redactToolResult({ result: { stdout: "hello", stderr: "" }, text: "hello" }), null, "clean result → null (return the original)");
  const bash = redactToolResult({ result: { stdout: "TOKEN=" + fakeAnthropic, stderr: "" }, text: "TOKEN=" + fakeAnthropic });
  assert.ok(bash && !bash.result.stdout.includes(fakeAnthropic) && bash.kinds.includes("anthropic"));
  const read = redactToolResult({ result: { file: { filePath: "x", content: "a\n" + fakeStripe + "\nb", numLines: 3 } } });
  assert.ok(read && !JSON.stringify(read.result).includes(fakeStripe), "nested Read-style records are redacted");
  assert.equal(redactToolResult({ deny: "no" }), null, "a deny is never touched");
  // drift: the Mod's generated copy must equal the harness source
  const src = require("C:/Users/sandm/.claude/hooks/lib/secret-patterns.cjs");
  assert.deepEqual(PATTERNS.map(([k, re]) => [k, re.source, re.flags]), src.PATTERNS.map(([k, re]) => [k, re.source, re.flags]), "secret-patterns.mjs drifted from hooks/lib/secret-patterns.cjs; run tests/gen-patterns.cjs");
});

// ---------------------------------------------------------------- routing
test("routing graph: downward passes, upward/peer rewrites, advisor one rung up, fable cap, haiku leaf denies, fork, pinned", () => {
  const p = (subagentType, model, parentModel, extra) => ({ subagentType, model, parentModel, prompt: "", ...extra });
  assert.equal(decideGraph(p("haiku-scout", "haiku", "claude-fable-5-1[1m]"), {}).action, "pass");
  let d = decideGraph(p("haiku-scout", "opus", "claude-sonnet-5"), {});
  assert.equal(d.action, "rewrite"); assert.equal(d.model, "haiku"); assert.ok(d.reasons.includes("upward-edge-not-in-graph"));
  d = decideGraph(p("sonnet-implementer", "sonnet", "claude-sonnet-5"), {});
  assert.equal(d.action, "rewrite"); assert.equal(d.model, "haiku"); assert.ok(d.reasons.includes("peer-edge-not-in-graph"));
  d = decideGraph(p("general-purpose", undefined, "claude-opus-5"), {});
  assert.equal(d.action, "rewrite"); assert.equal(d.model, "sonnet"); assert.ok(d.reasons.includes("model-undeclared"));
  d = decideGraph(p("advisor", "haiku", "claude-sonnet-5"), {});
  assert.equal(d.action, "rewrite"); assert.equal(d.model, "opus"); assert.ok(d.reasons.includes("advisor-upward-edge"));
  d = decideGraph(p("advisor", "fable", "claude-fable-5-1"), {});
  assert.equal(d.action, "pass"); assert.equal(d.model, "fable");
  d = decideGraph(p("opus-owner", "fable", "claude-fable-5-1"), { fableUsed: 3, fableCap: 3 });
  assert.equal(d.action, "rewrite"); assert.equal(d.model, "opus"); assert.ok(d.reasons.includes("fable-cap-3-per-session"));
  d = decideGraph(p("opus-owner", "fable", "claude-fable-5-1"), { fableUsed: 2, fableCap: 3 });
  assert.equal(d.action, "rewrite", "fable→fable is a peer edge even under the cap"); assert.equal(d.model, "opus");
  d = decideGraph(p("haiku-scout", "haiku", "claude-haiku-4-5"), {});
  assert.equal(d.action, "deny"); assert.ok(d.reasons.includes("haiku-is-a-leaf"));
  d = decideGraph(p("fork", undefined, "claude-fable-5-1", { fork: true }), {});
  assert.equal(d.action, "pass"); assert.equal(d.fableCounted, true);
  d = decideGraph(p("codex:codex-rescue", undefined, "claude-fable-5-1"), {});
  assert.equal(d.action, "pass"); assert.ok(d.reasons.includes("pinned-safe-subagent"));
  assert.ok(EXIT_TOOLS.includes("SubagentHandback"));
});

test("routing budget: EST parse, break-even with the learned prior, SPAWN_OK, exempt types, anti-thrash second attempt", () => {
  assert.deepEqual(parseEst("do x # EST: 12 calls, 4 files"), { calls: 12, files: 4, raw: "12 calls, 4 files" });
  assert.deepEqual(parseEst("#EST 3 files"), { calls: 0, files: 3, raw: "3 files" });
  assert.equal(parseEst("# EST: soon"), null);
  const ctx = { prior: 17000, priorSource: "prior lean", isWarm: false, deniedOnce: false };
  let b = decideBudget({ subagentType: "haiku-scout", prompt: "x # EST: 20 calls, 3 files" }, ctx);
  assert.equal(b.action, "pass"); assert.ok(b.reasons.includes("declared-scope-clears-break-even"));
  b = decideBudget({ subagentType: "haiku-scout", prompt: "x # EST: 1 calls, 0 files" }, ctx);
  assert.equal(b.action, "deny"); assert.ok(b.reasons.includes("below-break-even")); assert.match(b.reason, /prior lean/);
  b = decideBudget({ subagentType: "haiku-scout", prompt: "x # EST: 1 calls, 0 files" }, { ...ctx, deniedOnce: true });
  assert.equal(b.action, "pass", "anti-thrash: the identical dispatch is denied at most once");
  b = decideBudget({ subagentType: "haiku-scout", prompt: "no tag" }, ctx);
  assert.equal(b.action, "deny"); assert.ok(b.reasons.includes("no-est-tag"));
  b = decideBudget({ subagentType: "haiku-scout", prompt: "no tag # SPAWN_OK: isolation" }, ctx);
  assert.equal(b.action, "pass"); assert.equal(b.why, "isolation");
  b = decideBudget({ subagentType: "advisor", prompt: "no tag" }, ctx);
  assert.equal(b.action, "pass"); assert.ok(b.reasons.includes("budget-exempt-type"));
  const warm = decideBudget({ subagentType: "haiku-scout", prompt: "x # EST: 4 calls, 0 files" }, { ...ctx, isWarm: true });
  assert.equal(warm.action, "pass", "warm prefix lowers the overhead below 4 calls' inline cost");
  const whole = decide({ subagentType: "haiku-scout", model: "opus", parentModel: "claude-sonnet-5", prompt: "x # EST: 30 calls, 2 files" }, { ...ctx, fableUsed: 0 });
  assert.equal(whole.action, "rewrite"); assert.equal(whole.model, "haiku");
  assert.equal(signatureOf("s", "t", "p", "m"), signatureOf("s", "t", "p", "m")); assert.notEqual(signatureOf("s", "t", "p", "m"), signatureOf("s", "t", "q", "m")); assert.notEqual(signatureOf("s", "t", "p", "opus"), signatureOf("s", "t", "p", "haiku"));
});

// ---------------------------------------------------------------- budget ledger
test("budget ledger: reserve from prior, measure per step, settle refits the median, prediction error, calibration row", () => {
  const L = budget.newLedger();
  assert.deepEqual(budget.priorFor(L, "haiku-scout"), { tokens: 17000, source: "prior lean" });
  assert.deepEqual(budget.priorFor(L, "general-purpose"), { tokens: 60000, source: "prior full" });
  const t = 1000;
  budget.open(L, { agentId: "a1", type: "haiku-scout", model: "haiku", declared: 21000, reserved: 17000, reservedFrom: "prior lean" }, t);
  budget.step(L, "a1", { input_tokens: 100, output_tokens: 200, cache_read_input_tokens: 10000, cache_creation_input_tokens: 5000 }, t + 1);
  assert.equal(L.agents.a1.tokens, 100 + 200 + 5000 + 1000);
  assert.equal(budget.isWarm(L, t + 60000), true); assert.equal(budget.isWarm(L, t + 10 * 60000), false);
  const a = budget.settle(L, "a1", { usage: { input_tokens: 28, output_tokens: 591, cache_read_input_tokens: 41561, cache_creation_input_tokens: 12297 }, durationMs: 9333, reason: "answer" }, t + 2);
  assert.equal(a.measured, 28 + 591 + 12297 + 4156);
  assert.equal(a.predictionError, a.measured - 21000);
  assert.deepEqual(budget.priorFor(L, "haiku-scout"), { tokens: a.measured, source: "learned n=1" });
  const crow = budget.calibrationRow("s", a, "now");
  assert.equal(crow.decision, "measured"); assert.equal(crow.session, "s"); assert.equal(crow.measured, a.measured);
  assert.equal(budget.settle(L, "nope", {}, t), null);
  assert.equal(budget.medianOf([3, 1, 2]), 2); assert.equal(budget.medianOf([1, 2, 3, 4]), 3); assert.equal(budget.medianOf([]), 0);
});

// ---------------------------------------------------------------- shadow
test("shadow: rows pair by key; deny vs rewrite count as agreement on the violation; report per subsystem", () => {
  const rows = [
    row({ session: "s", side: "classic", subsystem: "routing", key: "k1", decision: "deny", enforced: true }),
    row({ session: "s", side: "mod", subsystem: "routing", key: "k1", decision: "rewrite", wouldRewrite: true }),
    row({ session: "s", side: "classic", subsystem: "routing", key: "k2", decision: "allow", enforced: true }),
    row({ session: "s", side: "mod", subsystem: "routing", key: "k2", decision: "deny" }),
    row({ session: "s", side: "mod", subsystem: "secretRedaction", key: "t1", decision: "redact" }),
  ];
  const p = pair(rows);
  assert.equal(p.find((x) => x.key.endsWith("|k1")).agreement, "agree");
  assert.equal(p.find((x) => x.key.endsWith("|k2")).agreement, "disagree");
  assert.equal(p.find((x) => x.key.endsWith("|t1")).agreement, "mod-only");
  const rep = report(rows);
  assert.equal(rep.bySubsystem.routing.agree, 1); assert.equal(rep.bySubsystem.routing.disagree, 1); assert.equal(rep.bySubsystem.routing.modRewrites, 1);
  assert.equal(rep.bySubsystem.secretRedaction.modOnly, 1);
});

// ---------------------------------------------------------------- usage
test("usage: nudge fires once per crossing of 80%, re-arms below, /clear wording at 92%", () => {
  const s = newNudgeState();
  const u = (pct) => ({ context: { percent: pct, tokens: pct * 10000, window: 1000000 }, rateLimits: [{ kind: "five_hour", percentUsed: 77.4 }], cost: { usd: 0.209 } });
  assert.equal(onUsage(s, u(50)), null);
  assert.match(onUsage(s, u(81)), /~81% .* \/compact/);
  assert.equal(onUsage(s, u(85)), null, "no second nudge while armed");
  assert.equal(onUsage(s, u(40)), null); assert.equal(s.armed, false, "re-armed below the threshold");
  assert.match(onUsage(s, u(93)), /use \/clear/);
  assert.equal(s.fired, 2);
  assert.equal(onUsage(s, { context: {} }), null, "no percent → no nudge, no crash");
  assert.equal(summary(u(6)), "ctx 6% · 5h 77% · 7d ? · $0.21");
});

// ---------------------------------------------------------------- canary
test("canary: a healthy status is ok; each failure class is named; mod mode on an unhealthy layer is flagged", () => {
  const good = () => ({ ...newStatus(), runtimeNoun: true, usageProbe: true, storeProbe: true, busEvents: 12, toolCalls: 3, order: ["harness-mods"], enforcementReached: { toolCall: true, agentSpawn: false },
    supports: { toolInterception: true, toolResultMutation: true, runtimeEvents: true, subagentEvents: true, dynamicPermissions: true, usageSignals: true, contextSignals: true, middleware: true, runtimeMemory: true } });
  assert.equal(judge(good(), { routing: "mod" }).ok, true);
  assert.match(judge({ ...good(), runtimeNoun: false }, {}).failures.join(), /adapter-noun-missing/);
  assert.match(judge({ ...good(), supports: { ...good().supports, toolResultMutation: false } }, {}).failures.join(), /capability-changed: toolResultMutation/);
  assert.match(judge({ ...good(), busEvents: 0 }, {}).failures.join(), /events-not-flowing/);
  assert.match(judge({ ...good(), order: ["other-plugin"] }, {}).failures.join(), /middleware-order/);
  assert.match(judge({ ...good(), enforcementReached: { toolCall: false } }, {}).failures.join(), /enforcement-unreachable/);
  assert.match(judge({ ...good(), hookErrors: 2, lastError: "tool.call" }, {}).failures.join(), /hook-failures: 2/);
  const v = judge({ ...good(), usageProbe: false }, { contextNudge: "mod" });
  assert.equal(v.ok, false); assert.match(v.failures.join(), /mod-mode-with-failures: contextNudge/);
  assert.equal(judge({ ...good(), toolCalls: 0, busEvents: 0 }, {}, "start").ok, true, "at session start no events is not a failure");
});
