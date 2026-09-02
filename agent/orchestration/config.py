"""Role profiles, capability graph, and project orchestration configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple


class OrchestrationConfigError(ValueError):
    """Raised when orchestration policy is invalid or unsafe."""


@dataclass(frozen=True)
class ModelTarget:
    preset: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    effort: Optional[str] = None
    base_url: Optional[str] = None
    api_key_env: Optional[str] = None
    inherit: bool = False

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ModelTarget":
        if not isinstance(value, Mapping):
            raise OrchestrationConfigError("role model targets must be JSON objects")
        unknown = set(value) - {
            "preset",
            "provider",
            "model",
            "effort",
            "base_url",
            "api_key_env",
            "inherit",
        }
        if unknown:
            raise OrchestrationConfigError(
                "unknown model target keys: " + ", ".join(sorted(unknown))
            )
        target = cls(
            preset=_optional_text(value.get("preset")),
            provider=_optional_text(value.get("provider")),
            model=_optional_text(value.get("model")),
            effort=_optional_text(value.get("effort")),
            base_url=_optional_text(value.get("base_url")),
            api_key_env=_optional_text(value.get("api_key_env")),
            inherit=bool(value.get("inherit", False)),
        )
        if not target.inherit and not target.preset and not (target.provider and target.model):
            raise OrchestrationConfigError(
                "a model target needs inherit=true, a preset, or provider plus model"
            )
        if target.inherit and any((target.preset, target.provider, target.model, target.base_url)):
            raise OrchestrationConfigError(
                "inherit=true cannot be combined with preset, provider, model, or base_url"
            )
        if target.preset and target.provider:
            raise OrchestrationConfigError("a model target cannot specify both preset and provider")
        if target.effort and target.effort not in {"low", "medium", "high"}:
            raise OrchestrationConfigError(f"unsupported reasoning effort '{target.effort}'")
        return target


@dataclass(frozen=True)
class RoleProfile:
    name: str
    description: str
    instructions: str
    permissions: Tuple[str, ...]
    allowed_children: Tuple[str, ...]
    allowed_advisors: Tuple[str, ...]
    workspace_mode: str
    models: Tuple[ModelTarget, ...]

    @property
    def can_mutate(self) -> bool:
        return bool({"write", "edit", "shell"}.intersection(self.permissions))


@dataclass(frozen=True)
class OrchestrationLimits:
    max_depth: int = 3
    max_children_per_agent: int = 8
    max_parallel_children: int = 4
    max_total_agents: int = 32
    max_concurrent_agents: int = 12
    max_advisor_calls_per_agent: int = 4
    max_model_calls: int = 100
    # Agents on an expensive model (see OrchestrationConfig.expensive_models) per
    # operation, root excluded; they never run inside a parallel fan-out.
    max_expensive_agents: int = 3


@dataclass(frozen=True)
class RoutingPreferences:
    delegation_complexity: int = 6
    advisor_ambiguity: int = 7
    parallel_workstreams: int = 2
    specialist_scope_max: int = 3


@dataclass(frozen=True)
class OrchestrationConfig:
    enabled: bool = False
    mode: str = "auto"
    root_role: str = "executive"
    roles: Dict[str, RoleProfile] = field(default_factory=dict)
    limits: OrchestrationLimits = field(default_factory=OrchestrationLimits)
    routing: RoutingPreferences = field(default_factory=RoutingPreferences)
    allow_shared_mutation: bool = False
    # Subagents run on subscriptions or local endpoints. A metered API provider is
    # rejected as unavailable unless a project opts in.
    allow_api_models: bool = False
    expensive_models: Tuple[str, ...] = ("claude-fable-5", "fable")
    source: Optional[Path] = None

    @classmethod
    def load(cls, workspace_root: Path) -> "OrchestrationConfig":
        path = Path(workspace_root).resolve() / ".agnostic" / "orchestration.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls.from_dict({}, source=None)
        except (OSError, ValueError) as exc:
            raise OrchestrationConfigError(f"cannot read {path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise OrchestrationConfigError(f"{path} must contain a JSON object")
        return cls.from_dict(raw, source=path)

    @classmethod
    def from_dict(
        cls, raw: Mapping[str, Any], source: Optional[Path] = None
    ) -> "OrchestrationConfig":
        unknown_top = set(raw) - {
            "enabled",
            "mode",
            "root_role",
            "roles",
            "limits",
            "routing",
            "allow_shared_mutation",
            "allow_api_models",
            "expensive_models",
        }
        if unknown_top:
            raise OrchestrationConfigError(
                "unknown orchestration keys: " + ", ".join(sorted(unknown_top))
            )
        for key in ("enabled", "allow_shared_mutation", "allow_api_models"):
            if key in raw and not isinstance(raw[key], bool):
                raise OrchestrationConfigError(f"{key} must be a boolean")
        expensive = raw.get("expensive_models", ["claude-fable-5", "fable"])
        if not isinstance(expensive, list) or not all(isinstance(m, str) for m in expensive):
            raise OrchestrationConfigError("expensive_models must be a list of model names")
        mode = str(raw.get("mode", "auto")).lower()
        if mode not in {"auto", "hierarchy", "advisor"}:
            raise OrchestrationConfigError("mode must be auto, hierarchy, or advisor")

        role_specs: Dict[str, Dict[str, Any]] = {
            name: dict(spec) for name, spec in DEFAULT_ROLE_SPECS.items()
        }
        configured = raw.get("roles", {})
        if not isinstance(configured, Mapping):
            raise OrchestrationConfigError("roles must be a JSON object")
        for name, override in configured.items():
            if not isinstance(override, Mapping):
                raise OrchestrationConfigError(f"role '{name}' must be a JSON object")
            unknown_role = set(override) - ROLE_SPEC_KEYS
            if unknown_role:
                raise OrchestrationConfigError(
                    f"unknown keys for role '{name}': " + ", ".join(sorted(unknown_role))
                )
            base = dict(role_specs.get(str(name), {}))
            base.update(override)
            if any(key in override for key in MODEL_SHORTHAND_KEYS):
                if "models" in override:
                    raise OrchestrationConfigError(
                        f"role '{name}' cannot combine models with preset/provider/model shorthand"
                    )
                primary = {key: override[key] for key in MODEL_SHORTHAND_KEYS if key in override}
                primary.pop("fallbacks", None)
                if not primary:
                    raise OrchestrationConfigError(
                        f"role '{name}' fallbacks need a preset, provider plus model, or inherit"
                    )
                # A shorthand target without an explicit fallback list keeps the documented
                # guarantee: every target falls back visibly to the parent model.
                fallbacks = override.get("fallbacks", [{"inherit": True}])
                if not isinstance(fallbacks, list):
                    raise OrchestrationConfigError(f"role '{name}' fallbacks must be a list")
                normalized = []
                for fallback in fallbacks:
                    normalized.append(
                        {"preset": fallback} if isinstance(fallback, str) else fallback
                    )
                base["models"] = [primary] + normalized
            role_specs[str(name)] = base

        roles = _resolve_roles(role_specs)
        _validate_capability_graph(roles)
        root_role = str(raw.get("root_role", "executive"))
        if root_role not in roles:
            raise OrchestrationConfigError(f"unknown root role '{root_role}'")

        limits = _dataclass_from_mapping(OrchestrationLimits, raw.get("limits", {}), "limits")
        for name, value in vars(limits).items():
            if value < 1 and name != "max_depth":
                raise OrchestrationConfigError(f"limits.{name} must be at least 1")
            if name == "max_depth" and value < 0:
                raise OrchestrationConfigError("limits.max_depth cannot be negative")
        routing = _dataclass_from_mapping(RoutingPreferences, raw.get("routing", {}), "routing")
        for name, value in vars(routing).items():
            if value < 1:
                raise OrchestrationConfigError(f"routing.{name} must be at least 1")
        return cls(
            enabled=bool(raw.get("enabled", False)),
            mode=mode,
            root_role=root_role,
            roles=roles,
            limits=limits,
            routing=routing,
            allow_shared_mutation=bool(raw.get("allow_shared_mutation", False)),
            allow_api_models=bool(raw.get("allow_api_models", False)),
            expensive_models=tuple(expensive),
            source=source,
        )

    def with_runtime(self, *, enabled: Optional[bool] = None, mode: Optional[str] = None):
        data = dict(vars(self))
        if enabled is not None:
            data["enabled"] = enabled
        if mode is not None:
            if mode not in {"auto", "hierarchy", "advisor"}:
                raise OrchestrationConfigError("mode must be auto, hierarchy, or advisor")
            data["mode"] = mode
        return OrchestrationConfig(**data)


def _optional_text(value: Any) -> Optional[str]:
    return str(value) if value not in (None, "") else None


def _dataclass_from_mapping(cls, value: Any, label: str):
    if not isinstance(value, Mapping):
        raise OrchestrationConfigError(f"{label} must be a JSON object")
    known = cls.__dataclass_fields__
    unknown = set(value) - set(known)
    if unknown:
        raise OrchestrationConfigError(f"unknown {label} keys: {', '.join(sorted(unknown))}")
    if any(isinstance(item, bool) for item in value.values()):
        raise OrchestrationConfigError(f"{label} values must be integers")
    try:
        return cls(**{key: int(item) for key, item in value.items()})
    except (TypeError, ValueError) as exc:
        raise OrchestrationConfigError(f"{label} values must be integers") from exc


def _resolve_roles(specs: Mapping[str, Mapping[str, Any]]) -> Dict[str, RoleProfile]:
    resolved: Dict[str, RoleProfile] = {}
    resolving = []

    def resolve(name: str) -> RoleProfile:
        if name in resolved:
            return resolved[name]
        if name in resolving:
            chain = " -> ".join(resolving + [name])
            raise OrchestrationConfigError(f"role inheritance cycle: {chain}")
        if name not in specs:
            raise OrchestrationConfigError(f"unknown base role '{name}'")
        resolving.append(name)
        spec = specs[name]
        base_name = _optional_text(spec.get("base"))
        base = resolve(base_name) if base_name else None

        def tuple_value(key: str, default=()):
            value = spec.get(key, default)
            if not isinstance(value, (list, tuple)):
                raise OrchestrationConfigError(f"role '{name}' {key} must be a list")
            return tuple(str(item) for item in value)

        permissions = tuple_value("permissions", base.permissions if base else ())
        permissions = tuple(dict.fromkeys(permissions + tuple_value("additional_permissions", ())))
        unknown_permissions = set(permissions) - ROLE_PERMISSIONS
        if unknown_permissions:
            raise OrchestrationConfigError(
                f"role '{name}' has unknown permissions: " + ", ".join(sorted(unknown_permissions))
            )
        children = tuple_value("allowed_children", base.allowed_children if base else ())
        advisors = tuple_value("allowed_advisors", base.allowed_advisors if base else ())
        instructions = str(spec.get("instructions", base.instructions if base else ""))
        additional = str(spec.get("additional_instructions", "")).strip()
        if additional:
            instructions = (instructions.rstrip() + "\n" + additional).strip()

        raw_models = spec.get("models")
        if raw_models is None:
            models = base.models if base else ()
        else:
            if not isinstance(raw_models, list) or not raw_models:
                raise OrchestrationConfigError(f"role '{name}' models must be a non-empty list")
            models = tuple(ModelTarget.from_dict(item) for item in raw_models)

        workspace_mode = str(spec.get("workspace", base.workspace_mode if base else "inherit"))
        if workspace_mode not in {"inherit", "branch"}:
            raise OrchestrationConfigError(f"role '{name}' workspace must be inherit or branch")
        profile = RoleProfile(
            name=name,
            description=str(spec.get("description", base.description if base else name)),
            instructions=instructions,
            permissions=permissions,
            allowed_children=children,
            allowed_advisors=advisors,
            workspace_mode=workspace_mode,
            models=models or (ModelTarget(inherit=True),),
        )
        resolving.pop()
        resolved[name] = profile
        return profile

    for role_name in specs:
        resolve(role_name)
    return resolved


def _validate_capability_graph(roles: Mapping[str, RoleProfile]) -> None:
    for role in roles.values():
        for target in role.allowed_children + role.allowed_advisors:
            if target not in roles:
                raise OrchestrationConfigError(
                    f"role '{role.name}' references unknown role '{target}'"
                )

    visiting = set()
    visited = set()

    def visit(name: str):
        if name in visiting:
            raise OrchestrationConfigError(f"delegation cycle includes role '{name}'")
        if name in visited:
            return
        visiting.add(name)
        for child in roles[name].allowed_children:
            visit(child)
        visiting.remove(name)
        visited.add(name)

    for role_name in roles:
        visit(role_name)


_CLAUDE_MODELS = {
    "executive": "claude-fable-5",
    "manager": "claude-opus-5",
    "engineer": "claude-sonnet-5",
    "specialist": "claude-haiku-4.5",
}

ROLE_PERMISSIONS = {
    "read",
    "search",
    "network",
    "shell",
    "write",
    "edit",
    "orchestrate",
    "advisor",
}

MODEL_SHORTHAND_KEYS = (
    "preset",
    "provider",
    "model",
    "effort",
    "base_url",
    "api_key_env",
    "inherit",
    "fallbacks",
)

ROLE_SPEC_KEYS = {
    "base",
    "description",
    "instructions",
    "additional_instructions",
    "permissions",
    "additional_permissions",
    "allowed_children",
    "allowed_advisors",
    "workspace",
    "models",
    "preset",
    "provider",
    "model",
    "effort",
    "base_url",
    "api_key_env",
    "inherit",
    "fallbacks",
}


def _models(kind: str, effort: str):
    # Subscription first, subscription fallback: the Claude login with the role's
    # model, then the Codex login with its default model. Never a metered API key.
    return [
        {
            "preset": "sub-claude-code",
            "model": _CLAUDE_MODELS[kind],
            "effort": effort,
        },
        {"preset": "sub-openai-codex", "effort": effort},
    ]


DEFAULT_ROLE_SPECS: Dict[str, Dict[str, Any]] = {
    "executive": {
        "description": "Strategic owner, escalation model, final reviewer, and advisor.",
        "instructions": (
            "Own strategy and difficult reasoning directly. Delegate only when specialization, "
            "parallelism, context isolation, or lower cost outweigh coordination overhead. Review "
            "child evidence before accepting it."
        ),
        "permissions": ["read", "search", "network", "shell", "orchestrate", "advisor"],
        "allowed_children": [
            "manager",
            "architecture-manager",
            "security-manager",
            "product-manager",
            "verification-manager",
            "engineer",
            "specialist",
            "researcher",
            "reviewer",
            "tester",
        ],
        "allowed_advisors": [],
        "models": _models("executive", "high"),
    },
    "manager": {
        "description": "Principal workstream owner, integrator, debugger, and reviewer.",
        "instructions": (
            "Perform small or sequential work yourself. Delegate only substantial independent "
            "units or focused investigations. Verify and synthesize child results; never blindly relay."
        ),
        "permissions": ["read", "search", "network", "shell", "orchestrate", "advisor"],
        "allowed_children": ["engineer", "specialist", "researcher", "reviewer", "tester"],
        "allowed_advisors": ["executive"],
        "models": _models("manager", "high"),
    },
    "engineer": {
        "description": "Autonomous implementation lead for multi-file engineering work.",
        "instructions": (
            "Own implementation, debugging, tests, and verification. Delegate only bounded "
            "specialist tasks; consult an advisor for unresolved architecture or difficult failures."
        ),
        "permissions": [
            "read",
            "search",
            "network",
            "shell",
            "write",
            "edit",
            "orchestrate",
            "advisor",
        ],
        "allowed_children": ["specialist", "researcher", "reviewer", "tester"],
        "allowed_advisors": ["manager", "executive"],
        "models": _models("engineer", "high"),
    },
    "specialist": {
        "description": "Bounded researcher, scout, tester, verifier, or mechanical implementer.",
        "instructions": (
            "Stay within the task packet, preserve evidence, and return a concise result. Do not "
            "spawn children. Workspace mutation is unavailable unless the configured role grants it."
        ),
        "permissions": ["read", "search"],
        "allowed_children": [],
        "allowed_advisors": ["engineer", "manager", "executive"],
        "models": _models("specialist", "low"),
    },
    "researcher": {
        "base": "specialist",
        "description": "Read-only code and documentation researcher.",
        "permissions": ["read", "search"],
        "additional_instructions": "Do not modify the workspace.",
    },
    "reviewer": {
        "base": "specialist",
        "description": "Read-only code, architecture, and security reviewer.",
        "permissions": ["read", "search"],
        "additional_instructions": "Do not modify the workspace; report findings with evidence.",
    },
    "tester": {
        "base": "specialist",
        "description": "Test designer and independent verifier.",
        "permissions": ["read", "search", "shell"],
    },
    "architecture-manager": {
        "base": "manager",
        "description": "Architecture-focused principal workstream owner.",
        "additional_instructions": "Focus on system boundaries, contracts, and long-term coherence.",
    },
    "security-manager": {
        "base": "manager",
        "description": "Security-focused workstream owner and boundary reviewer.",
        "additional_instructions": "Focus on threat boundaries, least privilege, and abuse cases.",
    },
    "product-manager": {
        "base": "manager",
        "description": "Product requirements and acceptance workstream owner.",
        "additional_instructions": "Focus on user outcomes, scope, and observable acceptance criteria.",
    },
    "verification-manager": {
        "base": "manager",
        "description": "Independent verification and release acceptance owner.",
        "additional_instructions": "Demand deterministic evidence and preserve failed observations.",
    },
}
