// ════════════════════════════════════════════════════════════════════════════
// PRODGUARD POLICY CORE — pure, synchronous, transport-independent.
//
// INVARIANT (checkable by grep, not by comment): this file never mentions `$`,
// never mentions `next`, never names a hook event, and performs no I/O. It is a
// pile of functions over plain data. The hook glue in ./index.tsx is the only
// thing that knows Claude Code exists. Swap the glue for an MCP server, an HTTP
// route or a unit test and every decision below is unchanged.
//
//   A1  DashClaw evidence classifier      ← ported from DashClaw app/lib/guard/evidence.ts
//   A2  offlocal policy engine            ← ported from offlocalai-mcp src/policy.ts
//   A3  offlocal → DashClaw bridge        ← ported from offlocalai-mcp src/dashclaw/guard.ts
//   A4  the seam neither project has: evidence flags → offlocal Capability
//   A5  registry resolution + decide(), the one entry point
//
// Every port cites the source path and line range it came from. Where the port
// deviates from the original, the comment says DEVIATION and why.
// ════════════════════════════════════════════════════════════════════════════

// ════════════════════════════════════════════════════════════════════════════
// A1 — DASHCLAW EVIDENCE CLASSIFIER
// Port of C:\Projects\DashClaw\app\lib\guard\evidence.ts (858 lines, zero
// imports, header: "Pure and synchronous (no I/O), unit-testable in isolation").
// Ported: the shell family (kind:'shell') and the file family (kind:'file'),
// which is what a Bash / Write / Edit / NotebookEdit tool call can supply.
// NOT ported: classifyHttp (evidence.ts:752-785) and classifyScriptExcerpt
// (evidence.ts:512-536) — a tool.call carries no HTTP act and no script body.
// ════════════════════════════════════════════════════════════════════════════

// evidence.ts:38 — clamp
function clamp(n) { return Math.max(0, Math.min(Math.round(n), 100)); }

// evidence.ts:41-44 — base_risk + Σ modifiers, clamped 0-100.
export function evidenceTotal(c) {
  return clamp(c.base_risk + c.modifiers.reduce(function (s, m) { return s + m.delta; }, 0));
}

// evidence.ts:46-47
const SENSITIVE_PATH_RE = /(\.env\b|secret|credential|private_key|\.pem\b|id_rsa|\.key\b)/i;
const CI_CONFIG_RE = /(\.github\/workflows|\.gitlab-ci|dockerfile|vercel\.json|\.circleci|jenkinsfile|\.deploy)/i;

// evidence.ts:59-62 — deliberately conservative: dot-dirs and unambiguous
// outputs only. No `build`/`out`/`target` — "too often real content".
const REGENERABLE_ARTIFACT_DIRS = new Set([
  ".next", ".turbo", ".cache", ".parcel-cache", "dist", "coverage",
  "node_modules", "__pycache__", ".pytest_cache", ".nuxt", ".svelte-kit",
]);

// evidence.ts:67, 75, 76-83, 85-87
const RM_RECURSIVE_RE = /\brm\s+-\S*r|\bremove-item\b[^&|;]*\s-\S*rec/i;
const FIND_DELETE_RE = /\bfind\b[^&|;]*(\s-delete\b|\s-exec\s+(\S*\/)?(rm|shred)\b)/i;
const INTERPRETER_DESTRUCTIVE_RE =
  /\b(python[0-9]?|node(?:js)?|ruby|perl|php|deno|bun|tsx|ts-node)\b[^&|;]*(shutil\.rmtree|os\.(remove|unlink|rmdir)|fs\.(rm|rmdir|unlink)|rmsync|unlinksync|rimraf)/i;
const INTERPRETER_DESTRUCTIVE_FULL_RE =
  /\b(python[0-9]?|node(?:js)?|ruby|perl|php|deno|bun|tsx|ts-node)\b[^\n]*(shutil\.rmtree|os\.(remove|unlink|rmdir)|fs\.(rm|rmdir|unlink)|rmsync|unlinksync|rimraf)/i;
