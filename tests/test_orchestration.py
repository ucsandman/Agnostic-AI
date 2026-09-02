"""Adaptive hierarchical orchestration contract tests."""

import json
import threading
from types import SimpleNamespace

import pytest

from agent.llm.client import LLMConfig


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
    def __init__(self, config, scripts):
        self.config = config
        self._scripts = scripts
        self._step = 0

    def chat_completion(self, messages, **_kwargs):
        script = self._scripts[self.config.sub_model or self.config.model]
        item = script[min(self._step, len(script) - 1)]
        self._step += 1
        return item


def _config(tmp_path, *, enabled=True, roles=None, limits=None, mode="auto"):
    from agent.orchestration.config import OrchestrationConfig

    raw = {"enabled": enabled, "mode": mode}
    if roles is not None:
        raw["roles"] = roles
    if limits is not None:
        raw["limits"] = limits
    return OrchestrationConfig.from_dict(raw, source=tmp_path / "orchestration.json")


def _manager(tmp_path, *, config=None, scripts=None, availability=None, cancel_event=None):
    from agent.orchestration.runtime import OrchestrationManager

    root_config = LLMConfig(provider="local", model="root-model", base_url="http://local/v1")
    root_client = ScriptedClient(root_config, scripts or {"root-model": [_message("root")]})

    def factory(model_config):
        model = model_config.sub_model or model_config.model
        return ScriptedClient(model_config, scripts or {model: [_message("done")]})

    manager = OrchestrationManager(
        root_client,
        workspace_root=tmp_path,
        confirm_callback=lambda _prompt: True,
        cancel_event=cancel_event,
        config=config or _config(tmp_path),
        client_factory=factory,
        availability=availability or (lambda _target, _cfg: (True, "available")),
    )
    return manager


def test_default_capability_graph_supports_direct_delegation(tmp_path):
    cfg = _config(tmp_path)
    assert {"manager", "engineer", "specialist"} <= set(cfg.roles["executive"].allowed_children)
    assert "specialist" in cfg.roles["engineer"].allowed_children
    assert cfg.roles["specialist"].allowed_children == ()
    assert "executive" in cfg.roles["engineer"].allowed_advisors


def test_role_inheritance_and_cycle_validation(tmp_path):
    from agent.orchestration.config import OrchestrationConfigError

    cfg = _config(
        tmp_path,
        roles={
            "lint-manager": {
                "base": "manager",
                "additional_instructions": "Own lint quality.",
            }
        },
    )
    assert "orchestrate" in cfg.roles["lint-manager"].permissions
    assert "Own lint quality" in cfg.roles["lint-manager"].instructions

    with pytest.raises(OrchestrationConfigError, match="cycle"):
        _config(
            tmp_path,
            roles={
                "a": {"base": "specialist", "allowed_children": ["b"]},
                "b": {"base": "specialist", "allowed_children": ["a"]},
            },
        )


@pytest.mark.parametrize(
    "raw",
    [
        {"enabled": "yes"},
        {"unknown_policy": True},
        {"roles": {"engineer": {"permisions": ["read"]}}},
        {"roles": {"engineer": {"permissions": ["read", "root"]}}},
        {
            "roles": {
                "engineer": {"models": [{"inherit": True, "provider": "local", "model": "bad"}]}
            }
        },
    ],
)
def test_invalid_policy_configuration_fails_closed(tmp_path, raw):
    from agent.orchestration.config import OrchestrationConfig, OrchestrationConfigError

    with pytest.raises(OrchestrationConfigError):
        OrchestrationConfig.from_dict(raw, source=tmp_path / "orchestration.json")


def test_authorized_direct_child_and_unauthorized_child(tmp_path):
    from agent.orchestration.runtime import OrchestrationError, TaskPacket

    manager = _manager(tmp_path)
    root = manager.register_root("executive")
    result = manager.delegate(root.agent_id, "engineer", TaskPacket(objective="Implement it"))
    assert result.ok and result.role == "engineer"

    with pytest.raises(OrchestrationError, match="not allowed"):
        manager.delegate(result.agent_id, "manager", TaskPacket(objective="Go upward"))


