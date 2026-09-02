"""Execution graph, routing, workspace leases, and bounded agent executor."""

from __future__ import annotations

import concurrent.futures
import json
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

from agent.llm.client import LLMClient, LLMConfig
from agent.orchestration.config import ModelTarget, OrchestrationConfig, RoleProfile
from agent.tools.registry import ToolRegistry, ToolResult, parse_tool_args


class OrchestrationError(RuntimeError):
    """A programmatic orchestration boundary rejected an operation."""


class OrchestrationCancelled(OrchestrationError):
    """The root cancellation signal stopped an orchestration operation."""


@dataclass(frozen=True)
class TaskPacket:
    objective: str
    scope: str = ""
    constraints: tuple[str, ...] = ()
    relevant_files: tuple[str, ...] = ()
    evidence: str = ""
    definition_of_done: tuple[str, ...] = ()
    parent_expectations: str = "Return a concise result with evidence and remaining uncertainty."

    @classmethod
    def coerce(cls, value: Any) -> "TaskPacket":
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            return cls(objective=value)
        if not isinstance(value, Mapping):
            raise OrchestrationError("task must be a TaskPacket, string, or object")
        objective = str(value.get("objective", "")).strip()
        if not objective:
            raise OrchestrationError("task objective is required")

        def strings(key: str):
            item = value.get(key, ())
            if isinstance(item, str):
                return (item,) if item else ()
            return tuple(str(part) for part in (item or ()))

        return cls(
            objective=objective,
            scope=str(value.get("scope", "")),
            constraints=strings("constraints"),
            relevant_files=strings("relevant_files"),
            evidence=str(value.get("evidence", "")),
            definition_of_done=strings("definition_of_done"),
            parent_expectations=str(
                value.get(
                    "parent_expectations",
                    "Return a concise result with evidence and remaining uncertainty.",
                )
            ),
        )

    def render(self) -> str:
        rows = [f"Objective: {self.objective}"]
        if self.scope:
            rows.append(f"Scope: {self.scope}")
        if self.constraints:
            rows.append("Constraints:\n- " + "\n- ".join(self.constraints))
        if self.relevant_files:
            rows.append("Relevant files:\n- " + "\n- ".join(self.relevant_files))
        if self.evidence:
            rows.append(f"Known evidence:\n{self.evidence}")
        if self.definition_of_done:
            rows.append("Definition of done:\n- " + "\n- ".join(self.definition_of_done))
        rows.append(f"Parent expectation: {self.parent_expectations}")
        return "\n\n".join(rows)


@dataclass(frozen=True)
class AgentResult:
    agent_id: str
    role: str
    output: str
    ok: bool = True
    error: str = ""
    workspace_artifact: str = ""

    def report(self) -> str:
        state = "" if self.ok else " - ERROR"
        suffix = f"\nWorkspace patch: {self.workspace_artifact}" if self.workspace_artifact else ""
        body = self.output if self.ok else self.error or self.output
        return f"### [Subagent Report: {self.role.upper()}{state}]\n{body}{suffix}\n"


@dataclass
class WorkspaceLease:
    path: Path
    owner_id: str
    mode: str
    writable: bool
    owned: bool = False
    note: str = ""


