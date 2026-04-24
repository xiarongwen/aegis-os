from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import AppPaths


@dataclass(slots=True)
class DoctorCheck:
    name: str
    ok: bool
    details: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_doctor(paths: AppPaths) -> dict[str, Any]:
    checks = [
        _python_check(),
        _module_check("rich"),
        _module_check("textual"),
        _binary_check("git"),
        _binary_check("codex", required=False),
        _binary_check("claude", required=False),
        _binary_check("tmux", required=False),
        _workspace_check(paths.workspace_root),
        _write_check(paths),
        _shim_check(paths),
    ]
    required_ok = all(check.ok for check in checks if check.name in {"python", "module:rich", "binary:git", "workspace", "write"})
    return {
        "ok": required_ok,
        "workspace_root": str(paths.workspace_root),
        "checks": [check.to_dict() for check in checks],
    }


def _python_check() -> DoctorCheck:
    ok = sys.version_info >= (3, 10)
    return DoctorCheck("python", ok, sys.version.split()[0])


def _module_check(name: str) -> DoctorCheck:
    ok = importlib.util.find_spec(name) is not None
    return DoctorCheck(f"module:{name}", ok, "available" if ok else "missing")


def _binary_check(name: str, *, required: bool = True) -> DoctorCheck:
    path = shutil.which(name)
    ok = path is not None or not required
    details = path or ("optional missing" if not required else "missing")
    return DoctorCheck(f"binary:{name}", ok, details)


def _workspace_check(workspace: Path) -> DoctorCheck:
    git_dir = workspace / ".git"
    if git_dir.exists():
        return DoctorCheck("workspace", True, "git workspace")
    completed = subprocess.run(["git", "-C", str(workspace), "rev-parse", "--show-toplevel"], text=True, capture_output=True, check=False)
    return DoctorCheck("workspace", completed.returncode == 0, "inside git workspace" if completed.returncode == 0 else "not a git workspace")


def _write_check(paths: AppPaths) -> DoctorCheck:
    try:
        paths.state_dir.mkdir(parents=True, exist_ok=True)
        probe = paths.state_dir / ".doctor-write"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return DoctorCheck("write", True, str(paths.state_dir))
    except OSError as exc:
        return DoctorCheck("write", False, str(exc))


def _shim_check(paths: AppPaths) -> DoctorCheck:
    aegis = shutil.which("aegis")
    if not aegis:
        return DoctorCheck("shim:aegis", False, "aegis not found in PATH")
    return DoctorCheck("shim:aegis", True, aegis)
