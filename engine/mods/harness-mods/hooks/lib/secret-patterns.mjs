// secret-patterns.mjs — GENERATED COPY of ~/.claude/hooks/lib/secret-patterns.cjs (a hooks module may
// import only its own files). tests/redact.test.mjs fails when the two drift; regenerate with:
//   node engine/mods/harness-mods/tests/gen-patterns.cjs
export const PATTERNS = [
  ["anthropic", /\bsk-ant-[A-Za-z0-9_-]{24,}/g],
  ["openai", /\bsk-(?:proj-)?[A-Za-z0-9]{32,}/g],
  ["stripe-live", /\b(?:sk|rk)_live_[A-Za-z0-9]{20,}/g],
  ["github-pat", /\bgh[pousr]_[A-Za-z0-9]{30,}/g],
  ["aws-key-id", /\bAKIA[0-9A-Z]{16}\b/g],
  ["slack-token", /\bxox[abprs]-[A-Za-z0-9-]{20,}/g],
  ["google-api", /\bAIza[0-9A-Za-z_-]{35}\b/g],
  ["private-key", /-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----/g],
  ["jwt", /\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}/g],
  ["neon-url", /\bpostgres(?:ql)?:\/\/[^\s:@/]+:[^\s:@/]{8,}@/g],
];
export const PLACEHOLDER = /(?:XXXX|xxxx|\.\.\.|<[^>]+>|\bYOUR_|\bEXAMPLE\b|\bPLACEHOLDER\b|\bREDACTED\b|A{12,}|0{12,}|1234567890)/;
export default { PATTERNS, PLACEHOLDER };
