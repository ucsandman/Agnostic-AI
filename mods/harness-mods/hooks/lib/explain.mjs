// explain.mjs — one reusable way to tell the model what a Mod changed. Pure.
//
// Why: the 2026-09-16 dogfood (DOGFOOD.md findings 2) showed the model reasoning from false beliefs
// after silent rewrites: it "requested opus" when it actually got haiku, and reported a command as
// "blocked" when it had been contained. Whenever a Mod materially changes what the model asked for,
// the result carries one concise hidden `context[]` line saying WHAT changed, WHY, and WHAT ACTUALLY
// HAPPENED. It is information, never instruction (R20): enforcement lives in the hook, not the note.

export const KINDS = {
  "model-rewrite": "subagent model rewritten",
  "command-containment": "command contained (dry-run)",
  "tool-substitution": "tool substituted",
  "result-replacement": "tool result replaced",
  "cache-serve": "result served from cache",
  "arg-normalization": "tool arguments normalized",
  "redaction": "secret redacted from result",
};

const MAX = 320;

function clip(s, n) {
  s = String(s == null ? "" : s).replace(/\s+/g, " ").trim();
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

/**
 * Build the one-line explanation.
 *   kind    one of KINDS (unknown kinds are kept verbatim)
 *   what    the change, in the model's terms ("model opus -> haiku")
 *   why     the reason codes or a short reason ("upward edge not in the capability graph")
 *   actual  what really happened ("the subagent ran on haiku and its answer below is real")
 *   by      the Mod that did it (default "harness-mods")
 */
export function explain({ kind, what, why, actual, by = "harness-mods" }) {
  const head = KINDS[kind] || String(kind || "changed");
  const parts = ["[" + by + "] " + head + ": " + clip(what, 120)];
  if (why) parts.push("why: " + clip(Array.isArray(why) ? why.join(", ") : why, 110));
  if (actual) parts.push("actual: " + clip(actual, 120));
  return clip(parts.join(" · "), MAX);
}

/** Attach an explanation to a tool.call / agent.spawn style result without clobbering existing context. */
export function withContext(result, note) {
  if (!note) return result;
  const r = result && typeof result === "object" ? result : {};
  const prev = Array.isArray(r.context) ? r.context : [];
  return { ...r, context: [...prev, note] };
}

/** The explanation for a routing decision (used by routing.mjs consumers). */
export function explainRoute(route) {
  if (!route || route.action !== "rewrite") return null;
  return explain({
    kind: "model-rewrite",
    what: (route.type || "agent") + " model " + (route.requested === undefined ? "(inherit)" : route.requested) + " -> " + route.model,
    why: route.reasons,
    actual: "the subagent ran on " + route.model + (route.resolvedModel ? " (" + route.resolvedModel + ")" : "") + "; its result is real",
  });
}
