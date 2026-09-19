---
name: parallel-agents-inbox
description: The protocol for a repo another agent shares, and for the agent-comms inbox: claim before touching, scope-lock, pull before read, push after write, the commit format, the inbox cap.
context:
  triggers:
    keywords: [inbox, agent-comms, shared repo, other agent, another agent, teammate, claim, scope-lock, parallel agents, team protocol]
    paths: ["~/clawd/agent-comms/**"]
  priority: 60
  stale_after: 180d
---
# Parallel agents and the inbox (loaded on demand)

Applies when another agent shares this repo or `~\clawd\agent-comms\inbox\` holds a file addressed to you. Check the inbox at the start of any session touching a shared repo. Claim a task before touching it (`[IN PROGRESS] - Claimed by <Agent>`). Arm `scope-lock <dir>` in shared repos. Pull before reading/editing, push after writing; commit format `AgentName: [TYPE] brief description`. Max 3 active messages per inbox. The full protocol: `~/clawd/agent-comms/TEAM_PROTOCOL.md`.