@pytest.mark.parametrize(
    ("limit_key", "limit_value", "expected"),
    [
        ("max_depth", 1, "depth"),
        ("max_children_per_agent", 1, "children"),
        ("max_total_agents", 2, "total agents"),
    ],
)
def test_delegation_limits(tmp_path, limit_key, limit_value, expected):
    from agent.orchestration.runtime import OrchestrationError, TaskPacket

    cfg = _config(tmp_path, limits={limit_key: limit_value})
    manager = _manager(tmp_path, config=cfg)
    root = manager.register_root("executive")
    first = manager.delegate(root.agent_id, "engineer", TaskPacket(objective="one"))
    assert first.ok

    parent = first.agent_id if limit_key == "max_depth" else root.agent_id
    role = "specialist" if limit_key == "max_depth" else "engineer"
    with pytest.raises(OrchestrationError, match=expected):
        manager.delegate(parent, role, TaskPacket(objective="two"))


def test_max_parallel_children_is_enforced(tmp_path):
    from agent.orchestration.runtime import OrchestrationError, TaskPacket

    cfg = _config(tmp_path, limits={"max_parallel_children": 1})
    entered = threading.Event()
    release = threading.Event()

    class BlockingClient(ScriptedClient):
        def chat_completion(self, messages, **kwargs):
            entered.set()
            release.wait(2)
            return _message("done")

    manager = _manager(tmp_path, config=cfg)
    manager.client_factory = lambda model_config: BlockingClient(model_config, {})
    root = manager.register_root("executive")
    errors = []

    thread = threading.Thread(
        target=lambda: manager.delegate(root.agent_id, "engineer", TaskPacket(objective="blocking"))
    )
    thread.start()
    assert entered.wait(1)
    try:
        with pytest.raises(OrchestrationError, match="parallel children"):
            manager.delegate(root.agent_id, "specialist", TaskPacket(objective="overflow"))
    finally:
        release.set()
        thread.join(2)
    assert not errors


def test_parallel_batch_admission_is_atomic(tmp_path):
    from agent.orchestration.runtime import OrchestrationError

    cfg = _config(tmp_path, limits={"max_total_agents": 2})
    manager = _manager(tmp_path, config=cfg)
    root = manager.register_root("executive")
    with pytest.raises(OrchestrationError, match="parallel children"):
        manager.spawn_parallel(
            root.agent_id,
            [
                {"role": "researcher", "task": "one"},
                {"role": "reviewer", "task": "two"},
            ],
        )
    assert len(manager.graph.snapshot()["nodes"]) == 1


def test_per_role_models_and_visible_fallback(tmp_path):
    from agent.orchestration.runtime import TaskPacket

    cfg = _config(
        tmp_path,
        roles={
            "engineer": {
                "models": [
                    {"provider": "missing", "model": "unavailable"},
                    {"provider": "local", "model": "fallback-model"},
                ]
            }
        },
    )

    def availability(target, _model_config):
        return (target.provider != "missing", "provider unavailable")

    scripts = {"root-model": [_message("root")], "fallback-model": [_message("fallback ok")]}
    manager = _manager(tmp_path, config=cfg, scripts=scripts, availability=availability)
    root = manager.register_root("executive")
    result = manager.delegate(root.agent_id, "engineer", TaskPacket(objective="fallback"))
    node = manager.graph.get_node(result.agent_id)
    assert result.ok and node.model == "fallback-model" and node.provider == "local"
    assert node.fallback_reason == "provider unavailable"


def test_roles_can_use_different_providers_and_models(tmp_path):
    cfg = _config(
        tmp_path,
        roles={
            "manager": {"models": [{"provider": "provider-a", "model": "model-a"}]},
            "engineer": {"models": [{"provider": "provider-b", "model": "model-b"}]},
        },
    )
    scripts = {
        "root-model": [_message("root")],
        "model-a": [_message("manager")],
        "model-b": [_message("engineer")],
    }
    manager = _manager(tmp_path, config=cfg, scripts=scripts)
    root = manager.register_root("executive")
    workstream = manager.delegate(root.agent_id, "manager", "own")
    implementation = manager.delegate(workstream.agent_id, "engineer", "build")
    manager_node = manager.graph.get_node(workstream.agent_id)
    engineer_node = manager.graph.get_node(implementation.agent_id)
    assert (manager_node.provider, manager_node.model) == ("provider-a", "model-a")
    assert (engineer_node.provider, engineer_node.model) == ("provider-b", "model-b")


