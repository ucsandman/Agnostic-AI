# Delegation in Codex (delegate-first)

The main loop runs the expensive model and is a **planner, not a typist**: it
reads enough to write a brief, decides, reviews, and answers. Implementation,
exploration and long-output jobs go to a child on a cheaper model through the
custom agents listed above (`spawn_agent` with `agent_type: "<name>"`; the agent
file fixes the model and effort, so never pass `model`). Codex's own runtime
note says "do not spawn sub-agents unless AGENTS.md explicitly asks": this
section is that explicit ask.

Pick the rung by complexity, the mid tier first: a brief that fits in one
paragraph with named files and a verify command is mid-tier work; if you cannot
name the files yet, send the scout tier to find them; the top tier only for a
job that spans many files, needs a root-cause hunt, touches auth, billing or
migrations, or after a mid-tier attempt failed. Give a child a clean context
(`fork_turns: "none"`), a precise brief (files, acceptance criteria, verify
command) and collect with ONE `wait_agent` call with `timeout_ms` of 600000 or
more: every `wait_agent` return is a full main-loop turn over the whole
context, so three short polls cost more than the child's entire job. A spawn is
not free either (the child re-reads this file and the tool catalog), so batch
related small edits into one brief; independent slices run in parallel.

Reads, tests, lint, git and installs are always yours to run directly. A fix-up
of a few lines stays in the main loop; a feature goes to a child.
