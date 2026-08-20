"""
agent/governance/memory.py — Persistent Auto-Memory Store
Workspace-local memories under .agnostic/memory/: one markdown file per memory with
frontmatter, plus a MEMORY.md index that is injected into the harness system prompt.
"""

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

INDEX_NAME = "MEMORY.md"
MEMORY_TYPES = ("user", "feedback", "project", "reference")
MAX_BODY_BYTES = 8192
MAX_MEMORIES = 200

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")


@dataclass
class Memory:
    slug: str
    name: str
    description: str
    type: str
    created: str
    body: str

    def index_line(self) -> str:
        return f"- [{self.name}]({self.slug}.md) — {self.description}"

    def to_markdown(self) -> str:
        return (
            "---\n"
            f"name: {self.name}\n"
            f"description: {self.description}\n"
            f"type: {self.type}\n"
            f"created: {self.created}\n"
            "---\n\n"
            f"{self.body.rstrip()}\n"
        )


def _one_line(text: str) -> str:
    return " ".join(str(text or "").split())


def _slugify(name: str) -> str:
    return _SLUG_STRIP_RE.sub("-", name.strip().lower()).strip("-")


def _tokens(text: str) -> set:
    return set(_TOKEN_RE.findall(text.lower()))


class MemoryStore:
    """Durable per-workspace memories. Stdlib only — no embeddings, no index server."""

    def __init__(self, workspace_root: Optional[str] = None):
        self.workspace_root = Path(workspace_root or ".").resolve()
        self.memory_dir = self.workspace_root / ".agnostic" / "memory"
        self.index_file = self.memory_dir / INDEX_NAME

    # --- naming & parsing -------------------------------------------------

    @staticmethod
    def slug_for(name: str) -> str:
        """Slug for a memory name, or ValueError when the name is unusable as a filename."""
        raw = str(name or "").strip()
        if not raw:
            raise ValueError("Memory name must not be empty.")
        if any(sep in raw for sep in ("/", "\\", os.sep)) or ".." in raw:
            raise ValueError(
                f"Memory name {raw!r} must not contain path separators or '..' — "
                "memories are stored as flat files under .agnostic/memory/."
            )
        if not raw.strip("."):
            raise ValueError(f"Memory name {raw!r} must contain more than dots.")
        slug = _slugify(raw)
        if not slug:
            raise ValueError(f"Memory name {raw!r} has no letters or digits to name a file with.")
        return slug

    @staticmethod
    def _parse(path: Path) -> Optional[Memory]:
        """Parse one memory file. Returns None when it is not a valid memory."""
        text = path.read_text(encoding="utf-8", errors="replace")
        if not text.startswith("---"):
            return None
        parts = text.split("---", 2)
        if len(parts) < 3:
            return None
        fields = {}
        for line in parts[1].strip().splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                fields[key.strip().lower()] = value.strip()
        if not fields.get("name"):
            return None
        return Memory(
            slug=path.stem,
            name=fields["name"],
            description=fields.get("description", ""),
            type=fields.get("type", "project"),
            created=fields.get("created", ""),
            body=parts[2].strip(),
        )

    def _scan(self) -> Tuple[List[Memory], List[str]]:
        """All parsable memories (oldest first) plus one issue string per bad file."""
        memories: List[Memory] = []
        issues: List[str] = []
        if not self.memory_dir.is_dir():
            return memories, issues
        for path in sorted(self.memory_dir.glob("*.md")):
            if path.name == INDEX_NAME:
                continue
            try:
                parsed = self._parse(path)
            except OSError as e:
                issues.append(f"- [!] {path.name} could not be read: {e}")
                continue
            if parsed is None:
                issues.append(f"- [!] {path.name} is not a valid memory file (skipped)")
                continue
            memories.append(parsed)
        memories.sort(key=lambda m: (m.created, m.slug))
        return memories, issues

    # --- CRUD -------------------------------------------------------------

    def list(self) -> List[Memory]:
        """Every stored memory, oldest first."""
        return self._scan()[0]

    def get(self, name: str) -> Optional[Memory]:
        path = self.memory_dir / f"{self.slug_for(name)}.md"
        if not path.is_file():
            return None
        try:
            return self._parse(path)
        except OSError:  # unreadable memory behaves like a missing one
            return None

    def save(self, name: str, description: str, body: str, type: str = "project") -> Memory:
        """Create or update a memory, then rewrite the MEMORY.md index."""
        slug = self.slug_for(name)
        if type not in MEMORY_TYPES:
            raise ValueError(
                f"Memory type must be one of {', '.join(MEMORY_TYPES)} — got {type!r}."
            )
        body = str(body or "").strip()
        if not body:
            raise ValueError("Memory body must not be empty.")
        if len(body.encode("utf-8")) > MAX_BODY_BYTES:
            raise ValueError(
                f"Memory body is too large ({len(body.encode('utf-8'))} bytes, "
                f"max {MAX_BODY_BYTES}). Store the durable fact, not the transcript."
            )

        existing = self.get(name)
        if existing is None and len(self.list()) >= MAX_MEMORIES:
            raise ValueError(
                f"Memory store is full ({MAX_MEMORIES} memories). "
                "Delete an obsolete memory before saving a new one."
            )

        memory = Memory(
            slug=slug,
            name=_one_line(name),
            description=_one_line(description),
            type=type,
            created=existing.created
            if existing and existing.created
            else datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            body=body,
        )
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self._write_atomic(self.memory_dir / f"{slug}.md", memory.to_markdown())
        self._write_index()
        return memory

    def delete(self, name: str) -> bool:
        path = self.memory_dir / f"{self.slug_for(name)}.md"
        if not path.is_file():
            return False
        path.unlink()
        self._write_index()
        return True

    # --- prompt injection & recall ---------------------------------------

    def index_text(self, max_chars: int = 4000) -> str:
        """The index as prompt text, oldest lines dropped first. Never raises."""
        try:
            memories, issues = self._scan()
            lines = [m.index_line() for m in memories] + issues
            while lines and len("\n".join(lines)) > max_chars:
                lines.pop(0)
            return "\n".join(lines)
        except Exception:  # a broken store must never break the system prompt
            return ""

    def recall(self, query: str, k: int = 5) -> List[Memory]:
        """Top-k memories by case-insensitive token overlap. Name/description count double."""
        wanted = _tokens(str(query or ""))
        if not wanted:
            return []
        scored = []
        for memory in self.list():
            head = _tokens(f"{memory.name} {memory.description}")
            body = _tokens(memory.body)
            score = 2 * len(wanted & head) + len(wanted & body)
            if score:
                scored.append((score, memory))
        scored.sort(key=lambda pair: (-pair[0], pair[1].slug))
        return [memory for _, memory in scored[:k]]

    # --- disk -------------------------------------------------------------

    @staticmethod
    def _write_atomic(path: Path, text: str):
        tmp = path.with_name(path.name + ".tmp")
        # open() not Path.write_text: the newline kwarg needs Python 3.10+ and CI runs 3.9.
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)

    def _write_index(self):
        memories, issues = self._scan()
        lines = ["# Memory index", ""] + [m.index_line() for m in memories] + issues
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self._write_atomic(self.index_file, "\n".join(lines) + "\n")
