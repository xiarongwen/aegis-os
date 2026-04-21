from __future__ import annotations

import hashlib
import os
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from tools.runtime_bridge import cli as runtime_bridge

from .registry import ModelRegistry
from .types import ModelSpec, RuntimeInvocation, RuntimeResult


class RuntimeExecutionError(RuntimeError):
    pass


SimulationResponder = Callable[[str, str, dict[str, Any]], str]


def _slug(value: str) -> str:
    normalized = "".join(char if char.isalnum() else "-" for char in value.lower())
    normalized = "-".join(part for part in normalized.split("-") if part)
    return normalized or "value"


def _approximate_cost(spec: ModelSpec, prompt: str, output: str) -> float:
    estimated_tokens = max(1, (len(prompt) + len(output)) // 4)
    return round(spec.cost_per_1k_tokens * (estimated_tokens / 1000), 4)


@dataclass(slots=True)
class AdapterContext:
    workspace_root: Path
    log_path: Path
    response_path: Path | None


class BaseRuntimeAdapter:
    def supports_bridge(self) -> bool:
        return False

    def bridge_model(self, spec: ModelSpec) -> str | None:
        return None

    def build_invocation(self, spec: ModelSpec, prompt: str, context: AdapterContext) -> RuntimeInvocation:
        raise NotImplementedError

    def extract_output(self, invocation: RuntimeInvocation, stdout: str, log_path: Path) -> str:
        if invocation.response_path:
            response_path = Path(invocation.response_path)
            if response_path.exists():
                content = response_path.read_text(encoding="utf-8", errors="replace").strip()
                if content:
                    return content
        cleaned = stdout.strip()
        if cleaned:
            return cleaned
        if not log_path.exists():
            return ""
        lines = []
        for raw_line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if raw_line.startswith(runtime_bridge.DONE_PREFIX):
                continue
            if raw_line.startswith("$ "):
                continue
            lines.append(raw_line)
        return "\n".join(lines).strip()


class CodexRuntimeAdapter(BaseRuntimeAdapter):
    def supports_bridge(self) -> bool:
        return True

    def bridge_model(self, spec: ModelSpec) -> str | None:
        return "codex"

    def build_invocation(self, spec: ModelSpec, prompt: str, context: AdapterContext) -> RuntimeInvocation:
        if context.response_path is None:
            raise RuntimeExecutionError("codex runtime requires a response path")
        command = [
            "codex",
            "exec",
            "--full-auto",
            "-C",
            str(context.workspace_root),
            "-o",
            str(context.response_path),
        ]
        if spec.name != "codex":
            command.extend(["-m", spec.name])
        command.append(prompt)
        return RuntimeInvocation(
            model=spec.name,
            runtime=spec.runtime,
            command=command,
            cwd=str(context.workspace_root),
            log_path=str(context.log_path),
            response_path=str(context.response_path),
        )


class ClaudeRuntimeAdapter(BaseRuntimeAdapter):
    def supports_bridge(self) -> bool:
        return True

    def bridge_model(self, spec: ModelSpec) -> str | None:
        return "claude"

    def build_invocation(self, spec: ModelSpec, prompt: str, context: AdapterContext) -> RuntimeInvocation:
        command = [
            "claude",
            "-p",
            "--bare",
            "--permission-mode",
            "bypassPermissions",
            "--output-format",
            "text",
            "--model",
            spec.name,
            "--add-dir",
            str(context.workspace_root),
            "--add-dir",
            str(Path(__file__).resolve().parents[2]),
            prompt,
        ]
        return RuntimeInvocation(
            model=spec.name,
            runtime=spec.runtime,
            command=command,
            cwd=str(context.workspace_root),
            log_path=str(context.log_path),
            response_path=None,
        )


class OpenAIRuntimeAdapter(CodexRuntimeAdapter):
    pass


class OllamaRuntimeAdapter(BaseRuntimeAdapter):
    def build_invocation(self, spec: ModelSpec, prompt: str, context: AdapterContext) -> RuntimeInvocation:
        model_name = str(spec.config.get("model_name", spec.name))
        command = ["ollama", "run", model_name, prompt]
        return RuntimeInvocation(
            model=spec.name,
            runtime=spec.runtime,
            command=command,
            cwd=str(context.workspace_root),
            log_path=str(context.log_path),
            response_path=None,
        )


class RuntimeManager:
    def __init__(
        self,
        registry: ModelRegistry,
        *,
        simulate: bool = False,
        use_bridge: bool = False,
        responder: SimulationResponder | None = None,
    ) -> None:
        self.registry = registry
        self.simulate = simulate
        self.use_bridge = use_bridge
        self.responder = responder
        self._adapters: dict[str, BaseRuntimeAdapter] = {
            "claude-code-cli": ClaudeRuntimeAdapter(),
            "codex-cli": CodexRuntimeAdapter(),
            "api:openai": OpenAIRuntimeAdapter(),
            "local:ollama": OllamaRuntimeAdapter(),
        }

    def mode_label(self) -> str:
        if self.simulate:
            return "simulate"
        return "bridge" if self.use_bridge else "execute"

    def _adapter_for_spec(self, spec: ModelSpec) -> BaseRuntimeAdapter:
        key = spec.runtime
        if spec.runtime == "api":
            key = f"api:{spec.provider}"
        elif spec.runtime == "local":
            key = f"local:{spec.provider}"
        adapter = self._adapters.get(key)
        if adapter is None:
            raise RuntimeExecutionError(f"no runtime adapter configured for {spec.name} ({key})")
        return adapter

    def _paths_for_request(self, session_id: str, stage_name: str, model_name: str) -> AdapterContext:
        digest = hashlib.sha1(f"{session_id}:{stage_name}:{model_name}".encode("utf-8")).hexdigest()[:10]
        stage_slug = _slug(stage_name)
        model_slug = _slug(model_name)
        log_path = self.registry.paths.logs_dir / f"{session_id}-{stage_slug}-{model_slug}-{digest}.log"
        response_path = self.registry.paths.responses_dir / f"{session_id}-{stage_slug}-{model_slug}-{digest}.txt"
        return AdapterContext(
            workspace_root=self.registry.paths.workspace_root,
            log_path=log_path,
            response_path=response_path,
        )

    def _simulation_output(self, model_name: str, prompt: str, metadata: dict[str, Any]) -> str:
        if self.responder is not None:
            return self.responder(model_name, prompt, metadata)
        stage_name = str(metadata.get("stage_name", "stage"))
        kind = str(metadata.get("kind", "completion"))
        preview = " ".join(prompt.strip().split())[:140]
        return f"[simulated {model_name}::{stage_name}::{kind}] {preview}"

    def complete(
        self,
        model_name: str,
        prompt: str,
        *,
        session_id: str,
        stage_name: str,
        metadata: dict[str, Any] | None = None,
    ) -> RuntimeResult:
        spec = self.registry.get(model_name)
        payload = dict(metadata or {})
        payload.setdefault("stage_name", stage_name)
        payload.setdefault("kind", "completion")
        if self.simulate:
            output = self._simulation_output(model_name, prompt, payload)
            return RuntimeResult(
                model=model_name,
                runtime=spec.runtime,
                output=output,
                exit_code=0,
                duration_ms=0,
                command=["simulate", model_name],
                log_path="",
                approximate_cost=_approximate_cost(spec, prompt, output),
                metadata=payload,
            )

        adapter = self._adapter_for_spec(spec)
        context = self._paths_for_request(session_id, stage_name, model_name)
        invocation = adapter.build_invocation(spec, prompt, context)
        start = time.monotonic()
        if self.use_bridge and adapter.supports_bridge():
            bridge_target = adapter.bridge_model(spec)
            if bridge_target is None:
                raise RuntimeExecutionError(f"bridge execution is not supported for {model_name}")
            result = runtime_bridge.submit_via_bridge(
                model=bridge_target,
                command=invocation.command,
                log_path=Path(invocation.log_path),
                workspace=Path(invocation.cwd),
            )
            stdout = ""
            exit_code = result.exit_code
        else:
            env = os.environ.copy()
            existing_pythonpath = env.get("PYTHONPATH")
            root = Path(__file__).resolve().parents[2]
            env["PYTHONPATH"] = str(root) if not existing_pythonpath else f"{root}{os.pathsep}{existing_pythonpath}"
            env["AEGIS_CORE_ROOT"] = str(root)
            env["AEGIS_WORKSPACE_ROOT"] = invocation.cwd
            completed = subprocess.run(
                invocation.command,
                cwd=invocation.cwd,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            log_path = Path(invocation.log_path)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            command_line = shlex.join(invocation.command)
            log_path.write_text(
                "\n".join(
                    [
                        f"$ {command_line}",
                        completed.stdout.rstrip(),
                        completed.stderr.rstrip(),
                    ]
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            stdout = completed.stdout
            exit_code = completed.returncode
        duration_ms = int((time.monotonic() - start) * 1000)
        output = adapter.extract_output(invocation, stdout, Path(invocation.log_path))
        if exit_code != 0:
            raise RuntimeExecutionError(f"{model_name} execution failed at {stage_name} with exit code {exit_code}")
        return RuntimeResult(
            model=model_name,
            runtime=spec.runtime,
            output=output,
            exit_code=exit_code,
            duration_ms=duration_ms,
            command=invocation.command,
            log_path=invocation.log_path,
            response_path=invocation.response_path,
            approximate_cost=_approximate_cost(spec, prompt, output),
            metadata=payload,
        )
