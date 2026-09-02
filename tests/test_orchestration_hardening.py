"""Regression tests for the adversarial review of adaptive orchestration.

Each test reproduces one finding against production code paths (model-facing tool
handlers, the flat SubagentManager facade, the subscription bridge argv) rather
than the internal API a scripted fake would flatter.
"""

import json
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.llm.client import LLMConfig, SubprocessSubscriptionBridge


def _message(content="", tool_calls=None):
    calls = []
    for index, (name, arguments) in enumerate(tool_calls or []):
        calls.append(
            SimpleNamespace(
                id=f"call_{index}",
                function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
            )
        )
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, tool_calls=calls or None),
                finish_reason="stop",
            )
        ]
    )


class ScriptedClient:
    def __init__(self, config, script=None):
        self.config = config
        self._script = list(script or [_message("done")])
        self._step = 0
        self.seen_tools = []

    def chat_completion(self, messages, tools=None, **_kwargs):
        self.seen_tools.append({t["function"]["name"] for t in tools or []})
        item = self._script[min(self._step, len(self._script) - 1)]
        self._step += 1
        return item() if callable(item) else item


def _config(**raw):
    from agent.orchestration.config import OrchestrationConfig

    raw.setdefault("enabled", True)
    return OrchestrationConfig.from_dict(raw)


def _manager(tmp_path, config=None, factory=None, **kwargs):
    from agent.orchestration.runtime import OrchestrationManager

    root = ScriptedClient(LLMConfig(provider="local", model="root", base_url="http://x/v1"))
    return OrchestrationManager(
        root,
        workspace_root=tmp_path,
        confirm_callback=kwargs.pop("confirm_callback", lambda _p: True),
        config=config or _config(),
        client_factory=factory or (lambda cfg: ScriptedClient(cfg)),
        availability=kwargs.pop("availability", lambda _t, _c: (True, "ok")),
        **kwargs,
    )