def test_first_request_failure_uses_visible_fallback_before_tools(tmp_path):
    from agent.orchestration.runtime import TaskPacket

    cfg = _config(
        tmp_path,
        roles={
            "engineer": {
                "models": [
                    {"provider": "local", "model": "preferred-model"},
                    {"provider": "local", "model": "fallback-model"},
                ]
            }
        },
    )

    class PreferredClient(ScriptedClient):
        def chat_completion(self, messages, **kwargs):
            raise RuntimeError("model rejected request")

    def factory(model_config):
        model = model_config.sub_model or model_config.model
        if model == "preferred-model":
            return PreferredClient(model_config, {})
        return ScriptedClient(model_config, {"fallback-model": [_message("fallback ok")]})

    manager = _manager(tmp_path, config=cfg)
    manager.client_factory = factory
    root = manager.register_root("executive")
    result = manager.delegate(root.agent_id, "engineer", TaskPacket(objective="fallback"))
    node = manager.graph.get_node(result.agent_id)
    assert result.ok and result.output == "fallback ok"
    assert node.model == "fallback-model"
    assert "preferred-model failed with RuntimeError" in node.fallback_reason


def test_unknown_preset_uses_configured_fallback(tmp_path):
    from agent.orchestration.runtime import TaskPacket

    cfg = _config(
        tmp_path,
        roles={
            "engineer": {
                "models": [
                    {"preset": "removed-provider-preset", "model": "old-model"},
                    {"provider": "local", "model": "fallback-model"},
                ]
            }
        },
    )
    manager = _manager(
        tmp_path,
        config=cfg,
        scripts={
            "root-model": [_message("root")],
            "fallback-model": [_message("fallback")],
        },
    )
    root = manager.register_root("executive")
    result = manager.delegate(root.agent_id, "engineer", TaskPacket(objective="fallback"))
    node = manager.graph.get_node(result.agent_id)
    assert result.ok and node.model == "fallback-model"
    assert "unknown preset" in node.fallback_reason


def test_model_failure_after_tool_execution_does_not_replay_on_fallback(tmp_path):
    from agent.orchestration.runtime import TaskPacket

    cfg = _config(
        tmp_path,
        roles={
            "engineer": {
                "models": [
                    {"provider": "local", "model": "preferred-model"},
                    {"provider": "local", "model": "fallback-model"},
                ]
            }
        },
    )

    class ToolThenFailClient(ScriptedClient):
        def chat_completion(self, messages, **kwargs):
            if self._step == 0:
                self._step += 1
                return _message(tool_calls=[("read_file", {"file_path": "evidence.txt"})])
            raise RuntimeError("failed after a tool")

    fallback_started = []

    def factory(model_config):
        model = model_config.sub_model or model_config.model
        if model == "preferred-model":
            return ToolThenFailClient(model_config, {})
        fallback_started.append(model)
        return ScriptedClient(model_config, {model: [_message("must not run")]})

    (tmp_path / "evidence.txt").write_text("evidence", encoding="utf-8")
    manager = _manager(tmp_path, config=cfg)
    manager.client_factory = factory
    root = manager.register_root("executive")
    result = manager.delegate(root.agent_id, "engineer", TaskPacket(objective="no replay"))
    assert result.ok is False and "failed after a tool" in result.error
    assert fallback_started == []


def test_unavailable_role_model_reports_clear_failure(tmp_path):
    from agent.orchestration.runtime import OrchestrationError, TaskPacket

    cfg = _config(
        tmp_path,
        roles={"engineer": {"models": [{"provider": "missing", "model": "nope"}]}},
    )
    manager = _manager(
        tmp_path,
        config=cfg,
        availability=lambda _target, _cfg: (False, "provider unavailable"),
    )
    root = manager.register_root("executive")
    with pytest.raises(OrchestrationError, match="provider unavailable"):
        manager.delegate(root.agent_id, "engineer", TaskPacket(objective="cannot run"))


def test_preset_config_does_not_inherit_an_unrelated_generic_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "unrelated-local-key")
    config = LLMConfig.from_preset("codex-gpt-5.6-sol")
    assert config.provider == "openai"
    assert config.api_key is None


def test_advisor_is_separate_read_only_and_limited(tmp_path):
    from agent.orchestration.runtime import OrchestrationError

    cfg = _config(tmp_path, limits={"max_advisor_calls_per_agent": 1})
    manager = _manager(tmp_path, config=cfg)
    root = manager.register_root("executive")
    engineer = manager.delegate(
        root.agent_id,
        "engineer",
        {"objective": "own the implementation"},
    )
    advice = manager.consult(
        engineer.agent_id,
        "executive",
        question="Review the boundary",
        context={"evidence": "one failing assertion", "hypothesis": "race"},
    )
    advisor = manager.graph.get_node(advice.agent_id)
    assert advice.ok and advisor.relationship == "advisor"
    assert advisor.workspace_read_only is True
    assert manager.graph.get_node(engineer.agent_id).status == "completed"

    with pytest.raises(OrchestrationError, match="advisor call limit"):
        manager.consult(engineer.agent_id, "executive", "Ask again", {})


