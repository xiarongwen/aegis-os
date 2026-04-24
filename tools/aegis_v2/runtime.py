from __future__ import annotations

import asyncio
import hashlib
import json
import os
import queue
import shlex
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from tools.host_runtime import HostCliRequest, augment_runtime_path, get_host_cli_adapter, resolve_runtime_binary
from tools.runtime_bridge import cli as runtime_bridge

from .registry import ModelRegistry, PROVIDER_ENV_MAP, RUNTIME_BINARY_MAP
from .types import ModelSpec, RuntimeInvocation, RuntimeResult


class RuntimeExecutionError(RuntimeError):
    def __init__(self, message: str, *, model_name: str | None = None, stage_name: str | None = None) -> None:
        super().__init__(message)
        self.model_name = model_name
        self.stage_name = stage_name


SimulationResponder = Callable[[str, str, dict[str, Any]], str]
RuntimeEventCallback = Callable[[dict[str, Any]], None]


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


def _codex_auth_source() -> Path | None:
    try:
        return Path.home() / ".codex" / "auth.json"
    except RuntimeError:
        return None


def _codex_config_source() -> Path | None:
    try:
        return Path.home() / ".codex" / "config.toml"
    except RuntimeError:
        return None


def _prepare_codex_home(workspace_root: Path) -> Path:
    codex_home = workspace_root / ".aegis" / "runtime-home" / "codex"
    codex_home.mkdir(parents=True, exist_ok=True)
    (codex_home / "sessions").mkdir(parents=True, exist_ok=True)

    for source, filename in (
        (_codex_auth_source(), "auth.json"),
        (_codex_config_source(), "config.toml"),
    ):
        if source is None or not source.exists():
            continue
        target = codex_home / filename
        try:
            source_mtime = source.stat().st_mtime
            target_mtime = target.stat().st_mtime if target.exists() else -1
            if target_mtime < source_mtime:
                shutil.copy2(source, target)
        except OSError:
            pass

    return codex_home


def _build_runtime_env(spec: ModelSpec, cwd: str, *, isolated_codex_home: bool = False) -> dict[str, str]:
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    root = Path(__file__).resolve().parents[2]
    env["PYTHONPATH"] = str(root) if not existing_pythonpath else f"{root}{os.pathsep}{existing_pythonpath}"
    env["AEGIS_CORE_ROOT"] = str(root)
    env["AEGIS_WORKSPACE_ROOT"] = cwd

    runtime_binary = RUNTIME_BINARY_MAP.get(spec.runtime)
    if runtime_binary:
        env["PATH"] = augment_runtime_path(env.get("PATH"), binary=runtime_binary)
        if spec.runtime == "codex-cli" and isolated_codex_home:
            env["CODEX_HOME"] = str(_prepare_codex_home(Path(cwd)))
    return env


def _normalize_invocation_command(invocation: RuntimeInvocation, spec: ModelSpec) -> None:
    runtime_binary = RUNTIME_BINARY_MAP.get(spec.runtime)
    if runtime_binary is None or not invocation.command:
        return
    resolved = resolve_runtime_binary(runtime_binary)
    if resolved:
        invocation.command[0] = resolved


def _extract_failure_reason(stdout: str, stderr: str, log_path: Path) -> str | None:
    combined = "\n".join(part for part in (stderr.strip(), stdout.strip()) if part).strip()
    if not combined and log_path.exists():
        combined = log_path.read_text(encoding="utf-8", errors="replace").strip()
    if not combined:
        return None
    lowered = combined.lower()
    if "usage limit" in lowered or "purchase more credits" in lowered:
        return "usage limit reached for the current Codex account"
    if "permission denied" in lowered and ".codex/sessions" in lowered:
        return "Codex session storage is not writable in the current environment"
    if "failed to load skill" in lowered and "invalid yaml" in lowered:
        return "a Codex skill in the current profile has invalid YAML"

    lines = [
        line.strip()
        for line in combined.splitlines()
        if line.strip() and not line.startswith("$ ") and "WARNING: proceeding" not in line
    ]
    if not lines:
        return None
    excerpt = lines[-1]
    return excerpt[:220]


