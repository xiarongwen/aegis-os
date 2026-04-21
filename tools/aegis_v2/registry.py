from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from typing import Any

from .config import AppPaths, load_config, load_registry
from .types import ModelHealth, ModelSpec


RUNTIME_BINARY_MAP = {
    "claude-code-cli": "claude",
    "codex-cli": "codex",
    "local": "ollama",
}

PROVIDER_ENV_MAP = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "ollama": None,
}


@dataclass(slots=True)
class RegistryBundle:
    models: dict[str, ModelSpec]
    config: dict[str, Any]
    registry: dict[str, Any]
    paths: AppPaths

    def enabled_model_names(self) -> list[str]:
        enabled = self.config.get("models", {}).get("enabled", [])
        if isinstance(enabled, list) and enabled:
            return [name for name in enabled if name in self.models]
        return list(self.models.keys())


class ModelRegistry:
    def __init__(self, bundle: RegistryBundle) -> None:
        self.bundle = bundle
        self._models = bundle.models

    @classmethod
    def from_workspace(cls, paths: AppPaths) -> "ModelRegistry":
        config_payload = load_config(paths)
        registry_payload = load_registry(paths)
        raw_models = registry_payload.get("models", {})
        models: dict[str, ModelSpec] = {}
        for name, payload in raw_models.items():
            if not isinstance(payload, dict):
                continue
            models[name] = ModelSpec(
                name=name,
                provider=str(payload.get("provider", "")),
                runtime=str(payload.get("runtime", "")),
                capabilities=[str(item) for item in payload.get("capabilities", [])],
                context_window=int(payload.get("context_window", 0) or 0),
                cost_per_1k_tokens=float(payload.get("cost_per_1k_tokens", 0.0) or 0.0),
                specialties=[str(item) for item in payload.get("specialties", [])],
                config=dict(payload.get("config", {})),
            )
        return cls(
            RegistryBundle(
                models=models,
                config=config_payload,
                registry=registry_payload,
                paths=paths,
            )
        )

    @property
    def config(self) -> dict[str, Any]:
        return self.bundle.config

    @property
    def paths(self) -> AppPaths:
        return self.bundle.paths

    def get(self, name: str) -> ModelSpec:
        return self._models[name]

    def names(self) -> list[str]:
        return list(self._models.keys())

    def list_models(self, *, enabled_only: bool = False) -> list[ModelSpec]:
        names = self.bundle.enabled_model_names() if enabled_only else self.names()
        return [self._models[name] for name in names]

    def enabled_models(self) -> list[ModelSpec]:
        return self.list_models(enabled_only=True)

    def check_model(self, name: str) -> ModelHealth:
        spec = self.get(name)
        runtime_binary = RUNTIME_BINARY_MAP.get(spec.runtime)
        provider_env = PROVIDER_ENV_MAP.get(spec.provider)
        binary_ok = True
        env_ok = True
        notes: list[str] = []
        if runtime_binary:
            binary_ok = shutil.which(runtime_binary) is not None
            notes.append(f"binary={runtime_binary}:{'ok' if binary_ok else 'missing'}")
        if provider_env:
            env_ok = bool(os.environ.get(provider_env))
            notes.append(f"env={provider_env}:{'set' if env_ok else 'missing'}")
        if spec.runtime == "api" and provider_env:
            binary_ok = True
        available = binary_ok and env_ok
        return ModelHealth(
            name=name,
            available=available,
            runtime=spec.runtime,
            provider=spec.provider,
            details=", ".join(notes) if notes else "no checks required",
        )

    def available_model_names(self, *, names: list[str] | None = None) -> list[str]:
        target_names = names or self.bundle.enabled_model_names()
        available: list[str] = []
        for name in target_names:
            if name not in self._models:
                continue
            if self.check_model(name).available:
                available.append(name)
        return available