def test_unauthorized_advisor_is_rejected(tmp_path):
    from agent.orchestration.runtime import OrchestrationError

    manager = _manager(tmp_path)
    root = manager.register_root("executive")
    with pytest.raises(OrchestrationError, match="advisor.*not allowed"):
        manager.consult(root.agent_id, "specialist", "Can you advise?", {})


def test_routing_is_inspectable_and_accounts_for_economics(tmp_path):
    from agent.orchestration.runtime import RoutingInput

    manager = _manager(tmp_path)
    direct = manager.route(RoutingInput(task="rename one variable", implementation_scope=1))
    parallel = manager.route(
        RoutingInput(
            task="audit auth, tenancy, and secrets independently",
            complexity=8,
            parallelizable_workstreams=3,
            risk=8,
        )
    )
    advisor = manager.route(
        RoutingInput(task="choose a security boundary", ambiguity=9, implementation_scope=2)
    )
    assert direct.action == "direct" and "overhead" in direct.reason
    assert parallel.action == "parallel" and parallel.role
    assert advisor.action == "advisor" and advisor.role


def test_routing_handles_fallback_escalation_capacity_and_cheapest_role(tmp_path):
    from agent.orchestration.runtime import RoutingInput

    manager = _manager(tmp_path)
    fallback = manager.route(RoutingInput(task="dispatch", model_available=False))
    escalation = manager.route(RoutingInput(task="recover", previous_failures=3, risk=9))
    specialist = manager.route(
        RoutingInput(task="isolated lookup", complexity=7, implementation_scope=1)
    )
    at_capacity = manager.route(
        RoutingInput(
            task="parallel audit",
            parallelizable_workstreams=3,
            current_worker_count=manager.config.limits.max_concurrent_agents,
        )
    )
    assert fallback.action == "fallback"
    assert escalation.action == "escalate" and escalation.role == "executive"
    assert specialist.action == "delegate" and specialist.role == "specialist"
    assert at_capacity.action == "direct"


def test_routing_modes_adjust_advisor_and_hierarchy_thresholds(tmp_path):
    from agent.orchestration.runtime import RoutingInput

    advisor_manager = _manager(tmp_path, config=_config(tmp_path, mode="advisor"))
    hierarchy_manager = _manager(tmp_path, config=_config(tmp_path, mode="hierarchy"))
    assert advisor_manager.route(RoutingInput(task="decide", ambiguity=5)).action == "advisor"
    hierarchy = hierarchy_manager.route(RoutingInput(task="workstream", complexity=5))
    assert hierarchy.action == "delegate"


def test_cancellation_propagates_to_worker_registry(tmp_path):
    from agent.orchestration.runtime import OrchestrationCancelled, TaskPacket

    cancel = threading.Event()
    cancel.set()
    manager = _manager(tmp_path, cancel_event=cancel)
    root = manager.register_root("executive")
    with pytest.raises(OrchestrationCancelled):
        manager.delegate(root.agent_id, "engineer", TaskPacket(objective="stop"))


def test_cancellation_during_model_call_records_cancelled_and_cleans_up(tmp_path):
    from agent.orchestration.runtime import OrchestrationCancelled, TaskPacket

    cancel = threading.Event()

    class CancellingClient(ScriptedClient):
        def chat_completion(self, messages, **kwargs):
            cancel.set()
            raise RuntimeError("provider stopped")

    manager = _manager(tmp_path, cancel_event=cancel)
    manager.client_factory = lambda model_config: CancellingClient(model_config, {})
    root = manager.register_root("executive")
    with pytest.raises(OrchestrationCancelled):
        manager.delegate(root.agent_id, "engineer", TaskPacket(objective="stop during call"))
    child = manager.graph.snapshot()["nodes"][-1]
    assert child["status"] == "cancelled"
    assert manager._active_agents == 1
    assert set(manager.workspaces._leases) == {root.agent_id}


