from __future__ import annotations

import hashlib
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .config import AppPaths
from .models import DEFAULT_MODELS, ModelSpec
from .types import RunStep


class RuntimeError1(RuntimeError):
    pass


@dataclass(slots=True)
class RuntimeResult:
    model: str
    runtime: str
    output: str
    exit_code: int
    duration_ms: int
    command: list[str]
    log_path: str
    response_path: str | None = None


class RuntimeManager:
    def __init__(self, paths: AppPaths, *, timeout_seconds: int = 180, use_bridge: bool = False) -> None:
        self.paths = paths
        self.timeout_seconds = timeout_seconds
        self.use_bridge = use_bridge

    def complete(self, step: RunStep, *, session_id: str, prompt: str) -> RuntimeResult:
        spec = DEFAULT_MODELS.get(step.model)
        if spec is None:
            raise RuntimeError1(f"model is not registered: {step.model}")
        digest = hashlib.sha1(f"{session_id}:{step.name}:{step.model}".encode("utf-8")).hexdigest()[:10]
        log_path = self.paths.logs_dir / f"{session_id}-{step.name}-{step.model}-{digest}.log"
        response_path = self.paths.responses_dir / f"{session_id}-{step.name}-{step.model}-{digest}.txt"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        response_path.parent.mkdir(parents=True, exist_ok=True)
        command = self._command_for(spec, prompt, response_path)
        if self.use_bridge and spec.runtime in {"codex-cli", "claude-code-cli"}:
            return self._complete_via_bridge(step, command, log_path, response_path, session_id=session_id, runtime=spec.runtime)
        return self._run_command(step, command, log_path, response_path, runtime=spec.runtime)

    def _command_for(self, spec: ModelSpec, prompt: str, response_path: Path) -> list[str]:
        runtime = spec.runtime
        model = spec.name
        runtime_model = spec.runtime_model
        if runtime == "codex-cli":
            if not shutil.which("codex"):
                raise RuntimeError1("codex CLI is missing; install/sign in to Codex or rerun with --simulate")
            command = ["codex", "exec", "--full-auto", "-C", str(self.paths.workspace_root), "-o", str(response_path)]
            if runtime_model:
                command.extend(["-m", runtime_model])
            command.append(prompt)
            return command
        if runtime == "claude-code-cli":
            if not shutil.which("claude"):
                raise RuntimeError1("claude CLI is missing; install/sign in to Claude Code or rerun with --simulate")
            command = [
                "claude",
                "-p",
                "--bare",
                "--permission-mode",
                "bypassPermissions",
                "--output-format",
                "text",
                "--add-dir",
                str(self.paths.workspace_root),
            ]
            if runtime_model:
                command.extend(["--model", runtime_model])
            command.append(prompt)
            return command
        raise RuntimeError1(f"unsupported runtime for {model}: {runtime}")

    def _run_command(
        self,
        step: RunStep,
        command: list[str],
        log_path: Path,
        response_path: Path,
        *,
        runtime: str,
    ) -> RuntimeResult:
        started = time.monotonic()
        with log_path.open("w", encoding="utf-8") as handle:
            handle.write(f"$ {shlex.join(command)}\n")
            completed = subprocess.run(
                command,
                cwd=str(self.paths.workspace_root),
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
            if completed.stdout:
                handle.write(completed.stdout)
            if completed.stderr:
                handle.write(completed.stderr)
        output = ""
        if response_path.exists():
            output = response_path.read_text(encoding="utf-8", errors="replace").strip()
        if not output:
            output = (completed.stdout or completed.stderr or "").strip()
        duration_ms = int((time.monotonic() - started) * 1000)
        if completed.returncode != 0:
            raise RuntimeError1(f"{step.name} {step.model} failed with exit code {completed.returncode}; log: {log_path}")
        return RuntimeResult(step.model, runtime, output, completed.returncode, duration_ms, command, str(log_path), str(response_path))

    def _complete_via_bridge(
        self,
        step: RunStep,
        command: list[str],
        log_path: Path,
        response_path: Path,
        *,
        session_id: str,
        runtime: str,
    ) -> RuntimeResult:
        from tools.runtime_bridge import cli as bridge

        model = "codex" if runtime == "codex-cli" else "claude"
        result = bridge.submit_via_bridge(
            workspace=self.paths.workspace_root,
            model=model,
            command=command,
            log_path=log_path,
        )
        output = ""
        if response_path.exists():
            output = response_path.read_text(encoding="utf-8", errors="replace").strip()
        if not output and log_path.exists():
            output = log_path.read_text(encoding="utf-8", errors="replace").strip()
        if result.exit_code != 0:
            raise RuntimeError1(f"{step.name} {step.model} bridge execution failed with exit code {result.exit_code}; log: {log_path}")
        return RuntimeResult(step.model, f"bridge:{runtime}", output, result.exit_code, 0, command, str(log_path), str(response_path))
