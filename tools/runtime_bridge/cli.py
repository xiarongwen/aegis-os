from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.control_plane import cli as control_plane


SUPPORTED_MODELS = ("aegis", "codex", "claude")
DONE_PREFIX = "__AEGIS_BRIDGE_DONE__"


class RuntimeBridgeError(RuntimeError):
    pass


@dataclass
class BridgeSession:
    session_name: str
    workspace_root: str
    window_name: str
    panes: dict[str, str]
    created_at: str
    updated_at: str
    active: bool


@dataclass
class BridgeSubmitResult:
    command: list[str]
    output_path: Path
    exit_code: int


def _bridge_root(workspace: Path) -> Path:
    return workspace / ".aegis" / "runtime-bridge"


def _session_dir(workspace: Path, session_name: str) -> Path:
    return _bridge_root(workspace) / "sessions" / session_name


def _session_file(workspace: Path, session_name: str) -> Path:
    return _session_dir(workspace, session_name) / "session.json"


def _lock_file(workspace: Path, session_name: str, model: str) -> Path:
    return _session_dir(workspace, session_name) / f"{model}.lock"


def _script_file(workspace: Path, session_name: str, model: str, request_id: str) -> Path:
    return _session_dir(workspace, session_name) / "scripts" / f"{model}-{request_id}.sh"


def bridge_session_name_for_workspace(workspace: Path) -> str:
    workspace = workspace.resolve()
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", workspace.name).strip("-").lower() or "workspace"
    digest = hashlib.sha1(str(workspace).encode("utf-8")).hexdigest()[:8]
    return f"aegis-{slug}-{digest}"