def _failure_hint_for_spec(spec: ModelSpec, detail: str | None) -> str:
    lowered = (detail or "").lower()
    if "usage limit" in lowered or "purchase more credits" in lowered:
        return "wait for quota reset, upgrade the current Codex account, or select another available model"
    if "permission denied" in lowered and ("session storage" in lowered or ".codex/sessions" in lowered):
        return "check write access for the workspace-scoped Codex runtime home, or select another available model"
    if "invalid yaml" in lowered and "skill" in lowered:
        return "repair or remove the broken Codex skill, or select another available model"
    if "stream disconnected" in lowered or "error sending request" in lowered:
        return "check network access for the nested runtime, or select another available model"
    if "unauthorized" in lowered or "invalid api key" in lowered or "authentication" in lowered:
        return "refresh the Codex login or API key, or select another available model"
    if spec.runtime in {"claude-code-cli", "codex-cli"}:
        binary = RUNTIME_BINARY_MAP.get(spec.runtime)
        return f"install or sign in to the `{binary}` CLI, or select another available model"
    if spec.runtime == "api":
        env_name = PROVIDER_ENV_MAP.get(spec.provider)
        return f"set `{env_name}` or choose a CLI-backed model"
    if spec.runtime == "local":
        return "install and start `ollama`, or switch to a hosted model"
    return "check runtime configuration or choose another model"


def _is_fallback_worthy_error(message: str) -> bool:
    lowered = message.lower()
    markers = (
        "unauthorized",
        "incorrect api key",
        "invalid api key",
        "authentication",
        "usage limit",
        "purchase more credits",
        "permission denied",
        "stream disconnected",
        "error sending request",
        "timed out",
        "runtime binary",
        "failed during",
    )
    return any(marker in lowered for marker in markers)


def _should_retry_codex_with_isolated_home(detail: str | None) -> bool:
    lowered = (detail or "").lower()
    if not lowered:
        return False
    return (
        ("permission denied" in lowered and ".codex/sessions" in lowered)
        or "session storage is not writable" in lowered
        or ("invalid yaml" in lowered and "skill" in lowered)
    )


def _start_stream_reader(
    stream: Any,
    *,
    source: str,
    target_queue: queue.Queue[tuple[str, str | None]],
) -> threading.Thread:
    def _reader() -> None:
        try:
            for line in iter(stream.readline, ""):
                if not line:
                    break
                target_queue.put((source, line))
        finally:
            target_queue.put((source, None))

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()
    return thread


def _simulated_subtasks(prompt: str, count: int) -> list[str]:
    request = prompt.split("Original request:\n", 1)[-1].strip() or prompt.strip()
    return [f"Subtask {index + 1}: {request}" for index in range(count)]


def _simulated_review_verdict(metadata: dict[str, Any]) -> str:
    iteration = int(metadata.get("iteration", 1) or 1)
    return "APPROVED" if iteration >= 2 else "REVISE"


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
        return get_host_cli_adapter("codex").bridge_name

    def build_invocation(self, spec: ModelSpec, prompt: str, context: AdapterContext) -> RuntimeInvocation:
        invocation = get_host_cli_adapter("codex").build_invocation(
            HostCliRequest(
                prompt=prompt,
                workspace_root=context.workspace_root,
                core_root=Path(__file__).resolve().parents[2],
                model=spec.name,
                output_path=context.response_path,
            )
        )
        return RuntimeInvocation(
            model=spec.name,
            runtime=spec.runtime,
            command=invocation.command,
            cwd=invocation.cwd or str(context.workspace_root),
            log_path=str(context.log_path),
            response_path=invocation.output_path,
        )


class ClaudeRuntimeAdapter(BaseRuntimeAdapter):
    def supports_bridge(self) -> bool:
        return True

    def bridge_model(self, spec: ModelSpec) -> str | None:
        return get_host_cli_adapter("claude").bridge_name

    def build_invocation(self, spec: ModelSpec, prompt: str, context: AdapterContext) -> RuntimeInvocation:
        invocation = get_host_cli_adapter("claude").build_invocation(
            HostCliRequest(
                prompt=prompt,
                workspace_root=context.workspace_root,
                core_root=Path(__file__).resolve().parents[2],
                model=spec.name,
                extra_args=["--dangerously-skip-permissions"],
            )
        )
        return RuntimeInvocation(
            model=spec.name,
            runtime=spec.runtime,
            command=invocation.command,
            cwd=invocation.cwd or str(context.workspace_root),
            log_path=str(context.log_path),
            response_path=None,
        )