def test_invalid_workspace_mode_does_not_reserve_an_agent(tmp_path):
    from agent.orchestration.runtime import OrchestrationError

    manager = _manager(tmp_path)
    root = manager.register_root("executive")
    with pytest.raises(OrchestrationError, match="workspace mode"):
        manager.delegate(root.agent_id, "engineer", "work", workspace_mode="shared")
    assert len(manager.graph.snapshot()["nodes"]) == 1
    assert manager._active_agents == 1


def test_workspace_lease_ownership_and_read_only_advisor(tmp_path, monkeypatch):
    from agent.orchestration.runtime import WorkspaceLease, WorkspaceManager

    workspace = WorkspaceManager(tmp_path)
    parent = workspace.inherit(owner_id="root", path=tmp_path, writable=True)
    child = workspace.inherit(owner_id="child", parent=parent, writable=False)
    assert child.path == parent.path and child.owned is False
    assert workspace.release(child, requester_id="child") is False
    assert tmp_path.exists()

    with pytest.raises(PermissionError, match="owner"):
        workspace.release(parent, requester_id="child")

    forged = WorkspaceLease(
        path=tmp_path.parent, owner_id="forged", mode="branch", writable=True, owned=True
    )
    workspace._leases["forged"] = forged
    with pytest.raises(PermissionError, match="outside"):
        workspace.release(forged, requester_id="forged")


def test_branch_acquisition_failure_releases_reservation(tmp_path, monkeypatch):
    from agent.orchestration.runtime import OrchestrationError

    manager = _manager(tmp_path)
    root = manager.register_root("executive")

    def fail(*args, **kwargs):
        raise OrchestrationError("worktree unavailable")

    monkeypatch.setattr(manager.workspaces, "acquire_branch", fail)
    result = manager.delegate(
        root.agent_id,
        "engineer",
        "isolated change",
        workspace_mode="branch",
        require_isolation=True,
    )
    assert result.ok is False and "worktree unavailable" in result.error
    assert manager._active_agents == 1
    assert set(manager.workspaces._leases) == {root.agent_id}


def test_parallel_mutating_siblings_require_isolation(tmp_path):
    from agent.orchestration.runtime import OrchestrationError, TaskPacket

    manager = _manager(tmp_path)
    root = manager.register_root("executive")
    tasks = [
        {"role": "engineer", "task": TaskPacket(objective="edit a"), "workspace_mode": "inherit"},
        {"role": "engineer", "task": TaskPacket(objective="edit b"), "workspace_mode": "inherit"},
    ]
    with pytest.raises(OrchestrationError, match="mutating siblings"):
        manager.spawn_parallel(root.agent_id, tasks)


def test_recursive_hierarchy_returns_distilled_results_and_graph(tmp_path):
    from agent.orchestration.runtime import TaskPacket

    scripts = {
        "root-model": [_message("root")],
        "claude-opus-5": [
            _message(tool_calls=[("delegate_agent", {"role": "engineer", "objective": "build"})]),
            _message("manager reviewed engineer evidence"),
        ],
        "claude-sonnet-5": [
            _message(
                tool_calls=[("delegate_agent", {"role": "specialist", "objective": "inspect"})]
            ),
            _message("engineer integrated specialist evidence"),
        ],
        "claude-haiku-4.5": [_message("specialist evidence")],
    }
    manager = _manager(tmp_path, scripts=scripts)
    root = manager.register_root("executive")
    result = manager.delegate(root.agent_id, "manager", TaskPacket(objective="own workstream"))
    assert result.ok and "reviewed" in result.output
    snapshot = manager.graph.snapshot()
    delegation = [n for n in snapshot["nodes"] if n["relationship"] == "delegation"]
    assert [n["role"] for n in delegation] == ["manager", "engineer", "specialist"]
    assert [n["depth"] for n in delegation] == [1, 2, 3]


def test_engineer_can_delegate_parallel_bounded_specialists(tmp_path):
    from agent.orchestration.runtime import TaskPacket

    scripts = {
        "root-model": [_message("root")],
        "claude-sonnet-5": [
            _message(
                tool_calls=[
                    (
                        "delegate_parallel",
                        {
                            "tasks": [
                                {"role": "researcher", "objective": "map calls"},
                                {"role": "reviewer", "objective": "review boundary"},
                            ]
                        },
                    )
                ]
            ),
            _message("engineer synthesized both reports"),
        ],
        "claude-haiku-4.5": [_message("bounded evidence")],
    }
    manager = _manager(tmp_path, scripts=scripts)
    root = manager.register_root("executive")
    result = manager.delegate(root.agent_id, "engineer", TaskPacket(objective="own work"))
    nodes = manager.graph.snapshot()["nodes"]
    engineer = next(node for node in nodes if node["role"] == "engineer")
    specialists = [node for node in nodes if node["role"] in {"researcher", "reviewer"}]
    assert result.ok and "synthesized" in result.output
    assert len(specialists) == 2
    assert all(node["parent_agent_id"] == engineer["agent_id"] for node in specialists)


