"""Execution graph, routing, workspace leases, and bounded agent executor."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace
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
            if not value.strip():
                raise OrchestrationError("task objective is required")
            return cls(objective=value.strip())
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


def worktree_root_for(workspace_root: Path) -> Path:
    """Where isolated worktrees for one repo live: outside the repo, so an
    inherit-mode sibling's path containment can never resolve into them."""
    digest = hashlib.sha1(str(Path(workspace_root).resolve()).encode("utf-8")).hexdigest()
    return Path(tempfile.gettempdir()) / "agnostic-worktrees" / digest[:12]


class WorkspaceManager:
    """Owns worktree leases; only the recorded owner may remove one."""

    def __init__(self, workspace_root: Path):
        self.workspace_root = Path(workspace_root).resolve()
        self.worktree_root = worktree_root_for(self.workspace_root)
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
        worktree_dir = self.worktree_root / owner_id
        worktree_dir.parent.mkdir(parents=True, exist_ok=True)
        # A branch child of a branch parent forks the parent's checkout, so anything the
        # parent committed in its worktree is visible. Uncommitted parent edits are not.
        source = parent.path if parent.owned else self.workspace_root
        try:
            result = subprocess.run(
                ["git", "worktree", "add", "--detach", str(worktree_dir), "HEAD"],
                cwd=source,
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
        try:
            lease.path.resolve().relative_to(self.worktree_root.resolve())
        except ValueError as exc:
            raise PermissionError("owned workspace resolves outside the worktree root") from exc
        self._git(["worktree", "remove", "--force", str(lease.path)], timeout=60)
        if lease.path.exists():
            shutil.rmtree(lease.path, ignore_errors=True)
        self._git(["worktree", "prune"], timeout=30)
        with self._lock:
            self._leases.pop(lease.owner_id, None)
        if lease.path.exists():
            # Something (a locked handle, an antivirus scan) kept the tree alive. The
            # caller reports it and `/org prune` sweeps it once the handle is gone.
            lease.note = "worktree removal incomplete; run /org prune"
            return False
        return True

    def _git(self, args: list, timeout: int) -> bool:
        try:
            result = subprocess.run(
                ["git"] + args,
                cwd=self.workspace_root,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0

    def prune(self) -> int:
        """Remove worktrees under this repo's worktree root that no live lease owns.
        Returns how many directories were swept (L2: a verdict carries its volume)."""
        if not self.worktree_root.exists():
            return 0
        with self._lock:
            live = {lease.path.resolve() for lease in self._leases.values() if lease.owned}
        swept = 0
        for entry in list(self.worktree_root.iterdir()):
            if not entry.is_dir() or entry.resolve() in live:
                continue
            self._git(["worktree", "remove", "--force", str(entry)], timeout=60)
            if entry.exists():
                shutil.rmtree(entry, ignore_errors=True)
            if not entry.exists():
                swept += 1
        self._git(["worktree", "prune"], timeout=30)
        return swept


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
    "search": {"grep_search", "find_files"},
    "network": {"read_url_content", "search_web"},
    "shell": {"run_command", "simulate_command"},
    "write": {"write_file"},
    "edit": {"edit_file", "apply_patch"},
}

MAX_CHILD_TURNS = 24


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
        self.client = manager.bind_client(client, lease)
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
        protocol = (
            "Tool protocol: a tool runs ONLY when you emit its call in the tool-call format you "
            "were given (one JSON block per call when tools are listed in the prompt). Never "
            "describe or announce a tool call in prose; emit the call, wait for its result, then "
            "answer. Your final message must contain the result itself, not an intention."
        )
        return "\n\n".join(
            part
            for part in (
                self.profile.instructions,
                relationship,
                economics,
                protocol,
                self.custom_instructions,
            )
            if part
        )

    def _registry(self) -> ToolRegistry:
        permissions = set(self.profile.permissions)
        if self.advisor:
            permissions -= {"write", "edit", "shell", "network", "orchestrate", "advisor"}
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
        last_content = ""
        empty_replies = 0
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
                        self.client = self.manager.bind_client(fallback, self.lease)
                        continue
                raise
            message = response.choices[0].message
            if message.content:
                last_content = message.content
            if not message.tool_calls:
                if not (message.content or "").strip() and empty_replies < 2:
                    # A subscription CLI with its native tools disabled sometimes hands
                    # back an empty result (the model reached for a tool it no longer
                    # has). An empty reply is never a child's answer: ask once more.
                    empty_replies += 1
                    messages.append({"role": "assistant", "content": ""})
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Your previous reply was empty. If you need a tool, emit its "
                                "call in the required format now; otherwise give the final "
                                "answer."
                            ),
                        }
                    )
                    continue
                return AgentResult(
                    agent_id=self.node.agent_id,
                    role=self.profile.name,
                    output=message.content or "[Worker finished with empty response]",
                    ok=bool((message.content or "").strip()),
                    error="" if (message.content or "").strip() else "worker returned no content",
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
                        confirm_callback=self.manager.confirm,
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
            output=last_content,
            ok=False,
            error=f"agent reached max turns limit ({max_turns}); last output:\n{last_content}",
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
        self._child_counts: Dict[str, int] = {}
        self._advisor_counts: Dict[str, int] = {}
        self._total_agents = 0
        self._active_agents = 0
        self._model_calls = 0
        # One human answers one prompt at a time: parallel children must never share
        # a single pending confirmation.
        self._confirm_lock = threading.Lock()
        self._in_turn = False
        self._expensive_count = 0

    @property
    def in_turn(self) -> bool:
        return self._in_turn

    @staticmethod
    def _model_name(config: Any) -> str:
        return str(getattr(config, "sub_model", None) or getattr(config, "model", "") or "")

    def is_expensive(self, config: Any) -> bool:
        name = self._model_name(config).lower()
        return any(
            name == m.lower() or name.startswith(m.lower()) for m in self.config.expensive_models
        )

    @property
    def root_is_expensive(self) -> bool:
        """The interactive model burns tokens fast (Fable): delegate-first applies."""
        return self.is_expensive(self.root_client.config)

    def begin_turn(self) -> None:
        """Start a budgeted operation: clear a stale cancel and reset per-turn counts.
        Called by AgentLoop.run_turn and by out-of-turn entry points (/research,
        /review, /swarm) so limits bound one operation, not the whole session."""
        self.cancel_event.clear()
        with self._lock:
            self._in_turn = True
            self._child_counts.clear()
            self._advisor_counts.clear()
            self._model_calls = 0
            self._expensive_count = 0
            self._total_agents = max(1, self._active_agents)

    def end_turn(self) -> None:
        with self._lock:
            self._in_turn = False

    def confirm(self, prompt: str) -> bool:
        if self.confirm_callback is None:
            return False
        with self._confirm_lock:
            return self.confirm_callback(prompt)

    def bind_client(self, client: LLMClient, lease: WorkspaceLease) -> LLMClient:
        """Confine a child's model transport to its lease: subscription CLIs run in
        the lease directory with their native tools disabled, so the only tools a
        child can use are the ones its ToolRegistry advertises."""
        config = getattr(client, "config", None)
        if config is not None:
            config.workdir = str(lease.path)
            config.native_tools = False
        return client

    def _display_path(self, path: Path) -> str:
        try:
            return Path(path).resolve().relative_to(self.workspace_root).as_posix() or "."
        except ValueError:
            return Path(path).name

    @staticmethod
    def _short_error(exc: BaseException) -> str:
        """Graph detail for a failure: the type and a bounded first line, never a
        subprocess transcript (which may echo secrets) and never an absolute path."""
        text = " ".join(str(exc).split())[:200]
        return f"{type(exc).__name__}: {text}" if text else type(exc).__name__

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
                workspace=".",
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

    @staticmethod
    def _is_api_provider(provider: str) -> bool:
        return provider != "local" and not provider.endswith("-sub")

    def _default_availability(self, target: ModelTarget, config: LLMConfig) -> tuple[bool, str]:
        if self._is_api_provider(config.provider) and not self.config.allow_api_models:
            return (
                False,
                f"provider '{config.provider}' is a metered API; subagents use subscriptions "
                "or local models (set allow_api_models to override)",
            )
        if target.inherit:
            return True, "inherited parent model"
        if target.preset and target.preset not in LLMConfig.PRESETS:
            return False, f"unknown preset '{target.preset}'"
        if (
            target.preset
            and not (config.provider.endswith("-sub") and self.client_factory is not LLMClient)
            and not LLMConfig.preset_available(LLMConfig.PRESETS[target.preset], include_local=True)
        ):
            return False, f"preset '{target.preset}' is unavailable"
        if (
            config.provider != "local"
            and not config.provider.endswith("-sub")
            and not config.api_key
        ):
            if target.base_url and not target.preset:
                # An explicit self-hosted endpoint (vLLM, Ollama on another box) may be keyless.
                return True, "available (keyless endpoint)"
            hint = f" (set {target.api_key_env})" if target.api_key_env else ""
            return False, f"provider '{config.provider}' has no configured API key{hint}"
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
        config = self._base_config_for_target(target, parent_client)
        if target.api_key_env and os.getenv(target.api_key_env):
            config.api_key = os.getenv(target.api_key_env)
        return config

    def _base_config_for_target(self, target: ModelTarget, parent_client: LLMClient) -> LLMConfig:
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
        reasons.append(f"{node.provider}/{node.model} failed: {self._short_error(error)}")
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
                child_count = self._child_counts.get(parent.agent_id, 0)
                if child_count >= self.config.limits.max_children_per_agent:
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
                self._child_counts[parent.agent_id] = child_count + 1
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
        if self.is_expensive(client.config):
            with self._lock:
                if self._expensive_count >= self.config.limits.max_expensive_agents:
                    self._release_counts(parent.agent_id, relationship)
                    self._total_agents -= 1
                    raise OrchestrationError(
                        f"expensive model agent limit reached "
                        f"({self.config.limits.max_expensive_agents} per operation)"
                    )
                self._expensive_count += 1
        agent_id = ("adv_" if relationship == "advisor" else "agent_") + uuid.uuid4().hex[:8]
        parent_lease = self._parent_lease(parent)
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
            workspace=self._display_path(lease.path),
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

    def _parent_lease(self, parent: AgentNode) -> WorkspaceLease:
        lease = self.workspaces._leases.get(parent.workspace_owner)
        if lease is not None:
            return lease
        parent_path = self.workspace_root / parent.workspace
        return WorkspaceLease(
            path=parent_path if parent_path.exists() else self.workspace_root,
            owner_id=parent.workspace_owner,
            mode=parent.workspace_mode,
            writable=not parent.workspace_read_only,
            owned=False,
        )

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
        max_turns = max(1, min(int(max_turns), MAX_CHILD_TURNS))
        # A mutating child that asked for isolation never silently lands in the shared tree.
        require_isolation = require_isolation or (requested_profile.can_mutate and mode == "branch")
        node, profile, client, lease = self._reserve(
            parent, role, "delegation", inherit_model=inherit_model
        )
        node.objective = packet.objective
        artifact = ""
        try:
            if mode == "branch":
                self.workspaces.release(lease, node.agent_id)
                lease = None
                lease = self.workspaces.acquire_branch(
                    node.agent_id,
                    self._parent_lease(parent),
                    writable=profile.can_mutate,
                    require_isolation=require_isolation,
                )
                node.workspace = self._display_path(lease.path)
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
            note = lease.note if lease is not None else ""
            output = result.output + (f"\n[{note}]" if note else "")
            result = AgentResult(
                agent_id=result.agent_id,
                role=result.role,
                output=output,
                ok=result.ok,
                error=result.error,
                workspace_artifact=artifact,
            )
            self.graph.update(
                node.agent_id,
                "completed" if result.ok else "failed",
                result.error[:200] if result.error else note,
            )
            return result
        except OrchestrationCancelled:
            self.graph.update(node.agent_id, "cancelled", "cancelled by root")
            raise
        except Exception as exc:
            if self.cancel_event.is_set():
                self.graph.update(node.agent_id, "cancelled", "cancelled by root")
                raise OrchestrationCancelled("orchestration cancelled by user") from exc
            self.graph.update(node.agent_id, "failed", self._short_error(exc))
            if lease is not None and not artifact:
                artifact = self.workspaces.capture_patch(lease)
            return AgentResult(
                node.agent_id, role, "", ok=False, error=str(exc), workspace_artifact=artifact
            )
        finally:
            if lease is not None:
                if not artifact and lease.owned and lease.writable:
                    # A cancelled or crashed branch child still hands its diff upward
                    # before the worktree goes away.
                    artifact = self.workspaces.capture_patch(lease)
                    if artifact:
                        self._emit("agent_patch", f"{node.agent_id} patch={artifact}")
                if not self.workspaces.release(lease, node.agent_id) and lease.owned:
                    self._emit("workspace_warning", f"{node.agent_id} {lease.note}")
            self._emit(
                "agent_end",
                f"{node.agent_id} role={role} status={self.graph.get_node(node.agent_id).status}",
            )
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
            self.graph.update(
                node.agent_id, "completed" if result.ok else "failed", result.error[:200]
            )
            return result
        except OrchestrationCancelled:
            self.graph.update(node.agent_id, "cancelled", "cancelled by root")
            raise
        except Exception as exc:
            if self.cancel_event.is_set():
                self.graph.update(node.agent_id, "cancelled", "cancelled by root")
                raise OrchestrationCancelled("orchestration cancelled by user") from exc
            self.graph.update(node.agent_id, "failed", self._short_error(exc))
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
            remaining_children = self.config.limits.max_children_per_agent - self._child_counts.get(
                parent.agent_id, 0
            )
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
        modes = []
        for item in tasks:
            role = str(item.get("role", ""))
            if role not in parent.allowed_child_roles:
                raise OrchestrationError(f"child role '{role}' is not allowed for '{parent.role}'")
            primary = self._profile(role).models[0]
            if not primary.inherit and self.is_expensive(
                SimpleNamespace(sub_model=primary.model, model=primary.model)
            ):
                raise OrchestrationError(
                    f"role '{role}' runs on an expensive model and never inside a parallel fan-out"
                )
            if parent.depth + 1 > self.config.limits.max_depth:
                raise OrchestrationError("maximum delegation depth reached")
            # A missing or null workspace_mode means the role default; the model-facing
            # tool omits the key, so `or` (not dict.get's default) decides.
            modes.append(item.get("workspace_mode") or self._profile(role).workspace_mode)
        mutating_shared = [
            item
            for item, mode in zip(tasks, modes)
            if self._profile(str(item["role"])).can_mutate and mode == "inherit"
        ]
        if len(mutating_shared) > 1 and not self.config.allow_shared_mutation:
            raise OrchestrationError(
                "parallel mutating siblings require branch workspaces or allow_shared_mutation"
            )

        def run(item: Mapping[str, Any], mode: str) -> AgentResult:
            role = str(item["role"])
            try:
                return self.delegate(
                    parent_id,
                    role,
                    item.get("task", item.get("prompt", "")),
                    custom_instructions=str(item.get("custom_instructions", "")),
                    workspace_mode=mode,
                    max_turns=int(item.get("max_turns", 8)),
                    inherit_model=bool(item.get("inherit_model", False)),
                )
            except OrchestrationCancelled:
                raise
            except OrchestrationError as exc:
                # One sibling's rejected reservation is that sibling's failure; the
                # others' finished work still reaches the parent.
                return AgentResult("", role, "", ok=False, error=str(exc))

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(tasks)) as executor:
            futures = [executor.submit(run, item, mode) for item, mode in zip(tasks, modes)]
            results = []
            first_cancel: Optional[BaseException] = None
            for future in futures:
                try:
                    results.append(future.result())
                except OrchestrationCancelled as exc:
                    first_cancel = first_cancel or exc
        if first_cancel is not None:
            raise first_cancel
        return results

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
        if self.root_is_expensive:
            # Delegate-first: the expensive root keeps decisions and synthesis, nothing else.
            delegation_threshold = 1
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
                        "max_turns": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": MAX_CHILD_TURNS,
                            "description": "Model turns the child may use (default 8).",
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
        can_route = ("orchestrate" in permissions and node.allowed_child_roles) or (
            "advisor" in permissions and node.allowed_advisor_roles
        )
        if not can_route:
            return
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
            key: value
            for key, value in args.items()
            if key not in {"role", "workspace_mode", "max_turns"}
        }
        try:
            result = self.delegate(
                parent_id,
                str(args["role"]),
                packet,
                workspace_mode=args.get("workspace_mode") or None,
                max_turns=int(args.get("max_turns") or 8),
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
            task = {"role": str(raw.get("role", "")), "task": packet}
            if raw.get("workspace_mode"):
                task["workspace_mode"] = raw["workspace_mode"]
            tasks.append(task)
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
        delegate_first = ""
        if self.root_is_expensive:
            delegate_first = (
                "\nDELEGATE-FIRST: you are running on an expensive model. Every research, "
                "search, implementation, test run, and review goes to a child role via "
                "delegate_agent or delegate_parallel (specialist/researcher for lookups, engineer "
                "for code, tester and reviewer for verification). You keep only decisions, "
                "synthesis of child evidence, and the final answer. Read a file yourself only when "
                "a child's report is insufficient for the decision at hand."
            )
        return (
            "## Adaptive Orchestration\n"
            f"Mode: {self.config.mode}. {mode_guidance} Available roles: {roles}.\n"
            "Use route_task when the economics are unclear. Work directly for one-line changes, "
            "simple lookups, and sequential edits. Use delegate_agent for bounded ownership when "
            "parallelism, specialization, or context isolation materially helps; use delegate_parallel "
            "for independent siblings. Use consult_advisor "
            "for a difficult decision while retaining ownership. All graph and permission limits are "
            "enforced by the runtime." + delegate_first
        )

    def status(self) -> str:
        source = str(self.config.source) if self.config.source else "built-in defaults"
        snap = self.graph.snapshot()
        running = sum(1 for node in snap["nodes"] if node["status"] == "running")
        delegate_first = "; delegate-first (expensive root model)" if self.root_is_expensive else ""
        return (
            f"orchestration: {'on' if self.enabled else 'off'}; mode: {self.config.mode}; "
            f"agents: {len(snap['nodes'])} ({running} running); config: {source}{delegate_first}"
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
        """Root cancellation: every descendant and pending advisor sees the event at
        its next check; a node that never started is marked here, a running one
        marks itself when it unwinds (so the graph never claims a thread is done
        while it is still executing)."""
        self.cancel_event.set()
        for node in self.graph.snapshot()["nodes"]:
            if node["status"] == "waiting":
                self.graph.update(node["agent_id"], "cancelled", "cancelled by root")

    def prune_workspaces(self) -> str:
        swept = self.workspaces.prune()
        return f"pruned {swept} orphaned worktree(s) under {self.workspaces.worktree_root}"
