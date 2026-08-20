"""
agent/governance/harvester.py — Bidirectional Cross-Agent Lesson Harvester
Scans transcripts and history logs from Claude Code, Cursor, and Codex on the machine to harvest corrections into the harness SSOT.
"""

import json
from pathlib import Path
from agent.governance.learn import learner


class CrossAgentHarvester:
    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root

    def scan_and_harvest(self) -> int:
        """Scan local logs for agent corrections."""
        harvested_count = 0
        home = Path.home()
        log_paths = [
            home / ".gemini" / "antigravity-cli" / "brain",
            self.workspace_root / "storage" / "corrections.jsonl",
        ]

        for p in log_paths:
            if p.is_file() and p.name == "corrections.jsonl":
                try:
                    lines = p.read_text(encoding="utf-8").splitlines()
                    for line in lines:
                        if line.strip():
                            data = json.loads(line)
                            txt = data.get("text") or data.get("correction")
                            if txt:
                                ok, _ = learner.record_lesson(txt, category="cross_agent_harvest")
                                if ok:
                                    harvested_count += 1
                except (
                    OSError,
                    ValueError,
                ):  # skip one unreadable/corrupt peer log, keep harvesting
                    pass

        return harvested_count


harvester = CrossAgentHarvester(Path("."))