class AiderRuntimeAdapter(BaseRuntimeAdapter):
    def build_invocation(self, spec: ModelSpec, prompt: str, context: AdapterContext) -> RuntimeInvocation:
        invocation = get_host_cli_adapter("aider").build_invocation(
            HostCliRequest(
                prompt=prompt,
                workspace_root=context.workspace_root,
                core_root=Path(__file__).resolve().parents[2],
                model=spec.name,
            )
        )
        return RuntimeInvocation(
            model=spec.name,
            runtime=spec.runtime,
            command=invocation.command,
            cwd=invocation.cwd or str(context.workspace_root),
            log_path=str(context.log_path),
            response_path=None,
        )


class OpencodeRuntimeAdapter(BaseRuntimeAdapter):
    def build_invocation(self, spec: ModelSpec, prompt: str, context: AdapterContext) -> RuntimeInvocation:
        invocation = get_host_cli_adapter("opencode").build_invocation(
            HostCliRequest(
                prompt=prompt,
                workspace_root=context.workspace_root,
                core_root=Path(__file__).resolve().parents[2],
                model=spec.name,
            )
        )
        return RuntimeInvocation(
            model=spec.name,
            runtime=spec.runtime,
            command=invocation.command,
            cwd=invocation.cwd or str(context.workspace_root),
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
        event_callback: RuntimeEventCallback | None = None,
    ) -> None:
        self.registry = registry
        self.simulate = simulate
        self.use_bridge = use_bridge
        self.responder = responder
        self.event_callback = event_callback
        self._adapters: dict[str, BaseRuntimeAdapter] = {
            "claude-code-cli": ClaudeRuntimeAdapter(),
            "codex-cli": CodexRuntimeAdapter(),
            "aider-cli": AiderRuntimeAdapter(),
            "opencode-cli": OpencodeRuntimeAdapter(),
            "api:openai": OpenAIRuntimeAdapter(),
            "local:ollama": OllamaRuntimeAdapter(),
        }

    def mode_label(self) -> str:
        if self.simulate:
            return "simulate"
        return "bridge" if self.use_bridge else "execute"

    def _emit_event(self, payload: dict[str, Any]) -> None:
        if self.event_callback is None:
            return
        self.event_callback(payload)

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

    def preflight_plan(self, plan: Any) -> None:
        if not self.use_bridge:
            return
        unsupported: list[str] = []
        for step in getattr(plan, "steps", []):
            model_name = getattr(step, "model", None)
            if not model_name or model_name not in self.registry.names():
                continue
            spec = self.registry.get(model_name)
            adapter = self._adapter_for_spec(spec)
            if not adapter.supports_bridge() or adapter.bridge_model(spec) is None:
                unsupported.append(f"{getattr(step, 'name', '<stage>')}:{model_name}")
        if unsupported:
            raise RuntimeExecutionError(
                "bridge preflight failed for stages: " + ", ".join(unsupported),
                stage_name="preflight",
            )

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
        role = str(metadata.get("role", "")).strip()
        perspective = str(metadata.get("perspective", "")).strip()
        subtask = str(metadata.get("subtask", "")).strip()
        if kind == "reviewer":
            verdict = _simulated_review_verdict(metadata)
            if verdict == "APPROVED":
                return "APPROVED\nImplementation now satisfies the requested constraints.\nNo blocking issues remain."
            return "REVISE\n- Add stronger edge-case handling.\n- Clarify failure behaviour.\n- Tighten test coverage around the main path."
        if kind == "splitter":
            worker_count = 3
            marker = "Return exactly "
            if marker in prompt:
                tail = prompt.split(marker, 1)[1]
                digits = "".join(ch for ch in tail[:3] if ch.isdigit())
                if digits:
                    worker_count = max(1, int(digits))
            subtasks = _simulated_subtasks(prompt, worker_count)
            return json.dumps(subtasks, ensure_ascii=False)
        if kind == "aggregator":
            if stage_name == "aggregate":
                return (
                    "Agreements\n- The proposed direction is broadly sound.\n\n"
                    "Disagreements\n- Some implementation details still vary across contributors.\n\n"
                    "Discarded Points\n- Low-confidence suggestions were omitted.\n\n"
                    "Final Decision\n- Proceed with the consolidated implementation plan.\n\n"
                    "Rationale\n- This combines the strongest shared recommendations while removing conflicts."
                )
            return f"Aggregated result for {stage_name}."
        if kind == "expert":
            role_line = role or "generalist"
            focus_line = perspective or "technical review"
            return (
                "Verdict\n- Conditionally approve.\n\n"
                f"Key Findings\n- Role `{role_line}` focused on {focus_line}.\n"
                "- The request is feasible with moderate implementation risk.\n\n"
                "Risks\n- Hidden edge cases should be verified.\n\n"
                "Recommendation\n- Proceed, but validate the critical path before merge.\n\n"
                "Confidence\n- 7/10"
            )
        if kind == "worker":
            return f"Worker output for {subtask or stage_name}: implemented the assigned slice and noted integration points."
        if kind == "coder":
            return f"Updated implementation draft for iteration {metadata.get('iteration', 1)} with reviewer feedback applied."
        if kind == "single":
            return f"Simulated single-stage result for {stage_name}: completed the requested task."
        if kind == "stage":
            return f"Simulated pipeline stage `{stage_name}` completed with a concise handoff summary for the next stage."
        preview = " ".join(prompt.strip().split())[:140]
        return f"[simulated {model_name}::{stage_name}::{kind}] {preview}"

    def _fallback_candidates(self, model_name: str) -> list[str]:
        return self._ranked_fallback_candidates(model_name, {})

    def _runtime_config(self) -> dict[str, Any]:
        return self.registry.config.get("runtime", {})

    def _retry_count(self) -> int:
        return max(1, int(self._runtime_config().get("retries", 1) or 1))

    def _timeout_seconds(self, spec: ModelSpec) -> int:
        timeout_cfg = self._runtime_config().get("timeout_seconds", {})
        if not isinstance(timeout_cfg, dict):
            return 120
        if spec.runtime in timeout_cfg:
            return int(timeout_cfg[spec.runtime])
        return int(timeout_cfg.get("default", 120))

    def _required_capabilities(self, metadata: dict[str, Any]) -> set[str]:
        kind = str(metadata.get("kind", "completion"))
        capability_map = {
            "coder": {"code_generation", "fast_code_generation", "refactoring"},
            "reviewer": {"code_review", "security_audit", "complex_reasoning"},
            "worker": {"fast_code_generation", "debugging", "testing", "code_review"},
            "aggregator": {"complex_reasoning", "long_context", "architecture_design", "code_review"},
            "splitter": {"complex_reasoning", "architecture_design"},
            "expert": {"complex_reasoning", "code_review", "architecture_design"},
            "stage": {"debugging", "code_generation", "testing"},
            "single": {"code_generation", "complex_reasoning"},
            "completion": set(),
        }
        return capability_map.get(kind, set())

    def _fallback_score(self, candidate: str, current: ModelSpec, metadata: dict[str, Any]) -> tuple[int, int, float, str]:
        spec = self.registry.get(candidate)
        required = self._required_capabilities(metadata)
        capabilities = set(spec.capabilities)
        matched = len(required & capabilities)
        same_runtime = 1 if spec.runtime == current.runtime else 0
        cost = spec.cost_per_1k_tokens
        return (-matched, -same_runtime, cost, spec.name)

    def _ranked_fallback_candidates(self, model_name: str, metadata: dict[str, Any]) -> list[str]:
        current = self.registry.get(model_name)
        enabled = self.registry.bundle.enabled_model_names()
        candidates = [
            candidate
            for candidate in enabled
            if candidate != model_name and candidate in self.registry.names() and self.registry.check_model(candidate).available
        ]
        return sorted(candidates, key=lambda candidate: self._fallback_score(candidate, current, metadata))

    def _hint_for_spec(self, spec: ModelSpec) -> str:
        if spec.runtime in {"claude-code-cli", "codex-cli"}:
            binary = RUNTIME_BINARY_MAP.get(spec.runtime)
            return f"install or sign in to the `{binary}` CLI, or select another available model"
        if spec.runtime == "api":
            env_name = PROVIDER_ENV_MAP.get(spec.provider)
            return f"set `{env_name}` or choose a CLI-backed model"
        if spec.runtime == "local":
            return "install and start `ollama`, or switch to a hosted model"
        return "check runtime configuration or choose another model"

    def _execute_once(
        self,
        spec: ModelSpec,
        prompt: str,
        *,
        session_id: str,
        stage_name: str,
        payload: dict[str, Any],
        isolated_codex_home: bool = False,
    ) -> RuntimeResult:
        adapter = self._adapter_for_spec(spec)
        context = self._paths_for_request(session_id, stage_name, spec.name)
        invocation = adapter.build_invocation(spec, prompt, context)
        _normalize_invocation_command(invocation, spec)
        start = time.monotonic()
        try:
            if self.use_bridge and adapter.supports_bridge():
                bridge_target = adapter.bridge_model(spec)
                if bridge_target is None:
                    raise RuntimeExecutionError(
                        f"bridge execution is not supported for `{spec.name}`; {self._hint_for_spec(spec)}",
                        model_name=spec.name,
                        stage_name=stage_name,
                    )
                result = runtime_bridge.submit_via_bridge(
                    model=bridge_target,
                    command=invocation.command,
                    log_path=Path(invocation.log_path),
                    workspace=Path(invocation.cwd),
                    event_callback=self.event_callback,
                    event_payload={
                        "model": spec.name,
                        "stage_name": stage_name,
                    },
                )
                stdout = ""
                stderr = ""
                exit_code = result.exit_code
            else:
                env = _build_runtime_env(spec, invocation.cwd, isolated_codex_home=isolated_codex_home)
                process = subprocess.Popen(
                    invocation.command,
                    cwd=invocation.cwd,
                    env=env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=1,
                )
                stream_queue: queue.Queue[tuple[str, str | None]] = queue.Queue()
                stdout_chunks: list[str] = []
                stderr_chunks: list[str] = []
                stdout_done = process.stdout is None
                stderr_done = process.stderr is None
                stdout_thread = None if process.stdout is None else _start_stream_reader(process.stdout, source="stdout", target_queue=stream_queue)
                stderr_thread = None if process.stderr is None else _start_stream_reader(process.stderr, source="stderr", target_queue=stream_queue)
                deadline = time.monotonic() + self._timeout_seconds(spec)
                while True:
                    if time.monotonic() > deadline:
                        process.kill()
                        raise subprocess.TimeoutExpired(invocation.command, self._timeout_seconds(spec))
                    try:
                        source, chunk = stream_queue.get(timeout=0.1)
                    except queue.Empty:
                        if process.poll() is not None and stdout_done and stderr_done:
                            break
                        continue
                    if chunk is None:
                        if source == "stdout":
                            stdout_done = True
                        elif source == "stderr":
                            stderr_done = True
                        if process.poll() is not None and stdout_done and stderr_done:
                            break
                        continue
                    line = chunk.rstrip("\n")
                    if source == "stdout":
                        stdout_chunks.append(line)
                    else:
                        stderr_chunks.append(line)
                    self._emit_event(
                        {
                            "kind": "runtime_output",
                            "model": spec.name,
                            "stage_name": stage_name,
                            "source": source,
                            "text": line,
                        }
                    )
                if stdout_thread is not None:
                    stdout_thread.join(timeout=1)
                if stderr_thread is not None:
                    stderr_thread.join(timeout=1)
                exit_code = process.wait(timeout=1)
                completed_stdout = "\n".join(stdout_chunks).strip()
                completed_stderr = "\n".join(stderr_chunks).strip()
                log_path = Path(invocation.log_path)
                log_path.parent.mkdir(parents=True, exist_ok=True)
                command_line = shlex.join(invocation.command)
                log_path.write_text(
                    "\n".join(
                        [
                            f"$ {command_line}",
                            completed_stdout,
                            completed_stderr,
                        ]
                    ).strip()
                    + "\n",
                    encoding="utf-8",
                )
                stdout = completed_stdout
                stderr = completed_stderr
        except FileNotFoundError as exc:
            raise RuntimeExecutionError(
                f"runtime binary for `{spec.name}` is missing; {self._hint_for_spec(spec)}",
                model_name=spec.name,
                stage_name=stage_name,
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeExecutionError(
                f"`{spec.name}` timed out during `{stage_name}` after {self._timeout_seconds(spec)}s; {self._hint_for_spec(spec)}",
                model_name=spec.name,
                stage_name=stage_name,
            ) from exc

        duration_ms = int((time.monotonic() - start) * 1000)
        output = adapter.extract_output(invocation, stdout, Path(invocation.log_path))
        if exit_code != 0:
            detail = _extract_failure_reason(stdout, stderr, Path(invocation.log_path))
            detail_suffix = f" Cause: {detail}." if detail else ""
            hint = _failure_hint_for_spec(spec, detail)
            raise RuntimeExecutionError(
                f"`{spec.name}` failed during `{stage_name}` with exit code {exit_code}.{detail_suffix} {hint}",
                model_name=spec.name,
                stage_name=stage_name,
            )
        return RuntimeResult(
            model=spec.name,
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
        health = self.registry.check_model(model_name)
        fallback_candidates = self._ranked_fallback_candidates(model_name, payload)
        if not health.available:
            if fallback_candidates:
                fallback_model = fallback_candidates[0]
                payload["fallback_from"] = model_name
                payload["fallback_reason"] = health.details
                payload["fallback_to"] = fallback_model
                spec = self.registry.get(fallback_model)
            else:
                raise RuntimeExecutionError(
                    f"`{model_name}` is unavailable ({health.details}); {self._hint_for_spec(spec)}",
                    model_name=model_name,
                    stage_name=stage_name,
                )

        attempts = self._retry_count()
        last_error: RuntimeExecutionError | None = None
        tried_models: list[str] = []

        while True:
            tried_models.append(spec.name)
            retried_with_isolated_home = False
            for attempt in range(1, attempts + 1):
                try:
                    payload["attempt"] = attempt
                    payload["max_attempts"] = attempts
                    payload["retrying"] = False
                    payload["isolated_codex_home"] = False
                    return self._execute_once(
                        spec,
                        prompt,
                        session_id=session_id,
                        stage_name=stage_name,
                        payload=payload,
                    )
                except RuntimeExecutionError as exc:
                    last_error = exc
                    payload["last_error"] = str(exc)
                    if spec.runtime == "codex-cli" and not retried_with_isolated_home and _should_retry_codex_with_isolated_home(str(exc)):
                        retried_with_isolated_home = True
                        payload["retrying"] = True
                        payload["isolated_codex_home"] = True
                        try:
                            return self._execute_once(
                                spec,
                                prompt,
                                session_id=session_id,
                                stage_name=stage_name,
                                payload=payload,
                                isolated_codex_home=True,
                            )
                        except RuntimeExecutionError as isolated_exc:
                            last_error = isolated_exc
                            payload["last_error"] = str(isolated_exc)
                    if attempt < attempts:
                        payload["retrying"] = True
                        continue
                    payload["retrying"] = False

            assert last_error is not None
            if not _is_fallback_worthy_error(str(last_error)):
                raise last_error

            fallback_candidates = [
                candidate
                for candidate in self._ranked_fallback_candidates(spec.name, payload)
                if candidate not in tried_models
            ]
            if not fallback_candidates:
                raise last_error

            fallback_model = fallback_candidates[0]
            payload["fallback_from"] = spec.name
            payload["fallback_reason"] = str(last_error)
            payload["fallback_to"] = fallback_model
            spec = self.registry.get(fallback_model)

    async def acomplete(
        self,
        model_name: str,
        prompt: str,
        *,
        session_id: str,
        stage_name: str,
        metadata: dict[str, Any] | None = None,
    ) -> RuntimeResult:
        """Async wrapper around :py meth:`complete`.

        Delegates to the synchronous implementation via :py func:`asyncio.to_thread`
        so that concurrent stages within a pattern can run under ``asyncio``
        instead of ``ThreadPoolExecutor``.
        """
        return await asyncio.to_thread(
            self.complete,
            model_name,
            prompt,
            session_id=session_id,
            stage_name=stage_name,
            metadata=metadata,
        )
