from __future__ import annotations

import os
import subprocess
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class AppPaths:
    workspace_root: Path
    aegis_dir: Path
    config_path: Path
    state_dir: Path
    runs_dir: Path
    session_db_path: Path
    logs_dir: Path
    responses_dir: Path


def find_git_root(start: Path) -> Path | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return Path(value).resolve() if value else None


def resolve_workspace(explicit: str | Path | None = None) -> Path:
    candidate = explicit or os.environ.get("AEGIS_WORKSPACE_ROOT")
    if candidate:
        return Path(candidate).expanduser().resolve()
    return find_git_root(Path.cwd()) or Path.cwd().resolve()


def build_paths(explicit: str | Path | None = None) -> AppPaths:
    workspace_root = resolve_workspace(explicit)
    aegis_dir = workspace_root / ".aegis"
    state_dir = aegis_dir / "state"
    return AppPaths(
        workspace_root=workspace_root,
        aegis_dir=aegis_dir,
        config_path=aegis_dir / "aegis-1.json",
        state_dir=state_dir,
        runs_dir=aegis_dir / "runs" / "aegis-1",
        session_db_path=state_dir / "aegis1_sessions.db",
        logs_dir=state_dir / "logs",
        responses_dir=state_dir / "responses",
    )


def ensure_dirs(paths: AppPaths) -> None:
    paths.aegis_dir.mkdir(parents=True, exist_ok=True)
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    paths.runs_dir.mkdir(parents=True, exist_ok=True)
    paths.logs_dir.mkdir(parents=True, exist_ok=True)
    paths.responses_dir.mkdir(parents=True, exist_ok=True)


DEFAULT_CONFIG: dict[str, Any] = {
    "version": "1.0",
    "mode": "balanced",
    "runtime": {
        "simulate_by_default": True,
        "timeout_seconds": 180,
        "bridge": "manual",
    },
    "verification": {
        "commands": [],
        "auto_detect": True,
    },
    "cost": {
        "per_task_budget": None,
    },
}


def load_config(paths: AppPaths) -> dict[str, Any]:
    if not paths.config_path.exists():
        return dict(DEFAULT_CONFIG)
    try:
        payload = json.loads(paths.config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return dict(DEFAULT_CONFIG)
    if not isinstance(payload, dict):
        return dict(DEFAULT_CONFIG)
    merged = dict(DEFAULT_CONFIG)
    for key, value in payload.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def init_config(paths: AppPaths, *, force: bool = False) -> list[Path]:
    ensure_dirs(paths)
    if paths.config_path.exists() and not force:
        return []
    paths.config_path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return [paths.config_path]