class WorkspaceManager:
    """Owns worktree leases; only the recorded owner may remove one."""

    def __init__(self, workspace_root: Path):
        self.workspace_root = Path(workspace_root).resolve()
        self._leases: Dict[str, WorkspaceLease] = {}
        self._lock = threading.RLock()

    def inherit(
        self,
        owner_id: str,
        parent: Optional[WorkspaceLease] = None,
        path: Optional[Path] = None,
        writable: bool = False,
    ) -> WorkspaceLease:
        lease = WorkspaceLease(
            path=Path(path or (parent.path if parent else self.workspace_root)).resolve(),
            owner_id=owner_id,
            mode="inherit",
            writable=writable,
            owned=False,
        )
        with self._lock:
            self._leases[owner_id] = lease
        return lease

    def acquire_branch(
        self,
        owner_id: str,
        parent: WorkspaceLease,
        writable: bool,
        require_isolation: bool = False,
    ) -> WorkspaceLease:
        worktree_dir = self.workspace_root / ".agnostic" / "worktrees" / owner_id
        worktree_dir.parent.mkdir(parents=True, exist_ok=True)
        try:
            result = subprocess.run(
                ["git", "worktree", "add", "--detach", str(worktree_dir), "HEAD"],
                cwd=self.workspace_root,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            result = None
            failure = str(exc)
        else:
            failure = (result.stderr or result.stdout or "git worktree creation failed").strip()
        if result is not None and result.returncode == 0 and worktree_dir.exists():
            lease = WorkspaceLease(
                path=worktree_dir.resolve(),
                owner_id=owner_id,
                mode="branch",
                writable=writable,
                owned=True,
            )
            with self._lock:
                self._leases[owner_id] = lease
            return lease
        if worktree_dir.exists():
            shutil.rmtree(worktree_dir, ignore_errors=True)
        if require_isolation:
            raise OrchestrationError(f"isolated workspace required but unavailable: {failure}")
        lease = self.inherit(owner_id=owner_id, parent=parent, writable=writable)
        lease.note = "isolated worktree unavailable; inherited the parent workspace"
        return lease

    def capture_patch(self, lease: WorkspaceLease) -> str:
        if not lease.owned or not lease.writable:
            return ""
        artifact_dir = self.workspace_root / ".agnostic" / "orchestration" / "patches"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                ["git", "add", "-N", "."],
                cwd=lease.path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            result = subprocess.run(
                ["git", "diff", "--binary", "HEAD"],
                cwd=lease.path,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        if result.returncode != 0 or not result.stdout.strip():
            return ""
        path = artifact_dir / f"{lease.owner_id}.diff"
        path.write_text(result.stdout, encoding="utf-8")
        return str(path.relative_to(self.workspace_root).as_posix())

    def release(self, lease: WorkspaceLease, requester_id: str) -> bool:
        if requester_id != lease.owner_id:
            raise PermissionError(
                f"workspace lease belongs to owner '{lease.owner_id}', not '{requester_id}'"
            )
        with self._lock:
            registered = self._leases.get(lease.owner_id)
        if registered is not lease:
            raise PermissionError("workspace lease is not the registered owner lease")
        if not lease.owned:
            with self._lock:
                self._leases.pop(lease.owner_id, None)
            return False
        worktree_root = (self.workspace_root / ".agnostic" / "worktrees").resolve()
        try:
            lease.path.resolve().relative_to(worktree_root)
        except ValueError as exc:
            raise PermissionError("owned workspace resolves outside the worktree root") from exc
        try:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(lease.path)],
                cwd=self.workspace_root,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            pass
        if lease.path.exists():
            shutil.rmtree(lease.path, ignore_errors=True)
        try:
            subprocess.run(
                ["git", "worktree", "prune"],
                cwd=self.workspace_root,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            pass
        with self._lock:
            self._leases.pop(lease.owner_id, None)
        return True


@dataclass
class AgentNode:
    agent_id: str
    parent_agent_id: Optional[str]
    root_agent_id: str
    role: str
    depth: int
    provider: str
    preset: Optional[str]
    model: str
    effort: str
    objective: str
    status: str
    workspace: str
    workspace_owner: str
    workspace_mode: str
    workspace_read_only: bool
    permissions: tuple[str, ...]
    allowed_child_roles: tuple[str, ...]
    allowed_advisor_roles: tuple[str, ...]
    relationship: str
    start_time: float
    completion_time: Optional[float] = None
    duration_s: Optional[float] = None
    detail: str = ""
    fallback_reason: str = ""
    children: list[str] = field(default_factory=list)
    advisor_calls: list[str] = field(default_factory=list)


class ExecutionGraph:
    def __init__(self):
        self._nodes: Dict[str, AgentNode] = {}
        self._edges: list[dict[str, str]] = []
        self._lock = threading.RLock()

    def add_node(self, node: AgentNode) -> None:
        with self._lock:
            if node.agent_id in self._nodes:
                raise OrchestrationError(f"duplicate agent id '{node.agent_id}'")
            if node.parent_agent_id and node.parent_agent_id not in self._nodes:
                raise OrchestrationError(f"unknown parent agent '{node.parent_agent_id}'")
            self._nodes[node.agent_id] = node
            if node.parent_agent_id:
                parent = self._nodes[node.parent_agent_id]
                bucket = parent.advisor_calls if node.relationship == "advisor" else parent.children
                bucket.append(node.agent_id)
                self._edges.append(
                    {
                        "source": node.parent_agent_id,
                        "target": node.agent_id,
                        "relationship": node.relationship,
                    }
                )

    def get_node(self, agent_id: str) -> AgentNode:
        with self._lock:
            try:
                return self._nodes[agent_id]
            except KeyError as exc:
                raise OrchestrationError(f"unknown agent '{agent_id}'") from exc

    def update(self, agent_id: str, status: str, detail: str = "") -> None:
        with self._lock:
            node = self.get_node(agent_id)
            node.status = status
            node.detail = detail
            if status in {"completed", "failed", "cancelled"}:
                node.completion_time = time.time()
                node.duration_s = max(0.0, node.completion_time - node.start_time)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "nodes": [asdict(node) for node in self._nodes.values()],
                "edges": [dict(edge) for edge in self._edges],
            }

    def list_subagents(self) -> list[dict[str, Any]]:
        rows = []
        for node in self.snapshot()["nodes"]:
            if node["relationship"] == "root":
                continue
            row = dict(node)
            row.update(
                {
                    "conversationId": node["agent_id"],
                    "type": node["role"],
                    "state": node["status"],
                }
            )
            rows.append(row)
        return rows


@dataclass(frozen=True)
class RoutingInput:
    task: str
    complexity: int = 3
    ambiguity: int = 2
    reasoning_quality: int = 3
    implementation_scope: int = 1
    parallelizable_workstreams: int = 1
    context_isolation_benefit: int = 1
    cost_sensitivity: int = 5
    latency_sensitivity: int = 5
    risk: int = 2
    previous_failures: int = 0
    current_depth: int = 0
    current_worker_count: int = 0
    required_tools: tuple[str, ...] = ()
    workspace_mutation: bool = False
    provider_available: bool = True
    model_available: bool = True


@dataclass(frozen=True)
class RoutingDecision:
    action: str
    role: Optional[str]
    reason: str
    signals: dict[str, Any]


PERMISSION_TO_TOOLS = {
    "read": {"read_file", "get_outline", "find_symbol", "read_project_memory"},
    "search": {"grep_search", "find_files", "read_url_content", "search_web"},
    "shell": {"run_command", "simulate_command"},
    "tests": set(),
    "write": {"write_file"},
    "edit": {"edit_file", "apply_patch"},
}


class AgentExecutor:
    """A fresh-context agent loop shared by delegation and advisor calls."""

    def __init__(
        self,
        manager: "OrchestrationManager",
        node: AgentNode,
        profile: RoleProfile,
        client: LLMClient,
        lease: WorkspaceLease,
        task: TaskPacket,
        advisor: bool = False,
        custom_instructions: str = "",
    ):
        self.manager = manager
        self.node = node
        self.profile = profile
        self.client = client
        self.lease = lease
        self.task = task
        self.advisor = advisor
        self.custom_instructions = custom_instructions

    def _system_prompt(self) -> str:
        relationship = (
            "You are a focused advisor. Return guidance only; ownership remains with the caller."
            if self.advisor
            else "You own this delegated task and must return a distilled result to your parent."
        )
        economics = (
            "Delegation has latency, cost, context, coordination, and merge overhead. Work directly "
            "for small or sequential tasks. Delegate only bounded work when the benefit is material."
        )
        return "\n\n".join(
            part
            for part in (
                self.profile.instructions,
                relationship,
                economics,
                self.custom_instructions,
            )
            if part
        )

    def _registry(self) -> ToolRegistry:
        permissions = set(self.profile.permissions)
        if self.advisor:
            permissions -= {"write", "edit", "shell", "tests", "orchestrate", "advisor"}
        allowed = set().union(*(PERMISSION_TO_TOOLS.get(item, set()) for item in permissions))
        registry = ToolRegistry(
            workspace_root=str(self.lease.path),
            cancel_event=self.manager.cancel_event,
            load_mcp=False,
            allowed_tools=allowed,
            record_undo=not self.lease.owned,
        )
        if not self.advisor:
            self.manager.register_agent_tools(registry, self.node.agent_id)
        return registry

    def run(self, max_turns: int = 8) -> AgentResult:
        messages = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": self.task.render()},
        ]
        registry = self._registry()
        tools_executed = False
        for _ in range(max_turns):
            self.manager.check_cancelled()
            self.manager.before_model_call()
            try:
                response = self.client.chat_completion(
                    messages=messages,
                    tools=registry.get_openai_tools(),
                    tool_choice="auto",
                    cancel_event=self.manager.cancel_event,
                )
            except Exception as exc:
                if self.manager.cancel_event.is_set():
                    raise OrchestrationCancelled("orchestration cancelled by user") from exc
                if not tools_executed:
                    fallback = self.manager.activate_fallback(self.node, self.profile, exc)
                    if fallback is not None:
                        self.client = fallback
                        continue
                raise
            message = response.choices[0].message
            if not message.tool_calls:
                return AgentResult(
                    agent_id=self.node.agent_id,
                    role=self.profile.name,
                    output=message.content or "[Worker finished with empty response]",
                )
            calls = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in message.tool_calls
            ]
            messages.append(
                {"role": "assistant", "content": message.content or "", "tool_calls": calls}
            )
            for call in message.tool_calls:
                if self.manager.cancel_event.is_set():
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": "[cancelled by user]",
                        }
                    )
                    continue
                args, error = parse_tool_args(call.function.arguments)
                result = (
                    ToolResult(error, is_error=True)
                    if error
                    else registry.execute(
                        call.function.name,
                        args,
                        confirm_callback=self.manager.confirm_callback,
                    )
                )
                tools_executed = True
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": result.output[:4000],
                    }
                )
        return AgentResult(
            agent_id=self.node.agent_id,
            role=self.profile.name,
            output="",
            ok=False,
            error=f"agent reached max turns limit ({max_turns})",
        )