def _git_repo(path):
    for cmd in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "t@example.invalid"],
        ["git", "config", "user.name", "t"],
    ):
        subprocess.run(cmd, cwd=path, check=True, capture_output=True)
    (path / "seed.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=path, check=True, capture_output=True)


# --- 1. subscription-CLI children are confined -------------------------------------


def test_child_client_is_bound_to_lease_with_native_tools_off(tmp_path):
    manager = _manager(tmp_path)
    root = manager.register_root("executive")
    made = []
    manager.client_factory = lambda cfg: made.append(ScriptedClient(cfg)) or made[-1]
    result = manager.delegate(root.agent_id, "reviewer", "look")
    assert result.ok
    assert made[0].config.native_tools is False
    assert Path(made[0].config.workdir) == tmp_path.resolve()


def test_bridge_strips_native_tools_and_sets_cwd(monkeypatch, tmp_path):
    argv = {}

    class Proc:
        returncode = 0
        stdin = None

        def __init__(self, cmd, **kwargs):
            argv["cmd"] = cmd
            argv["cwd"] = kwargs.get("cwd")
            self.stdout = iter([json.dumps({"type": "result", "result": "ok"}) + "\n"])

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return 0

        def kill(self):
            pass

        def communicate(self, timeout=None):
            return ("", "")

    monkeypatch.setattr(subprocess, "Popen", Proc)
    SubprocessSubscriptionBridge.execute_turn(
        "anthropic-sub",
        [{"role": "user", "content": "hi"}],
        cwd=str(tmp_path),
        native_tools=False,
    )
    assert argv["cwd"] == str(tmp_path)
    assert "--tools" in argv["cmd"] and argv["cmd"][argv["cmd"].index("--tools") + 1] == ""

    SubprocessSubscriptionBridge.execute_turn(
        "openai-sub", [{"role": "user", "content": "hi"}], cwd=str(tmp_path), native_tools=False
    )
    cmd = argv["cmd"]
    assert "--dangerously-bypass-approvals-and-sandbox" not in cmd
    assert cmd[cmd.index("--sandbox") + 1] == "read-only" and cmd[cmd.index("-C") + 1] == str(
        tmp_path
    )

    with pytest.raises(RuntimeError, match="tool-restricted"):
        SubprocessSubscriptionBridge.execute_turn(
            "google-sub", [{"role": "user", "content": "hi"}], native_tools=False
        )


# --- 2. read-only roles: no network egress, no file:// reads --------------------------


def test_read_url_content_rejects_non_http_schemes(tmp_path):
    from agent.tools.registry import ToolRegistry

    secret = tmp_path / "secret.txt"
    secret.write_text("TOKEN=abc", encoding="utf-8")
    registry = ToolRegistry(workspace_root=str(tmp_path), load_mcp=False)
    result = registry.execute("read_url_content", {"url": secret.resolve().as_uri()})
    assert result.is_error and "TOKEN" not in result.output


def test_read_only_roles_have_no_network_tools(tmp_path):
    manager = _manager(tmp_path)
    root = manager.register_root("executive")
    made = []
    manager.client_factory = lambda cfg: made.append(ScriptedClient(cfg)) or made[-1]
    for role in ("researcher", "reviewer", "specialist", "tester"):
        manager.delegate(root.agent_id, role, "look")
        assert not {"read_url_content", "search_web"} & made[-1].seen_tools[0], role
    manager.delegate(root.agent_id, "engineer", "build")
    assert "read_url_content" in made[-1].seen_tools[0]


def test_tests_is_no_longer_a_permission():
    from agent.orchestration.config import OrchestrationConfigError

    with pytest.raises(OrchestrationConfigError, match="unknown permissions"):
        _config(roles={"tester": {"permissions": ["read", "tests"]}})


# --- 3. delegate_parallel without workspace_mode ---------------------------------------


def test_delegate_parallel_tool_without_workspace_mode_requires_isolation(tmp_path):
    manager = _manager(tmp_path)
    root = manager.register_root("executive")
    result = manager._tool_delegate_parallel(
        root.agent_id,
        {"tasks": [{"role": "engineer", "objective": "a"}, {"role": "engineer", "objective": "b"}]},
    )
    assert result.is_error and "mutating siblings" in result.output
    assert [n["role"] for n in manager.graph.snapshot()["nodes"]] == ["executive"]


# --- 4/6. budgets are per operation; a stale cancel does not poison the next spawn -------


def test_flat_subagents_survive_many_spawns_and_swarms(tmp_path):
    from agent.tools.subagent import SubagentManager

    client = ScriptedClient(LLMConfig(provider="local", model="m"))
    manager = SubagentManager(
        client=client,
        workspace_root=str(tmp_path),
        client_factory=lambda cfg: ScriptedClient(cfg, [_message("ok")]),
    )
    assert manager.orchestrator.enabled is False
    reports = [manager.spawn("reviewer", f"review {i}") for i in range(10)]
    assert all("ERROR" not in r for r in reports), reports
    for _ in range(3):
        batch = manager.spawn_parallel(
            [{"role": r, "prompt": "p"} for r in ("researcher", "tester", "reviewer")]
        )
        assert all("ERROR" not in r for r in batch), batch


def test_spawn_after_stale_cancel_runs(tmp_path):
    from agent.tools.subagent import SubagentManager

    cancel = threading.Event()
    cancel.set()
    manager = SubagentManager(
        client=ScriptedClient(LLMConfig(provider="local", model="m")),
        workspace_root=str(tmp_path),
        cancel_event=cancel,
        client_factory=lambda cfg: ScriptedClient(cfg, [_message("fresh")]),
    )
    assert "fresh" in manager.spawn("researcher", "go")


def test_budget_is_reset_per_turn_but_bounded_within_one(tmp_path):
    from agent.orchestration.runtime import OrchestrationError

    manager = _manager(tmp_path, config=_config(limits={"max_children_per_agent": 2}))
    root = manager.register_root("executive")
    manager.begin_turn()
    manager.delegate(root.agent_id, "researcher", "a")
    manager.delegate(root.agent_id, "researcher", "b")
    with pytest.raises(OrchestrationError, match="children per agent"):
        manager.delegate(root.agent_id, "researcher", "c")
    manager.end_turn()
    manager.begin_turn()
    assert manager.delegate(root.agent_id, "researcher", "next turn").ok


# --- 5. confirmations are serialized across parallel children ---------------------------


def test_confirmations_are_serialized_across_parallel_children(tmp_path):
    inside = []
    overlap = []
    lock_probe = threading.Lock()

    def confirm(_prompt):
        if not lock_probe.acquire(blocking=False):
            overlap.append(True)
            return True
        inside.append(True)
        threading.Event().wait(0.05)
        lock_probe.release()
        return True

    manager = _manager(tmp_path, confirm_callback=confirm)
    threads = [threading.Thread(target=manager.confirm, args=("x",)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(2)
    assert len(inside) == 4 and not overlap


# --- 7. one rejected sibling never discards the others' work ----------------------------


def test_parallel_batch_keeps_completed_siblings_when_one_reservation_fails(tmp_path):
    manager = _manager(tmp_path)
    root = manager.register_root("executive")
    real = manager._reserve

    def reserve(parent, role, relationship, inherit_model=False):
        if role == "reviewer":
            from agent.orchestration.runtime import OrchestrationError

            raise OrchestrationError("no available model for role 'reviewer'")
        return real(parent, role, relationship, inherit_model=inherit_model)

    manager._reserve = reserve
    result = manager._tool_delegate_parallel(
        root.agent_id,
        {
            "tasks": [
                {"role": "researcher", "objective": "a"},
                {"role": "reviewer", "objective": "b"},
                {"role": "tester", "objective": "c"},
            ]
        },
    )
    assert result.is_error  # one sibling failed
    assert result.output.count("Subagent Report") == 3
    assert "no available model" in result.output and result.output.count("done") == 2


# --- 8. requested isolation fails closed --------------------------------------------------


def test_delegate_agent_tool_branch_request_fails_closed_without_git(tmp_path):
    manager = _manager(tmp_path)  # tmp_path is not a git repository
    root = manager.register_root("executive")
    result = manager._tool_delegate(
        root.agent_id, {"role": "engineer", "objective": "edit", "workspace_mode": "branch"}
    )
    assert result.is_error and "isolated workspace required" in result.output
    child = manager.graph.snapshot()["nodes"][-1]
    assert child["status"] == "failed" and child["workspace_mode"] == "inherit"


def test_read_only_branch_fallback_is_reported(tmp_path):
    manager = _manager(tmp_path)
    root = manager.register_root("executive")
    result = manager.delegate(root.agent_id, "researcher", "look", workspace_mode="branch")
    assert result.ok and "inherited the parent workspace" in result.output


# --- 9. a failed branch child still hands its diff upward ------------------------------


def test_failed_branch_child_still_captures_patch(tmp_path):
    _git_repo(tmp_path)

    def factory(cfg):
        def write():
            return _message(tool_calls=[("write_file", {"file_path": "new.txt", "content": "x"})])

        def boom():
            raise RuntimeError("provider died after the edit")

        return ScriptedClient(cfg, [write, boom])

    manager = _manager(tmp_path, factory=factory)
    root = manager.register_root("executive")
    result = manager.delegate(root.agent_id, "engineer", "edit", workspace_mode="branch")
    assert result.ok is False and result.workspace_artifact
    assert "new.txt" in (tmp_path / result.workspace_artifact).read_text(encoding="utf-8")
    assert not (tmp_path / "new.txt").exists()
    assert not any(manager.workspaces.worktree_root.iterdir())


# --- 10. malformed config is a notice, not a failed turn -------------------------------


def test_malformed_config_is_reported_as_system_not_error(tmp_path):
    from agent.loop import AgentLoop

    (tmp_path / ".agnostic").mkdir()
    (tmp_path / ".agnostic" / "orchestration.json").write_text("{not json", encoding="utf-8")
    events = []
    loop = AgentLoop(workspace_root=str(tmp_path), output_callback=lambda t, c: events.append(t))
    assert "system" in events and "error" not in events
    assert loop.orchestration.enabled is False


# --- 11/12. model target semantics --------------------------------------------------------


def test_shorthand_override_keeps_inherit_fallback_and_rejects_mixed_forms():
    from agent.orchestration.config import OrchestrationConfigError

    cfg = _config(roles={"engineer": {"preset": "sub-openai-codex", "model": "gpt-5.6-terra"}})
    models = cfg.roles["engineer"].models
    assert [m.preset for m in models] == ["sub-openai-codex", None] and models[-1].inherit
    explicit = _config(roles={"engineer": {"preset": "sub-openai-codex", "fallbacks": []}})
    assert len(explicit.roles["engineer"].models) == 1
    with pytest.raises(OrchestrationConfigError, match="cannot combine"):
        _config(roles={"engineer": {"preset": "sub-openai-codex", "models": [{"inherit": True}]}})


def test_non_preset_provider_with_base_url_is_available(monkeypatch, tmp_path):
    from agent.orchestration.config import ModelTarget

    monkeypatch.setenv("VLLM_KEY", "k")
    manager = _manager(tmp_path)
    manager.availability = manager._default_availability
    parent = manager.root_client
    keyless = ModelTarget(provider="local", model="m", base_url="http://gpu-box:8000/v1")
    keyed = ModelTarget(provider="vllm", model="m", base_url="http://h/v1", api_key_env="VLLM_KEY")
    assert manager.availability(keyless, manager._config_for_target(keyless, parent))[0]
    # A metered provider is refused by default, even with a key in the environment...
    cfg = manager._config_for_target(keyed, parent)
    ok, reason = manager.availability(keyed, cfg)
    assert ok is False and "metered API" in reason
    # ...and accepted only when the project opts in.
    opted = _manager(tmp_path, config=_config(allow_api_models=True))
    opted.availability = opted._default_availability
    cfg = opted._config_for_target(keyed, opted.root_client)
    assert opted.availability(keyed, cfg)[0] and cfg.api_key == "k"
    bare = ModelTarget(provider="vllm", model="m")
    assert opted.availability(bare, opted._config_for_target(bare, opted.root_client))[0] is False


# --- 13. nested branch children fork the parent's checkout -------------------------------


def test_nested_branch_child_forks_from_parent_worktree(tmp_path):
    from agent.orchestration.runtime import WorkspaceManager

    _git_repo(tmp_path)
    ws = WorkspaceManager(tmp_path)
    root = ws.inherit("root", path=tmp_path, writable=True)
    parent = ws.acquire_branch("parent", root, writable=True, require_isolation=True)
    (parent.path / "parent.txt").write_text("committed in the parent worktree", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=parent.path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "parent work"],
        cwd=parent.path,
        check=True,
        capture_output=True,
    )
    child = ws.acquire_branch("child", parent, writable=True, require_isolation=True)
    try:
        assert (child.path / "parent.txt").exists()
        assert tmp_path not in child.path.parents  # worktrees live outside the repo
    finally:
        assert ws.release(child, "child") and ws.release(parent, "parent")


# --- 14. max_turns keeps the work and is bounded --------------------------------------


def test_max_turns_exhaustion_keeps_last_output_and_tool_bound(tmp_path):
    def factory(cfg):
        return ScriptedClient(
            cfg,
            [lambda: _message("progress so far", tool_calls=[("find_files", {"pattern": "*.py"})])],
        )

    manager = _manager(tmp_path, factory=factory)
    root = manager.register_root("executive")
    result = manager._tool_delegate(
        root.agent_id, {"role": "researcher", "objective": "loop", "max_turns": 2}
    )
    assert result.is_error and "progress so far" in result.output
    assert "max turns limit (2)" in result.output


# --- 15. incomplete cleanup is reported and /org prune sweeps orphans --------------------


def test_release_reports_incomplete_cleanup(tmp_path, monkeypatch):
    from agent.orchestration import runtime
    from agent.orchestration.runtime import WorkspaceManager

    _git_repo(tmp_path)
    ws = WorkspaceManager(tmp_path)
    root = ws.inherit("root", path=tmp_path, writable=True)
    lease = ws.acquire_branch("stuck", root, writable=True, require_isolation=True)
    monkeypatch.setattr(ws, "_git", lambda *a, **k: False)
    monkeypatch.setattr(runtime.shutil, "rmtree", lambda *a, **k: None)
    assert ws.release(lease, "stuck") is False
    assert lease.path.exists() and "prune" in lease.note
    monkeypatch.undo()
    assert ws.prune() == 1 and not lease.path.exists()


def test_org_prune_command_reports_volume(tmp_path):
    from agent.ui_common import org_command

    manager = _manager(tmp_path)
    agent = SimpleNamespace(orchestration=manager, is_busy=False)
    assert org_command(agent, "prune").startswith("pruned 0 orphaned worktree(s)")


# --- 16/17. telemetry is visible and redacted ---------------------------------------------


def test_orchestration_events_render_on_the_subagent_channel(tmp_path):
    from agent.loop import AgentLoop

    events = []
    loop = AgentLoop(
        workspace_root=str(tmp_path), output_callback=lambda t, c: events.append((t, c))
    )
    loop.subagents.orchestrator.client_factory = lambda cfg: ScriptedClient(cfg)
    loop.subagents.spawn("researcher", "look")
    kinds = [t for t, _ in events]
    assert kinds.count("subagent") >= 2 and not {"agent_start", "agent_end"} & set(kinds)


def test_graph_detail_is_redacted_and_workspace_relative(tmp_path):
    def factory(cfg):
        def leak():
            raise RuntimeError("stdout tail: OPENAI_API_KEY=sk-live-" + "x" * 500)

        return ScriptedClient(cfg, [leak])

    manager = _manager(tmp_path, factory=factory)
    root = manager.register_root("executive")
    result = manager.delegate(root.agent_id, "researcher", "x")
    node = manager.graph.get_node(result.agent_id)
    assert (
        node.status == "failed"
        and len(node.detail) <= 220
        and node.detail.startswith("RuntimeError")
    )
    assert node.workspace == "." and str(tmp_path) not in json.dumps(manager.graph.snapshot())


# --- 19-23. smaller edges -----------------------------------------------------------------


def test_org_command_refuses_toggle_while_busy(tmp_path):
    from agent.ui_common import org_command

    calls = []
    agent = SimpleNamespace(
        orchestration=_manager(tmp_path),
        is_busy=True,
        configure_orchestration=lambda **kw: calls.append(kw),
    )
    assert "turn is running" in org_command(agent, "on") and not calls
    assert "orchestration:" in org_command(agent, "status")


def test_route_task_only_offered_where_it_can_be_acted_on(tmp_path):
    from agent.tools.registry import ToolRegistry

    manager = _manager(tmp_path)
    root = manager.register_root("executive")
    child = manager.delegate(root.agent_id, "researcher", "x")
    registry = ToolRegistry(workspace_root=str(tmp_path), load_mcp=False, allowed_tools=set())
    manager.register_agent_tools(registry, child.agent_id)
    assert registry.get_openai_tools() == []
    manager.register_agent_tools(registry, root.agent_id)
    assert "route_task" in {t["function"]["name"] for t in registry.get_openai_tools()}


def test_blank_task_string_is_rejected():
    from agent.orchestration.runtime import OrchestrationError, TaskPacket

    with pytest.raises(OrchestrationError, match="objective"):
        TaskPacket.coerce("   ")


def test_retry_loop_stops_on_cancel():
    from agent.llm.client import LLMClient

    client = LLMClient.__new__(LLMClient)
    client.config = LLMConfig(provider="local", model="m", max_retries=5, retry_backoff=10)
    cancel = threading.Event()
    attempts = []

    class Transient(Exception):
        status_code = 503

    def call():
        attempts.append(1)
        cancel.set()
        raise Transient("service unavailable")

    with pytest.raises(RuntimeError, match="cancelled"):
        client._with_retry(call, cancel)
    assert len(attempts) == 1


def test_cancel_marks_waiting_nodes_only(tmp_path):
    from agent.orchestration.runtime import AgentNode

    manager = _manager(tmp_path)
    root = manager.register_root("executive")
    for status in ("waiting", "running"):
        manager.graph.add_node(
            AgentNode(
                agent_id=status,
                parent_agent_id=root.agent_id,
                root_agent_id=root.agent_id,
                role="researcher",
                depth=1,
                provider="local",
                preset=None,
                model="m",
                effort="low",
                objective="",
                status=status,
                workspace=".",
                workspace_owner=status,
                workspace_mode="inherit",
                workspace_read_only=True,
                permissions=(),
                allowed_child_roles=(),
                allowed_advisor_roles=(),
                relationship="delegation",
                start_time=0.0,
            )
        )
    manager.cancel()
    assert manager.cancel_event.is_set()
    assert manager.graph.get_node("waiting").status == "cancelled"
    assert manager.graph.get_node("running").status == "running"


def test_swarm_reports_a_rejected_batch_instead_of_raising(tmp_path):
    from agent.workflows.swarm import SwarmCoordinator

    class Rejecting:
        confirm_callback = None
        workspace_root = tmp_path

        def spawn_parallel(self, tasks):
            raise RuntimeError("maximum total agents reached")

    class Lead:
        config = LLMConfig(provider="local", model="m")

        def chat_completion(self, messages, **_k):
            return _message("synthesis: " + messages[-1]["content"][:40])

    swarm = SwarmCoordinator(Rejecting(), Lead())
    assert "synthesis" in swarm.dispatch_swarm("anything")


# --- subscription only, never the API ---------------------------------------------------


@pytest.fixture  # noqa: vulture -- used via @pytest.mark.usefixtures
def subscription_available(monkeypatch):
    monkeypatch.setattr(LLMConfig, "preset_available", staticmethod(lambda *_a, **_k: True))


@pytest.mark.usefixtures("subscription_available")
def test_default_roles_resolve_to_claude_subscription_with_haiku_for_workers(tmp_path):
    manager = _manager(tmp_path)
    manager.availability = manager._default_availability
    root = manager.register_root("executive")
    made = []
    manager.client_factory = lambda cfg: made.append(ScriptedClient(cfg)) or made[-1]
    for role in ("researcher", "reviewer", "tester", "specialist"):
        manager.delegate(root.agent_id, role, "x")
        cfg = made[-1].config
        assert (cfg.provider, cfg.preset_key, cfg.sub_model) == (
            "anthropic-sub",
            "sub-claude-code",
            "claude-haiku-4.5",
        ), role
    manager.delegate(root.agent_id, "engineer", "x")
    assert made[-1].config.sub_model == "claude-sonnet-5"
    # no default target is a metered API
    for role in manager.config.roles.values():
        assert all(t.preset in {"sub-claude-code", "sub-openai-codex"} for t in role.models), (
            role.name
        )


def test_api_providers_are_unavailable_to_subagents_by_default(tmp_path, monkeypatch):
    from agent.orchestration.runtime import OrchestrationError

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    cfg = _config(roles={"researcher": {"preset": "claude-haiku-4.5", "fallbacks": []}})
    manager = _manager(tmp_path, config=cfg)
    manager.availability = manager._default_availability
    root = manager.register_root("executive")
    with pytest.raises(OrchestrationError, match="metered API"):
        manager.delegate(root.agent_id, "researcher", "x")


def test_bridge_strips_api_keys_and_maps_model_aliases(monkeypatch):
    seen = {}

    class Proc:
        returncode = 0
        stdin = None

        def __init__(self, cmd, **kwargs):
            seen["cmd"], seen["env"] = cmd, kwargs.get("env")
            self.stdout = iter([json.dumps({"type": "result", "result": "ok"}) + "\n"])

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return 0

        def kill(self):
            pass

        def communicate(self, timeout=None):
            return ("", "")

    monkeypatch.setattr(subprocess, "Popen", Proc)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak-either")
    SubprocessSubscriptionBridge.execute_turn(
        "anthropic-sub", [{"role": "user", "content": "hi"}], model="claude-haiku-4.5"
    )
    assert "ANTHROPIC_API_KEY" not in seen["env"] and "OPENAI_API_KEY" in seen["env"]
    assert seen["cmd"][seen["cmd"].index("--model") + 1] == "haiku"
    SubprocessSubscriptionBridge.execute_turn("openai-sub", [{"role": "user", "content": "hi"}])
    assert "OPENAI_API_KEY" not in seen["env"] and "ANTHROPIC_API_KEY" in seen["env"]


def test_legacy_role_refuses_to_clone_a_metered_session_model(tmp_path):
    from agent.tools.subagent import SubagentManager

    client = ScriptedClient(LLMConfig(provider="anthropic", model="claude-fable-5", api_key="k"))
    manager = SubagentManager(client=client, workspace_root=str(tmp_path))
    report = manager.spawn("bespoke-role", "do it")
    assert "ERROR" in report and "metered API" in report


# --- delegate-first whenever the interactive model is expensive (Fable) -----------------


def _fable_manager(tmp_path, **kw):
    from agent.orchestration.runtime import OrchestrationManager

    root_cfg = LLMConfig.from_preset("sub-claude-code", model="claude-fable-5")
    return OrchestrationManager(
        ScriptedClient(root_cfg),
        workspace_root=tmp_path,
        confirm_callback=lambda _p: True,
        config=kw.pop("config", _config()),
        client_factory=lambda cfg: ScriptedClient(cfg),
        availability=lambda _t, _c: (True, "ok"),
    )


def test_expensive_root_routes_delegate_first_and_says_so(tmp_path):
    from agent.orchestration.runtime import RoutingInput

    manager = _fable_manager(tmp_path)
    assert manager.root_is_expensive
    assert manager.route(RoutingInput(task="small lookup", complexity=2)).action == "delegate"
    assert "DELEGATE-FIRST" in manager.prompt_fragment()
    assert "delegate-first" in manager.status()
    cheap = _manager(tmp_path)
    assert cheap.route(RoutingInput(task="small lookup", complexity=2)).action == "direct"
    assert "DELEGATE-FIRST" not in cheap.prompt_fragment()


def test_agent_loop_turns_orchestration_on_for_an_expensive_root(tmp_path):
    from agent.loop import AgentLoop

    events = []
    loop = AgentLoop(
        workspace_root=str(tmp_path), output_callback=lambda t, c: events.append((t, c))
    )
    assert loop.orchestration.enabled is False
    loop.llm_client.config.provider = "anthropic-sub"
    loop.llm_client.config.sub_model = "claude-fable-5"
    loop._enforce_delegate_first()
    assert loop.orchestration.enabled and loop.orchestration.config.mode == "hierarchy"
    names = {t["function"]["name"] for t in loop.registry.get_openai_tools()}
    assert "delegate_agent" in names and "invoke_subagent" not in names
    assert "DELEGATE-FIRST" in loop.history[0]["content"]
    assert any(t == "system" and "delegate-first" in c for t, c in events)


def test_expensive_model_agents_are_capped_and_never_in_fan_outs(tmp_path):
    from agent.orchestration.runtime import OrchestrationError

    cfg = _config(
        limits={"max_expensive_agents": 1},
        roles={"reviewer": {"preset": "sub-claude-code", "model": "claude-fable-5"}},
    )
    manager = _manager(tmp_path, config=cfg)
    root = manager.register_root("executive")
    assert manager.delegate(root.agent_id, "reviewer", "one").ok
    with pytest.raises(OrchestrationError, match="expensive model agent limit"):
        manager.delegate(root.agent_id, "reviewer", "two")
    with pytest.raises(OrchestrationError, match="never inside a parallel fan-out"):
        manager.spawn_parallel(root.agent_id, [{"role": "reviewer", "task": "x"}])
    assert manager.delegate(root.agent_id, "researcher", "cheap is fine").ok


def test_empty_child_reply_is_nudged_then_reported(tmp_path):
    def factory(cfg):
        return ScriptedClient(cfg, [_message(""), _message("real answer")])

    manager = _manager(tmp_path, factory=factory)
    root = manager.register_root("executive")
    result = manager.delegate(root.agent_id, "researcher", "x")
    assert result.ok and result.output == "real answer"

    always_empty = _manager(tmp_path, factory=lambda cfg: ScriptedClient(cfg, [_message("")]))
    root = always_empty.register_root("executive")
    result = always_empty.delegate(root.agent_id, "researcher", "x")
    assert result.ok is False and "no content" in result.error
