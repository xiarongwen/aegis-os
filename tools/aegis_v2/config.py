from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import os

import yaml

from .defaults import DEFAULT_CONFIG_YAML, DEFAULT_REGISTRY_YAML


@dataclass(slots=True)
class AppPaths:
    workspace_root: Path
    aegis_dir: Path
    config_path: Path
    registry_path: Path
    state_dir: Path
    logs_dir: Path
    responses_dir: Path
    session_db_path: Path


def find_git_root(start: Path) -> Path | None:
    current = start.resolve()
    if (current / ".git").exists():
        return current
    try:
        completed = subprocess.run(
            ["git", "-C", str(current), "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None
    if completed.returncode != 0:
        return None
    candidate = completed.stdout.strip()
    return Path(candidate).resolve() if candidate else None


def resolve_workspace_root(explicit: str | Path | None = None) -> Path:
    candidate = explicit or os.environ.get("AEGIS_WORKSPACE_ROOT")
    if candidate:
        return Path(candidate).expanduser().resolve()
    git_root = find_git_root(Path.cwd())
    if git_root is not None:
        return git_root
    return Path.cwd().resolve()


def build_paths(explicit_workspace: str | Path | None = None) -> AppPaths:
    workspace_root = resolve_workspace_root(explicit_workspace)
    aegis_dir = workspace_root / ".aegis"
    state_dir = aegis_dir / "state"
    return AppPaths(
        workspace_root=workspace_root,
        aegis_dir=aegis_dir,
        config_path=aegis_dir / "config.yml",
        registry_path=aegis_dir / "models" / "registry.yml",
        state_dir=state_dir,
        logs_dir=state_dir / "logs",
        responses_dir=state_dir / "responses",
        session_db_path=state_dir / "sessions.db",
    )


def ensure_runtime_dirs(paths: AppPaths) -> None:
    paths.aegis_dir.mkdir(parents=True, exist_ok=True)
    paths.registry_path.parent.mkdir(parents=True, exist_ok=True)
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    paths.logs_dir.mkdir(parents=True, exist_ok=True)
    paths.responses_dir.mkdir(parents=True, exist_ok=True)


def load_yaml(path: Path, default_text: str) -> dict[str, Any]:
    if not path.exists():
        payload = yaml.safe_load(default_text)
        return payload if isinstance(payload, dict) else {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def load_config(paths: AppPaths) -> dict[str, Any]:
    return load_yaml(paths.config_path, DEFAULT_CONFIG_YAML)


def load_registry(paths: AppPaths) -> dict[str, Any]:
    return load_yaml(paths.registry_path, DEFAULT_REGISTRY_YAML)


def init_workspace_files(paths: AppPaths, *, force: bool = False) -> list[Path]:
    ensure_runtime_dirs(paths)
    written: list[Path] = []
    desired = (
        (paths.config_path, DEFAULT_CONFIG_YAML),
        (paths.registry_path, DEFAULT_REGISTRY_YAML),
    )
    for path, content in desired:
        if path.exists() and not force:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written
