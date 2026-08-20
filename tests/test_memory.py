"""
tests/test_memory.py — Regression Tests for the Persistent Auto-Memory Store
Covers the save/get/list/delete round trip, upsert, name safety, body and store caps,
index truncation, corrupt files, token-overlap recall, the two agent tools, and the
"## Memory (auto-recalled)" system-prompt injection.
"""

import inspect
from pathlib import Path

import pytest

from agent.governance.memory import MAX_BODY_BYTES, MemoryStore
from agent.loop import AgentLoop
from agent.tools.registry import ToolRegistry


def _store(tmp_path):
    return MemoryStore(str(tmp_path))


def _loop(tmp_path):
    """AgentLoop stub with just enough state for the prompt and the memory tools."""
    loop = object.__new__(AgentLoop)
    loop.workspace_root = Path(tmp_path)
    loop.output_callback = lambda msg_type, content: None
    return loop


def _write_compiled_prompt(tmp_path, text):
    compiled = tmp_path / "storage" / "compiled"
    compiled.mkdir(parents=True, exist_ok=True)
    (compiled / "system_prompt.md").write_text(text, encoding="utf-8")


# --- CRUD round trip ------------------------------------------------------


def test_save_get_list_delete_round_trip(tmp_path):
    store = _store(tmp_path)
    store.save("Dashboard port", "the command center binds 7843+", "Port 7842 is taken by hooop.")

    got = store.get("Dashboard port")
    assert got is not None
    assert got.slug == "dashboard-port"
    assert got.description == "the command center binds 7843+"
    assert got.type == "project"
    assert got.created  # ISO date stamped at save time
    assert "hooop" in got.body

    assert [m.name for m in store.list()] == ["Dashboard port"]

    on_disk = (tmp_path / ".agnostic" / "memory" / "dashboard-port.md").read_text(encoding="utf-8")
    assert on_disk.startswith("---\nname: Dashboard port\n")

    index = (tmp_path / ".agnostic" / "memory" / "MEMORY.md").read_text(encoding="utf-8")
    assert "- [Dashboard port](dashboard-port.md) — the command center binds 7843+" in index

    assert store.delete("Dashboard port") is True
    assert store.get("Dashboard port") is None
    assert store.list() == []
    assert "dashboard-port.md" not in (tmp_path / ".agnostic" / "memory" / "MEMORY.md").read_text(
        encoding="utf-8"
    )
    assert store.delete("Dashboard port") is False


def test_save_upserts_and_keeps_the_original_created_date(tmp_path):
    store = _store(tmp_path)
    first = store.save("Test runner", "old line", "use nose", type="user")
    (tmp_path / ".agnostic" / "memory" / "test-runner.md").write_text(
        (tmp_path / ".agnostic" / "memory" / "test-runner.md")
        .read_text(encoding="utf-8")
        .replace(f"created: {first.created}", "created: 2020-01-01"),
        encoding="utf-8",
    )

    second = store.save("test  runner", "new line", "use pytest", type="feedback")

    assert second.created == "2020-01-01", "an upsert must not reset the creation date"
    assert len(store.list()) == 1, "the slug is normalised, so this is one memory, not two"
    assert store.get("Test Runner").body == "use pytest"
    index = (tmp_path / ".agnostic" / "memory" / "MEMORY.md").read_text(encoding="utf-8")
    assert "old line" not in index and "new line" in index


# --- Safety ---------------------------------------------------------------


@pytest.mark.parametrize("bad", ["../../etc/passwd", "a/b", "a\\b", "..", "...", "   ", "%%%"])
def test_unsafe_names_are_rejected(tmp_path, bad):
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        store.save(bad, "d", "b")
    assert not (tmp_path / ".agnostic" / "memory").exists(), "a rejected name must write nothing"


def test_oversized_body_and_unknown_type_are_rejected(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="too large"):
        store.save("big", "d", "x" * (MAX_BODY_BYTES + 1))
    with pytest.raises(ValueError, match="type"):
        store.save("typed", "d", "b", type="secrets")
    assert store.list() == []


def test_store_is_capped(tmp_path, monkeypatch):
    monkeypatch.setattr("agent.governance.memory.MAX_MEMORIES", 3)
    store = _store(tmp_path)
    for i in range(3):
        store.save(f"m{i}", "d", "b")
    with pytest.raises(ValueError, match="full"):
        store.save("m3", "d", "b")
    store.save("m1", "d", "updated")  # an upsert still works at the cap
    assert store.get("m1").body == "updated"


def test_writes_leave_no_temp_files(tmp_path):
    store = _store(tmp_path)
    store.save("clean", "d", "b")
    assert [p.name for p in (tmp_path / ".agnostic" / "memory").glob("*.tmp")] == []


# --- Index ----------------------------------------------------------------


def test_index_text_truncation_keeps_whole_lines(tmp_path):
    store = _store(tmp_path)
    for i in range(12):
        store.save(f"memory {i:02d}", "d" * 60, "body")

    full = store.index_text()
    assert len(full.splitlines()) == 12

    clipped = store.index_text(max_chars=300)
    assert len(clipped) <= 300
    lines = clipped.splitlines()
    assert lines, "truncation must keep the newest lines, not everything"
    assert len(lines) < 12
    assert all(line in full.splitlines() for line in lines), "no line may be cut mid-way"
    assert lines[-1] == full.splitlines()[-1], "the oldest lines go first"
    assert "memory 00" not in clipped


