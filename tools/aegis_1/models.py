from __future__ import annotations

import shutil
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(slots=True)
class ModelSpec:
    name: str
    provider: str
    runtime: str
    roles: list[str]
    runtime_model: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_MODELS: dict[str, ModelSpec] = {
    "codex": ModelSpec("codex", "agent-cli", "codex-cli", ["builder", "researcher", "verifier"]),
    "claude": ModelSpec("claude", "agent-cli", "claude-code-cli", ["planner", "reviewer", "aggregator", "orchestrator"]),
}


RUNTIME_BINARIES = {
    "codex-cli": "codex",
    "claude-code-cli": "claude",
}


class ModelResolver:
    def __init__(self, models: dict[str, ModelSpec] | None = None) -> None:
        self.models = models or DEFAULT_MODELS

    def names(self) -> list[str]:
        return list(self.models)

    def list_models(self) -> list[ModelSpec]:
        return list(self.models.values())

    def check(self, name: str) -> dict[str, Any]:
        spec = self.models[name]
        binary = RUNTIME_BINARIES.get(spec.runtime)
        available = True if binary is None else shutil.which(binary) is not None
        return {
            "name": spec.name,
            "provider": spec.provider,
            "runtime": spec.runtime,
            "available": available,
            "details": "no binary required" if binary is None else f"binary={binary}:{'ok' if available else 'missing'}",
        }

    def resolve_for_role(self, role: str, explicit_models: list[str] | None = None) -> str:
        if explicit_models:
            for model_name in explicit_models:
                if model_name in self.models:
                    return model_name
            raise ValueError(f"none of the requested models are registered: {', '.join(explicit_models)}")
        for spec in self.models.values():
            if role in spec.roles:
                return spec.name
        return "codex"
