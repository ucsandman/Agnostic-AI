// shadow.mjs — the classic-vs-Mod comparison record. Pure.
//
// One row per decision, written by whichever side decided (classic writes via
// ~/.claude/hooks/lib/mods-mode.cjs recordShadow; the Mod writes via index.tsx). Rows join on
// (session, subsystem, action key). `report()` answers the Phase-19 questions from a row set.

export function row(fields) {
  return {
    ts: fields.ts || new Date().toISOString(),
    session: fields.session || null,
    side: fields.side,                       // "classic" | "mod"
    subsystem: fields.subsystem,             // "routing" | "secretRedaction" | "readCache" | "subagentAccounting"
    action: fields.action,                   // what was decided on ("Agent haiku-scout", "Bash …", "context 82%")
    key: fields.key || null,                 // join key (signature / tool_use_id / path)
    mode: fields.mode || null,               // effective mode when the row was written
    decision: fields.decision,               // "allow" | "deny" | "rewrite" | "redact" | "serve" | "nudge" | "none"
    requestedValue: fields.requestedValue === undefined ? null : fields.requestedValue,
    resolvedValue: fields.resolvedValue === undefined ? null : fields.resolvedValue,
    reasonCodes: fields.reasonCodes || [],
    wouldRewrite: !!fields.wouldRewrite,
    enforced: !!fields.enforced,             // did this side actually enforce
    latencyMs: fields.latencyMs === undefined ? null : fields.latencyMs,
    retryCount: fields.retryCount === undefined ? null : fields.retryCount,
    actualOutcome: fields.actualOutcome === undefined ? null : fields.actualOutcome,
    note: fields.note || null,
  };
}

/** Pair classic and mod rows by (session, subsystem, key) and grade agreement. */
export function pair(rows) {
  const by = {};
  for (const r of rows) {
    const k = [r.session, r.subsystem, r.key].join("|");
    (by[k] = by[k] || { classic: [], mod: [] })[r.side === "classic" ? "classic" : "mod"].push(r);
  }
  const out = [];
  for (const k of Object.keys(by)) {
    const c = by[k].classic[0] || null, m = by[k].mod[0] || null;
    const agreement = c && m ? (normalize(c.decision) === normalize(m.decision) ? "agree" : "disagree") : c ? "classic-only" : "mod-only";
    out.push({ key: k, subsystem: (c || m).subsystem, classic: c, mod: m, agreement,
      classicDecision: c ? c.decision : null, modDecision: m ? m.decision : null,
      modWouldRewrite: m ? m.wouldRewrite : null, reasonCodes: m ? m.reasonCodes : c ? c.reasonCodes : [],
      latencyMs: { classic: c ? c.latencyMs : null, mod: m ? m.latencyMs : null } });
  }
  return out;
}

// A classic "deny" and a Mod "rewrite" disagree in mechanism but agree on the policy violation.
function normalize(d) { return d === "rewrite" ? "deny" : d; }

export function report(rows) {
  const pairs = pair(rows);
  const bySub = {};
  for (const p of pairs) {
    const s = bySub[p.subsystem] = bySub[p.subsystem] || { pairs: 0, agree: 0, disagree: 0, classicOnly: 0, modOnly: 0, modRewrites: 0, classicDenies: 0, modDenies: 0, disagreements: [] };
    s.pairs++;
    if (p.agreement === "agree") s.agree++;
    else if (p.agreement === "disagree") { s.disagree++; s.disagreements.push({ key: p.key, classic: p.classicDecision, mod: p.modDecision, reasons: p.reasonCodes }); }
    else if (p.agreement === "classic-only") s.classicOnly++;
    else s.modOnly++;
    if (p.mod && p.mod.decision === "rewrite") s.modRewrites++;
    if (p.classic && p.classic.decision === "deny") s.classicDenies++;
    if (p.mod && p.mod.decision === "deny") s.modDenies++;
  }
  return { rows: rows.length, pairs: pairs.length, bySubsystem: bySub };
}
