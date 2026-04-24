from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import AppPaths


@dataclass(slots=True)
class VerificationResult:
    passed: bool
    commands: list[list[str]]
    output: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_verification_commands(paths: AppPaths, config: dict[str, Any]) -> list[list[str]]:
    configured = config.get("verification", {}).get("commands", [])
    if isinstance(configured, list) and configured:
        commands: list[list[str]] = []
        for item in configured:
            if isinstance(item, list):
                commands.append([str(part) for part in item])
            elif isinstance(item, str):
                commands.append(item.split())
        return commands

    workspace = paths.workspace_root
    if (workspace / "package.json").exists():
        try:
            package = json.loads((workspace / "package.json").read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            package = {}
        scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
        if "test" in scripts:
            return [["npm", "test"]]
    if (workspace / "pyproject.toml").exists() or (workspace / "pytest.ini").exists() or (workspace / "tests").exists():
        return [["python3", "-m", "pytest"]]
    if (workspace / "go.mod").exists():
        return [["go", "test", "./..."]]
    return []


def run_verification(paths: AppPaths, config: dict[str, Any], *, timeout_seconds: int = 120) -> VerificationResult:
    commands = detect_verification_commands(paths, config)
    if not commands:
        return VerificationResult(True, [], "no verification commands detected")
    outputs: list[str] = []
    for command in commands:
        completed = subprocess.run(
            command,
            cwd=str(paths.workspace_root),
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        outputs.append(f"$ {' '.join(command)}\n{completed.stdout}{completed.stderr}")
        if completed.returncode != 0:
            return VerificationResult(False, commands, "\n".join(outputs).strip())
    return VerificationResult(True, commands, "\n".join(outputs).strip())

