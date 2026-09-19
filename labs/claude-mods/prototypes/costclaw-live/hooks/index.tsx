// ============================================================================
// COSTCLAW LIVE — "Claude is wasting tokens RIGHT NOW"
//
// A hooks module that does live what C:\Projects\costclaw does post-hoc over
// ~/.claude/projects/**.jsonl, and then acts on one finding instead of filing
// it: the Nth identical Read of an unchanged file is answered from this
// plugin's own cache and never reaches the tool or the bill.
//
// PORTED (a Mod cannot import; this is a copy, read-only origins):
//   - C:\Projects\costclaw\packages\engine\src\pricing.ts
//       PRICES_PER_MTOK rate card (snapshot 2026-09-14), canonicalModel/lookup/
//       priceFor, readCounter, normalizeUsage (incl. the cache_creation TTL
//       split + invalid-counter rejection + conflict warnings),
//       pricingMultiplier, costForNormalizedUsage,
//       uncachedInputExposureForNormalizedUsage, cacheHitRate, isPremiumModel.
//   - C:\Projects\costclaw\packages\engine\src\parser.ts:65-100
//       commandTarget() (the "cd X && ..." hop stripper, 2026-09-11) and
//       targetFor() — the (tool, target) grain the thrash rules run on.
//   - C:\Projects\claude-mods-rnd\archaeology\clones\AgentLens\src\repeated-runs.js
//       classifyRun() / detectRepeatedRuns() — the high/medium/low confidence
//       taxonomy by REQUEST SPREAD. Live this stops being a heuristic: the
//       request boundary is an event (turn.step), not a guess about requestIds.
//   - C:\Projects\costclaw\packages\engine\src\optimizer.ts thresholds
//       REDUNDANT_TARGET_MIN_FIRES=10, HEAVY_TOOL_FIRES=100, DECAY_DROP=0.25,
//       LATE_FLOOR=0.5, and severityForSavings' bands.
//
// DELIBERATELY NOT PORTED: costclaw's share gates (HEAVY_TOOL_MIN_SHARE 0.6,
// REDUNDANT_TARGET_MIN_SHARE 0.25). They exist to suppress false positives that
// AgentLens solves by grading the evidence instead of raising the bar, and a
// hook has the request boundary that made the gates necessary. See README.
//
// costclaw's rule: a Finding carries a dollar figure only where one is
// DERIVABLE from measured numbers, and 0/none otherwise. Kept. Every $ printed
// below comes from measured chars or measured tokens times the dated rate card.
// ============================================================================

const EVIDENCE_DIR = "C:/Projects/claude-mods-rnd/prototypes/costclaw-live/evidence/";

// ---------------------------------------------------------------------------
// PORTED from costclaw packages/engine/src/pricing.ts
// ---------------------------------------------------------------------------
const PRICING_SNAPSHOT_DATE = "2026-09-14";

// USD per 1,000,000 tokens. Dated rate card; update in lockstep with costclaw.
const PRICES_PER_MTOK = {
  "claude-fable-5-1": { input: 10, output: 50, cache_write: 12.5, cache_write_1h: 20, cache_read: 0.25 },
  "claude-fable-5": { input: 10, output: 50, cache_write: 12.5, cache_write_1h: 20, cache_read: 1 },
  "claude-mythos-5-1": { input: 10, output: 50, cache_write: 12.5, cache_write_1h: 20, cache_read: 0.25 },
  "claude-mythos-5": { input: 10, output: 50, cache_write: 12.5, cache_write_1h: 20, cache_read: 1 },
  "claude-opus-5": { input: 5, output: 25, cache_write: 6.25, cache_write_1h: 10, cache_read: 0.5 },
  "claude-opus-4-8": { input: 5, output: 25, cache_write: 6.25, cache_write_1h: 10, cache_read: 0.5 },
  "claude-sonnet-5": { input: 2, output: 10, cache_write: 2.5, cache_write_1h: 4, cache_read: 0.2 },
  "claude-opus-4-7": { input: 5, output: 25, cache_write: 6.25, cache_write_1h: 10, cache_read: 0.5 },
  "claude-opus-4-7[1m]": { input: 5, output: 25, cache_write: 6.25, cache_write_1h: 10, cache_read: 0.5 },
  "claude-opus-4-6": { input: 5, output: 25, cache_write: 6.25, cache_write_1h: 10, cache_read: 0.5 },
  "claude-opus-4-5": { input: 5, output: 25, cache_write: 6.25, cache_write_1h: 10, cache_read: 0.5 },
  "claude-opus-4-1": { input: 15, output: 75, cache_write: 18.75, cache_write_1h: 30, cache_read: 1.5 },
  "claude-opus-4": { input: 15, output: 75, cache_write: 18.75, cache_write_1h: 30, cache_read: 1.5 },
  "claude-sonnet-4-6": { input: 3, output: 15, cache_write: 3.75, cache_write_1h: 6, cache_read: 0.3 },
  "claude-sonnet-4-5": { input: 3, output: 15, cache_write: 3.75, cache_write_1h: 6, cache_read: 0.3 },
  "claude-sonnet-4": { input: 3, output: 15, cache_write: 3.75, cache_write_1h: 6, cache_read: 0.3 },
  "claude-haiku-4-5": { input: 1, output: 5, cache_write: 1.25, cache_write_1h: 2, cache_read: 0.1 },
  "claude-haiku-4-5-20251001": { input: 1, output: 5, cache_write: 1.25, cache_write_1h: 2, cache_read: 0.1 },
  "claude-haiku-3-5": { input: 0.8, output: 4, cache_write: 1, cache_write_1h: 1.6, cache_read: 0.08 },
};
const FALLBACK = { input: 3, output: 15, cache_write: 3.75, cache_write_1h: 6, cache_read: 0.3 };

const INVALID_USAGE_WARNING = "Invalid usage counters were ignored.";
const CACHE_SPLIT_CONFLICT_WARNING = "Conflicting cache-write totals were valued at the conservative one-hour rate.";
const CACHE_TTL_ASSUMED_WARNING = "Cache writes without TTL metadata were estimated at the standard five-minute rate.";
const CACHE_TTL_FALLBACK_WARNING = "Cache writes with unusable TTL metadata were conservatively estimated at the one-hour rate.";
const UNSUPPORTED_PRICING_WARNING = "Unsupported pricing metadata was ignored and standard current rates were used.";