class OrchestrationManager:
    """Canonical bounded runtime for hierarchy, advisors, flat workers, and swarms."""

    TOOL_NAMES = (
        "delegate_agent",
        "delegate_parallel",
        "consult_advisor",
        "route_task",
    )

    def __init__(
        self,
        root_client: LLMClient,
        workspace_root: Path,
        confirm_callback: Optional[Callable[[str], bool]] = None,
        cancel_event: Optional[threading.Event] = None,
        config: Optional[OrchestrationConfig] = None,
        client_factory: Callable[[LLMConfig], LLMClient] = LLMClient,
        availability: Optional[Callable[[ModelTarget, LLMConfig], tuple[bool, str]]] = None,
        telemetry_callback: Optional[Callable[[str, str], None]] = None,
    ):
        self.root_client = root_client
        self.workspace_root = Path(workspace_root).resolve()
        self.confirm_callback = confirm_callback
        self.cancel_event = cancel_event or threading.Event()
        self.config = config or OrchestrationConfig.load(self.workspace_root)
        self.client_factory = client_factory
        self.availability = availability or self._default_availability
        self.telemetry_callback = telemetry_callback
        self.graph = ExecutionGraph()
        self.workspaces = WorkspaceManager(self.workspace_root)
        self.root_id: Optional[str] = None
        self._lock = threading.RLock()
        self._active_children: Dict[str, int] = {}
        self._advisor_counts: Dict[str, int] = {}
        self._total_agents = 0
        self._active_agents = 0
        self._model_calls = 0

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def set_enabled(self, enabled: bool) -> None:
        self.config = self.config.with_runtime(enabled=enabled)

    def set_mode(self, mode: str) -> None:
        self.config = self.config.with_runtime(mode=mode)

    def register_root(self, role: Optional[str] = None) -> AgentNode:
        with self._lock:
            if self.root_id:
                return self.graph.get_node(self.root_id)
            role_name = role or self.config.root_role
            profile = self._profile(role_name)
            agent_id = "root_" + uuid.uuid4().hex[:8]
            lease = self.workspaces.inherit(
                owner_id=agent_id, path=self.workspace_root, writable=True
            )
            cfg = self.root_client.config
            node = AgentNode(
                agent_id=agent_id,
                parent_agent_id=None,
                root_agent_id=agent_id,
                role=role_name,
                depth=0,
                provider=cfg.provider,
                preset=getattr(cfg, "preset_key", None),
                model=cfg.display_model(),
                effort=cfg.reasoning_effort,
                objective="User-owned root task",
                status="running",
                workspace=str(lease.path),
                workspace_owner=lease.owner_id,
                workspace_mode=lease.mode,
                workspace_read_only=False,
                permissions=profile.permissions,
                allowed_child_roles=profile.allowed_children,
                allowed_advisor_roles=profile.allowed_advisors,
                relationship="root",
                start_time=time.time(),
            )
            self.graph.add_node(node)
            self.root_id = agent_id
            self._total_agents = 1
            self._active_agents = 1
            return node

    def _profile(self, role: str) -> RoleProfile:
        try:
            return self.config.roles[role]
        except KeyError as exc:
            raise OrchestrationError(f"unknown orchestration role '{role}'") from exc

    def check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise OrchestrationCancelled("orchestration cancelled by user")

    def before_model_call(self) -> None:
        self.check_cancelled()
        with self._lock:
            if self._model_calls >= self.config.limits.max_model_calls:
                raise OrchestrationError("maximum total model calls reached")
            self._model_calls += 1

    def _default_availability(self, target: ModelTarget, config: LLMConfig) -> tuple[bool, str]:
        if target.inherit:
            return True, "inherited parent model"
        if target.preset and target.preset not in LLMConfig.PRESETS:
            return False, f"unknown preset '{target.preset}'"
        if target.preset and not LLMConfig.preset_available(
            LLMConfig.PRESETS[target.preset], include_local=True
        ):
            return False, f"preset '{target.preset}' is unavailable"
        if (
            config.provider != "local"
            and not config.provider.endswith("-sub")
            and not config.api_key
        ):
            return False, f"provider '{config.provider}' has no configured API key"
        return True, "available"

    @staticmethod
    def _clone_config(config: LLMConfig) -> LLMConfig:
        clone = LLMConfig(
            base_url=config.base_url,
            api_key=config.api_key,
            model=config.model,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            reasoning_effort=config.reasoning_effort,
            provider=config.provider,
            context_window=config.context_window,
            timeout=config.timeout,
            max_retries=config.max_retries,
            retry_backoff=config.retry_backoff,
        )
        clone.sub_model = getattr(config, "sub_model", None)
        clone.preset_key = getattr(config, "preset_key", None)
        return clone

    def _config_for_target(self, target: ModelTarget, parent_client: LLMClient) -> LLMConfig:
        if target.inherit:
            config = self._clone_config(parent_client.config)
            if target.effort:
                config.reasoning_effort = target.effort
            return config
        if target.preset:
            try:
                return LLMConfig.from_preset(
                    target.preset,
                    model=target.model,
                    reasoning_effort=target.effort,
                    base_url=target.base_url,
                )
            except ValueError as exc:
                raise OrchestrationError(str(exc)) from exc
        if target.provider == parent_client.config.provider:
            config = self._clone_config(parent_client.config)
            if config.provider.endswith("-sub"):
                config.sub_model = target.model
            else:
                config.model = target.model
            config.base_url = target.base_url or config.base_url
            config.reasoning_effort = target.effort or config.reasoning_effort
            config.preset_key = None
            return config

        candidates = [
            key
            for key, preset in LLMConfig.PRESETS.items()
            if preset.get("provider") == target.provider
        ]
        exact = [key for key in candidates if LLMConfig.PRESETS[key].get("model") == target.model]
        if exact or candidates:
            return LLMConfig.from_preset(
                (exact or candidates)[0],
                model=target.model,
                reasoning_effort=target.effort,
                base_url=target.base_url,
            )

        config = LLMConfig(
            base_url=target.base_url or parent_client.config.base_url,
            api_key=parent_client.config.api_key if target.provider == "local" else None,
            model=target.model,
            reasoning_effort=target.effort or "medium",
            provider=target.provider,
            context_window=parent_client.config.context_window,
        )
        if target.provider != "local":
            config.api_key = None
        return config

    def _resolve_client(
        self, profile: RoleProfile, parent_client: LLMClient
    ) -> tuple[LLMClient, ModelTarget, str, int]:
        failures = []
        for index, target in enumerate(profile.models):
            try:
                config = self._config_for_target(target, parent_client)
            except OrchestrationError as exc:
                failures.append(str(exc))
                continue
            available, reason = self.availability(target, config)
            if available:
                fallback_reason = "; ".join(failures) if index else ""
                try:
                    client = self.client_factory(config)
                except Exception as exc:
                    failures.append(f"target initialization failed with {type(exc).__name__}")
                    continue
                return client, target, fallback_reason, index
            failures.append(reason)
        raise OrchestrationError(
            f"no available model for role '{profile.name}': " + "; ".join(failures)
        )

    def activate_fallback(
        self, node: AgentNode, profile: RoleProfile, error: Exception
    ) -> Optional[LLMClient]:
        """Select the next available target before any worker tool has executed."""
        current_index = int(getattr(node, "_target_index", 0))
        reasons = [part for part in [node.fallback_reason] if part]
        reasons.append(f"{node.provider}/{node.model} failed with {type(error).__name__}")
        parent = self.graph.get_node(node.parent_agent_id) if node.parent_agent_id else node
        parent_client = self._parent_client(parent)
        for index in range(current_index + 1, len(profile.models)):
            target = profile.models[index]
            try:
                config = self._config_for_target(target, parent_client)
            except OrchestrationError as exc:
                reasons.append(str(exc))
                continue
            available, reason = self.availability(target, config)
            if not available:
                reasons.append(reason)
                continue
            try:
                client = self.client_factory(config)
            except Exception as exc:
                reasons.append(f"fallback initialization failed with {type(exc).__name__}")
                continue
            with self._lock:
                node.provider = client.config.provider
                node.preset = getattr(client.config, "preset_key", None)
                node.model = client.config.sub_model or client.config.model
                node.effort = client.config.reasoning_effort
                node.fallback_reason = "; ".join(reasons)
                setattr(node, "_client", client)
                setattr(node, "_target_index", index)
            self._emit(
                "agent_fallback",
                f"{node.agent_id} role={node.role} model={node.model} reason={node.fallback_reason}",
            )
            return client
        return None

    def _parent_client(self, parent: AgentNode) -> LLMClient:
        client = getattr(parent, "_client", None)
        return client or self.root_client

    def _reserve(
        self,
        parent: AgentNode,
        role: str,
        relationship: str,
        inherit_model: bool = False,
    ) -> tuple[AgentNode, RoleProfile, LLMClient, WorkspaceLease]:
        self.check_cancelled()
        profile = self._profile(role)
        if inherit_model:
            profile = replace(profile, models=(ModelTarget(inherit=True),))
        with self._lock:
            allowed = (
                parent.allowed_advisor_roles
                if relationship == "advisor"
                else parent.allowed_child_roles
            )
            label = "advisor" if relationship == "advisor" else "child"
            if role not in allowed:
                raise OrchestrationError(
                    f"{label} role '{role}' is not allowed for '{parent.role}'"
                )
            depth = parent.depth + 1
            if relationship == "delegation" and depth > self.config.limits.max_depth:
                raise OrchestrationError("maximum delegation depth reached")
            if self._total_agents >= self.config.limits.max_total_agents:
                raise OrchestrationError("maximum total agents reached")
            if self._active_agents >= self.config.limits.max_concurrent_agents:
                raise OrchestrationError("maximum concurrent agents reached")
            if relationship == "delegation":
                if len(parent.children) >= self.config.limits.max_children_per_agent:
                    raise OrchestrationError("maximum children per agent reached")
                parallel_limit = min(
                    self.config.limits.max_parallel_children,
                    self.config.limits.max_children_per_agent,
                )
                if self._active_children.get(parent.agent_id, 0) >= parallel_limit:
                    raise OrchestrationError("maximum parallel children reached")
                self._active_children[parent.agent_id] = (
                    self._active_children.get(parent.agent_id, 0) + 1
                )
            else:
                calls = self._advisor_counts.get(parent.agent_id, 0)
                if calls >= self.config.limits.max_advisor_calls_per_agent:
                    raise OrchestrationError("advisor call limit reached")
                self._advisor_counts[parent.agent_id] = calls + 1
            self._total_agents += 1
            self._active_agents += 1

        try:
            client, _target, fallback_reason, target_index = self._resolve_client(
                profile, self._parent_client(parent)
            )
        except Exception:
            self._release_counts(parent.agent_id, relationship)
            with self._lock:
                self._total_agents -= 1
            raise
        agent_id = ("adv_" if relationship == "advisor" else "agent_") + uuid.uuid4().hex[:8]
        parent_lease = self.workspaces._leases.get(parent.workspace_owner)
        if parent_lease is None:
            parent_path = Path(parent.workspace)
            if not parent_path.exists():
                parent_path = self.workspace_root
            parent_lease = WorkspaceLease(
                path=parent_path,
                owner_id=parent.workspace_owner,
                mode=parent.workspace_mode,
                writable=not parent.workspace_read_only,
                owned=False,
            )
        writable = profile.can_mutate and relationship != "advisor"
        workspace_mode = "inherit" if relationship == "advisor" else profile.workspace_mode
        lease = self.workspaces.inherit(agent_id, parent=parent_lease, writable=writable)
        node = AgentNode(
            agent_id=agent_id,
            parent_agent_id=parent.agent_id,
            root_agent_id=parent.root_agent_id,
            role=role,
            depth=depth,
            provider=client.config.provider,
            preset=getattr(client.config, "preset_key", None),
            model=client.config.sub_model or client.config.model,
            effort=client.config.reasoning_effort,
            objective="",
            status="waiting",
            workspace=str(lease.path),
            workspace_owner=lease.owner_id,
            workspace_mode=workspace_mode,
            workspace_read_only=not writable,
            permissions=tuple(
                item
                for item in profile.permissions
                if not relationship == "advisor" or item in {"read", "search"}
            ),
            allowed_child_roles=() if relationship == "advisor" else profile.allowed_children,
            allowed_advisor_roles=() if relationship == "advisor" else profile.allowed_advisors,
            relationship=relationship,
            start_time=time.time(),
            fallback_reason=fallback_reason,
        )
        setattr(node, "_client", client)
        setattr(node, "_target_index", target_index)
        self.graph.add_node(node)
        return node, profile, client, lease

    def _release_counts(self, parent_id: str, relationship: str) -> None:
        with self._lock:
            self._active_agents = max(0, self._active_agents - 1)
            if relationship == "delegation":
                self._active_children[parent_id] = max(
                    0, self._active_children.get(parent_id, 1) - 1
                )

    def _emit(self, event: str, message: str) -> None:
        if self.telemetry_callback:
            try:
                self.telemetry_callback(event, message)
            except Exception:
                pass
            return
        try:
            from agent.web.server import companion_telemetry

            companion_telemetry.log_event(event, message)
        except ImportError:
            pass

    def delegate(
        self,
        parent_id: str,
        role: str,
        task: Any,
        custom_instructions: str = "",
        workspace_mode: Optional[str] = None,
        max_turns: int = 8,
        require_isolation: bool = False,
        inherit_model: bool = False,
    ) -> AgentResult:
        packet = TaskPacket.coerce(task)
        parent = self.graph.get_node(parent_id)
        requested_profile = self._profile(role)
        mode = workspace_mode or requested_profile.workspace_mode
        if mode not in {"inherit", "branch"}:
            raise OrchestrationError("workspace mode must be inherit or branch")
        node, profile, client, lease = self._reserve(
            parent, role, "delegation", inherit_model=inherit_model
        )
        node.objective = packet.objective
        artifact = ""
        try:
            if mode == "branch":
                self.workspaces.release(lease, node.agent_id)
                lease = None
                parent_lease = self.workspaces._leases.get(parent.workspace_owner)
                if parent_lease is None:
                    parent_path = Path(parent.workspace)
                    parent_lease = WorkspaceLease(
                        path=parent_path if parent_path.exists() else self.workspace_root,
                        owner_id=parent.workspace_owner,
                        mode=parent.workspace_mode,
                        writable=not parent.workspace_read_only,
                        owned=False,
                    )
                lease = self.workspaces.acquire_branch(
                    node.agent_id,
                    parent_lease,
                    writable=profile.can_mutate,
                    require_isolation=require_isolation,
                )
                node.workspace = str(lease.path)
                node.workspace_mode = lease.mode
                node.workspace_owner = lease.owner_id
                node.workspace_read_only = not lease.writable
                if lease.note:
                    node.detail = lease.note
            self.graph.update(node.agent_id, "running", node.detail)
            self._emit(
                "agent_start",
                f"{node.agent_id} role={role} parent={parent_id} model={node.model} depth={node.depth}",
            )
            result = AgentExecutor(
                self,
                node,
                profile,
                client,
                lease,
                packet,
                custom_instructions=custom_instructions,
            ).run(max_turns=max_turns)
            artifact = self.workspaces.capture_patch(lease)
            result = AgentResult(
                agent_id=result.agent_id,
                role=result.role,
                output=result.output,
                ok=result.ok,
                error=result.error,
                workspace_artifact=artifact,
            )
            self.graph.update(node.agent_id, "completed" if result.ok else "failed", result.error)
            return result
        except OrchestrationCancelled:
            self.graph.update(node.agent_id, "cancelled", "cancelled by root")
            raise
        except Exception as exc:
            if self.cancel_event.is_set():
                self.graph.update(node.agent_id, "cancelled", "cancelled by root")
                raise OrchestrationCancelled("orchestration cancelled by user") from exc
            self.graph.update(node.agent_id, "failed", str(exc))
            return AgentResult(node.agent_id, role, "", ok=False, error=str(exc))
        finally:
            self._emit(
                "agent_end",
                f"{node.agent_id} role={role} status={self.graph.get_node(node.agent_id).status}",
            )
            if lease is not None:
                self.workspaces.release(lease, node.agent_id)
            self._release_counts(parent_id, "delegation")

    def consult(
        self,
        caller_id: str,
        advisor_role: str,
        question: str,
        context: Mapping[str, Any],
        max_turns: int = 4,
    ) -> AgentResult:
        if not str(question).strip():
            raise OrchestrationError("advisor question is required")
        if not isinstance(context, Mapping):
            raise OrchestrationError("advisor context must be an object")
        caller = self.graph.get_node(caller_id)
        node, profile, client, lease = self._reserve(caller, advisor_role, "advisor")
        node.objective = str(question).strip()
        try:
            focused_evidence = []
            for key in ("evidence", "hypothesis", "constraints", "decision"):
                if context.get(key):
                    focused_evidence.append(f"{key.replace('_', ' ').title()}: {context[key]}")
            packet = TaskPacket(
                objective=str(question).strip(),
                constraints=("Return guidance; do not take ownership or modify the workspace.",),
                evidence="\n".join(focused_evidence),
                parent_expectations=(
                    "Address the requested decision. State assumptions, risks, and a recommended next step."
                ),
                scope=str(context.get("scope", "")),
            )
            self.graph.update(node.agent_id, "running")
            self._emit(
                "advisor_start",
                f"{node.agent_id} advisor={advisor_role} caller={caller_id} model={node.model}",
            )
            result = AgentExecutor(self, node, profile, client, lease, packet, advisor=True).run(
                max_turns=max_turns
            )
            self.graph.update(node.agent_id, "completed" if result.ok else "failed", result.error)
            return result
        except OrchestrationCancelled:
            self.graph.update(node.agent_id, "cancelled", "cancelled by root")
            raise
        except Exception as exc:
            if self.cancel_event.is_set():
                self.graph.update(node.agent_id, "cancelled", "cancelled by root")
                raise OrchestrationCancelled("orchestration cancelled by user") from exc
            self.graph.update(node.agent_id, "failed", str(exc))
            return AgentResult(node.agent_id, advisor_role, "", ok=False, error=str(exc))
        finally:
            self._emit(
                "advisor_end",
                f"{node.agent_id} advisor={advisor_role} status={self.graph.get_node(node.agent_id).status}",
            )
            self.workspaces.release(lease, node.agent_id)
            self._release_counts(caller_id, "advisor")

    def spawn_parallel(
        self, parent_id: str, tasks: Sequence[Mapping[str, Any]]
    ) -> list[AgentResult]:
        if not tasks:
            return []
        parent = self.graph.get_node(parent_id)
        with self._lock:
            remaining_children = self.config.limits.max_children_per_agent - len(parent.children)
            remaining_total = self.config.limits.max_total_agents - self._total_agents
            remaining_active = self.config.limits.max_concurrent_agents - self._active_agents
        batch_limit = min(
            self.config.limits.max_parallel_children,
            remaining_children,
            remaining_total,
            remaining_active,
        )
        if len(tasks) > batch_limit:
            raise OrchestrationError("maximum parallel children exceeded")
        for item in tasks:
            role = str(item.get("role", ""))
            if role not in parent.allowed_child_roles:
                raise OrchestrationError(f"child role '{role}' is not allowed for '{parent.role}'")
            if parent.depth + 1 > self.config.limits.max_depth:
                raise OrchestrationError("maximum delegation depth reached")
        mutating_shared = [
            item
            for item in tasks
            if self._profile(str(item["role"])).can_mutate
            and item.get("workspace_mode", self._profile(str(item["role"])).workspace_mode)
            == "inherit"
        ]
        if len(mutating_shared) > 1 and not self.config.allow_shared_mutation:
            raise OrchestrationError(
                "parallel mutating siblings require branch workspaces or allow_shared_mutation"
            )

        def run(item: Mapping[str, Any]):
            mode = item.get("workspace_mode")
            return self.delegate(
                parent_id,
                str(item["role"]),
                item.get("task", item.get("prompt", "")),
                custom_instructions=str(item.get("custom_instructions", "")),
                workspace_mode=mode,
                max_turns=int(item.get("max_turns", 8)),
                require_isolation=(
                    self._profile(str(item["role"])).can_mutate and mode == "branch"
                ),
                inherit_model=bool(item.get("inherit_model", False)),
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(tasks)) as executor:
            futures = [executor.submit(run, item) for item in tasks]
            return [future.result() for future in futures]

    def route(self, signals: RoutingInput) -> RoutingDecision:
        prefs = self.config.routing
        advisor_threshold = max(
            1,
            prefs.advisor_ambiguity - (2 if self.config.mode == "advisor" else 0),
        )
        delegation_threshold = max(
            1,
            prefs.delegation_complexity - (1 if self.config.mode == "hierarchy" else 0),
        )
        values = {name: value for name, value in vars(signals).items() if name != "task"}
        if not signals.provider_available or not signals.model_available:
            return RoutingDecision(
                "fallback",
                None,
                "The preferred provider or model is unavailable; resolve the configured visible fallback before dispatch.",
                values,
            )
        if signals.current_depth >= self.config.limits.max_depth:
            return RoutingDecision(
                "advisor" if signals.ambiguity >= advisor_threshold else "direct",
                "executive" if signals.ambiguity >= advisor_threshold else None,
                "The delegation depth limit rules out another owned child; retain ownership or ask focused advice.",
                values,
            )
        if signals.previous_failures >= 3 and (signals.risk >= 7 or signals.reasoning_quality >= 8):
            return RoutingDecision(
                "escalate",
                "executive",
                "Repeated failures on high-risk or reasoning-intensive work justify explicit ownership escalation.",
                values,
            )
        if signals.previous_failures >= 2:
            return RoutingDecision(
                "advisor",
                "executive",
                "Repeated failures justify focused stronger-model guidance without moving ownership.",
                values,
            )
        if (
            signals.ambiguity >= advisor_threshold
            and signals.implementation_scope <= prefs.specialist_scope_max
        ):
            return RoutingDecision(
                "advisor",
                "manager",
                "A focused ambiguous decision benefits from advice more than ownership transfer.",
                values,
            )
        worker_capacity = max(
            0,
            min(
                self.config.limits.max_parallel_children,
                self.config.limits.max_concurrent_agents - signals.current_worker_count,
            ),
        )
        if (
            signals.parallelizable_workstreams >= prefs.parallel_workstreams
            and worker_capacity >= signals.parallelizable_workstreams
        ):
            mutating = signals.workspace_mutation or bool(
                set(signals.required_tools)
                & {"run_command", "write_file", "edit_file", "apply_patch"}
            )
            return RoutingDecision(
                "parallel",
                "engineer"
                if signals.implementation_scope > prefs.specialist_scope_max or mutating
                else "specialist",
                "Independent workstreams and available worker capacity outweigh bounded coordination and latency overhead.",
                values,
            )
        if signals.risk >= 8 or signals.reasoning_quality >= 9:
            return RoutingDecision(
                "advisor",
                "executive",
                "High-risk or exceptionally reasoning-intensive work warrants stronger-model review while ownership stays local.",
                values,
            )
        if signals.complexity >= delegation_threshold or signals.context_isolation_benefit >= 7:
            role = (
                "specialist"
                if signals.implementation_scope <= prefs.specialist_scope_max
                and not signals.workspace_mutation
                and signals.risk < 7
                else "engineer"
            )
            return RoutingDecision(
                "delegate",
                role,
                "Complexity or context isolation benefit exceeds delegation overhead; the least costly capable role was selected.",
                values,
            )
        return RoutingDecision(
            "direct",
            None,
            "The task is small or sequential, so delegation overhead would cost more than it saves.",
            values,
        )

    def register_agent_tools(self, registry: ToolRegistry, agent_id: str) -> None:
        node = self.graph.get_node(agent_id)
        permissions = set(node.permissions)
        if "orchestrate" in permissions and node.allowed_child_roles:
            registry.register(
                "delegate_agent",
                "Delegate a bounded task to an authorized child role with a fresh context.",
                {
                    "type": "object",
                    "properties": {
                        "role": {"type": "string", "enum": list(node.allowed_child_roles)},
                        "objective": {"type": "string"},
                        "scope": {"type": "string"},
                        "constraints": {"type": "array", "items": {"type": "string"}},
                        "relevant_files": {"type": "array", "items": {"type": "string"}},
                        "evidence": {"type": "string"},
                        "definition_of_done": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "workspace_mode": {
                            "type": "string",
                            "enum": ["inherit", "branch"],
                        },
                    },
                    "required": ["role", "objective"],
                },
                lambda args, **_kw: self._tool_delegate(agent_id, args),
            )
            registry.register(
                "delegate_parallel",
                "Delegate independent bounded tasks concurrently to authorized child roles.",
                {
                    "type": "object",
                    "properties": {
                        "tasks": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": self.config.limits.max_parallel_children,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "role": {
                                        "type": "string",
                                        "enum": list(node.allowed_child_roles),
                                    },
                                    "objective": {"type": "string"},
                                    "scope": {"type": "string"},
                                    "constraints": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "relevant_files": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "definition_of_done": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "workspace_mode": {
                                        "type": "string",
                                        "enum": ["inherit", "branch"],
                                    },
                                },
                                "required": ["role", "objective"],
                            },
                        }
                    },
                    "required": ["tasks"],
                },
                lambda args, **_kw: self._tool_delegate_parallel(agent_id, args),
            )
        if "advisor" in permissions and node.allowed_advisor_roles:
            registry.register(
                "consult_advisor",
                "Ask an authorized advisor a focused question without transferring ownership.",
                {
                    "type": "object",
                    "properties": {
                        "advisor_role": {
                            "type": "string",
                            "enum": list(node.allowed_advisor_roles),
                        },
                        "question": {"type": "string"},
                        "evidence": {"type": "string"},
                        "hypothesis": {"type": "string"},
                        "constraints": {"type": "string"},
                    },
                    "required": ["advisor_role", "question"],
                },
                lambda args, **_kw: self._tool_consult(agent_id, args),
            )
        registry.register(
            "route_task",
            "Inspect the configured routing policy before delegating or consulting.",
            {
                "type": "object",
                "properties": {
                    "task": {"type": "string"},
                    "complexity": {"type": "integer"},
                    "ambiguity": {"type": "integer"},
                    "implementation_scope": {"type": "integer"},
                    "parallelizable_workstreams": {"type": "integer"},
                    "context_isolation_benefit": {"type": "integer"},
                    "risk": {"type": "integer"},
                    "previous_failures": {"type": "integer"},
                    "current_depth": {"type": "integer"},
                    "current_worker_count": {"type": "integer"},
                    "required_tools": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "workspace_mutation": {"type": "boolean"},
                    "provider_available": {"type": "boolean"},
                    "model_available": {"type": "boolean"},
                },
                "required": ["task"],
            },
            lambda args, **_kw: ToolResult(json.dumps(asdict(self.route(RoutingInput(**args))))),
        )

    def _tool_delegate(self, parent_id: str, args: Mapping[str, Any]) -> ToolResult:
        packet = {
            key: value for key, value in args.items() if key not in {"role", "workspace_mode"}
        }
        try:
            result = self.delegate(
                parent_id,
                str(args["role"]),
                packet,
                workspace_mode=args.get("workspace_mode"),
            )
        except OrchestrationError as exc:
            return ToolResult(f"Delegation rejected: {exc}", is_error=True)
        return ToolResult(result.report(), is_error=not result.ok)

    def _tool_consult(self, caller_id: str, args: Mapping[str, Any]) -> ToolResult:
        context = {
            key: value for key, value in args.items() if key not in {"advisor_role", "question"}
        }
        try:
            result = self.consult(
                caller_id,
                str(args["advisor_role"]),
                str(args["question"]),
                context,
            )
        except OrchestrationError as exc:
            return ToolResult(f"Advisor consultation rejected: {exc}", is_error=True)
        return ToolResult(
            f"### [Advisor Guidance: {result.role.upper()}]\n{result.output or result.error}",
            is_error=not result.ok,
        )

    def _tool_delegate_parallel(self, parent_id: str, args: Mapping[str, Any]) -> ToolResult:
        raw_tasks = args.get("tasks")
        if not isinstance(raw_tasks, list) or not raw_tasks:
            return ToolResult(
                "Parallel delegation rejected: tasks must be a non-empty array",
                is_error=True,
            )
        tasks = []
        for raw in raw_tasks:
            if not isinstance(raw, Mapping):
                return ToolResult(
                    "Parallel delegation rejected: each task must be an object",
                    is_error=True,
                )
            packet = {
                key: value for key, value in raw.items() if key not in {"role", "workspace_mode"}
            }
            tasks.append(
                {
                    "role": str(raw.get("role", "")),
                    "task": packet,
                    "workspace_mode": raw.get("workspace_mode"),
                }
            )
        try:
            results = self.spawn_parallel(parent_id, tasks)
        except OrchestrationError as exc:
            return ToolResult(f"Parallel delegation rejected: {exc}", is_error=True)
        return ToolResult(
            "\n".join(result.report() for result in results),
            is_error=not all(result.ok for result in results),
        )

    def prompt_fragment(self) -> str:
        if not self.enabled:
            return ""
        roles = ", ".join(sorted(self.config.roles))
        mode_guidance = {
            "auto": "Choose the least costly effective composition for each task.",
            "hierarchy": "Prefer delegated ownership for substantial independent workstreams, without inserting unnecessary levels.",
            "advisor": "Keep execution ownership local and prefer focused advisor calls for difficult decisions.",
        }[self.config.mode]
        return (
            "## Adaptive Orchestration\n"
            f"Mode: {self.config.mode}. {mode_guidance} Available roles: {roles}.\n"
            "Use route_task when the economics are unclear. Work directly for one-line changes, "
            "simple lookups, and sequential edits. Use delegate_agent for bounded ownership when "
            "parallelism, specialization, or context isolation materially helps; use delegate_parallel "
            "for independent siblings. Use consult_advisor "
            "for a difficult decision while retaining ownership. All graph and permission limits are "
            "enforced by the runtime."
        )

    def status(self) -> str:
        source = str(self.config.source) if self.config.source else "built-in defaults"
        snap = self.graph.snapshot()
        running = sum(1 for node in snap["nodes"] if node["status"] == "running")
        return (
            f"orchestration: {'on' if self.enabled else 'off'}; mode: {self.config.mode}; "
            f"agents: {len(snap['nodes'])} ({running} running); config: {source}"
        )

    def render_tree(self) -> str:
        snap = self.graph.snapshot()
        if not snap["nodes"]:
            return "No orchestration agents have run."
        by_parent: Dict[Optional[str], list[dict[str, Any]]] = {}
        for node in snap["nodes"]:
            by_parent.setdefault(node["parent_agent_id"], []).append(node)
        lines = []

        def walk(node: dict[str, Any], prefix: str = ""):
            advisor = " consulted" if node["relationship"] == "advisor" else ""
            fallback = f" fallback: {node['fallback_reason']}" if node["fallback_reason"] else ""
            lines.append(
                f"{prefix}{advisor} {node['role']} [{node['provider']}/{node['model']}] "
                f"{node['status']}{fallback}".strip()
            )
            children = by_parent.get(node["agent_id"], [])
            for child in children:
                walk(child, prefix + "  -> ")

        roots = by_parent.get(None, [])
        for root in roots:
            walk(root)
        return "\n".join(lines)

    def cancel(self) -> None:
        self.cancel_event.set()
        for node in self.graph.snapshot()["nodes"]:
            if node["status"] in {"running", "waiting"} and node["relationship"] != "root":
                self.graph.update(node["agent_id"], "cancelled", "cancelled by root")
