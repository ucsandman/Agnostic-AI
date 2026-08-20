"""
agent/governance/learn.py — Learning Loop & Self-Distillation Engine (/learn, /distill)
Connects the Agnostic Coding Agent directly into the harness candidates.jsonl and 4-tier distillation ladder.
"""

import json
import os
import time
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional, Tuple


def hash_fingerprint(text: str) -> str:
    norm = "".join(ch.lower() for ch in text if ch.isalnum() or ch.isspace()).strip()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


class Learner:
    def __init__(self, workspace_root: Optional[str] = None):
        self.workspace_root = Path(workspace_root or ".").resolve()
        self.storage_dir = self.workspace_root / "storage"
        self.candidates_file = self.storage_dir / "candidates.jsonl"
        self.corrections_file = self.storage_dir / "corrections.jsonl"

    def record_lesson(
        self,
        lesson_text: str,
        category: str = "manual_correction",
        repo_context: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Record an explicit or implicit lesson directly into the harness candidate ladder."""
        if not lesson_text.strip():
            return False, "Lesson cannot be empty."

        self.storage_dir.mkdir(parents=True, exist_ok=True)
        fp = hash_fingerprint(lesson_text)
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        entry = {
            "id": fp,
            "text": lesson_text.strip(),
            "tier": 0,  # Tier 0: Observation
            "sightings": 1,
            "category": category,
            "first_seen": timestamp,
            "last_seen": timestamp,
            "repo": repo_context or self.workspace_root.name,
        }

        # Check existing candidates
        existing_entries: Dict[str, Dict[str, Any]] = {}
        if self.candidates_file.exists():
            for line in self.candidates_file.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        item = json.loads(line)
                        existing_entries[item.get("id")] = item
                    except (
                        json.JSONDecodeError,
                        AttributeError,
                    ):  # drop one corrupt candidate line
                        pass

        if fp in existing_entries:
            item = existing_entries[fp]
            item["sightings"] = item.get("sightings", 1) + 1
            item["last_seen"] = timestamp
            # Auto-promote to Tier 1 Fact if seen 2+ times
            if item["sightings"] >= 2 and item.get("tier", 0) == 0:
                item["tier"] = 1
            existing_entries[fp] = item
            msg = f"Reinforced existing lesson (Sightings: {item['sightings']}, Tier: {item['tier']}): {lesson_text[:80]}"
        else:
            existing_entries[fp] = entry
            msg = f"Logged new Tier 0 lesson: {lesson_text[:80]}"

        # Write back via a sibling temp file: a crash mid-write must never
        # truncate the existing ladder. os.replace is atomic on both platforms.
        lines = [json.dumps(item) for item in existing_entries.values()]
        tmp_file = self.candidates_file.with_name(self.candidates_file.name + ".tmp")
        tmp_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(str(tmp_file), str(self.candidates_file))
        return True, msg


learner = Learner()