const DEVICE_WRITE_RE =
  /(>\s*|\bof=)("|')?(\/dev\/(sd[a-z]|hd[a-z]|nvme\d+(?:n\d+)?(?:p\d+)?|disk\d+|mmcblk\d+|vd[a-z]|xvd[a-z])\b|\\\\\.\\physicaldrive\d+)/i;

// evidence.ts:89-101
function findRootTargets(segment) {
  const tokens = segment.trim().split(/\s+/).map(function (t) { return t.replace(/^["']|["']$/g, ""); });
  const idx = tokens.findIndex(function (t) { return /^(?:\S*\/)?find$/i.test(t); });
  if (idx === -1) return [];
  const roots = [];
  for (const t of tokens.slice(idx + 1)) {
    if (!t || t.startsWith("-") || t.startsWith("!") || t.startsWith("(")) break;
    roots.push(t);
  }
  return roots;
}

// evidence.ts:102-108
function rmDeleteTargets(segment) {
  const tokens = segment.trim().split(/\s+/).map(function (t) { return t.replace(/^["']|["']$/g, ""); });
  const idx = tokens.findIndex(function (t) { return /^(?:\S*\/)?rm$/i.test(t) || /^remove-item$/i.test(t); });
  if (idx === -1) return [];
  return tokens.slice(idx + 1).filter(function (t) { return t && !t.startsWith("-"); });
}

// evidence.ts:123 — directories the OS designates as scratch.
const OS_SCRATCH_ROOTS = ["/tmp/", "/var/tmp/", "/private/tmp/", "/appdata/local/temp/"];

// evidence.ts:134-149
function isOsScratchTarget(target) {
  const t = target.replace(/\\/g, "/").replace(/\/+$/, "");
  if (!t || t.split("/").includes("..")) return false;
  let low = t.toLowerCase();
  if (!low.startsWith("/")) {
    if (!/^[a-z]:\//.test(low)) return false;
    low = "/" + low;
  }
  return OS_SCRATCH_ROOTS.some(function (root) {
    const idx = low.indexOf(root);
    return idx !== -1 && low.length > idx + root.length;
  });
}

// evidence.ts:150-166 — the F5 alarm-fatigue fix. `rm -rf node_modules` used to
// grade identically to `rm -rf /c/Users/<user>`; "a safety system that blocks
// routine artifact cleanup trains the operator to turn it off — alarm fatigue is
// how governance actually dies" (evidence.ts:50-52).
function isRegenerableArtifactTarget(target) {
  if (/[*?[]/.test(target)) return false;
  if (isOsScratchTarget(target)) return true;
  let t = target.replace(/\\/g, "/").replace(/\/+$/, "");
  if (t.startsWith("./")) t = t.slice(2);
  if (!t || t.startsWith("/") || t.startsWith("~") || /^[a-z]:/i.test(t)) return false;
  const parts = t.toLowerCase().split("/");
  if (parts.includes("..")) return false;
  return REGENERABLE_ARTIFACT_DIRS.has(parts[0] || "");
}

// evidence.ts:167-182 — the catastrophic-root class. Roots only.
function isProtectedRootTarget(target) {
  let t = target.replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
  if (!t) return target.includes("/");
  if (t === "~" || t === "$home" || t === "${home}" || t === "%userprofile%") return true;
  if (/^[a-z]:$/.test(t)) return true;
  if (/^\/[a-z]$/.test(t)) return true;
  t = t.replace(/^[a-z]:/, "");
  if (t === "" || t === "/") return true;
  if (/^\/(c\/)?(users|home)\/[^/]+$/.test(t)) return true;
  if (t === "/root") return true;
  if (/^\/(windows|winnt|etc|usr|bin|sbin|boot|system32|program files( \(x86\))?)($|\/)/.test(t)) return true;
  return false;
}

// evidence.ts:198, 210-211 — the inert git-message exemption. A commit message
// describing a destructive command is data git never executes; scanning it as if
// it were the command hard-blocked commits at risk 100 (2026-08-08).
const GIT_MESSAGE_VERB_RE = /^\s*git\s+(?:(?:-c\s+\S+|--\S+)\s+)*(?:commit|tag|stash|notes)\b/i;
const TRANSPARENT_PREFIX_RE =
  /^(?:[a-z_]\w*=\S*|sudo|env|nohup|nice|ionice|time|timeout|command|builtin|rtk|-\S*|\d+(?:\.\d+)?[smhd]?)$/i;

// evidence.ts:219-226
function isCommandWordPosition(skeletonSoFar) {
  const tail = skeletonSoFar.split(/[|&;\n\r(]/).pop() || "";
  const tokens = tail.split(/\s+/).filter(Boolean);
  const preceding = /\s$/.test(tail) || !tail ? tokens : tokens.slice(0, -1);
  return preceding.every(function (t) { return TRANSPARENT_PREFIX_RE.test(t); });
}

// evidence.ts:242-285 — executable skeleton: quoted ARGUMENT content is blanked
// (data), command substitution is preserved (a shell executes it regardless of
// quotes), and a quoted span in COMMAND-WORD position is kept because `"rm" -rf /`
// is legal shell that still deletes the filesystem.
function codeSkeleton(command) {
  let out = "";
  let quote = null;
  for (let i = 0; i < command.length; i++) {
    const ch = command[i];
    if (quote === "'") {
      if (ch === "'") quote = null;
      out += " ";
      continue;
    }
    if (quote === '"') {
      if (ch === "\\") { out += "  "; i++; continue; }
      if (ch === "`") { out += "`"; continue; }
      if (ch === "$" && command[i + 1] === "(") {
        let depth = 0;
        while (i < command.length) {
          const c = command[i];
          if (c === "(") depth++;
          else if (c === ")") { depth--; out += c; i++; if (depth === 0) break; continue; }
          out += c;
          i++;
        }
        i--;
        continue;
      }
      if (ch === '"') quote = null;
      out += " ";
      continue;
    }
    if (ch === '"' || ch === "'") {
      if (isCommandWordPosition(out)) {
        const close = command.indexOf(ch, i + 1);
        const end = close === -1 ? command.length : close;
        out += " " + command.slice(i + 1, end) + (close === -1 ? "" : " ");
        i = end;
        continue;
      }
      quote = ch; out += " "; continue;
    }
    out += ch;
  }
  return out;
}

// evidence.ts:286-300
function isInertGitMessageCommand(command) {
  const skel = codeSkeleton(command);
  if (!GIT_MESSAGE_VERB_RE.test(skel)) return false;
  return !/[|&;\n\r]|\$\(|`/.test(skel);
}

// evidence.ts:309-315
function isInertGitMessageSegment(seg) {
  if (/[\n\r]|\$\(|`/.test(seg)) return false;
  return GIT_MESSAGE_VERB_RE.test(seg);
}

// evidence.ts:329-334 — quoted data can only become code through an exec sink.
const EXEC_SINK_RE =
  /(^|[\s|&;(/])(sh|bash|zsh|ksh|dash|fish|csh|tcsh|pwsh|powershell|cmd|eval|exec|source|ssh|su|xargs|python[0-9]?|node(?:js)?|ruby|perl|php|deno|bun|tsx|ts-node)\b/i;
function hasExecSink(skeleton) {
  return EXEC_SINK_RE.test(skeleton) || /\$\(|`/.test(skeleton);
}

// evidence.ts:338
const ENV_LAUNCHER_PREFIX_RE = /^\s*env((\s+-u\s+\S+)|(\s+-[i0]\b)|(\s+\w+=\S*))*\s+(?=\S)/;

// ── database acts — evidence.ts:349-437 ─────────────────────────────────────
const DB_URL_LITERAL_RE = /\bpostgres(?:ql)?:\/\//i;
const PKG_RUNNER_RE = /^(npx|bunx|pnpm|yarn|npm)$/i;
const PKG_RUNNER_NOISE_RE = /^(dlx|exec|run|-y|--yes|--silent|-s)$/i;
const DB_CLIENT_RE = /^(?:\S*[/\\])?(psql|pg_restore)(?:\.exe)?$/i;
const DB_MIGRATION_TOOLS = {
  prisma: /^(db\s+(push|execute)|migrate\s+(deploy|dev|reset))\b/i,
  "drizzle-kit": /^(push|migrate|drop)\b/i,
};

// evidence.ts:363-377
function commandSlotTokens(segment) {
  const tokens = segment.trim().split(/\s+/).map(function (t) { return t.replace(/^["']|["']$/g, ""); }).filter(Boolean);
  let i = 0;
  while (i < tokens.length && TRANSPARENT_PREFIX_RE.test(tokens[i])) i++;
  while (i < tokens.length && PKG_RUNNER_RE.test(tokens[i])) {
    i++;
    while (i < tokens.length && PKG_RUNNER_NOISE_RE.test(tokens[i])) i++;
  }
  return tokens.slice(i);
}

// evidence.ts:379-391
function isDatabaseSegment(scanText) {
  if (DB_URL_LITERAL_RE.test(scanText)) return true;
  const tokens = commandSlotTokens(scanText);
  const cmd = tokens[0];
  if (!cmd) return false;
  if (DB_CLIENT_RE.test(cmd)) return true;
  const tool = cmd.replace(/^\S*[/\\]/, "").replace(/\.exe$/i, "").toLowerCase();
  const subcommands = DB_MIGRATION_TOOLS[tool];
  return subcommands ? subcommands.test(tokens.slice(1).join(" ")) : false;
}

// evidence.ts:393-402 — read from the RAW segment: an argument's quoted content
// names what runs. `-f file` is NOT inline (the statements are never seen).
function inlineSqlOf(segment) {
  const m = /(?:^|\s)(?:-c|--command)(?:\s+|=)(?:"([^"]*)"|'([^']*)'|(\S+))/i.exec(segment);
  if (!m) return null;
  const sql = (m[1] || m[2] || m[3] || "").trim();
  return sql || null;
}

// evidence.ts:404-419
function databaseActClassification(inlineSql) {
  if (inlineSql) {
    const sqlCls = classifySql({ statement: inlineSql });
    return {
      derived_action_type: sqlCls.derived_action_type,
      base_risk: sqlCls.base_risk,
      modifiers: sqlCls.modifiers,
      reversible_hint: sqlCls.reversible_hint,
      flags: ["database"].concat(sqlCls.flags),
    };
  }
  return { derived_action_type: "migrate", base_risk: 60, modifiers: [], reversible_hint: false, flags: ["database"] };
}

// evidence.ts:421-431
const DB_HEREDOC_RE = /<<-?\s*(['"]?)([A-Za-z_][A-Za-z0-9_]*)\1[^\n]*\n([\s\S]*?)\n[ \t]*\2\b/;
function databaseHeredocClassification(command) {
  const m = DB_HEREDOC_RE.exec(command);
  if (!m) return null;
  if (!isDatabaseSegment(command.slice(0, m.index))) return null;
  const body = (m[3] || "").trim();
  return body ? databaseActClassification(body) : null;
}

// ── spend (real money) — evidence.ts:439-498 ────────────────────────────────
// 2026-09-04: an agent bought two domains from `node domain-buy.mjs <name>`
// inside a governed Bash call; the command text carried no money signal.
// DEVIATION: the original builds SPEND_URL_PATH_RE with `new RegExp(String.raw…)`
// (evidence.ts:439-451). A hooks module's static scan is happiest with literals,
// so the same alternation is written as one literal here. Same source, same flags.
const SPEND_URL_PATH_RE = /\/registrar\/|\/domains\/[^\/\s"'?]+\/(buy|transfer-in|renew)\b|\/domains\/(buy|purchase)\b|\/v1\/(charges|payment_intents|checkout\/sessions|subscriptions|setup_intents)\b|\/invoices\/[^\/\s"'?]+\/pay\b|\/v[12]\/(checkout\/orders|payments)\b/i;
const SPEND_GENERIC_URL_PATH_RE = /\/(purchase|purchases|checkout|top-?up|buy[-_]credits|credits\/(buy|purchase))\b/i;
const SPEND_GENERIC_API_SHAPE_RE = /\/(api|v\d+)\//i;
const SPEND_GENERIC_HOST_RE = /^(api|checkout|pay|payments|billing|commerce|shop|store|secure)\./i;
const SPEND_LOOKUP_PATH_RE = /\/(availability|price|prices|status|quote)\b/i;
const SPEND_CLI_RE =
  /\bvercel\s+domains?\s+(buy|transfer-in)\b|\bstripe\s+(charges|payment_intents|subscriptions|checkout\s+sessions)\s+create\b|\bagentcash\s+pay\b|\bgcloud\s+billing\b|\baws\s+\S+\s+purchase-\S+|\bnamecheap\b[^&|;]*domains\.create\b/i;
const URL_IN_TEXT_RE = /https?:\/\/[^\s"'<>)\]]+/gi;

// evidence.ts:466-486 — `URL` is one of the globals a hooks module keeps.
function spendUrlHit(url) {
  let path = url;
  let hostname = "";
  try {
    const parsed = new URL(url);
    path = parsed.pathname;
    hostname = parsed.hostname;
  } catch (err) {
    path = url.replace(/^[a-z]+:\/\/[^/]*/i, "").split(/[?#]/)[0] || "";
  }
  const specificHit = SPEND_URL_PATH_RE.test(path);
  const genericMatch = SPEND_GENERIC_URL_PATH_RE.exec(path);
  const genericHit =
    genericMatch !== null &&
    (SPEND_GENERIC_API_SHAPE_RE.test(path.slice(0, genericMatch.index + 1)) ||
      SPEND_GENERIC_HOST_RE.test(hostname));
  if (!specificHit && !genericHit) return null;
  if (SPEND_LOOKUP_PATH_RE.test(path)) return null;
  return "purchase endpoint " + path;
}

// evidence.ts:488-497
function spendHitInText(text) {
  if (SPEND_CLI_RE.test(text)) return "purchase CLI";
  for (const url of text.match(URL_IN_TEXT_RE) || []) {
    const hit = spendUrlHit(url);
    if (hit) return hit;
  }
  return null;
}

// evidence.ts:500 — a URL a read/print command carries is data being shown.
const READ_PRINT_CMD_RE = /^\s*(sudo\s+)?(cat|ls|head|tail|less|more|grep|rg|find|stat|pwd|whoami|echo|printf|which|wc|diff|file|type)\b/i;

// evidence.ts:537-657 — the shell segment classifier.
function classifyShellSegment(seg, rawScan) {
  if (isInertGitMessageSegment(seg)) {
    return { derived_action_type: "apply", base_risk: 35, modifiers: [], reversible_hint: true, flags: ["git_message"] };
  }

  const s = seg.toLowerCase().replace(ENV_LAUNCHER_PREFIX_RE, "");
  const scan = rawScan ? s : codeSkeleton(seg).toLowerCase().replace(ENV_LAUNCHER_PREFIX_RE, "");
  const flags = [];
  const modifiers = [];
  let base = 30;
  let action = "other";
  let reversible = null;

  const isSudo = /^\s*sudo\b/.test(s);
  const deviceWrite = DEVICE_WRITE_RE.test(scan);

  if (RM_RECURSIVE_RE.test(scan) || /\bshred\b|\bmkfs(\.|\b)|^\s*(sudo\s+)?dd\s|\btruncate\b/.test(scan)
      || FIND_DELETE_RE.test(scan) || INTERPRETER_DESTRUCTIVE_RE.test(scan) || deviceWrite) {
    base = 80; action = "security"; reversible = false; flags.push("destructive");
    if (INTERPRETER_DESTRUCTIVE_RE.test(scan)) flags.push("interpreter_destructive");
    if (deviceWrite) {
      modifiers.push({ reason: "raw block device write target", delta: 20 });
      flags.push("device_write", "protected_target");
    } else if (/\bmkfs(\.|\b)/.test(scan)) {
      modifiers.push({ reason: "filesystem format (raw device write)", delta: 20 });
      flags.push("device_write", "protected_target");
    } else if (RM_RECURSIVE_RE.test(scan)) {
      const targets = rmDeleteTargets(s);
      if (targets.length > 0 && targets.every(isRegenerableArtifactTarget)) {
        base = 45; action = "cleanup"; flags.push("regenerable_artifact");
      } else if (targets.some(isProtectedRootTarget)) {
        modifiers.push({ reason: "protected root/home/system delete target", delta: 20 });
        flags.push("protected_target");
      }
    } else if (FIND_DELETE_RE.test(scan)) {
      const roots = findRootTargets(s);
      if (roots.length > 0 && roots.every(isRegenerableArtifactTarget)) {
        base = 45; action = "cleanup"; flags.push("regenerable_artifact");
      } else if (roots.some(isProtectedRootTarget)) {
        modifiers.push({ reason: "protected root/home/system delete target", delta: 20 });
        flags.push("protected_target");
      }
    }
  } else if (SPEND_CLI_RE.test(scan) || (!READ_PRINT_CMD_RE.test(s) && spendHitInText(s))) {
    const hit = SPEND_CLI_RE.test(scan) ? "purchase CLI" : spendHitInText(s);
    base = 75; action = "spend"; reversible = false; flags.push("spend");
    modifiers.push({ reason: "real-money spend: " + hit, delta: 0 });
  } else if (/\bgit\s+push\b[^&|;]*(--force\b|--force-with-lease\b|(^|\s)-f\b)|\bgit\s+reset\s+--hard\b|\bgit\s+clean\s+-\S*f/.test(scan)) {
    base = 70; action = "security"; reversible = false; flags.push("vcs_dangerous");
  } else if (/\bvercel\b[^&|;]*--prod|\bkubectl\s+apply\b|\bterraform\s+(apply|destroy)\b/.test(scan)) {
    base = 75; action = "deploy"; flags.push("deploy");
  } else if (/\b(npm|pnpm|yarn)\s+(i\b|install\b|add\b)|\bpip3?\s+install\b|\bpipx\s+install\b|\b(gem|cargo|go|brew|apt|apt-get|dnf|yum)\s+install\b/.test(scan)) {
    base = 30; action = "build"; flags.push("package");
  } else if (/(^|\s)printenv(\s|$)|(^|\s)env(\s+-[0i]*)?\s*$|\bcat\s[^&|;]*(\.env\b|id_rsa|\.pem\b|secret)/.test(s)) {
    base = 40; action = "security"; flags.push("secret_exposure");
  } else if (isDatabaseSegment(scan)) {
    const db = databaseActClassification(inlineSqlOf(seg));
    base = db.base_risk; action = db.derived_action_type; reversible = db.reversible_hint;
    for (const m of db.modifiers) modifiers.push(m);
    for (const f of db.flags) flags.push(f);
  } else if (/^\s*(cat|ls|head|tail|grep|rg|find|stat|pwd|whoami|echo|which|wc|diff|file)\b|^\s*git\s+(status|log|diff|show|branch|remote)\b/.test(s)) {
    base = 5; action = "review"; reversible = true;
  } else if (/^\s*(cp|mv|mkdir|touch|chmod|chown|ln|tee|write)\b|\bsed\s+-i|^\s*git\s+(add|commit|checkout|switch|restore|merge|pull|fetch)\b/.test(s)) {
    base = 35; action = "apply";
  }

  if (SENSITIVE_PATH_RE.test(s) && flags.indexOf("secret_exposure") === -1) {
    modifiers.push({ reason: "sensitive path referenced", delta: 15 });
    flags.push("sensitive_path");
  }

  if (isSudo) {
    if (base < 75) {
      base = 75;
      if (action === "other" || action === "review" || action === "apply") action = "deploy";
    }
    if (flags.indexOf("privilege") === -1) flags.push("privilege");
  }

  return { derived_action_type: action, base_risk: base, modifiers: modifiers, reversible_hint: reversible, flags: flags };
}

// evidence.ts:658-673. DEVIATION: the `script` argument is dropped — a Claude Code
// tool.call carries no script body, so classifyScriptExcerpt has no input.
function classifyShell(command) {
  if (isInertGitMessageCommand(command)) {
    return { derived_action_type: "apply", base_risk: 35, modifiers: [], reversible_hint: true, flags: ["git_message"] };
  }
  return classifyShellCommand(command);
}

// evidence.ts:675-738
function classifyShellCommand(command) {
  const skeleton = codeSkeleton(command);
  const rawScan = hasExecSink(skeleton);
  const pipeToInterp = /\b(curl|wget)\b[^\n]*\|\s*(sudo\s+)?(sh|bash|zsh|python[0-9]?|node(?:js)?)\b\s*(\S*)/i.exec(rawScan ? command : skeleton);
  if (pipeToInterp) {
    const interp = (pipeToInterp[3] || "").toLowerCase();
    const firstArg = pipeToInterp[4] || "";
    const inlineDataPipe =
      !/^(sh|bash|zsh)$/.test(interp) &&
      /^(-c|-e|-p|--eval|--print)$/.test(firstArg) &&
      !/\b(exec|eval)\s*\(/i.test(command);
    if (!inlineDataPipe) {
      return { derived_action_type: "security", base_risk: 70, modifiers: [], reversible_hint: false, flags: ["remote_exec"] };
    }
  }
  if (rawScan && INTERPRETER_DESTRUCTIVE_FULL_RE.test(command)) {
    return {
      derived_action_type: "security", base_risk: 80, modifiers: [],
      reversible_hint: false, flags: ["destructive", "interpreter_destructive"],
    };
  }
  const segments = command.split(/&&|\|\||;|\||[\n\r]/).map(function (p) { return p.trim(); }).filter(Boolean);
  const parts = segments.length ? segments : [command];
  const folded = parts.map(function (p) { return classifyShellSegment(p, rawScan); })
    .reduce(function (a, b) { return evidenceTotal(b) >= evidenceTotal(a) ? b : a; });
  const heredoc = databaseHeredocClassification(command);
  if (heredoc && evidenceTotal(heredoc) > evidenceTotal(folded)) return heredoc;
  return folded;
}

// evidence.ts:786-814
function classifySql(act) {
  const stmt = typeof act.statement === "string" ? act.statement : "";
  const s = stmt.trim().toLowerCase();
  const modifiers = [];
  const flags = [];
  let base = 35;
  let action = "apply";
  let reversible = null;

  if (/^select\b/.test(s)) {
    base = 10; action = "review"; reversible = true;
  } else if (/^insert\b/.test(s)) {
    base = 35; action = "apply";
  } else if (/^update\b/.test(s)) {
    base = 45; action = "apply";
  } else if (/^delete\b/.test(s)) {
    base = 60; action = "security"; reversible = false;
  } else if (/^(drop|truncate|alter|create)\b/.test(s)) {
    base = 75; action = "migrate"; reversible = false; flags.push("ddl");
  }

  if (/^(update|delete)\b/.test(s) && !/\bwhere\b/.test(s)) {
    modifiers.push({ reason: "UPDATE/DELETE without WHERE", delta: 20 });
    flags.push("whereless");
  }

  return { derived_action_type: action, base_risk: base, modifiers: modifiers, reversible_hint: reversible, flags: flags };
}

// evidence.ts:817-831
function classifyFile(act) {
  const f = act.file || {};
  const path = typeof f.path === "string" ? f.path : "";
  const modifiers = [];
  const flags = [];
  if (SENSITIVE_PATH_RE.test(path)) {
    modifiers.push({ reason: "sensitive path " + path, delta: 20 });
    flags.push("sensitive_path");
  }
  if (CI_CONFIG_RE.test(path)) {
    modifiers.push({ reason: "CI / deploy config write", delta: 15 });
    flags.push("ci_config");
  }
  return { derived_action_type: "apply", base_risk: 35, modifiers: modifiers, reversible_hint: null, flags: flags };
}

// evidence.ts:837-858. DEVIATION: 'http' and 'sql' kinds return null here — a
// Claude Code tool.call only ever produces a shell or a file act.
export function classifyAct(act) {
  if (!act || typeof act !== "object" || Array.isArray(act)) return null;
  if (act.kind === "shell") {
    return typeof act.command === "string" && act.command.trim() ? classifyShell(act.command) : null;
  }
  if (act.kind === "file") {
    return act.file && typeof act.file === "object" && typeof act.file.path === "string" && act.file.path
      ? classifyFile(act)
      : null;
  }
  return null;
}

// ════════════════════════════════════════════════════════════════════════════
// A2 — OFFLOCAL POLICY ENGINE
// Verbatim port of C:\Projects\offlocalai-mcp\src\policy.ts (lines 31-160).
// "The policy engine is the safety core. It reasons about capability ×
//  environment kind × provider × live-flag rather than about individual tool
//  names, so any new tool inherits safe defaults automatically." (policy.ts:9-13)
// ════════════════════════════════════════════════════════════════════════════

// policy.ts:31-97
export function defaultDecision(ctx) {
  const capability = ctx.capability;
  const environment = ctx.environment;
  const live = ctx.live;
  const provider = ctx.provider;
  const isProd = environment.isProduction;

  if (capability === "destructive_sql") {
    return {
      effect: "block",
      reason: "Destructive SQL (DROP/TRUNCATE/DELETE/ALTER and similar) is blocked everywhere by default.",
      source: "default:destructive_sql",
    };
  }
  if (capability === "delete") {
    return {
      effect: "block",
      reason: "Deleting resources is blocked everywhere by default.",
      source: "default:delete",
    };
  }
  if (capability === "purchase") {
    return {
      effect: "approval_required",
      reason: "Purchases spend real money and always require approval.",
      source: "default:purchase",
    };
  }
  if (capability === "read") {
    return { effect: "allow", reason: "Read-only action.", source: "default:read" };
  }
  if (live) {
    return {
      effect: "approval_required",
      reason: "Live/irreversible " + provider + " write requires approval by default.",
      source: "default:live_write",
    };
  }
  if (isProd) {
    const what =
      capability === "deploy"
        ? "Production deploys"
        : capability === "env_change"
          ? "Production environment-variable changes"
          : "Production writes";
    return {
      effect: "approval_required",
      reason: what + " require approval by default.",
      source: "default:production_write",
    };
  }
  return {
    effect: "allow",
    reason: "Non-production " + capability + " is allowed by default.",
    source: "default:nonprod_write",
  };
}

// policy.ts:99-107 — unset match fields are wildcards.
function ruleMatches(rule, ctx) {
  const m = rule.match || {};
  if (m.projectId && m.projectId !== ctx.project.id) return false;
  if (m.environmentId && m.environmentId !== ctx.environment.id) return false;
  if (m.environmentKind && m.environmentKind !== ctx.environment.kind) return false;
  if (m.provider && m.provider !== ctx.provider) return false;
  if (m.capability && m.capability !== ctx.capability) return false;
  return true;
}

// policy.ts:109-136 — highest priority wins, then the purchase clamp.
export function evaluatePolicy(rules, ctx) {
  const matching = (rules || [])
    .filter(function (r) { return ruleMatches(r, ctx); })
    .sort(function (a, b) { return b.priority - a.priority; });

  const resolved =
    matching.length > 0
      ? {
          effect: matching[0].effect,
          reason:
            matching[0].description ||
            ("Matched explicit policy rule " + matching[0].id + " (effect=" + matching[0].effect + ")."),
          source: "rule:" + matching[0].id,
        }
      : defaultDecision(ctx);

  // The invariant (policy.ts:125-133): a purchase can never resolve below
  // approval_required, even when an explicit allow rule matches.
  if (ctx.capability === "purchase" && resolved.effect === "allow") {
    return {
      effect: "approval_required",
      reason: "Purchases always require approval; the matching allow rule was clamped.",
      source: "clamp:purchase",
    };
  }

  return resolved;
}

// policy.ts:139-156
export function capabilityLabel(c) {
  if (c === "read") return "read";
  if (c === "write") return "write";
  if (c === "deploy") return "deploy";
  if (c === "env_change") return "environment-variable change";
  if (c === "delete") return "delete";
  if (c === "destructive_sql") return "destructive SQL";
  if (c === "purchase") return "purchase";
  return c;
}

// policy.ts:158-160
// WIRE-DARK[lab prototype moved verbatim from claude-mods-rnd; consumer is policy.ts in the prodguard plugin when it is promoted]
export function effectIsExecutable(effect) { return effect === "allow"; }

// ════════════════════════════════════════════════════════════════════════════
// A3 — OFFLOCAL → DASHCLAW BRIDGE
// Port of C:\Projects\offlocalai-mcp\src\dashclaw\guard.ts (lines 29-83).
// NOT ported: guardWithDashclaw / buildDashclawGuardPayload's HTTP half — this
// prototype is the local tier only. sqlFingerprint is dropped because it needs
// node:crypto, which a hooks module cannot import (archaeology §Limitations).
// ════════════════════════════════════════════════════════════════════════════

// guard.ts:29-39
export function actionType(ctx) {
  if (ctx.capability === "purchase") return "provider_purchase";
  if (ctx.provider === "stripe" && ctx.live && ctx.capability === "write") return "stripe_live_write";
  if (ctx.provider === "supabase" && ctx.capability === "destructive_sql") return "database_destructive_sql";
  if (ctx.provider === "supabase" && ctx.capability === "write") return "database_write";
  if (ctx.capability === "deploy") return "provider_deploy";
  if (ctx.capability === "env_change") return "provider_env_change";
  if (ctx.capability === "delete") return "provider_delete";
  if (ctx.capability === "write") return "provider_write";
  return "provider_read";
}

// guard.ts:41-51
export function riskScore(ctx) {
  if (ctx.capability === "purchase") return 95;
  if (ctx.capability === "destructive_sql" || ctx.capability === "delete") return 95;
  if (ctx.live === true) return 90;
  if (ctx.capability === "deploy" && ctx.environment.isProduction) return 85;
  if (ctx.capability === "env_change" && ctx.environment.isProduction) return 85;
  if (ctx.capability === "write" && ctx.environment.isProduction) return 80;
  if (ctx.capability === "deploy" || ctx.capability === "env_change") return 65;
  if (ctx.capability === "write") return 60;
  return 20;
}

// guard.ts:53-59
export function isReversible(ctx) {
  if (ctx.capability === "purchase") return false;
  if (ctx.capability === "destructive_sql" || ctx.capability === "delete") return false;
  if (ctx.live === true) return false;
  if (ctx.environment.isProduction && (ctx.capability === "deploy" || ctx.capability === "env_change")) return false;
  return true;
}

// guard.ts:61-74 — VERBATIM. Nothing leaves this machine without passing through
// it: not the audit line, not the AbovePrompt band, not the approval question.
export function sanitizeDashclawText(value) {
  return String(value)
    .replace(
      /\b(?=[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_?KEY|ACCESS_TOKEN|DATABASE_URL))[A-Z0-9_]+\s*=\s*[^\s,;}]+/gi,
      "[redacted]",
    )
    .replace(/\b(?:sk|pk)_(?:live|test)_[A-Za-z0-9_]+/g, "[redacted]")
    .replace(/\bwhsec_[A-Za-z0-9]+/g, "[redacted]")
    .replace(/\b(?:postgres|postgresql|mysql|mongodb|redis):\/\/[^\s,;}]+/gi, "[redacted]")
    .replace(
      /\b(?=[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_?KEY|ACCESS_TOKEN|DATABASE_URL))[A-Z0-9_]+\b/gi,
      "[redacted]",
    );
}

// guard.ts:80-83
export function systemsTouched(ctx) {
  const resource = ctx.resourceLabel
    ? ctx.provider + ":" + sanitizeDashclawText(ctx.resourceLabel)
    : ctx.provider;
  return [resource, "project:" + ctx.project.slug, "environment:" + ctx.environment.name];
}

// ════════════════════════════════════════════════════════════════════════════
// A4 — THE SEAM
// New code. DashClaw reads shell text and has no idea which environment it is
// aimed at; offlocal knows the environment and cannot read a shell command
// (grepping offlocalai-mcp/src for `--prod`, `wrangler`, `git push` returns zero
// matches). This maps one vocabulary onto the other.
//
// Three carve-outs, each with its evidence:
//  * `regenerable_artifact` → read. `rm -rf node_modules` must not gate, or the
//    operator turns the guard off (evidence.ts:50-52, the F5 alarm-fatigue fix).
//    Deleting a disposable local artifact touches no environment.
//  * an unflagged local act (`ls`, `echo`, `npm test`, an ordinary file edit)
//    → read. offlocal's `read` means "safe with respect to this environment",
//    and a local edit is exactly that. It still gets a decision and an audit line.
//  * `secret_exposure` → env_change is the closest of offlocal's seven
//    capabilities to "reads this environment's secrets". It overstates (a read
//    is not a change). Named in the README's limitations rather than hidden.
// ════════════════════════════════════════════════════════════════════════════

export function capabilityOf(cls) {
  const flags = cls.flags || [];
  const has = function (f) { return flags.indexOf(f) !== -1; };
  const action = cls.derived_action_type;

  if (has("spend")) return "purchase";

  if (has("database")) {
    if (has("ddl") || has("whereless") || action === "migrate" || action === "security") return "destructive_sql";
    if (action === "review") return "read";
    return "write";
  }

  // F5 carve-out — checked BEFORE `destructive`, which the cleanup branch also sets.
  if (has("regenerable_artifact")) return "read";

  if (has("destructive") || has("device_write") || has("protected_target")) return "delete";
  if (has("vcs_dangerous")) return "delete";          // force-push / reset --hard destroys shared remote state
  if (has("remote_exec")) return "deploy";            // executing fetched code is an unreviewed deployment
  if (has("deploy")) return "deploy";
  if (has("ci_config")) return "deploy";              // a write to .github/workflows changes what deploys
  if (has("secret_exposure")) return "env_change";
  if (has("sensitive_path") && action === "apply") return "env_change";  // writing .env IS an env change
  if (has("privilege")) return "deploy";

  return "read";
}

// Which provider a command is aimed at. Unknown → the provider the environment
// is mapped to, so a policy rule scoped to that provider still matches.
const PROVIDER_CLI_RE = [
  ["vercel", /\bvercel\b/i],
  ["railway", /\brailway\b/i],
  ["render", /\brender\b/i],
  ["supabase", /\bsupabase\b|\bpsql\b|\bpg_restore\b|\bprisma\b|\bdrizzle-kit\b/i],
  ["neon", /\bneonctl\b|\bneon\b/i],
  ["stripe", /\bstripe\b/i],
  ["github", /\bgit\b|\bgh\b/i],
  ["namecheap", /\bnamecheap\b/i],
  ["cloudflare_r2", /\bwrangler\b/i],
  ["sentry", /\bsentry-cli\b/i],
  ["resend", /\bresend\b/i],
  ["twilio", /\btwilio\b/i],
  ["clerk", /\bclerk\b/i],
  ["upstash", /\bupstash\b/i],
  ["posthog", /\bposthog\b/i],
];

export function providerOf(text, fallback) {
  const skeleton = codeSkeleton(String(text || ""));
  for (const pair of PROVIDER_CLI_RE) {
    if (pair[1].test(skeleton)) return pair[0];
  }
  return fallback;
}

// Is this act "live" in offlocal's sense — irreversible independent of the
// environment kind? A Stripe live-mode mapping, or a classification the evidence
// says cannot be undone.
export function isLive(cls, provider, mappingResource) {
  if (provider === "stripe" && mappingResource && mappingResource.mode === "live") return true;
  return cls.reversible_hint === false && (cls.flags || []).indexOf("spend") !== -1;
}

// ════════════════════════════════════════════════════════════════════════════
// A5 — REGISTRY RESOLUTION AND THE ONE ENTRY POINT
// Reads a plain object in offlocalai-mcp's .offlocal/state.json shape
// (src/types.ts StoreData). No file I/O here — the caller hands over parsed JSON.
// ════════════════════════════════════════════════════════════════════════════

// Port of the intent of offlocalai-mcp/src/resolve.ts resolveProject (11-30) and
// resolveEnvironment (32-54).
// DEVIATION, deliberate and load-bearing: resolveEnvironment THROWS when a project
// has more than one environment and the caller named none ("specify which"). An
// MCP tool can throw, because every call names its environment. A hook has no such
// argument, and a guard that throws is a guard that is off. So this resolver fails
// CLOSED: with no selection it takes the production environment. Being wrong here
// costs an approval prompt; being wrong the other way costs production.
export function resolveContextFrom(state) {
  const projects = state.projects || [];
  const environments = state.environments || [];
  let project = null;
  if (state.selectedProjectId) {
    project = projects.find(function (p) { return p.id === state.selectedProjectId; }) || null;
  }
  if (!project) project = projects[0] || null;
  if (!project) return null;

  const envs = environments.filter(function (e) { return e.projectId === project.id; });
  if (!envs.length) return null;
  let environment = null;
  if (state.selectedEnvironmentId) {
    environment = envs.find(function (e) { return e.id === state.selectedEnvironmentId; }) || null;
  }
  if (!environment) environment = envs.find(function (e) { return e.isProduction === true; }) || null;
  if (!environment) environment = envs[0];

  const mappings = (state.mappings || []).filter(function (m) { return m.environmentId === environment.id; });
  const mapping = mappings[0] || null;

  return {
    project: project,
    environment: environment,
    environments: envs,
    mapping: mapping,
    mappedProvider: mapping ? mapping.provider : "github",
    resourceLabel: mapping ? resourceLabelOf(mapping.resource) : undefined,
    rules: state.policyRules || [],
    fellBackToProduction: !state.selectedEnvironmentId && environment.isProduction && envs.length > 1,
  };
}

function resourceLabelOf(resource) {
  if (!resource || typeof resource !== "object") return undefined;
  if (resource.provider === "vercel") return resource.projectName || resource.projectId;
  if (resource.provider === "github") return resource.owner + "/" + resource.repo;
  if (resource.provider === "supabase") return resource.projectRef;
  if (resource.provider === "stripe") return resource.mode;
  return resource.projectId || resource.serviceId || resource.databaseId || undefined;
}

// Build the act a tool call represents. `tool` + `input` in, ActInput out.
export function actOfToolCall(tool, input) {
  if (tool === "Bash") {
    const command = typeof input.command === "string" ? input.command : "";
    return command.trim() ? { kind: "shell", command: command } : null;
  }
  if (tool === "Write" || tool === "Edit" || tool === "NotebookEdit") {
    const path = typeof input.file_path === "string"
      ? input.file_path
      : (typeof input.notebook_path === "string" ? input.notebook_path : "");
    return path ? { kind: "file", file: { path: path } } : null;
  }
  return null;
}

// THE ENTRY POINT. Everything above folds into this. Pure: same arguments in,
// same verdict out, no clock, no file, no network, no `$`.
export function decide(ctx0, tool, input) {
  const act = actOfToolCall(tool, input);
  if (!act) return null;
  const cls = classifyAct(act);
  if (!cls) return null;

  const subject = act.kind === "shell" ? act.command : act.file.path;
  const capability = capabilityOf(cls);
  const provider = act.kind === "shell"
    ? providerOf(act.command, ctx0.mappedProvider)
    : ctx0.mappedProvider;
  const live = isLive(cls, provider, ctx0.mapping ? ctx0.mapping.resource : null);

  const actionCtx = {
    project: ctx0.project,
    environment: ctx0.environment,
    provider: provider,
    capability: capability,
    tool: tool,
    summary: capabilityLabel(capability) + " via " + tool + ": " + sanitizeDashclawText(subject),
    live: live,
    resourceLabel: ctx0.resourceLabel,
  };

  const policy = evaluatePolicy(ctx0.rules, actionCtx);

  return {
    effect: policy.effect,                       // allow | block | approval_required
    reason: policy.reason,
    source: policy.source,
    capability: capability,
    provider: provider,
    live: live,
    evidence: {
      derived_action_type: cls.derived_action_type,
      base_risk: cls.base_risk,
      evidence_total: evidenceTotal(cls),
      modifiers: cls.modifiers,
      flags: cls.flags,
      reversible_hint: cls.reversible_hint,
    },
    // DashClaw wire vocabulary (app/lib/validate.js:289 GUARD_INPUT_SCHEMA).
    action_type: actionType(actionCtx),
    risk_score: Math.max(riskScore(actionCtx), evidenceTotal(cls)),  // risk.ts: a term may raise, never lower
    reversible: isReversible(actionCtx) && cls.reversible_hint !== false,
    systems_touched: systemsTouched(actionCtx),
    subject: sanitizeDashclawText(subject),
  };
}

// A harmless demonstration of DashClaw containment (app/lib/guard/containment.ts):
// instead of refusing a scoped act, redirect it. Here the redirect is an echo, so
// the prototype can show the mechanism without staging a git worktree.
// Shell metacharacters in the original are neutralised so the echo cannot become
// a second command, and the text is sanitized so a secret never reaches the shell
// history.
export function containedCommand(original) {
  const safe = sanitizeDashclawText(String(original))
    .replace(/[\\"`$]/g, "")
    .replace(/[\r\n]+/g, " ");
  return 'echo "[contained by prodguard] ' + safe + '"';
}