function canonicalModel(model) {
  if (!model) return null;
  const noTag = model.replace(/\[[^\]]*\]$/, "");
  return noTag.replace(/-\d{8}$/, "");
}
function lookupRates(model) {
  if (!model) return null;
  return PRICES_PER_MTOK[model]
    || PRICES_PER_MTOK[model.replace(/\[[^\]]*\]$/, "")]
    || PRICES_PER_MTOK[canonicalModel(model) || ""]
    || null;
}
function priceFor(model) { return lookupRates(model) || FALLBACK; }
function isKnownModel(model) { return lookupRates(model) !== null; }
function isPremiumModel(model) {
  const base = canonicalModel(model);
  if (!base) return false;
  return base.indexOf("claude-opus") === 0 || base.indexOf("claude-fable") === 0 || base.indexOf("claude-mythos") === 0;
}

function readCounter(value, present) {
  if (!present) return { value: 0, present: false, invalid: false };
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0
    ? { value, present: true, invalid: false }
    : { value: 0, present: true, invalid: true };
}
function own(value, key) { return Object.prototype.hasOwnProperty.call(value, key); }

// normalizeUsage — ported whole. turn.step's TurnUsage is the FOUR-FIELD shape
// (input/output/cache_read/cache_creation, no ephemeral_5m/1h split), which is
// exactly the legacy branch below: it values the writes at the 5-minute rate
// and records CACHE_TTL_ASSUMED_WARNING so the estimate is never silent.
function normalizeUsage(raw) {
  const usage = raw && typeof raw === "object" ? raw : {};
  const warnings = new Set();
  const input = readCounter(usage.input_tokens, own(usage, "input_tokens"));
  const output = readCounter(usage.output_tokens, own(usage, "output_tokens"));
  const cacheRead = readCounter(usage.cache_read_input_tokens, own(usage, "cache_read_input_tokens"));
  const cacheTop = readCounter(usage.cache_creation_input_tokens, own(usage, "cache_creation_input_tokens"));

  let splitPresent = false;
  let splitMalformed = false;
  let cache5m = { value: 0, present: false, invalid: false };
  let cache1h = { value: 0, present: false, invalid: false };
  const splitProvided = own(usage, "cache_creation");
  if (splitProvided) {
    if (usage.cache_creation && typeof usage.cache_creation === "object" && !Array.isArray(usage.cache_creation)) {
      const split = usage.cache_creation;
      cache5m = readCounter(split.ephemeral_5m_input_tokens, own(split, "ephemeral_5m_input_tokens"));
      cache1h = readCounter(split.ephemeral_1h_input_tokens, own(split, "ephemeral_1h_input_tokens"));
      splitPresent = cache5m.present || cache1h.present;
    } else {
      splitMalformed = true;
    }
  }

  let invalid = input.invalid || output.invalid || cacheRead.invalid || cacheTop.invalid || cache5m.invalid || cache1h.invalid || splitMalformed;
  if (invalid) warnings.add(INVALID_USAGE_WARNING);

  const validSplitSum = cache5m.value + cache1h.value;
  let creationTotal = 0;
  let creation5m = 0;
  let creation1h = 0;
  let conflicting = false;
  if (cacheTop.present && !cacheTop.invalid) {
    creationTotal = cacheTop.value;
    if (splitPresent && !cache5m.invalid && !cache1h.invalid) {
      if (validSplitSum === cacheTop.value) {
        creation5m = cache5m.value;
        creation1h = cache1h.value;
      } else {
        conflicting = true;
        creation1h = cacheTop.value;
        warnings.add(CACHE_SPLIT_CONFLICT_WARNING);
      }
    } else if (splitProvided) {
      creation1h = cacheTop.value;
      warnings.add(CACHE_TTL_FALLBACK_WARNING);
    } else {
      creation5m = cacheTop.value;
      if (cacheTop.value > 0) warnings.add(CACHE_TTL_ASSUMED_WARNING);
    }
  } else if (splitPresent) {
    creationTotal = validSplitSum;
    creation5m = cache5m.value;
    creation1h = cache1h.value;
  }

  let speed = "standard";
  if (usage.speed === "fast") speed = "fast";
  else if (usage.speed != null && usage.speed !== "standard") warnings.add(UNSUPPORTED_PRICING_WARNING);

  let inferenceGeo = "global";
  if (usage.inference_geo === "us") inferenceGeo = "us";
  else if (usage.inference_geo != null && usage.inference_geo !== "global") warnings.add(UNSUPPORTED_PRICING_WARNING);

  let batch = false;
  if (usage.batch === true) batch = true;
  else if (usage.batch != null && usage.batch !== false) warnings.add(UNSUPPORTED_PRICING_WARNING);

  const normalized = {
    input_tokens: input.value,
    output_tokens: output.value,
    cache_creation_input_tokens: creationTotal,
    cache_read_input_tokens: cacheRead.value,
    cache_creation_5m_input_tokens: creation5m,
    cache_creation_1h_input_tokens: creation1h,
    cache_ttl_known: splitPresent || splitProvided,
    web_search_requests: 0,
    speed,
    inference_geo: inferenceGeo,
    batch,
  };
  const billable = normalized.input_tokens > 0
    || normalized.output_tokens > 0
    || normalized.cache_creation_input_tokens > 0
    || normalized.cache_read_input_tokens > 0;
  return { usage: normalized, billable, warnings: [...warnings], invalid, conflicting };
}

function pricingMultiplier(model, usage) {
  let multiplier = 1;
  const base = canonicalModel(model);
  if (usage.speed === "fast" && (base === "claude-opus-5" || base === "claude-opus-4-8")) multiplier *= 2;
  if (usage.inference_geo === "us") {
    const geoEligible = base != null && (
      base.indexOf("claude-fable-5") === 0
      || base.indexOf("claude-mythos-5") === 0
      || base === "claude-opus-5" || base === "claude-opus-4-8"
      || base === "claude-opus-4-7" || base === "claude-opus-4-6"
      || base === "claude-sonnet-5" || base === "claude-sonnet-4-6"
    );
    if (geoEligible) multiplier *= 1.1;
  }
  if (usage.batch) multiplier *= 0.5;
  return multiplier;
}

function costForNormalizedUsage(model, usage) {
  const p = priceFor(model);
  const tokenCost = (
    usage.input_tokens * p.input
    + usage.output_tokens * p.output
    + usage.cache_creation_5m_input_tokens * p.cache_write
    + usage.cache_creation_1h_input_tokens * p.cache_write_1h
    + usage.cache_read_input_tokens * p.cache_read
  ) / 1000000;
  return tokenCost * pricingMultiplier(model, usage);
}

// The genuinely recoverable half: raw input that should have been a cache read.
function uncachedInputExposureForNormalizedUsage(model, usage) {
  const p = priceFor(model);
  return usage.input_tokens * (p.input - p.cache_read) * pricingMultiplier(model, usage) / 1000000;
}