def test_direct_executive_to_engineer_and_engineer_to_advisor(tmp_path):
    from agent.orchestration.runtime import TaskPacket

    scripts = {
        "root-model": [_message("root")],
        "claude-sonnet-5": [
            _message(
                tool_calls=[
                    (
                        "consult_advisor",
                        {
                            "advisor_role": "executive",
                            "question": "Review this plan",
                            "evidence": "two options",
                            "hypothesis": "option A",
                        },
                    )
                ]
            ),
            _message("executor retained ownership"),
        ],
        "claude-fable-5": [_message("advisor guidance")],
    }
    manager = _manager(tmp_path, scripts=scripts)
    root = manager.register_root("executive")
    result = manager.delegate(root.agent_id, "engineer", TaskPacket(objective="execute"))
    snapshot = manager.graph.snapshot()
    assert result.ok and "retained ownership" in result.output
    assert any(edge["relationship"] == "advisor" for edge in snapshot["edges"])


def test_specialist_cannot_spawn_a_child_or_exceed_four_levels(tmp_path):
    from agent.orchestration.runtime import OrchestrationError, TaskPacket

    manager = _manager(tmp_path)
    root = manager.register_root("executive")
    manager_result = manager.delegate(root.agent_id, "manager", TaskPacket(objective="manager"))
    engineer_result = manager.delegate(
        manager_result.agent_id, "engineer", TaskPacket(objective="engineer")
    )
    specialist_result = manager.delegate(
        engineer_result.agent_id, "specialist", TaskPacket(objective="specialist")
    )
    with pytest.raises(OrchestrationError, match="not allowed"):
        manager.delegate(
            specialist_result.agent_id, "specialist", TaskPacket(objective="fifth level")
        )


def test_project_config_is_optional_and_headless_loads_enabled_mode(tmp_path):
    from agent.orchestration.config import OrchestrationConfig

    assert OrchestrationConfig.load(tmp_path).enabled is False
    config_dir = tmp_path / ".agnostic"
    config_dir.mkdir()
    (config_dir / "orchestration.json").write_text(
        json.dumps({"enabled": True, "mode": "advisor"}), encoding="utf-8"
    )
    loaded = OrchestrationConfig.load(tmp_path)
    assert loaded.enabled is True and loaded.mode == "advisor"


def test_legacy_subagent_manager_remains_compatible(tmp_path):
    from agent.tools.subagent import SubagentManager

    client = ScriptedClient(
        LLMConfig(provider="local", model="legacy-model"),
        {"legacy-model": [_message("legacy report")]},
    )
    manager = SubagentManager(client=client, workspace_root=str(tmp_path))
    report = manager.spawn("researcher", "Find files")
    assert "Subagent Report: RESEARCHER" in report
    assert "legacy report" in report


def test_disabled_orchestration_parallel_workers_inherit_root_model(tmp_path):
    from agent.tools.subagent import SubagentManager

    client = ScriptedClient(
        LLMConfig(provider="local", model="legacy-model"),
        {"legacy-model": [_message("legacy report")]},
    )
    manager = SubagentManager(client=client, workspace_root=str(tmp_path))
    reports = manager.spawn_parallel(
        [
            {"role": "researcher", "prompt": "find"},
            {"role": "reviewer", "prompt": "review"},
        ]
    )
    nodes = manager.orchestrator.graph.snapshot()["nodes"]
    assert all("legacy report" in report for report in reports)
    assert {node["model"] for node in nodes if node["relationship"] != "root"} == {"legacy-model"}


def test_enabled_agent_loop_registers_and_toggles_orchestration_tools(tmp_path):
    from agent.loop import AgentLoop

    config_dir = tmp_path / ".agnostic"
    config_dir.mkdir()
    (config_dir / "orchestration.json").write_text(json.dumps({"enabled": True}), encoding="utf-8")
    loop = AgentLoop(workspace_root=str(tmp_path))
    names = {tool["function"]["name"] for tool in loop.registry.get_openai_tools()}
    assert {"delegate_agent", "delegate_parallel", "route_task"} <= names
    assert "invoke_subagent" not in names
    assert "Adaptive Orchestration" in loop.history[0]["content"]

    loop.configure_orchestration(enabled=False)
    names = {tool["function"]["name"] for tool in loop.registry.get_openai_tools()}
    assert {
        "delegate_agent",
        "delegate_parallel",
        "consult_advisor",
        "route_task",
    }.isdisjoint(names)
    assert "invoke_subagent" in names
    assert "Adaptive Orchestration" not in loop.history[0]["content"]