def _tmux(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    if not shutil.which("tmux"):
        raise RuntimeBridgeError("tmux is required for AEGIS runtime bridge mode")
    return subprocess.run(["tmux", *args], text=True, capture_output=True, check=check)


def _write_session(session_path: Path, payload: dict[str, Any]) -> None:
    session_path.parent.mkdir(parents=True, exist_ok=True)
    control_plane.write_json(session_path, payload)


def _load_session(session_path: Path) -> BridgeSession | None:
    if not session_path.exists():
        return None
    payload = control_plane.load_json(session_path)
    if not isinstance(payload, dict):
        return None
    return BridgeSession(
        session_name=str(payload.get("session_name") or ""),
        workspace_root=str(payload.get("workspace_root") or ""),
        window_name=str(payload.get("window_name") or "bridge"),
        panes={str(key): str(value) for key, value in dict(payload.get("panes") or {}).items()},
        created_at=str(payload.get("created_at") or ""),
        updated_at=str(payload.get("updated_at") or ""),
        active=bool(payload.get("active", True)),
    )


def _pane_alive(pane_id: str) -> bool:
    if not pane_id:
        return False
    result = _tmux("display-message", "-p", "-t", pane_id, "#{pane_id}", check=False)
    return result.returncode == 0


def _session_alive(session_name: str) -> bool:
    return _tmux("has-session", "-t", session_name, check=False).returncode == 0


def _rename_pane(pane_id: str, title: str) -> None:
    _tmux("select-pane", "-t", pane_id, "-T", title)


def _send_shell_command(pane_id: str, command: str) -> None:
    _tmux("send-keys", "-t", pane_id, command, "C-m")


def _make_shell_ready(pane_id: str, workspace: Path, model: str) -> None:
    _send_shell_command(
        pane_id,
        f"cd {shlex.quote(str(workspace))} && clear && echo '[AEGIS bridge] {model} ready in {workspace.name}'",
    )


def ensure_bridge_session(
    *,
    workspace: Path | None = None,
    session_name: str | None = None,
    models: list[str] | None = None,
) -> BridgeSession:
    workspace = (workspace or control_plane.resolve_workspace()).resolve()
    models = [model for model in (models or ["aegis", "codex", "claude"]) if model in SUPPORTED_MODELS]
    if not models:
        raise RuntimeBridgeError("bridge session requires at least one supported model")
    session_name = session_name or bridge_session_name_for_workspace(workspace)
    session_path = _session_file(workspace, session_name)
    existing = _load_session(session_path)
    if existing and _session_alive(existing.session_name):
        missing = [model for model in models if not _pane_alive(existing.panes.get(model, ""))]
        if not missing:
            return existing

    window_name = "bridge"
    if not _session_alive(session_name):
        first_model = models[0]
        _tmux("new-session", "-d", "-s", session_name, "-n", window_name, "zsh -l")
        first_pane = _tmux("display-message", "-p", "-t", f"{session_name}:{window_name}.1", "#{pane_id}").stdout.strip()
        panes = {first_model: first_pane}
        _rename_pane(first_pane, first_model)
        _make_shell_ready(first_pane, workspace, first_model)
        for model in models[1:]:
            pane_id = _tmux("split-window", "-P", "-F", "#{pane_id}", "-t", f"{session_name}:{window_name}", "zsh -l").stdout.strip()
            panes[model] = pane_id
            _rename_pane(pane_id, model)
            _make_shell_ready(pane_id, workspace, model)
        _tmux("select-layout", "-t", f"{session_name}:{window_name}", "tiled")
        created_at = control_plane.utc_now()
    else:
        panes = {}
        created_at = existing.created_at if existing else control_plane.utc_now()
        for model in models:
            pane_id = existing.panes.get(model, "") if existing else ""
            if pane_id and _pane_alive(pane_id):
                panes[model] = pane_id
                continue
            target = f"{session_name}:{window_name}"
            pane_id = _tmux("split-window", "-P", "-F", "#{pane_id}", "-t", target, "zsh -l").stdout.strip()
            panes[model] = pane_id
            _rename_pane(pane_id, model)
            _make_shell_ready(pane_id, workspace, model)
        _tmux("select-layout", "-t", f"{session_name}:{window_name}", "tiled")
    payload = {
        "session_name": session_name,
        "workspace_root": str(workspace),
        "window_name": window_name,
        "panes": panes,
        "created_at": created_at,
        "updated_at": control_plane.utc_now(),
        "active": True,
    }
    _write_session(session_path, payload)
    return _load_session(session_path) or BridgeSession(
        session_name=session_name,
        workspace_root=str(workspace),
        window_name=window_name,
        panes=panes,
        created_at=created_at,
        updated_at=payload["updated_at"],
        active=True,
    )


def list_bridge_sessions(*, workspace: Path | None = None) -> list[BridgeSession]:
    workspace = (workspace or control_plane.resolve_workspace()).resolve()
    sessions_dir = _bridge_root(workspace) / "sessions"
    if not sessions_dir.exists():
        return []
    sessions: list[BridgeSession] = []
    for session_path in sorted(sessions_dir.glob("*/session.json")):
        session = _load_session(session_path)
        if session is not None:
            sessions.append(session)
    return sessions


def stop_bridge_session(*, workspace: Path | None = None, session_name: str | None = None) -> str:
    workspace = (workspace or control_plane.resolve_workspace()).resolve()
    session_name = session_name or bridge_session_name_for_workspace(workspace)
    session_path = _session_file(workspace, session_name)
    session = _load_session(session_path)
    if session is None:
        raise RuntimeBridgeError(f"bridge session not found: {session_name}")
    _tmux("kill-session", "-t", session.session_name, check=False)
    payload = {
        "session_name": session.session_name,
        "workspace_root": session.workspace_root,
        "window_name": session.window_name,
        "panes": session.panes,
        "created_at": session.created_at,
        "updated_at": control_plane.utc_now(),
        "active": False,
    }
    _write_session(session_path, payload)
    return session.session_name


def _build_bridge_script(
    *,
    workspace: Path,
    session_name: str,
    model: str,
    request_id: str,
    command: list[str],
    log_path: Path,
) -> Path:
    script_path = _script_file(workspace, session_name, model, request_id)
    script_path.parent.mkdir(parents=True, exist_ok=True)
    quoted_command = shlex.join(command)
    lines = [
        "#!/usr/bin/env bash",
        "set -uo pipefail",
        f"cd {shlex.quote(str(workspace))}",
        f"mkdir -p {shlex.quote(str(log_path.parent))}",
        f"echo \"$ {quoted_command}\" | tee -a {shlex.quote(str(log_path))}",
        f"{quoted_command} 2>&1 | tee -a {shlex.quote(str(log_path))}",
        "status=${PIPESTATUS[0]}",
        f"printf '{DONE_PREFIX}:{request_id}:%s\\n' \"$status\" | tee -a {shlex.quote(str(log_path))}",
        "exit 0",
    ]
    script_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    script_path.chmod(0o755)
    return script_path


def bridge_command_for_logging(command: list[str], log_path: Path) -> list[str]:
    normalized: list[str] = []
    skip_next = False
    target_log = str(log_path)
    for index, item in enumerate(command):
        if skip_next:
            skip_next = False
            continue
        if item == "-o" and index + 1 < len(command) and command[index + 1] == target_log:
            skip_next = True
            continue
        normalized.append(item)
    return normalized


def _poll_log(
    *,
    log_path: Path,
    request_id: str,
    idle_timeout_seconds: int,
    event_callback: Any | None = None,
    event_payload: dict[str, Any] | None = None,
) -> int:
    offset = 0
    idle_deadline = time.monotonic() + idle_timeout_seconds
    while True:
        if log_path.exists():
            size = log_path.stat().st_size
            if size < offset:
                offset = 0
            with log_path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(offset)
                chunk = handle.read()
                offset = handle.tell()
            if chunk:
                idle_deadline = time.monotonic() + idle_timeout_seconds
                for raw_line in chunk.splitlines():
                    line = raw_line.rstrip("\n")
                    if line.startswith(f"{DONE_PREFIX}:{request_id}:"):
                        try:
                            return int(line.rsplit(":", 1)[1])
                        except ValueError as exc:
                            raise RuntimeBridgeError(f"invalid bridge sentinel in {log_path}") from exc
                    if event_callback is not None:
                        payload = dict(event_payload or {})
                        payload.update({"kind": "agent_output", "source": "stdout", "text": line})
                        event_callback(payload)
        if time.monotonic() > idle_deadline:
            raise RuntimeBridgeError(f"bridge request {request_id} became idle after {idle_timeout_seconds}s")
        time.sleep(0.15)


def submit_via_bridge(
    *,
    model: str,
    command: list[str],
    log_path: Path,
    workspace: Path | None = None,
    session_name: str | None = None,
    idle_timeout_seconds: int = 180,
    event_callback: Any | None = None,
    event_payload: dict[str, Any] | None = None,
) -> BridgeSubmitResult:
    if model not in SUPPORTED_MODELS:
        raise RuntimeBridgeError(f"unsupported bridge model: {model}")
    workspace = (workspace or control_plane.resolve_workspace()).resolve()
    session = ensure_bridge_session(workspace=workspace, session_name=session_name, models=[model])
    pane_id = session.panes.get(model)
    if not pane_id or not _pane_alive(pane_id):
        raise RuntimeBridgeError(f"bridge pane unavailable for model {model}")
    request_id = hashlib.sha1(f"{time.time()}:{model}:{log_path}".encode("utf-8")).hexdigest()[:10]
    script_path = _build_bridge_script(
        workspace=workspace,
        session_name=session.session_name,
        model=model,
        request_id=request_id,
        command=command,
        log_path=log_path,
    )
    lock_path = _lock_file(workspace, session.session_name, model)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as handle:
        if os.name != "nt":
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        _send_shell_command(pane_id, f"bash {shlex.quote(str(script_path))}")
        exit_code = _poll_log(
            log_path=log_path,
            request_id=request_id,
            idle_timeout_seconds=idle_timeout_seconds,
            event_callback=event_callback,
            event_payload=event_payload,
        )
    return BridgeSubmitResult(command=command, output_path=log_path, exit_code=exit_code)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AEGIS runtime bridge")
    parser.add_argument("--workspace")
    sub = parser.add_subparsers(dest="command", required=True)

    up_cmd = sub.add_parser("up")
    up_cmd.add_argument("--session")
    up_cmd.add_argument("--model", action="append", default=[])

    status_cmd = sub.add_parser("status")
    status_cmd.add_argument("--session")

    stop_cmd = sub.add_parser("stop")
    stop_cmd.add_argument("--session")

    args = parser.parse_args(argv)
    workspace = control_plane.resolve_workspace(workflow=None) if not args.workspace else Path(args.workspace).resolve()
    if args.command == "up":
        models = args.model or ["aegis", "codex", "claude"]
        session = ensure_bridge_session(workspace=workspace, session_name=args.session, models=models)
        print(json.dumps(session.__dict__, ensure_ascii=False, indent=2))
        return 0
    if args.command == "status":
        sessions = list_bridge_sessions(workspace=workspace)
        if args.session:
            sessions = [session for session in sessions if session.session_name == args.session]
        print(json.dumps([session.__dict__ for session in sessions], ensure_ascii=False, indent=2))
        return 0
    if args.command == "stop":
        session_name = stop_bridge_session(workspace=workspace, session_name=args.session)
        print(session_name)
        return 0
    return 1