// cacheHitRate — reads over everything that entered the context this request.
function cacheHitRateOf(inputTok, creationTok, readTok) {
  const denom = inputTok + creationTok + readTok;
  if (!Number.isFinite(denom) || denom <= 0) return 0;
  return readTok / denom;
}

function roundMoneyHalfUp(value, places) {
  const n = places === undefined ? 2 : places;
  if (!Number.isFinite(value)) return 0;
  const factor = Math.pow(10, n);
  const scaled = Math.abs(value) * factor;
  const tolerance = Number.EPSILON * Math.max(1, scaled) * 2;
  return Math.sign(value) * Math.floor(scaled + 0.5 + tolerance) / factor;
}

// ---------------------------------------------------------------------------
// PORTED from costclaw packages/engine/src/parser.ts:65-100
// The (tool, target) grain feeds the same-target thrash rule, so a shell target
// must identify WHAT ran: drop a leading "cd <dir> &&" / "Set-Location <dir>;"
// hop and env assignments, then keep the command plus its first argument.
// First-word-only collided every "cd repo && ..." call on "cd" (2026-09-11).
// ---------------------------------------------------------------------------
function commandTarget(command) {
  let s = command.trim();
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

function targetFor(name, input) {
  const s = (v, n) => (typeof v === "string" && v.length ? v.slice(0, n) : null);
  if (["Read", "Edit", "Write", "NotebookEdit"].includes(name)) return s(input.file_path, 200);
  if (["Grep", "Glob"].includes(name)) return s(input.path || input.glob || input.pattern, 160);
  if (["Bash", "PowerShell"].includes(name)) {
    return typeof input.command === "string" ? commandTarget(input.command) : null;
  }
  if (name.indexOf("Task") === 0) return s(input.subject || input.description, 80);
  if (["WebFetch", "WebSearch"].includes(name)) return s(input.url || input.query, 60);
  if (name === "Agent") return s(input.subagent_type || input.description, 60);
  return null;
}

// ---------------------------------------------------------------------------
// PORTED from AgentLens src/repeated-runs.js — the confidence taxonomy.
// Inputs: tool events in session order, each {name, requestId?, target?}.
//   high   — same target across >= 3 distinct model requests (repeated work,
//            no progress). ONLY this grade may carry a dollar figure.
//   medium — >= 2 distinct requests but the target signal is weak.
//   low    — the run sits inside ONE model request: a batch, not a stuck loop.
// "callers should NOT compute savings from low-confidence runs."
// ---------------------------------------------------------------------------
const RUN_THRESHOLD = 3;

function classifyRun(run, startIndex, endIndex) {
  const name = run[0].name;
  const requestIds = new Set(run.map(x => x.requestId).filter(Boolean));
  const targets = new Set(run.map(x => x.target).filter(t => t !== null && t !== undefined && t !== ""));
  const requestSpread = requestIds.size;
  const targetSpread = targets.size;
  const allInOneRequest = requestSpread === 1 || (requestSpread === 0 && run.every(x => x.requestId === run[0].requestId));

  let confidence = "low";
  let evidence;
  if (requestSpread >= 3 && targetSpread <= 1) {
    confidence = "high";
    evidence = `${run.length} ${name} calls across ${requestSpread} model requests on the same target — strong signal of repeated work without progress.`;
  } else if (requestSpread >= 2) {
    confidence = "medium";
    evidence = targetSpread > 1
      ? `${run.length} ${name} calls across ${requestSpread} requests, touching ${targetSpread} different targets — could be batch follow-ups rather than a loop.`
      : `${run.length} ${name} calls across ${requestSpread} requests — same tool but unknown target similarity.`;
  } else {
    confidence = "low";
    evidence = allInOneRequest
      ? `${run.length} ${name} calls inside a single model request — almost certainly a batch, not a stuck loop.`
      : `${run.length} ${name} calls with no request_id evidence — cannot tell loop from batch.`;
  }
  return {
    name, count: run.length, startIndex, endIndex, confidence, evidence,
    requestSpread, targetSpread, allInOneRequest: !!allInOneRequest,
    targets: [...targets].slice(0, 8),
  };
}

function detectRepeatedRuns(events, threshold) {
  const th = threshold === undefined ? RUN_THRESHOLD : threshold;
  if (!Array.isArray(events) || events.length < th) return [];
  const signals = [];
  let runName = null;
  let runStart = -1;
  for (let i = 0; i <= events.length; i++) {
    const cur = i < events.length ? events[i] : null;
    if (cur && cur.name === runName) continue;
    if (runName !== null && (i - runStart) >= th) {
      signals.push(classifyRun(events.slice(runStart, i), runStart, i - 1));
    }
    runName = cur ? cur.name : null;
    runStart = i;
  }
  return signals;
}

// ---------------------------------------------------------------------------
// PORTED thresholds — costclaw packages/engine/src/optimizer.ts:10-37
// ---------------------------------------------------------------------------
const REDUNDANT_TARGET_MIN_FIRES = 10; // 10, not lower: re-reading a file you are
                                       // actively editing 5-9 times in one session
                                       // is normal iterative work, not thrash.
const HEAVY_TOOL_FIRES = 100;
const DECAY_DROP = 0.25;
const LATE_FLOOR = 0.5;
const MARATHON_MIN_REQUESTS = 6;       // lowered from costclaw's MARATHON_MIN_TURNS=40:
                                       // the batch rule needs 40 turns of history to
                                       // trust thirds; live we only claim a decay
                                       // SIGNAL (never a monthly figure) so 6 requests
                                       // is the smallest window with 2 per third.
const RESULT_BLOAT_CHARS = 20000;      // a single tool result over 20k chars
const DEFAULT_SERVE_AFTER = 4;         // the Nth identical Read gets served from cache
const CHARS_PER_TOKEN = 4;             // tokenizer estimate; every figure using it is "~"

function severityForSavings(usd) {
  if (usd >= 50) return "critical";
  if (usd >= 10) return "warn";
  return "info";
}

// ---------------------------------------------------------------------------
// Session state (in-memory for this session; nothing is uploaded anywhere).
// ---------------------------------------------------------------------------
const state = {
  sessionId: "",
  repo: "",
  startedAt: Date.now(),
  serveAfter: DEFAULT_SERVE_AFTER,

  requestIndex: 0,          // increments on every turn.step — THE request boundary
  requests: [],             // {idx, model, agentId, usage, costUsd, hitRate, exposureUsd}
  byModel: {},              // model -> {input, output, cacheRead, cacheWrite, costUsd, requests}
  costUsd: 0,
  warnings: {},             // normalizeUsage warning -> count
  unknownModels: {},

  toolEvents: [],           // {name, requestId, target, chars, t, served}
  targetCount: {},          // "tool|target" -> fires
  targetRequests: {},       // "tool|target" -> Set of request indices
  bloat: [],                // {tool, target, chars, requestId}

  readCache: {},            // readKey -> {result, chars, size, mtimeMs, firstRequest, target}
  mutated: {},              // target -> count of Write/Edit/NotebookEdit
  served: [],               // {target, requestId, tokens, usd, n}
  savedTokens: 0,
  savedUsd: 0,

  lastUsage: null,          // $.session.usage() snapshot
  usageChecks: [],          // {ours, engine, deltaUsd}
  log: [],                  // evidence JSONL rows
  dirty: false,
};

function primaryModel() {
  let best = null;
  let bestTok = -1;
  for (const m of Object.keys(state.byModel)) {
    const e = state.byModel[m];
    const tok = e.input + e.cacheRead + e.cacheWrite + e.output;
    if (tok > bestTok) { bestTok = tok; best = m; }
  }
  return best;
}

function totals() {
  let input = 0, output = 0, cacheRead = 0, cacheWrite = 0;
  for (const m of Object.keys(state.byModel)) {
    const e = state.byModel[m];
    input += e.input; output += e.output; cacheRead += e.cacheRead; cacheWrite += e.cacheWrite;
  }
  return { input, output, cacheRead, cacheWrite };
}

function sessionHitRate() {
  const t = totals();
  return cacheHitRateOf(t.input, t.cacheWrite, t.cacheRead);
}

// Early-third vs late-third cache decay (costclaw MARATHON_SESSION, live).
// Returns {assessed:false} until there are enough requests — costclaw
// scoring.ts:28 makeCheck discipline: a check with no evidence is NOT assessed,
// it is not defaulted to zero.
function cacheDecay() {
  const n = state.requests.length;
  if (n < MARATHON_MIN_REQUESTS) return { assessed: false, reason: `${n}/${MARATHON_MIN_REQUESTS} requests` };
  const third = Math.floor(n / 3);
  if (third === 0) return { assessed: false, reason: "third is empty" };
  let eRead = 0, eTot = 0, lRead = 0, lTot = 0, lateExposure = 0;
  for (let i = 0; i < third; i++) { eRead += state.requests[i].read; eTot += state.requests[i].total; }
  for (let i = n - third; i < n; i++) { lRead += state.requests[i].read; lTot += state.requests[i].total; lateExposure += state.requests[i].exposureUsd; }
  if (lTot === 0) return { assessed: false, reason: "late third had no context tokens" };
  const earlyHit = eTot > 0 ? eRead / eTot : 0;
  const lateHit = lRead / lTot;
  const drop = earlyHit - lateHit;
  const fired = drop >= DECAY_DROP && lateHit < LATE_FLOOR;
  // Savings, derivable: the share of the late third's uncached-input exposure
  // attributable to the shortfall against the early hit rate.
  const expectedReads = lTot * earlyHit;
  const shortfall = Math.max(0, expectedReads - lRead);
  const lateMiss = lTot - lRead;
  const affectedShare = lateMiss > 0 ? Math.min(1, shortfall / lateMiss) : 0;
  return { assessed: true, fired, earlyHit, lateHit, drop, requests: n, usd: lateExposure * affectedShare };
}

// Repeated reads: same (tool,target) more than once, graded with classifyRun
// over that target's own events, so "same target across >=3 model requests"
// is a FACT (the request index came from turn.step), not an inference.
function repeatedTargets() {
  const out = [];
  for (const key of Object.keys(state.targetCount)) {
    const fires = state.targetCount[key];
    if (fires < 2) continue;
    const sep = key.indexOf("|");
    const tool = key.slice(0, sep);
    const target = key.slice(sep + 1);
    const run = state.toolEvents.filter(x => x.name === tool && x.target === target);
    const graded = classifyRun(run, 0, run.length - 1);
    const redundant = fires - 1;
    const chars = run.reduce((s, x) => s + (x.chars || 0), 0);
    const perCall = run.length ? Math.round(chars / run.length) : 0;
    const wastedTokens = Math.ceil((perCall * redundant) / CHARS_PER_TOKEN);
    out.push({ tool, target, fires, redundant, graded, wastedTokens, thrash: fires >= REDUNDANT_TARGET_MIN_FIRES });
  }
  out.sort((a, b) => b.fires - a.fires);
  return out;
}

function toolLoopStatus() {
  const runs = detectRepeatedRuns(state.toolEvents, RUN_THRESHOLD);
  let heavy = null;
  const byTool = {};
  for (const x of state.toolEvents) byTool[x.name] = (byTool[x.name] || 0) + 1;
  for (const t of Object.keys(byTool)) if (byTool[t] >= HEAVY_TOOL_FIRES) heavy = { tool: t, fires: byTool[t] };
  const high = runs.filter(r => r.confidence === "high");
  const medium = runs.filter(r => r.confidence === "medium");
  let status = "none";
  if (high.length || heavy) status = "active";
  else if (medium.length) status = "emerging";
  return { status, runs, high, medium, heavy };
}

// Tokens a repeated read would have cost, priced at the session's primary model
// input rate. Upper bound (the tokens might have landed as a cache read on a
// later request); stated as such in the README and as "~" everywhere it prints.
function usdForTokens(tokens) {
  const p = priceFor(primaryModel());
  return tokens * p.input / 1000000;
}

// ---------------------------------------------------------------------------
// Efficiency score /100 — this plugin's own rubric, deterministic, documented.
// Start at 100, deduct. A component with no evidence yet is NOT assessed and
// deducts nothing (costclaw scoring.ts:28 makeCheck discipline); the HUD says
// which components were skipped rather than pretending they scored full marks.
//   cache      up to -30  max(0, 0.80 - hitRate) * 100 * 0.5, needs >= 2 requests
//   repeats    up to -25  3 per redundant high/medium-confidence same-target read
//   loop       up to -20  active -20, emerging -10
//   bloat      up to -15  5 per tool result over 20k chars
//   decay      up to -10  -10 when DECAY_DROP crossed and late third < LATE_FLOOR
// ---------------------------------------------------------------------------
function efficiencyScore() {
  const parts = [];
  let score = 100;

  if (state.requests.length >= 2) {
    const hit = sessionHitRate();
    const pen = Math.min(30, Math.max(0, Math.round((0.80 - hit) * 100 * 0.5)));
    score -= pen; parts.push({ name: "cache", penalty: pen, assessed: true });
  } else parts.push({ name: "cache", penalty: 0, assessed: false });

  const reps = repeatedTargets();
  const graded = reps.filter(r => r.graded.confidence !== "low");
  if (state.toolEvents.length > 0) {
    const redundant = graded.reduce((s, r) => s + r.redundant, 0);
    const pen = Math.min(25, redundant * 3);
    score -= pen; parts.push({ name: "repeats", penalty: pen, assessed: true });
  } else parts.push({ name: "repeats", penalty: 0, assessed: false });

  const loop = toolLoopStatus();
  if (state.toolEvents.length >= RUN_THRESHOLD) {
    const pen = loop.status === "active" ? 20 : loop.status === "emerging" ? 10 : 0;
    score -= pen; parts.push({ name: "loop", penalty: pen, assessed: true });
  } else parts.push({ name: "loop", penalty: 0, assessed: false });

  if (state.toolEvents.length > 0) {
    const pen = Math.min(15, state.bloat.length * 5);
    score -= pen; parts.push({ name: "bloat", penalty: pen, assessed: true });
  } else parts.push({ name: "bloat", penalty: 0, assessed: false });

  const decay = cacheDecay();
  if (decay.assessed) {
    const pen = decay.fired ? 10 : 0;
    score -= pen; parts.push({ name: "decay", penalty: pen, assessed: true });
  } else parts.push({ name: "decay", penalty: 0, assessed: false });

  return { score: Math.max(0, Math.min(100, Math.round(score))), parts, notAssessed: parts.filter(p => !p.assessed).map(p => p.name) };
}

// ---------------------------------------------------------------------------
// Findings. A dollar figure ONLY where it is derivable from measured numbers.
// costclaw's rule, kept verbatim in spirit: never invented.
// ---------------------------------------------------------------------------
function buildFindings() {
  const out = [];

  for (const r of repeatedTargets()) {
    if (r.redundant < 1) continue;
    const derivable = r.graded.confidence === "high";
    out.push({
      ruleId: r.thrash ? "REDUNDANT_TARGET_THRASH" : "REPEATED_TARGET",
      confidence: r.graded.confidence,
      title: `${r.tool} hit ${r.target} ${r.fires}x`,
      evidence: `${r.graded.evidence} requests=[${[...(state.targetRequests[r.tool + "|" + r.target] || [])].join(",")}]`,
      usd: derivable ? usdForTokens(r.wastedTokens) : null,
      tokens: derivable ? r.wastedTokens : null,
      severity: derivable ? severityForSavings(usdForTokens(r.wastedTokens)) : "info",
    });
  }

  const loop = toolLoopStatus();
  for (const r of loop.high) {
    out.push({
      ruleId: "HEAVY_TOOL_LOOPS", confidence: "high",
      title: `Consecutive ${r.name} run (${r.count} calls)`,
      evidence: r.evidence, usd: null, tokens: null, severity: "warn",
    });
  }
  if (loop.heavy) {
    out.push({
      ruleId: "HEAVY_TOOL_LOOPS", confidence: "high",
      title: `${loop.heavy.tool} fired ${loop.heavy.fires}x (>= ${HEAVY_TOOL_FIRES})`,
      evidence: `costclaw HEAVY_TOOL_FIRES threshold crossed.`, usd: null, tokens: null, severity: "warn",
    });
  }

  for (const b of state.bloat) {
    const tokens = Math.ceil(b.chars / CHARS_PER_TOKEN);
    out.push({
      ruleId: "RESULT_BLOAT", confidence: "high",
      title: `${b.tool} returned ${b.chars} chars from ${b.target}`,
      evidence: `A single tool result over ${RESULT_BLOAT_CHARS} chars entered the context at request #${b.requestId}; ~${tokens} tokens.`,
      usd: usdForTokens(tokens), tokens, severity: severityForSavings(usdForTokens(tokens)),
    });
  }

  const decay = cacheDecay();
  if (decay.assessed && decay.fired) {
    out.push({
      ruleId: "MARATHON_SESSION", confidence: "high",
      title: `Cache hit fell ${Math.round(decay.earlyHit * 100)}% -> ${Math.round(decay.lateHit * 100)}%`,
      evidence: `${decay.requests} model requests; early-third vs late-third drop ${Math.round(decay.drop * 100)}pp crossed DECAY_DROP=${DECAY_DROP * 100}pp with the late third under LATE_FLOOR=${LATE_FLOOR * 100}%.`,
      usd: decay.usd, tokens: null, severity: severityForSavings(decay.usd),
    });
  }

  if (state.served.length) {
    out.push({
      ruleId: "SERVED_FROM_CACHE", confidence: "high",
      title: `${state.served.length} Read call${state.served.length === 1 ? "" : "s"} answered by costclaw-live, not by the tool`,
      evidence: state.served.map(s => `#${s.requestId} ${s.target} (read ${s.n}) ~${s.tokens} tok`).join(" · "),
      usd: -state.savedUsd, tokens: -state.savedTokens, severity: "info",
    });
  }

  return out;
}

// ---------------------------------------------------------------------------
// Rendering helpers
// ---------------------------------------------------------------------------
// Two decimals for real money, more for the sub-cent figures a single cached
// read is worth: rounding those to $0.00 hid the only number the saving has.
function money(usd) {
  const a = Math.abs(usd);
  const places = a >= 0.01 ? 2 : a >= 0.0001 ? 4 : 6;
  const v = roundMoneyHalfUp(usd, places);
  return (v < 0 ? "-$" : "$") + Math.abs(v).toFixed(places);
}
function pct(x) { return Math.round(x * 100) + "%"; }

function headline() {
  const s = efficiencyScore();
  const reps = repeatedTargets().filter(r => r.redundant >= 1);
  const redundant = reps.reduce((a, r) => a + r.redundant, 0);
  const redundantTokens = reps.reduce((a, r) => a + (r.graded.confidence === "high" ? r.wastedTokens : 0), 0);
  const loop = toolLoopStatus();
  const ctx = state.lastUsage && state.lastUsage.context && state.lastUsage.context.percent !== undefined
    ? state.lastUsage.context.percent : "?";
  return `COSTCLAW LIVE · efficiency ${s.score}/100 · repeated reads ${redundant} (~${redundantTokens} tok) · cache health ${pct(sessionHitRate())} · tool loop ${loop.status} · context ${ctx}% · ${money(state.costUsd)}`;
}

function findingLines() {
  return buildFindings().map(f => {
    const dollars = f.usd === null || f.usd === undefined ? "" : ` ${money(f.usd)}`;
    return `${f.ruleId} [${f.confidence}]${dollars} — ${f.title}`;
  });
}

// ---------------------------------------------------------------------------
// $-using helpers. The loader's static scan allows `$` as the parameter of a
// TOP-LEVEL function declaration, used only as `$.noun.method(...)`.
// ---------------------------------------------------------------------------
function note($, line) { $.ui.log(line); }

async function flushEvidence($) {
  if (!state.dirty) return;
  state.dirty = false;
  const name = state.sessionId ? state.sessionId : "unknown";
  const body = state.log.map(x => JSON.stringify(x)).join("\n") + "\n";
  try { await $.fs.write(EVIDENCE_DIR + "live-" + name + ".jsonl", body); } catch (err) { /* evidence is best-effort */ }
}

async function statUnchanged($, path, entry) {
  try {
    const st = await $.fs.stat(path);
    return st && st.kind === "file" && st.size === entry.size && st.mtimeMs === entry.mtimeMs;
  } catch (err) {
    return false;
  }
}

async function readServeAfter($) {
  try {
    const v = await $.store.get("serveAfter");
    if (typeof v === "number" && Number.isSafeInteger(v) && v >= 2 && v <= 50) return v;
  } catch (err) { /* store is optional */ }
  return DEFAULT_SERVE_AFTER;
}

async function writeServeAfter($, n) {
  try { await $.store.set("serveAfter", n); } catch (err) { /* store is optional */ }
}

async function refreshUsage($) {
  try {
    state.lastUsage = await $.session.usage();
    return state.lastUsage;
  } catch (err) {
    return null;
  }
}

async function bootSession($) {
  try { state.sessionId = await $.session.id(); } catch (err) { state.sessionId = "unknown"; }
  try { const r = await $.session.repo(); state.repo = r && r.name ? r.name : ""; } catch (err) { state.repo = ""; }
}

function pushLog(kind, data) {
  state.log.push(Object.assign({ t: Date.now(), kind }, data));
  if (state.log.length > 4000) state.log.shift();
  state.dirty = true;
}

function tick($) { $.ui.status(headline()); }

// ---------------------------------------------------------------------------
export const register = (on, options) => {

  // ---- 1. turn.step: per-request usage, cost, cache hit rate ----------------
  // turn.step is THE request boundary. Every tool.call after it belongs to this
  // index, which is what makes AgentLens's confidence grading a fact.
  on("turn.step", async function* ($, e, next) {
    state.requestIndex += 1;
    const myIndex = state.requestIndex;
    const stream = next(e);
    for await (const c of stream) yield c;
    const r = await stream.result;

    const raw = r && r.usage ? r.usage : null;
    if (raw) {
      const model = raw.model || e.model;
      const norm = normalizeUsage(raw);
      for (const w of norm.warnings) state.warnings[w] = (state.warnings[w] || 0) + 1;
      if (!isKnownModel(model)) state.unknownModels[model] = (state.unknownModels[model] || 0) + 1;
      const u = norm.usage;
      const costUsd = costForNormalizedUsage(model, u);
      const exposureUsd = uncachedInputExposureForNormalizedUsage(model, u);
      const read = u.cache_read_input_tokens;
      const total = u.input_tokens + u.cache_creation_input_tokens + u.cache_read_input_tokens;
      const hit = cacheHitRateOf(u.input_tokens, u.cache_creation_input_tokens, read);

      state.costUsd += costUsd;
      const m = state.byModel[model] || { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, costUsd: 0, requests: 0 };
      m.input += u.input_tokens; m.output += u.output_tokens;
      m.cacheRead += u.cache_read_input_tokens; m.cacheWrite += u.cache_creation_input_tokens;
      m.costUsd += costUsd; m.requests += 1;
      state.byModel[model] = m;

      state.requests.push({
        idx: myIndex, model, agentId: e.agentId || null,
        input: u.input_tokens, output: u.output_tokens,
        cacheRead: read, cacheWrite: u.cache_creation_input_tokens,
        read, total, hitRate: hit, costUsd, exposureUsd,
        premium: isPremiumModel(model),
      });
      pushLog("request", {
        idx: myIndex, model, agentId: e.agentId || null, messageCount: e.messageCount,
        input: u.input_tokens, output: u.output_tokens, cacheRead: read,
        cacheWrite: u.cache_creation_input_tokens, hitRate: hit,
        costUsd, exposureUsd, sessionCostUsd: state.costUsd, warnings: norm.warnings,
      });
    }
    return r;
  });

  // ---- 2 + 3. tool.call: record, detect, and INTERVENE ----------------------
  on("tool.call", async ($, e, next) => {
    const tool = e.tool;
    const target = targetFor(tool, e);
    const requestId = state.requestIndex;

    // A Write/Edit invalidates the cache for that path, always, first.
    if ((tool === "Write" || tool === "Edit" || tool === "NotebookEdit") && target) {
      state.mutated[target] = (state.mutated[target] || 0) + 1;
      for (const k of Object.keys(state.readCache)) {
        if (state.readCache[k].target === target) delete state.readCache[k];
      }
      pushLog("invalidate", { tool, target, requestId });
    }

    // --- THE INTERVENTION -------------------------------------------------
    // The Nth identical Read of a file nothing wrote to, whose size+mtime are
    // still what they were at the first read, is answered from this plugin's
    // cache: no tool run, no tokens, and the model is told in a hidden context
    // block that the result is the cached one.
    if (tool === "Read" && target) {
      const readKey = target + "|" + (e.offset === undefined ? "" : e.offset) + "|" + (e.limit === undefined ? "" : e.limit);
      const entry = state.readCache[readKey];
      const priorFires = state.targetCount["Read|" + target] || 0;
      const nth = priorFires + 1;
      if (entry && nth >= state.serveAfter && !state.mutated[target]) {
        const unchanged = await statUnchanged($, target, entry);
        if (unchanged) {
          const tokens = Math.ceil(entry.chars / CHARS_PER_TOKEN);
          const usd = usdForTokens(tokens);
          state.savedTokens += tokens; state.savedUsd += usd;
          state.served.push({ target, requestId, tokens, usd, n: nth });
          state.targetCount["Read|" + target] = nth;
          const reqs = state.targetRequests["Read|" + target] || new Set();
          reqs.add(requestId); state.targetRequests["Read|" + target] = reqs;
          state.toolEvents.push({ name: "Read", requestId, target, chars: 0, t: Date.now(), served: true });
          pushLog("served", { target, requestId, nth, tokens, usd, savedTokensTotal: state.savedTokens, savedUsdTotal: state.savedUsd, firstReadAtRequest: entry.firstRequest });
          note($, `⟦costclaw-live⟧ SERVED FROM CACHE  read #${nth} of ${target}  saved ~${tokens} tokens (${money(usd)})  · file unchanged since request #${entry.firstRequest}`);
          await flushEvidence($);
          return {
            result: entry.result,
            context: [`costclaw-live: served from cache, file unchanged since first read (saved ~${tokens} tokens)`],
          };
        }
      }
    }

    // --- normal path ------------------------------------------------------
    const r = await next(e);

    const text = r && typeof r.text === "string" ? r.text : (r && r.result !== undefined ? safeLen(r.result) : "");
    const chars = typeof text === "string" ? text.length : 0;

    if (target) {
      const key = tool + "|" + target;
      state.targetCount[key] = (state.targetCount[key] || 0) + 1;
      const reqs = state.targetRequests[key] || new Set();
      reqs.add(requestId);
      state.targetRequests[key] = reqs;
    }
    state.toolEvents.push({ name: tool, requestId, target, chars, t: Date.now(), served: false });
    if (state.toolEvents.length > 5000) state.toolEvents.shift();

    if (chars > RESULT_BLOAT_CHARS) {
      state.bloat.push({ tool, target, chars, requestId });
      pushLog("bloat", { tool, target, chars, requestId, tokens: Math.ceil(chars / CHARS_PER_TOKEN) });
      note($, `⟦costclaw-live⟧ RESULT BLOAT  ${tool} ${target} returned ${chars} chars (~${Math.ceil(chars / CHARS_PER_TOKEN)} tokens)`);
    }

    // Cache the first successful Read so the Nth can be served from it.
    if (tool === "Read" && target && r && !r.isError && r.result !== undefined) {
      const readKey = target + "|" + (e.offset === undefined ? "" : e.offset) + "|" + (e.limit === undefined ? "" : e.limit);
      if (!state.readCache[readKey] && !state.mutated[target]) {
        let size = -1, mtimeMs = -1;
        try { const st = await $.fs.stat(target); if (st && st.kind === "file") { size = st.size; mtimeMs = st.mtimeMs; } } catch (err) { /* uncacheable */ }
        if (size >= 0) {
          state.readCache[readKey] = { result: r.result, chars, size, mtimeMs, firstRequest: requestId, target };
          pushLog("cached", { target, requestId, chars, size, mtimeMs });
        }
      }
    }

    pushLog("tool", { tool, target, requestId, chars, isError: !!(r && r.isError), deny: r && r.deny ? String(r.deny).slice(0, 120) : null });
    state.dirty = true;
    return r;
  });

  // ---- 6. turn.complete: $.session.usage() cross-check ---------------------
  on("turn.complete", async ($, e, next) => {
    const r = await next(e);
    if (!e.agentId) {
      const u = await refreshUsage($);
      if (u) {
        const engineUsd = u.cost && typeof u.cost.usd === "number" ? u.cost.usd : null;
        const check = {
          oursUsd: roundMoneyHalfUp(state.costUsd, 4),
          engineUsd,
          deltaUsd: engineUsd === null ? null : roundMoneyHalfUp(state.costUsd - engineUsd, 4),
          contextPercent: u.context ? u.context.percent : null,
          contextTokens: u.context ? u.context.tokens : null,
          contextWindow: u.context ? u.context.window : null,
          rateLimits: (u.rateLimits || []).map(x => ({ kind: x.kind, percentUsed: Math.round(x.percentUsed) })),
          requests: state.requests.length,
        };
        state.usageChecks.push(check);
        pushLog("usage-check", check);
        // The findings snapshot goes in the ledger too: there is no HUD in a
        // headless session, so this is the only place a `-p` run can read them.
        pushLog("findings", { score: efficiencyScore().score, headline: headline(), findings: buildFindings() });
        const five = (u.rateLimits || []).filter(x => x.kind === "five_hour")[0];
        note($, `⟦costclaw-live⟧ ${headline()}`);
        note($, `⟦costclaw-live⟧ cost cross-check: ours ${money(state.costUsd)} (${state.requests.length} requests, rate card ${PRICING_SNAPSHOT_DATE}) vs engine ${engineUsd === null ? "n/a" : money(engineUsd)}${check.deltaUsd === null ? "" : ` · delta ${money(check.deltaUsd)}`} · five-hour ${five ? five.percentUsed + "%" : "n/a"}`);
      }
    }
    await flushEvidence($);
    return r;
  });

  // ---- 4. HUD above the prompt --------------------------------------------
  on("ui.render", { component: "AbovePrompt", surface: "terminal" }, async ($, e, next) => {
    const { Box, Text } = $.ui.resolve(e);
    const width = Math.max(40, (e.props && e.props.bodyColumns ? e.props.bodyColumns : 100) - 4);
    const lines = findingLines().slice(0, 5);
    const s = efficiencyScore();
    const rows = lines.map((t, i) => (
      <Text key={"f" + i} color={t.indexOf("SERVED_FROM_CACHE") === 0 ? "green" : "yellow"} wrap="truncate-end">{t.slice(0, width)}</Text>
    ));
    const skipped = s.notAssessed.length ? `not assessed: ${s.notAssessed.join(",")}` : "all components assessed";
    return (
      <Box flexDirection="column" borderStyle="round" borderColor="cyan" paddingX={1}>
        <Text bold color="cyan">{headline().slice(0, width)}</Text>
        {rows}
        <Text dimColor wrap="truncate-end">{`${skipped} · saved so far ~${state.savedTokens} tok (${money(state.savedUsd)}) · serve-after ${state.serveAfter} · /costclaw for evidence`}</Text>
      </Box>
    );
  });

  // ---- 5. /costclaw --------------------------------------------------------
  on("command.run", { command: "costclaw" }, async ($, e, next) => {
    const arg = (e.args || "").trim().toLowerCase();
    if (arg.indexOf("serve") === 0) {
      const n = parseInt(arg.split(/\s+/)[1], 10);
      if (!Number.isSafeInteger(n) || n < 2 || n > 50) return { text: `costclaw-live: serve-after must be an integer 2..50 (currently ${state.serveAfter})` };
      state.serveAfter = n;
      await writeServeAfter($, n);
      $.ui.invalidate("ui.render");
      return { text: `costclaw-live: serve-after -> ${n} (the ${n}th identical Read of an unchanged file is answered from cache)` };
    }

    await refreshUsage($);
    const s = efficiencyScore();
    const t = totals();
    const decay = cacheDecay();
    const loop = toolLoopStatus();
    const findings = buildFindings();

    const modelRows = Object.keys(state.byModel).map(m => {
      const x = state.byModel[m];
      return `  ${m}${isKnownModel(m) ? "" : "  (NO RATE-CARD ENTRY — priced at the fallback, figure is an estimate)"}\n    requests ${x.requests} · in ${x.input} · out ${x.output} · cacheR ${x.cacheRead} · cacheW ${x.cacheWrite} · ${money(x.costUsd)}`;
    }).join("\n");

    const findingRows = findings.length ? findings.map((f, i) => {
      const dollars = f.usd === null || f.usd === undefined ? "(no dollar figure is derivable)" : money(f.usd);
      return `  ${i + 1}. ${f.ruleId} [${f.confidence}/${f.severity}] ${dollars}\n     ${f.title}\n     EVIDENCE: ${f.evidence}`;
    }).join("\n") : "  none yet";

    const repRows = repeatedTargets().length ? repeatedTargets().map(r =>
      `  ${r.tool} x${r.fires} ${r.target}\n     requests [${[...(state.targetRequests[r.tool + "|" + r.target] || [])].join(",")}] · confidence ${r.graded.confidence}${r.thrash ? ` · >= REDUNDANT_TARGET_MIN_FIRES(${REDUNDANT_TARGET_MIN_FIRES})` : ""}`
    ).join("\n") : "  none";

    const servedRows = state.served.length ? state.served.map(x =>
      `  request #${x.requestId}: read ${x.n} of ${x.target} answered from cache, ~${x.tokens} tokens (${money(x.usd)}) not spent`
    ).join("\n") : "  none (no file has been read " + state.serveAfter + " times unchanged yet)";

    const u = state.lastUsage;
    const engineUsd = u && u.cost && typeof u.cost.usd === "number" ? u.cost.usd : null;
    const deltaLine = engineUsd === null
      ? "  engine cost unavailable"
      : `  ours ${money(state.costUsd)} · engine $.session.usage().cost ${money(engineUsd)} · delta ${money(state.costUsd - engineUsd)}` +
        (Math.abs(state.costUsd - engineUsd) > Math.max(0.01, Math.abs(engineUsd) * 0.15)
          ? "\n  DISCREPANCY: ours counts only requests seen through turn.step since this plugin loaded and prices them from the "
            + PRICING_SNAPSHOT_DATE + " list-price snapshot; the engine's figure covers the whole session and its own accounting. Neither is an invoice."
          : "\n  within 15% — the two agree.");

    const warnRows = Object.keys(state.warnings).length
      ? Object.keys(state.warnings).map(w => `  ${state.warnings[w]}x ${w}`).join("\n")
      : "  none";

    const text = [
      `COSTCLAW LIVE — session ${state.sessionId}${state.repo ? " · repo " + state.repo : ""}`,
      headline(),
      "",
      `SCORE ${s.score}/100 (rubric: 100 minus cache<=30, repeats<=25, loop<=20, bloat<=15, decay<=10)`,
      `  ${s.parts.map(p => `${p.name} ${p.assessed ? "-" + p.penalty : "not assessed"}`).join(" · ")}`,
      "",
      "FINDINGS",
      findingRows,
      "",
      "REPEATED (tool,target)",
      repRows,
      "",
      "INTERVENTIONS (answered by costclaw-live, not by the tool)",
      servedRows,
      `  total saved ~${state.savedTokens} tokens (${money(state.savedUsd)}), serve-after = ${state.serveAfter}`,
      "",
      "CACHE",
      `  session hit rate ${pct(sessionHitRate())} over ${state.requests.length} model requests`,
      decay.assessed
        ? `  early third ${pct(decay.earlyHit)} -> late third ${pct(decay.lateHit)} (drop ${Math.round(decay.drop * 100)}pp; DECAY_DROP=${DECAY_DROP * 100}pp, LATE_FLOOR=${LATE_FLOOR * 100}%) ${decay.fired ? "FIRED" : "not fired"}`
        : `  decay NOT ASSESSED (${decay.reason})`,
      "",
      "TOOL LOOP",
      `  status ${loop.status}${loop.heavy ? ` · ${loop.heavy.tool} x${loop.heavy.fires}` : ""}`,
      loop.runs.length ? loop.runs.map(r => `  [${r.confidence}] ${r.evidence}`).join("\n") : "  no consecutive run of >= " + RUN_THRESHOLD,
      "",
      "MODELS (rate card " + PRICING_SNAPSHOT_DATE + ")",
      modelRows || "  none yet",
      `  totals: in ${t.input} · out ${t.output} · cacheR ${t.cacheRead} · cacheW ${t.cacheWrite}`,
      "",
      "COST CROSS-CHECK",
      deltaLine,
      u && u.context ? `  context ${u.context.percent}% (${u.context.tokens} of ${u.context.window})` : "  context unavailable",
      u && u.rateLimits ? "  " + u.rateLimits.map(x => `${x.kind} ${Math.round(x.percentUsed)}%`).join(" · ") : "  rate limits unavailable",
      "",
      "PRICING WARNINGS",
      warnRows,
      Object.keys(state.unknownModels).length ? "  UNPRICED MODELS: " + Object.keys(state.unknownModels).join(", ") : "",
      "",
      `EVIDENCE: ${EVIDENCE_DIR}live-${state.sessionId}.jsonl (${state.log.length} rows)`,
    ].join("\n");

    await flushEvidence($);
    return { text };
  });

  // ---- session.start -------------------------------------------------------
  on("session.start", async ($, e, next) => {
    await bootSession($);
    state.serveAfter = await readServeAfter($);
    if (options && typeof options.serveAfter === "number" && Number.isSafeInteger(options.serveAfter) && options.serveAfter >= 2) {
      state.serveAfter = options.serveAfter;
    }
    await $.command.register({
      name: "costclaw",
      description: "COSTCLAW LIVE: findings with evidence, cost cross-check, cache decay. /costclaw serve <n> sets the read-cache threshold.",
      argumentHint: "[serve <n>]",
      immediate: true,
    });
    $.ui.status(headline());
    $.clock.every(2000, () => tick($));
    note($, `⟦costclaw-live⟧ armed · serve-after=${state.serveAfter} · rate card ${PRICING_SNAPSHOT_DATE} · evidence -> ${EVIDENCE_DIR}live-${state.sessionId}.jsonl`);
    pushLog("start", { sessionId: state.sessionId, repo: state.repo, serveAfter: state.serveAfter, snapshot: PRICING_SNAPSHOT_DATE });
    await flushEvidence($);
    return next(e);
  });
};

function safeLen(v) {
  try { const s = JSON.stringify(v); return typeof s === "string" ? s : ""; } catch (err) { return ""; }
}