def test_index_text_survives_a_corrupt_file(tmp_path):
    store = _store(tmp_path)
    store.save("good", "still readable", "body")
    (tmp_path / ".agnostic" / "memory" / "junk.md").write_text("not a memory", encoding="utf-8")

    text = store.index_text()
    assert "- [good](good.md) — still readable" in text
    assert "- [!] junk.md is not a valid memory file (skipped)" in text
    assert [m.name for m in store.list()] == ["good"]


def test_index_text_is_empty_without_a_store(tmp_path):
    assert _store(tmp_path).index_text() == ""


# --- Recall ---------------------------------------------------------------


def test_recall_ranks_the_matching_memory_first(tmp_path):
    store = _store(tmp_path)
    store.save("Ruff config", "lint settings", "line length is 100 characters")
    store.save("Deploy steps", "how to ship", "push the tag, CI does the rest")
    store.save("Editor", "editor choice", "the ruff formatter runs on save")

    hits = store.recall("ruff lint")
    assert [m.name for m in hits] == ["Ruff config", "Editor"], (
        "a name/description hit must outrank a body-only hit"
    )
    assert store.recall("kubernetes") == []
    assert store.recall("") == []
    assert len(store.recall("ruff lint deploy editor ship", k=2)) == 2


# --- Agent tools ----------------------------------------------------------


def test_memory_tools_are_registered_and_round_trip(tmp_path):
    loop = _loop(tmp_path)
    loop.registry = ToolRegistry(workspace_root=str(tmp_path))
    loop._register_memory_tools()

    names = {t["function"]["name"] for t in loop.registry.get_openai_tools()}
    assert {"save_memory", "recall_memory"} <= names

    saved = loop.registry.execute(
        "save_memory",
        {"name": "Line length", "description": "ruff", "body": "100 chars", "type": "user"},
    )
    assert not saved.is_error and "line-length.md" in saved.output

    recalled = loop.registry.execute("recall_memory", {"query": "line length"})
    assert not recalled.is_error and "100 chars" in recalled.output

    assert loop.registry.execute("recall_memory", {"query": "nothing here"}).output.startswith(
        "No stored memory matches"
    )

    bad = loop.registry.execute("save_memory", {"name": "../evil", "description": "d", "body": "b"})
    assert bad.is_error and "path separators" in bad.output


def test_loop_source_registers_both_memory_tools():
    text = Path(inspect.getfile(AgentLoop)).read_text(encoding="utf-8")
    assert "self._register_memory_tools()" in text, "the tools must be wired in __init__"

    registrations = inspect.getsource(AgentLoop._register_memory_tools)
    assert registrations.count("self.registry.register(") == 2
    assert 'name="save_memory"' in registrations
    assert 'name="recall_memory"' in registrations
    assert "never store secrets" in registrations.lower()


# --- System prompt injection ---------------------------------------------


def test_memory_index_is_injected_into_the_system_prompt(tmp_path):
    _write_compiled_prompt(tmp_path, "# Global Rules\nbe surgical\n")
    loop = _loop(tmp_path)

    loop._load_harness_system_prompt(compact=False)
    assert "## Memory (auto-recalled)" not in loop.history[0]["content"], (
        "an empty store must not add a section"
    )

    _store(tmp_path).save("Dashboard port", "binds 7843+", "7842 is taken")
    loop._load_harness_system_prompt(compact=False)
    system = loop.history[0]["content"]
    assert "## Memory (auto-recalled)" in system
    assert "- [Dashboard port](dashboard-port.md) — binds 7843+" in system
    assert "be surgical" in system


def test_memory_index_is_skipped_when_compact_has_no_room(tmp_path):
    _write_compiled_prompt(tmp_path, "# Global Rules\n" + "x" * 9000)
    (tmp_path / "AGENTS.md").write_text("y" * 3500, encoding="utf-8")
    store = _store(tmp_path)
    for i in range(40):
        store.save(f"memory {i:02d}", "d" * 60, "body")

    loop = _loop(tmp_path)
    loop._load_harness_system_prompt(compact=True)
    compact_prompt = loop.history[0]["content"]
    assert "Project Agreement" in compact_prompt, "the agreement keeps its budget priority"
    assert "## Memory (auto-recalled)" not in compact_prompt

    loop._load_harness_system_prompt(compact=False)
    assert "## Memory (auto-recalled)" in loop.history[0]["content"]


def test_project_agreement_still_lands_alongside_memory(tmp_path):
    _write_compiled_prompt(tmp_path, "# Global Rules\nbe surgical\n")
    (tmp_path / "AGENTS.md").write_text("Run pytest before claiming done.", encoding="utf-8")
    _store(tmp_path).save("Dashboard port", "binds 7843+", "7842 is taken")

    loop = _loop(tmp_path)
    loop._load_harness_system_prompt(compact=True)
    system = loop.history[0]["content"]
    assert "### [Project Agreement: AGENTS.md]" in system
    assert system.index("Project Agreement") < system.index("## Memory (auto-recalled)")
