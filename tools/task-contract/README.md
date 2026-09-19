# task-contract

Validates a `TASK_CONTRACT.md`, and with `--run` discharges it.

```bash
node task-contract.mjs path/to/TASK_CONTRACT.md          # shape only
node task-contract.mjs path/to/TASK_CONTRACT.md --run    # also run every test-tier check
node task-contract.mjs path/to/TASK_CONTRACT.md --json   # machine-readable
```

Exit codes are the verdict, so CI can branch on them:

| code | verdict | means |
|---|---|---|
| 0 | `pass` | every test-tier check ran and passed, nothing unresolved |
| 1 | `fail` | a test-tier check failed, **or could not be run** |
| 2 | `insufficient_spec` | an obligation nothing can settle — routes to a human |
| 3 | — | the contract itself is malformed |

No dependencies. Node 18+.

## Why it works this way

A verifier catches only what the specification named. When an obligation was
never written down and no convention determines it, the comparison is vacuous —
any behavior is "consistent with the spec." The verifier is not failing to
reason; it is reasoning correctly over an input that does not contain the
answer, and it reports about the same confidence it uses when it is right.

Measured on a purpose-built corpus: a confident false pass on 100% of runs
[94–100] with the edge omitted, converting to a 98% [91–100] catch once the same
edge is written into the spec. The blind spot reproduces across model tiers, and
a roughly 30× cost increase recovers none of it. Re-reading harder cannot
recover information the artifact never carried.

So this tool does not try to be clever. It reads a contract someone wrote at
spec time and holds two rules that are easy to argue away:

**A check that could not be RUN fails.** It tells you exactly as much about the
code as a check that ran and failed. Calling it a skip is how a pipeline
manufactures a green.

**`insufficient_spec` is not a softer failure.** It means the artifact does not
contain the answer, so no amount of re-reading produces one. It goes to a
person. A caller that coerces it to `pass` has reintroduced the entire failure
the contract exists to prevent.

That second verdict fires from the `non_inferable` field in the contract —
written ahead of time, by someone reading the requirement — never from asking a
model whether it feels unsure. Self-assessed uncertainty fires on whatever
ambiguity the model happens to notice and essentially never on the real blind
spot, because a model cannot feel a blind spot. A tag in the artifact routes
correctly even when the reader would have named the wrong reason, which is the
only kind of mechanism that helps here.

Tag sparingly. A false `non_inferable` makes a capable reviewer defer on a
genuine, spec-determined bug about a third of the time, so precision in the tag
is load-bearing and a long list is worse than a short one.

## Contract shape

Canonical schema and a worked example live in the `spec-probe` skill
(`skills/spec-probe/references/contract-schema.md`), which is also what writes
one. The short version:

```yaml
contract_version: 1
subject: "what this contract governs"

must_haves:
  - id: MH-01
    requirement: "the obligation, stated so a stranger could test it"
    shape: [numeric-range | collection | text | stateful | io]
    edge_category: boundaries | adjacency | empty | encoding |
                   ordering | precision | idempotency | concurrency | none
    disposition: specify | backstop | dismiss | defer
    tier: test | judgment
    non_inferable: false
    check: "<runnable command — required when tier: test>"

prohibitions:
  - id: PR-01
    must_not: "what this feature must never silently become"
    tier: test
    repo_check: "<repo-wide rule: grep, AST, lint, a walking test>"
```

A prohibition owes a repo-wide rule rather than a reviewer's attention.
Prohibitions are not hard because they are negative — catch rate is identical
under "must" and "must NOT" framing. They are hard because they quantify over
the whole repository while any one review samples it.

## The YAML reader is not a YAML parser

`parse.mjs` accepts exactly the subset above and throws on anything else —
nested maps included. Silently half-parsing a contract that drifted from the
schema is the same class of failure the contract exists to prevent: a green that
means "I did not look." Its own tests caught that on the first run, when nested
maps were being flattened instead of rejected.

## Tests

```bash
cd tools/task-contract && node --test
```

16 tests. Most of them are deliberate breakage — a test-tier item with no check,
a backstop not tagged `non_inferable`, a prohibition with no repo-wide rule, an
open question blocking an id that does not exist. Each was observed failing
before the rule that catches it was written, because a check never seen failing
has been run, not verified.

## What it does not do

It does not replace held-out tests. On genuine blind spots — edges the probe
fails to name *and* that the spec's other obligations do not imply — a verifier
still false-passes most of the time even once the edge is surfaced. The oracle
stays.