def test_role_tool_permissions_and_bounded_specialist_mutation(tmp_path):
    from agent.orchestration.runtime import TaskPacket

    observed = {}

    class InspectingClient(ScriptedClient):
        def chat_completion(self, messages, tools=None, **kwargs):
            model = self.config.sub_model or self.config.model
            observed[model] = {item["function"]["name"] for item in tools or []}
            return _message("inspected")

    cfg = _config(
        tmp_path,
        roles={"specialist": {"additional_permissions": ["write", "edit"]}},
    )
    manager = _manager(tmp_path, config=cfg)
    manager.client_factory = lambda model_config: InspectingClient(model_config, {})
    root = manager.register_root("executive")
    manager.delegate(root.agent_id, "researcher", TaskPacket(objective="read"))
    researcher_tools = observed["claude-haiku-4.5"]
    assert "read_file" in researcher_tools
    assert "write_file" not in researcher_tools
    assert "delegate_agent" not in researcher_tools

    manager.delegate(root.agent_id, "specialist", TaskPacket(objective="bounded edit"))
    specialist_tools = observed["claude-haiku-4.5"]
    assert {"write_file", "apply_patch"} <= specialist_tools
    assert "delegate_agent" not in specialist_tools


def test_secret_guard_still_blocks_child_write(tmp_path):
    from agent.orchestration.runtime import TaskPacket

    cfg = _config(
        tmp_path,
        roles={"specialist": {"additional_permissions": ["write"]}},
    )
    scripts = {
        "root-model": [_message("root")],
        "claude-haiku-4.5": [
            _message(tool_calls=[("write_file", {"file_path": ".env", "content": "SECRET=x"})]),
            _message("guard evidence preserved"),
        ],
    }
    manager = _manager(tmp_path, config=cfg, scripts=scripts)
    root = manager.register_root("executive")
    result = manager.delegate(root.agent_id, "specialist", TaskPacket(objective="try secret"))
    assert result.ok
    assert not (tmp_path / ".env").exists()


def test_model_call_limit_stops_recursive_work(tmp_path):
    from agent.orchestration.runtime import TaskPacket

    cfg = _config(tmp_path, limits={"max_model_calls": 1})
    scripts = {
        "root-model": [_message("root")],
        "claude-sonnet-5": [
            _message(tool_calls=[("delegate_agent", {"role": "specialist", "objective": "more"})]),
            _message("should not finish"),
        ],
        "claude-haiku-4.5": [_message("child")],
    }
    manager = _manager(tmp_path, config=cfg, scripts=scripts)
    root = manager.register_root("executive")
    result = manager.delegate(root.agent_id, "engineer", TaskPacket(objective="bounded"))
    assert result.ok is False
    assert "maximum total model calls" in result.error


def test_child_and_advisor_failures_are_observable(tmp_path):
    from agent.orchestration.runtime import TaskPacket

    class FailingClient(ScriptedClient):
        def chat_completion(self, messages, **kwargs):
            raise RuntimeError("provider exploded")

    manager = _manager(tmp_path)
    manager.client_factory = lambda model_config: FailingClient(model_config, {})
    root = manager.register_root("executive")
    child = manager.delegate(root.agent_id, "engineer", TaskPacket(objective="fail"))
    assert child.ok is False and "provider exploded" in child.error
    assert manager.graph.get_node(child.agent_id).status == "failed"

    advisor = manager.consult(child.agent_id, "executive", "diagnose", {"evidence": child.error})
    assert advisor.ok is False and "provider exploded" in advisor.error
    assert manager.graph.get_node(advisor.agent_id).status == "failed"


