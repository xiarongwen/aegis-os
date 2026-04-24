from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path


COMMON_BINARY_DIRS = (
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/usr/bin",
    "/bin",
)

HOME_BINARY_DIRS = (
    ".local/bin",
    "bin",
    ".bun/bin",
    ".volta/bin",
)

HOST_RUNTIME_BINARY_MAP = {
    "codex": "codex",
    "claude": "claude",
    "aider": "aider",
    "opencode": "opencode",
}


def _home_dir() -> Path | None:
    try:
        return Path.home()
    except RuntimeError:
        return None


def runtime_search_dirs(binary: str) -> list[Path]:
    directories: list[Path] = []
    seen: set[str] = set()

    def add_directory(path: Path) -> None:
        candidate = str(path)
        if candidate in seen:
            return
        seen.add(candidate)
        directories.append(path)

    for raw in os.environ.get("PATH", "").split(os.pathsep):
        if raw:
            add_directory(Path(raw).expanduser())

    home = _home_dir()
    if home is not None:
        for rel in HOME_BINARY_DIRS:
            add_directory(home / rel)
        if binary in {"codex", "claude", "opencode"}:
            for path in sorted((home / ".nvm" / "versions" / "node").glob("*/bin")):
                add_directory(path)

    for raw in COMMON_BINARY_DIRS:
        add_directory(Path(raw))

    return [path for path in directories if path.exists() and path.is_dir()]


def augment_runtime_path(path_value: str | None, *, binary: str | None = None) -> str:
    entries: list[str] = []
    seen: set[str] = set()

    def add_entry(value: str) -> None:
        if not value or value in seen:
            return
        seen.add(value)
        entries.append(value)

    for raw in (path_value or "").split(os.pathsep):
        if raw:
            add_entry(raw)
    for directory in runtime_search_dirs(binary or ""):
        add_entry(str(directory))
    return os.pathsep.join(entries)


def resolve_runtime_binary(binary: str) -> str | None:
    direct = shutil.which(binary)
    if direct:
        return direct
    for directory in runtime_search_dirs(binary):
        candidate = directory / binary
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
    return None


def build_base_env(
    *,
    core_root: Path,
    workspace_root: Path,
    binary: str | None = None,
    env_overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(core_root) if not existing_pythonpath else f"{core_root}{os.pathsep}{existing_pythonpath}"
    env["AEGIS_CORE_ROOT"] = str(core_root)
    env["AEGIS_WORKSPACE_ROOT"] = str(workspace_root)
    if binary:
        env["PATH"] = augment_runtime_path(env.get("PATH"), binary=binary)
    if env_overrides:
        env.update(env_overrides)
    return env


@dataclass(slots=True)
class HostCliInvocation:
    runtime: str
    command: list[str]
    env: dict[str, str]
    cwd: str | None = None
    output_path: str | None = None


@dataclass(slots=True)
class HostCliRequest:
    prompt: str
    workspace_root: Path
    core_root: Path
    model: str | None = None
    output_path: Path | None = None
    use_search: bool = False
    extra_args: list[str] = field(default_factory=list)
    extra_add_dirs: list[Path] = field(default_factory=list)
    env_overrides: dict[str, str] = field(default_factory=dict)


class HostCliAdapter:
    name = "base"
    binary = ""
    bridge_name: str | None = None

    def available(self) -> bool:
        return resolve_runtime_binary(self.binary) is not None

    def _resolved_binary(self) -> str:
        return self.binary

    def _base_env(self, request: HostCliRequest) -> dict[str, str]:
        return build_base_env(
            core_root=request.core_root,
            workspace_root=request.workspace_root,
            binary=self.binary,
            env_overrides=request.env_overrides,
        )

    def build_invocation(self, request: HostCliRequest) -> HostCliInvocation:
        raise NotImplementedError


class CodexHostAdapter(HostCliAdapter):
    name = "codex"
    binary = "codex"
    bridge_name = "codex"

    def build_invocation(self, request: HostCliRequest) -> HostCliInvocation:
        if request.output_path is None:
            raise ValueError("codex requires an output_path")
        command = [self._resolved_binary()]
        if request.use_search:
            command.append("--search")
        command.extend(["exec", "--full-auto", "-C", str(request.workspace_root), "-o", str(request.output_path)])
        if request.model and request.model != "codex":
            command.extend(["-m", request.model])
        command.extend(request.extra_args)
        command.append(request.prompt)
        return HostCliInvocation(
            runtime=self.name,
            command=command,
            env=self._base_env(request),
            cwd=str(request.workspace_root),
            output_path=str(request.output_path),
        )


class ClaudeHostAdapter(HostCliAdapter):
    name = "claude"
    binary = "claude"
    bridge_name = "claude"

    def build_invocation(self, request: HostCliRequest) -> HostCliInvocation:
        command = [self._resolved_binary(), "-p", "--bare"]
        command.extend(request.extra_args)
        command.extend(["--output-format", "text"])
        for add_dir in [request.workspace_root, request.core_root, *request.extra_add_dirs]:
            command.extend(["--add-dir", str(add_dir)])
        command.append(request.prompt)
        return HostCliInvocation(
            runtime=self.name,
            command=command,
            env=self._base_env(request),
            cwd=str(request.workspace_root),
        )


class AiderHostAdapter(HostCliAdapter):
    name = "aider"
    binary = "aider"
    bridge_name = None

    def build_invocation(self, request: HostCliRequest) -> HostCliInvocation:
        command = [self._resolved_binary(), "--message", request.prompt]
        if request.model:
            command.extend(["--model", request.model])
        command.extend(request.extra_args)
        return HostCliInvocation(
            runtime=self.name,
            command=command,
            env=self._base_env(request),
            cwd=str(request.workspace_root),
        )


class OpencodeHostAdapter(HostCliAdapter):
    name = "opencode"
    binary = "opencode"
    bridge_name = None

    def build_invocation(self, request: HostCliRequest) -> HostCliInvocation:
        command = [self._resolved_binary(), "run"]
        if request.model:
            command.extend(["--model", request.model])
        command.extend(request.extra_args)
        command.append(request.prompt)
        return HostCliInvocation(
            runtime=self.name,
            command=command,
            env=self._base_env(request),
            cwd=str(request.workspace_root),
        )


HOST_CLI_ADAPTERS: dict[str, HostCliAdapter] = {
    "codex": CodexHostAdapter(),
    "claude": ClaudeHostAdapter(),
    "aider": AiderHostAdapter(),
    "opencode": OpencodeHostAdapter(),
}


def get_host_cli_adapter(name: str) -> HostCliAdapter:
    adapter = HOST_CLI_ADAPTERS.get(name)
    if adapter is None:
        raise KeyError(f"unsupported host cli adapter: {name}")
    return adapter


def available_host_clis(names: list[str] | None = None) -> list[str]:
    requested = names or list(HOST_CLI_ADAPTERS.keys())
    return [name for name in requested if name in HOST_CLI_ADAPTERS and HOST_CLI_ADAPTERS[name].available()]