def test_parent_failure_preserves_completed_child_evidence(tmp_path):
    from agent.orchestration.runtime import TaskPacket

    class ManagerClient(ScriptedClient):
        def chat_completion(self, messages, **kwargs):
            if self._step == 0:
                self._step += 1
                return _message(
                    tool_calls=[("delegate_agent", {"role": "engineer", "objective": "build"})]
                )
            raise RuntimeError("manager synthesis failed")

    def factory(model_config):
        model = model_config.sub_model or model_config.model
        if model == "claude-opus-5":
            return ManagerClient(model_config, {})
        return ScriptedClient(model_config, {model: [_message("child evidence")]})

    manager = _manager(tmp_path)
    manager.client_factory = factory
    root = manager.register_root("executive")
    result = manager.delegate(root.agent_id, "manager", TaskPacket(objective="own"))
    nodes = manager.graph.snapshot()["nodes"]
    child = next(node for node in nodes if node["role"] == "engineer")
    assert result.ok is False and "synthesis failed" in result.error
    assert child["status"] == "completed"


def test_child_registry_honors_current_trust_tier(tmp_path):
    from agent.governance.guard import guard
    from agent.tools.registry import ToolRegistry

    previous = guard.get_trust_tier()
    try:
        guard.set_trust_tier("strict")
        registry = ToolRegistry(
            workspace_root=str(tmp_path),
            allowed_tools={"run_command"},
            load_mcp=False,
        )
        result = registry.execute(
            "run_command",
            {"command": "git reset --hard HEAD"},
            confirm_callback=lambda _prompt: False,
        )
        assert result.is_error and any(
            word in result.output.lower() for word in ("rejected", "blocked")
        )
        assert registry._active_guard().get_trust_tier() == "strict"
    finally:
        guard.set_trust_tier(previous)


def test_child_shell_cannot_select_an_outside_workspace_cwd(tmp_path):
    from agent.tools.registry import ToolRegistry

    registry = ToolRegistry(
        workspace_root=str(tmp_path),
        allowed_tools={"run_command"},
        load_mcp=False,
    )
    result = registry.execute(
        "run_command",
        {"command": "echo should-not-run", "cwd": ".."},
        confirm_callback=lambda _prompt: True,
    )
    assert result.is_error and "outside the workspace" in result.output


def test_branch_worker_patch_is_preserved_and_owned_worktree_is_cleaned(tmp_path):
    from agent.orchestration.runtime import TaskPacket
    from agent.governance.undo import undo_manager

    subprocess = pytest.importorskip("subprocess")
    for command in (
        ["git", "init"],
        ["git", "config", "user.email", "tests@example.invalid"],
        ["git", "config", "user.name", "Tests"],
    ):
        subprocess.run(command, cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "seed.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "seed.txt"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=tmp_path, check=True, capture_output=True)

    scripts = {
        "root-model": [_message("root")],
        "claude-sonnet-5": [
            _message(
                tool_calls=[("write_file", {"file_path": "child.txt", "content": "isolated\n"})]
            ),
            _message("implementation complete"),
        ],
    }
    manager = _manager(tmp_path, scripts=scripts)
    root = manager.register_root("executive")
    undo_count = len(undo_manager.history)
    result = manager.delegate(
        root.agent_id,
        "engineer",
        TaskPacket(objective="isolated implementation"),
        workspace_mode="branch",
    )
    assert result.ok and result.workspace_artifact
    assert not (tmp_path / "child.txt").exists()
    assert "child.txt" in (tmp_path / result.workspace_artifact).read_text(encoding="utf-8")
    worktrees = tmp_path / ".agnostic" / "worktrees"
    assert not worktrees.exists() or not any(worktrees.iterdir())
    assert len(undo_manager.history) == undo_count


def test_graph_telemetry_has_parent_root_model_and_advisor_edges(tmp_path):
    manager = _manager(tmp_path)
    root = manager.register_root("executive")
    engineer = manager.delegate(root.agent_id, "engineer", "implement")
    manager.consult(engineer.agent_id, "executive", "review", {"evidence": "diff"})
    snapshot = manager.graph.snapshot()
    child = next(node for node in snapshot["nodes"] if node["role"] == "engineer")
    assert child["parent_agent_id"] == root.agent_id
    assert child["root_agent_id"] == root.agent_id
    assert child["provider"] and child["model"]
    assert any(edge["relationship"] == "advisor" for edge in snapshot["edges"])


def test_telemetry_callback_receives_each_lifecycle_event_once(tmp_path):
    events = []
    manager = _manager(tmp_path)
    manager.telemetry_callback = lambda event, message: events.append((event, message))
    root = manager.register_root("executive")
    manager.delegate(root.agent_id, "researcher", "inspect")
    assert [event for event, _ in events] == ["agent_start", "agent_end"]
