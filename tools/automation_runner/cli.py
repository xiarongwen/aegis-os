from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from tools.host_runtime import HostCliRequest, get_host_cli_adapter
from tools.control_plane import cli as control_plane


ROOT = control_plane.ROOT
INTENT_LOCK_SCHEMA_PATH = ROOT / "shared-contexts/intent-lock-schema.json"
DEFAULT_STOP_BEFORE = {"L5_DEPLOY"}
DEFAULT_RUNTIME_IDLE_TIMEOUT_SECONDS = int(os.environ.get("AEGIS_RUNTIME_TIMEOUT_SECONDS", "180"))
DEFAULT_RUNTIME_SILENT_TIMEOUT_SECONDS = int(os.environ.get("AEGIS_RUNTIME_SILENT_TIMEOUT_SECONDS", "20"))


class AutomationRunnerError(RuntimeError):
    pass


class RuntimeNoOutputError(AutomationRunnerError):
    def __init__(self, runtime_name: str, agent_id: str, state_name: str, timeout_seconds: int) -> None:
        super().__init__(
            f"runtime {runtime_name} produced no output for {agent_id} in {state_name} after {timeout_seconds}s"
        )
        self.runtime_name = runtime_name
        self.agent_id = agent_id
        self.state_name = state_name
        self.timeout_seconds = timeout_seconds


@dataclass
class IntentRoute:
    mode: str
    workflow_type: str
    entry_state: str
    target_state: str
    summary: str
    rationale: str
    execution_plan: list[str] | None = None
    team_action: str | None = None
    team_id: str | None = None
    team_scope: str | None = None
    team_request: str | None = None


@dataclass
class RuntimeResult:
    command: list[str]
    output_path: Path


@dataclass
class RuntimeChoice:
    runtime: str
    rationale: str


@dataclass
class RuntimeInvocation:
    command: list[str]
    env: dict[str, str]
    cwd: str | None = None


EventCallback = Callable[[dict[str, Any]], None]


def ensure_log_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_log_stub(
    path: Path,
    *,
    runtime: str,
    agent_id: str,
    state_name: str,
    workflow_id: str,
    command: list[str],
    status: str,
    note: str | None = None,
) -> None:
    ensure_log_parent(path)
    payload: dict[str, Any] = {
        "runtime": runtime,
        "agent": agent_id,
        "state": state_name,
        "workflow_id": workflow_id,
        "status": status,
        "command": command,
        "updated_at": control_plane.utc_now(),
    }
    if note:
        payload["note"] = note
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def append_log_note(path: Path, title: str, content: str) -> None:
    ensure_log_parent(path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n[{title}]\n{content}\n")


class RuntimeAdapter:
    name = "base"

    def prepare(
        self,
        *,
        agent_id: str,
        workflow_id: str,
        state_name: str,
        prompt: str,
        log_path: Path,
        use_search: bool,
    ) -> RuntimeInvocation:
        raise NotImplementedError

    def run(
        self,
        *,
        agent_id: str,
        workflow_id: str,
        state_name: str,
        prompt: str,
        log_path: Path,
        use_search: bool,
        event_callback: EventCallback | None = None,
    ) -> RuntimeResult:
        raise NotImplementedError


def bridge_mode_enabled() -> bool:
    return os.environ.get("AEGIS_RUNTIME_BRIDGE", "").strip().lower() in {"1", "true", "yes", "tmux"}


def emit_event(callback: EventCallback | None, **payload: Any) -> None:
    if callback is None:
        return
    callback(payload)


def emit_bridge_unavailable(
    event_callback: EventCallback | None,
    *,
    workflow_id: str,
    state_name: str,
    agent_id: str,
    runtime_name: str,
    reason: str,
) -> None:
    emit_event(
        event_callback,
        kind="runtime_bridge_unavailable",
        workflow_id=workflow_id,
        state=state_name,
        agent=agent_id,
        runtime=runtime_name,
        reason=reason,
    )


def _append_stream_chunk(log_path: Path, source: str, text: str) -> None:
    if not text:
        return
    ensure_log_parent(log_path)
    with log_path.open("a", encoding="utf-8") as handle:
        for line in text.splitlines():
            handle.write(f"[{source}] {line}\n")


def _start_reader_thread(
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


def run_invocation_streaming(
    *,
    invocation: RuntimeInvocation,
    runtime_name: str,
    agent_id: str,
    workflow_id: str,
    state_name: str,
    log_path: Path,
    event_callback: EventCallback | None = None,
    write_stdout_to_log: bool = True,
) -> RuntimeResult:
    write_log_stub(
        log_path,
        runtime=runtime_name,
        agent_id=agent_id,
        state_name=state_name,
        workflow_id=workflow_id,
        command=invocation.command,
        status="starting",
    )
    process = subprocess.Popen(
        invocation.command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=invocation.env,
        cwd=invocation.cwd,
        bufsize=1,
    )
    emit_event(
        event_callback,
        kind="agent_started",
        agent=agent_id,
        state=state_name,
        runtime=runtime_name,
        workflow_id=workflow_id,
        log_path=control_plane.display_path(log_path),
        pid=process.pid,
    )
    stream_queue: queue.Queue[tuple[str, str | None]] = queue.Queue()
    stdout_done = process.stdout is None
    stderr_done = process.stderr is None
    stdout_thread = None if process.stdout is None else _start_reader_thread(process.stdout, source="stdout", target_queue=stream_queue)
    stderr_thread = None if process.stderr is None else _start_reader_thread(process.stderr, source="stderr", target_queue=stream_queue)
    idle_deadline = time.monotonic() + DEFAULT_RUNTIME_IDLE_TIMEOUT_SECONDS
    silent_deadline = time.monotonic() + DEFAULT_RUNTIME_SILENT_TIMEOUT_SECONDS
    saw_output = False
    while True:
        if not saw_output and time.monotonic() > silent_deadline:
            process.kill()
            if stdout_thread is not None:
                stdout_thread.join(timeout=1)
            if stderr_thread is not None:
                stderr_thread.join(timeout=1)
            append_log_note(
                log_path,
                "silent-timeout",
                f"runtime produced no output after {DEFAULT_RUNTIME_SILENT_TIMEOUT_SECONDS}s",
            )
            emit_event(
                event_callback,
                kind="agent_silent_timeout",
                agent=agent_id,
                state=state_name,
                runtime=runtime_name,
                workflow_id=workflow_id,
                timeout_seconds=DEFAULT_RUNTIME_SILENT_TIMEOUT_SECONDS,
            )
            raise RuntimeNoOutputError(runtime_name, agent_id, state_name, DEFAULT_RUNTIME_SILENT_TIMEOUT_SECONDS)
        if saw_output and time.monotonic() > idle_deadline:
            process.kill()
            if stdout_thread is not None:
                stdout_thread.join(timeout=1)
            if stderr_thread is not None:
                stderr_thread.join(timeout=1)
            append_log_note(log_path, "timeout", f"runtime became idle after {DEFAULT_RUNTIME_IDLE_TIMEOUT_SECONDS}s")
            emit_event(
                event_callback,
                kind="agent_timeout",
                agent=agent_id,
                state=state_name,
                runtime=runtime_name,
                workflow_id=workflow_id,
                timeout_seconds=DEFAULT_RUNTIME_IDLE_TIMEOUT_SECONDS,
            )
            raise AutomationRunnerError(
                f"runtime {runtime_name} became idle for {agent_id} in {state_name} after {DEFAULT_RUNTIME_IDLE_TIMEOUT_SECONDS}s"
            )
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
        text = chunk.rstrip("\n")
        saw_output = True
        idle_deadline = time.monotonic() + DEFAULT_RUNTIME_IDLE_TIMEOUT_SECONDS
        if source == "stdout" and write_stdout_to_log:
            _append_stream_chunk(log_path, source, text)
        elif source == "stderr":
            _append_stream_chunk(log_path, source, text)
        emit_event(
            event_callback,
            kind="agent_output",
            agent=agent_id,
            state=state_name,
            runtime=runtime_name,
            workflow_id=workflow_id,
            source=source,
            text=text,
            log_path=control_plane.display_path(log_path),
        )
    if stdout_thread is not None:
        stdout_thread.join(timeout=1)
    if stderr_thread is not None:
        stderr_thread.join(timeout=1)
    returncode = process.wait(timeout=1)
    if returncode != 0:
        raise AutomationRunnerError(f"runtime {runtime_name} failed for {agent_id} in {state_name}: process exited with {returncode}")
    if not log_path.exists() or not log_path.read_text(encoding="utf-8").strip():
        write_log_stub(
            log_path,
            runtime=runtime_name,
            agent_id=agent_id,
            state_name=state_name,
            workflow_id=workflow_id,
            command=invocation.command,
            status="completed_without_runtime_log",
            note="runtime exited successfully but produced no log file",
        )
    emit_event(
        event_callback,
        kind="agent_completed",
        agent=agent_id,
        state=state_name,
        runtime=runtime_name,
        workflow_id=workflow_id,
        log_path=control_plane.display_path(log_path),
    )
    return RuntimeResult(command=invocation.command, output_path=log_path)


def run_invocation_via_bridge(
    *,
    invocation: RuntimeInvocation,
    runtime_name: str,
    agent_id: str,
    workflow_id: str,
    state_name: str,
    log_path: Path,
    event_callback: EventCallback | None = None,
) -> RuntimeResult:
    from tools.runtime_bridge import cli as runtime_bridge

    workspace = Path(invocation.cwd or control_plane.resolve_workspace(workflow=workflow_id))
    bridge_command = runtime_bridge.bridge_command_for_logging(invocation.command, log_path)
    emit_event(
        event_callback,
        kind="agent_started",
        agent=agent_id,
        state=state_name,
        runtime=runtime_name,
        workflow_id=workflow_id,
        log_path=control_plane.display_path(log_path),
        pid="tmux-bridge",
    )
    result = runtime_bridge.submit_via_bridge(
        model=runtime_name,
        command=bridge_command,
        log_path=log_path,
        workspace=workspace,
        idle_timeout_seconds=DEFAULT_RUNTIME_IDLE_TIMEOUT_SECONDS,
        event_callback=event_callback,
        event_payload={
            "agent": agent_id,
            "state": state_name,
            "runtime": runtime_name,
            "workflow_id": workflow_id,
            "log_path": control_plane.display_path(log_path),
        },
    )
    if result.exit_code != 0:
        raise AutomationRunnerError(
            f"runtime {runtime_name} failed for {agent_id} in {state_name}: process exited with {result.exit_code}"
        )
    emit_event(
        event_callback,
        kind="agent_completed",
        agent=agent_id,
        state=state_name,
        runtime=runtime_name,
        workflow_id=workflow_id,
        log_path=control_plane.display_path(log_path),
    )
    return RuntimeResult(command=bridge_command, output_path=log_path)


class HostCliRuntimeAdapter(RuntimeAdapter):
    name = "base"
    cli_name = "base"

    def build_request(
        self,
        *,
        prompt: str,
        workspace: Path,
        log_path: Path,
        use_search: bool,
    ) -> HostCliRequest:
        raise NotImplementedError

    def prepare(
        self,
        *,
        agent_id: str,
        workflow_id: str,
        state_name: str,
        prompt: str,
        log_path: Path,
        use_search: bool,
    ) -> RuntimeResult:
        del agent_id, state_name
        workspace = control_plane.resolve_workspace(workflow=workflow_id)
        request = self.build_request(
            prompt=prompt,
            workspace=workspace,
            log_path=log_path,
            use_search=use_search,
        )
        invocation = get_host_cli_adapter(self.cli_name).build_invocation(request)
        return RuntimeInvocation(command=invocation.command, env=invocation.env, cwd=invocation.cwd)


class CodexRuntimeAdapter(HostCliRuntimeAdapter):
    name = "codex"
    cli_name = "codex"

    def build_request(
        self,
        *,
        prompt: str,
        workspace: Path,
        log_path: Path,
        use_search: bool,
    ) -> HostCliRequest:
        return HostCliRequest(
            prompt=prompt,
            workspace_root=workspace,
            core_root=ROOT,
            output_path=log_path,
            use_search=use_search,
        )

    def run(
        self,
        *,
        agent_id: str,
        workflow_id: str,
        state_name: str,
        prompt: str,
        log_path: Path,
        use_search: bool,
        event_callback: EventCallback | None = None,
    ) -> RuntimeResult:
        invocation = self.prepare(
            agent_id=agent_id,
            workflow_id=workflow_id,
            state_name=state_name,
            prompt=prompt,
            log_path=log_path,
            use_search=use_search,
        )
        if bridge_mode_enabled():
            try:
                return run_invocation_via_bridge(
                    invocation=invocation,
                    runtime_name=self.name,
                    agent_id=agent_id,
                    workflow_id=workflow_id,
                    state_name=state_name,
                    log_path=log_path,
                    event_callback=event_callback,
                )
            except Exception as exc:
                emit_bridge_unavailable(
                    event_callback,
                    workflow_id=workflow_id,
                    state_name=state_name,
                    agent_id=agent_id,
                    runtime_name=self.name,
                    reason=str(exc),
                )
        return run_invocation_streaming(
            invocation=invocation,
            runtime_name=self.name,
            agent_id=agent_id,
            workflow_id=workflow_id,
            state_name=state_name,
            log_path=log_path,
            event_callback=event_callback,
            write_stdout_to_log=False,
        )


class ClaudeRuntimeAdapter(HostCliRuntimeAdapter):
    name = "claude"
    cli_name = "claude"

    def build_request(
        self,
        *,
        prompt: str,
        workspace: Path,
        log_path: Path,
        use_search: bool,
    ) -> HostCliRequest:
        del log_path, use_search
        return HostCliRequest(
            prompt=prompt,
            workspace_root=workspace,
            core_root=ROOT,
            extra_args=["--permission-mode", "bypassPermissions"],
        )

    def run(
        self,
        *,
        agent_id: str,
        workflow_id: str,
        state_name: str,
        prompt: str,
        log_path: Path,
        use_search: bool,
        event_callback: EventCallback | None = None,
    ) -> RuntimeResult:
        invocation = self.prepare(
            agent_id=agent_id,
            workflow_id=workflow_id,
            state_name=state_name,
            prompt=prompt,
            log_path=log_path,
            use_search=use_search,
        )
        if bridge_mode_enabled():
            try:
                return run_invocation_via_bridge(
                    invocation=invocation,
                    runtime_name=self.name,
                    agent_id=agent_id,
                    workflow_id=workflow_id,
                    state_name=state_name,
                    log_path=log_path,
                    event_callback=event_callback,
                )
            except Exception as exc:
                emit_bridge_unavailable(
                    event_callback,
                    workflow_id=workflow_id,
                    state_name=state_name,
                    agent_id=agent_id,
                    runtime_name=self.name,
                    reason=str(exc),
                )
        return run_invocation_streaming(
            invocation=invocation,
            runtime_name=self.name,
            agent_id=agent_id,
            workflow_id=workflow_id,
            state_name=state_name,
            log_path=log_path,
            event_callback=event_callback,
            write_stdout_to_log=True,
        )


class AiderRuntimeAdapter(HostCliRuntimeAdapter):
    name = "aider"
    cli_name = "aider"

    def build_request(
        self,
        *,
        prompt: str,
        workspace: Path,
        log_path: Path,
        use_search: bool,
    ) -> HostCliRequest:
        del log_path, use_search
        return HostCliRequest(prompt=prompt, workspace_root=workspace, core_root=ROOT)

    def run(
        self,
        *,
        agent_id: str,
        workflow_id: str,
        state_name: str,
        prompt: str,
        log_path: Path,
        use_search: bool,
        event_callback: EventCallback | None = None,
    ) -> RuntimeResult:
        invocation = self.prepare(
            agent_id=agent_id,
            workflow_id=workflow_id,
            state_name=state_name,
            prompt=prompt,
            log_path=log_path,
            use_search=use_search,
        )
        return run_invocation_streaming(
            invocation=invocation,
            runtime_name=self.name,
            agent_id=agent_id,
            workflow_id=workflow_id,
            state_name=state_name,
            log_path=log_path,
            event_callback=event_callback,
            write_stdout_to_log=True,
        )


class OpencodeRuntimeAdapter(AiderRuntimeAdapter):
    name = "opencode"
    cli_name = "opencode"


def load_intent_lock_schema() -> dict[str, Any]:
    return control_plane.load_json(INTENT_LOCK_SCHEMA_PATH)


def validate_intent_lock(payload: dict[str, Any]) -> None:
    schema = load_intent_lock_schema()
    missing = [key for key in schema["required"] if key not in payload]
    if missing:
        raise AutomationRunnerError(f"intent lock missing required keys: {', '.join(missing)}")


def strip_host_prefix(request: str) -> str:
    return re.sub(r"^\s*(?:/)?aegis\b(?![-_])[\s:：-]*", "", request.strip(), count=1, flags=re.IGNORECASE)


def extract_invoked_team_id(request: str) -> str | None:
    matched = re.search(r"\b(AEGIS[-_][A-Za-z0-9][A-Za-z0-9_-]{1,62})\b", request, flags=re.IGNORECASE)
    if not matched:
        return None
    return matched.group(1)


def trim_team_invocation_request(request: str, team_id: str) -> str:
    pattern = rf"^\s*{re.escape(team_id)}\b[\s:：,-]*"
    trimmed = re.sub(pattern, "", request.strip(), count=1, flags=re.IGNORECASE).strip()
    return trimmed or request.strip()


def route_request(request: str) -> IntentRoute:
    raw_request = request.strip()
    normalized_request = strip_host_prefix(raw_request)
    normalized = normalized_request.lower()
    if not normalized:
        raise AutomationRunnerError("request cannot be empty")
    team_creation_terms = ("创建", "生成", "组建", "创建一个", "create", "make", "spin up", "setup", "build me")
    team_interest_terms = ("团队", "team", "team pack")
    if any(term in normalized for term in team_interest_terms) and any(term in normalized for term in team_creation_terms):
        inferred_domain = control_plane.infer_domain_from_request(normalized_request)
        team_id = (
            control_plane.extract_named_team_id(normalized_request)
            or control_plane.default_team_id_for_domain(inferred_domain)
        )
        team_scope = control_plane.infer_scope_from_request(normalized_request)
        return IntentRoute(
            mode="team_pack",
            workflow_type="team_pack_compose",
            entry_state="TEAM_READY",
            target_state="TEAM_READY",
            summary="Create and install a reusable AEGIS Team Pack",
            rationale="request explicitly asks to create a long-lived team",
            execution_plan=["compose_team_pack", "install_team_pack"],
            team_action="compose",
            team_id=team_id,
            team_scope=team_scope,
            team_request=normalized_request,
        )

    invoked_team_id = extract_invoked_team_id(normalized_request)
    if invoked_team_id:
        team_request = trim_team_invocation_request(normalized_request, invoked_team_id)
        inferred_scope = control_plane.infer_scope_from_request(normalized_request)
        return IntentRoute(
            mode="team_pack",
            workflow_type="team_pack_run",
            entry_state="TEAM_RUN_READY",
            target_state="TEAM_RUN_READY",
            summary=f"Prepare a Team Pack run for {invoked_team_id}",
            rationale="request targets an installed AEGIS Team Pack by name",
            execution_plan=["prepare_team_run"],
            team_action="invoke",
            team_id=invoked_team_id,
            team_scope=inferred_scope if inferred_scope != "global" else "all",
            team_request=team_request,
        )

    research_terms = ("调研", "研究", "research", "竞品", "市场", "分析")
    planning_terms = ("prd", "规划", "plan", "架构", "任务拆解", "需求")
    build_terms = (
        "开发",
        "实现",
        "build",
        "页面",
        "网页",
        "网站",
        "demo",
        "原型",
        "功能",
        "chat page",
        "web demo",
        "landing page",
        "聊天页面",
        "frontend",
        "backend",
    )
    direct_build_terms = ("demo", "原型", "web demo", "landing page", "网页", "网站")
    launch_terms = ("部署", "发布", "上线", "deploy", "launch", "release")
    audit_terms = ("审计", "review", "复盘", "security", "安全")

    has_research = any(term in normalized for term in research_terms)
    has_planning = any(term in normalized for term in planning_terms)
    has_build = any(term in normalized for term in build_terms)
    has_direct_build = any(term in normalized for term in direct_build_terms)
    has_launch = any(term in normalized for term in launch_terms)
    has_audit = any(term in normalized for term in audit_terms)

    plan_stages: list[str]
    entry_state: str
    target_state: str
    workflow_type: str
    summary: str
    rationale: str

    if has_launch:
        workflow_type = "launch"
        entry_state = "L5_DEPLOY"
        target_state = "L5_REVIEW"
        plan_stages = ["deploy", "review"]
        summary = "Launch approved work"
        rationale = "analysis matched a release/deploy request"
    elif has_build and (has_research or has_planning or not has_direct_build):
        workflow_type = "build"
        if has_research or not has_planning:
            entry_state = "L1_RESEARCH"
            plan_stages = ["research", "planning", "build", "validate", "review"]
            rationale = "analysis found implementation work that benefits from upfront discovery and planning"
        else:
            entry_state = "L2_PLANNING"
            plan_stages = ["planning", "build", "validate", "review"]
            rationale = "analysis found implementation work with planning requirements but no separate research phase"
        target_state = "L4_REVIEW"
        summary = "Generate a fit-for-purpose implementation workflow from analysis"
    elif has_build:
        workflow_type = "build"
        entry_state = "L3_DEVELOP"
        target_state = "L4_REVIEW"
        plan_stages = ["build", "validate", "review"]
        summary = "Build and validate a scoped deliverable"
        rationale = "analysis found a direct implementation request that can start at development"
    elif has_research and has_planning:
        workflow_type = "planning"
        entry_state = "L1_RESEARCH"
        target_state = "L2_REVIEW"
        plan_stages = ["research", "planning", "review"]
        summary = "Research a topic and lock a PRD"
        rationale = "analysis found a discovery + planning request"
    elif has_planning:
        workflow_type = "planning"
        entry_state = "L2_PLANNING"
        target_state = "L2_REVIEW"
        plan_stages = ["planning", "review"]
        summary = "Create a PRD and locked plan"
        rationale = "analysis found a planning request that can skip research"
    elif has_audit:
        workflow_type = "audit"
        entry_state = "L3_CODE_REVIEW"
        target_state = "L4_REVIEW"
        plan_stages = ["code_review", "security_audit", "validate", "review"]
        summary = "Audit existing implementation and close findings"
        rationale = "analysis found an audit/review request"
    else:
        workflow_type = "research"
        entry_state = "L1_RESEARCH"
        target_state = "L1_REVIEW"
        plan_stages = ["research", "review"]
        summary = "Research a topic and produce reviewed findings"
        rationale = "analysis did not find implementation or release intent, so it falls back to research"

    return IntentRoute(
        mode="workflow",
        workflow_type=workflow_type,
        entry_state=entry_state,
        target_state=target_state,
        summary=summary,
        rationale=rationale,
        execution_plan=plan_stages,
    )


def workflow_id_from_request(request: str) -> str:
    ascii_words = re.findall(r"[a-z0-9]+", request.lower())
    prefix = "-".join(ascii_words[:4]).strip("-")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if prefix:
        return f"{prefix[:40]}-{stamp}"
    return f"workflow-{stamp}"


def intent_lock_path(workflow_id: str) -> Path:
    return control_plane.workflow_root(workflow_id) / "intent-lock.json"


def runner_dir(workflow_id: str) -> Path:
    return control_plane.workflow_root(workflow_id) / "runner"


def write_intent_lock(workflow_id: str, request: str, route: IntentRoute, runtime_name: str) -> dict[str, Any]:
    payload = {
        "version": "1.0.0",
        "workflow_id": workflow_id,
        "created_at": control_plane.utc_now(),
        "original_request": request,
        "normalized_goal": route.summary,
        "workflow_type": route.workflow_type,
        "entry_state": route.entry_state,
        "target_state": route.target_state,
        "execution_plan": route.execution_plan or [],
        "routing_rationale": route.rationale,
        "runtime": runtime_name,
        "status": "locked",
    }
    validate_intent_lock(payload)
    control_plane.write_json(intent_lock_path(workflow_id), payload)
    return payload


def ensure_route_enabled(route: IntentRoute) -> None:
    if route.mode != "workflow":
        return
    workspace = control_plane.resolve_workspace()
    manifest = control_plane.load_json(control_plane.project_manifest_path(workspace))
    control_plane.validate_project_manifest(manifest, workspace)
    enabled_workflows = manifest.get("enabled_workflows", [])
    if enabled_workflows and route.workflow_type not in enabled_workflows:
        raise AutomationRunnerError(
            f"workflow type `{route.workflow_type}` is disabled for workspace `{manifest['project_id']}`"
        )


def update_state_metadata(workflow_id: str, route: IntentRoute, request: str, runtime_name: str) -> None:
    state = control_plane.load_state(workflow_id)
    state["workflow_type"] = route.workflow_type
    state["entry_state"] = route.entry_state
    state["intent_summary"] = route.summary
    state["target_state"] = route.target_state
    state["execution_plan"] = route.execution_plan or []
    state["automation"] = {
        "enabled": True,
        "runtime": runtime_name,
        "original_request": request,
        "last_updated": control_plane.utc_now(),
    }
    control_plane.write_json(control_plane.state_path(workflow_id), state)
    control_plane.ensure_runtime_snapshot(workflow_id, workflow_type=route.workflow_type, refresh=True)
    workspace = control_plane.resolve_workspace(workflow=workflow_id)
    control_plane.update_workflow_index(
        workflow_id,
        workspace=workspace,
        workflow_type=route.workflow_type,
        current_state=state["current_state"],
    )


def synthesize_build_bootstrap_artifacts(workflow_id: str, request: str, route: IntentRoute) -> None:
    planning_dir = control_plane.workflow_root(workflow_id) / "l2-planning"
    planning_dir.mkdir(parents=True, exist_ok=True)
    (planning_dir / "PRD.md").write_text(
        "# Bootstrap PRD\n\n"
        f"- Request: {request}\n"
        f"- Workflow type: {route.workflow_type}\n"
        f"- Generated execution plan: {' -> '.join(route.execution_plan or [])}\n",
        encoding="utf-8",
    )
    (planning_dir / "architecture.md").write_text(
        "# Bootstrap Architecture\n\n"
        "This workflow was generated from upfront request analysis so execution can start directly in development.\n",
        encoding="utf-8",
    )
    task_breakdown = {
        "version": "1.0.0",
        "workflow_id": workflow_id,
        "created_at": control_plane.utc_now(),
        "planning_mode": "l3_parallel_execution",
        "development_principles": [
            "dry_first",
            "parallel_by_default",
            "contract_before_code",
            "owned_write_scope",
            "host_capability_enhancement",
        ],
        "parallel_execution": {
            "default_mode": "parallel_by_default",
            "max_parallel_agents": 2,
        },
        "tasks": [
            {
                "id": "FE-1",
                "title": "Implement the user-facing experience for the request",
                "owner": "frontend-squad",
                "stage": "L3_DEVELOP",
                "depends_on": [],
                "parallel_group": "ui-api",
                "write_scope": [f".aegis/runs/{workflow_id}/l3-dev/frontend/**"],
                "acceptance_criteria": ["Frontend artifacts satisfy the analyzed request scope"],
                "dry_reuse_targets": [f".aegis/runs/{workflow_id}/l3-dev/frontend"],
                "host_capability_needs": ["resolve_host_capability", "scan_repo_reuse"],
            },
            {
                "id": "BE-1",
                "title": "Implement supporting backend or data logic when needed",
                "owner": "backend-squad",
                "stage": "L3_DEVELOP",
                "depends_on": [],
                "parallel_group": "ui-api",
                "write_scope": [f".aegis/runs/{workflow_id}/l3-dev/backend/**"],
                "acceptance_criteria": ["Backend artifacts satisfy the analyzed request scope"],
                "dry_reuse_targets": [f".aegis/runs/{workflow_id}/l3-dev/backend"],
                "host_capability_needs": ["resolve_host_capability", "scan_repo_reuse"],
            },
        ],
    }
    implementation_contracts = {
        "version": "1.0.0",
        "workflow_id": workflow_id,
        "generated_at": control_plane.utc_now(),
        "contract_version": "1.0.0",
        "shared_interfaces": [],
        "owned_write_scopes": {
            "frontend-squad": [f".aegis/runs/{workflow_id}/l3-dev/frontend/**"],
            "backend-squad": [f".aegis/runs/{workflow_id}/l3-dev/backend/**"],
        },
        "integration_rules": {
            "required_before_parallel": ["contract_before_code"],
        },
        "change_control": {"owner": "user", "mode": "explicit_approval"},
    }
    requirements_lock = {
        "version": "1.0.0",
        "workflow_id": workflow_id,
        "source_stage": "ANALYSIS",
        "locked_at": control_plane.utc_now(),
        "product_goal": route.summary,
        "scope": {
            "in": list(route.execution_plan or []),
            "out": ["unrequested expansion", "production rollout unless explicitly requested"],
        },
        "user_stories": [
            {
                "id": "USR-1",
                "story": request,
                "acceptance_criteria": ["Implementation remains inside the analyzed request scope"],
            }
        ],
        "non_functional_requirements": [],
        "assumptions": ["Execution plan was synthesized from request analysis before development start"],
        "change_control": {"owner": "user", "mode": "explicit_approval"},
        "lock_hash": "",
    }
    requirements_lock["lock_hash"] = control_plane.compute_requirements_lock_hash(requirements_lock)
    control_plane.write_json(control_plane.task_breakdown_path(workflow_id), task_breakdown)
    control_plane.write_json(control_plane.implementation_contracts_path(workflow_id), implementation_contracts)
    control_plane.write_json(control_plane.requirements_lock_path(workflow_id), requirements_lock)
    state = control_plane.load_state(workflow_id)
    state["requirements_lock_hash"] = requirements_lock["lock_hash"]
    control_plane.write_json(control_plane.state_path(workflow_id), state)


def pick_adapter(name: str) -> RuntimeAdapter:
    if name == "codex":
        return CodexRuntimeAdapter()
    if name == "claude":
        return ClaudeRuntimeAdapter()
    if name == "aider":
        return AiderRuntimeAdapter()
    if name == "opencode":
        return OpencodeRuntimeAdapter()
    raise AutomationRunnerError(f"unsupported runtime: {name}")


def alternate_runtime_name(current_name: str) -> str | None:
    for candidate in available_runtimes():
        if candidate != current_name:
            return candidate
    return None


def available_runtimes() -> list[str]:
    names: list[str] = []
    if shutil.which("codex"):
        names.append("codex")
    if shutil.which("claude"):
        names.append("claude")
    if shutil.which("aider"):
        names.append("aider")
    if shutil.which("opencode"):
        names.append("opencode")
    return names


def choose_runtime_for_state(
    *,
    workflow_id: str | None,
    state_name: str | None,
    requested_runtime: str,
    for_dispatch: bool,
) -> RuntimeChoice:
    if requested_runtime != "auto":
        return RuntimeChoice(runtime=requested_runtime, rationale=f"explicit runtime override: {requested_runtime}")

    available = available_runtimes()
    if not available:
        raise AutomationRunnerError("no supported agent CLI found; install `codex` or `claude`")

    host_runtime = os.environ.get("AEGIS_HOST_RUNTIME")
    if host_runtime and host_runtime not in {"codex", "claude"}:
        host_runtime = None
    if host_runtime and host_runtime not in available:
        host_runtime = None

    if for_dispatch:
        if host_runtime and len(available) > 1:
            for candidate in available:
                if candidate != host_runtime:
                    return RuntimeChoice(
                        runtime=candidate,
                        rationale=f"dispatch selected the non-host runtime `{candidate}` to keep the host session free for orchestration",
                    )
        if "codex" in available and state_name == "L3_DEVELOP":
            return RuntimeChoice(
                runtime="codex",
                rationale="dispatch selected `codex` for parallel L3 worker execution because it is available and optimized for exec-style workers",
            )
        return RuntimeChoice(runtime=available[0], rationale=f"dispatch selected the only available runtime: {available[0]}")

    if host_runtime:
        return RuntimeChoice(runtime=host_runtime, rationale=f"using declared host runtime from AEGIS_HOST_RUNTIME: {host_runtime}")
    if len(available) == 1:
        return RuntimeChoice(runtime=available[0], rationale=f"only available runtime is {available[0]}")
    if state_name in {"L1_RESEARCH", "L1_REVIEW", "L2_PLANNING", "L2_REVIEW", "L4_REVIEW", "L5_REVIEW"} and "claude" in available:
        return RuntimeChoice(runtime="claude", rationale="selected `claude` for planning/review-oriented orchestration")
    if state_name in {"L3_DEVELOP", "L4_VALIDATE", "L5_DEPLOY"} and "codex" in available:
        return RuntimeChoice(runtime="codex", rationale="selected `codex` for implementation/verification-oriented execution")
    return RuntimeChoice(runtime=available[0], rationale=f"selected first available runtime: {available[0]}")


def state_requires_human_input(registry: dict[str, Any], orchestrator: dict[str, Any], state_name: str) -> bool:
    agents = control_plane.registry_by_id(registry)
    for agent_id in orchestrator["state_agents"].get(state_name, []):
        if "contract:ask_user" in agents[agent_id].get("dependencies", []):
            return True
    return False


def target_satisfied(route: IntentRoute, state: dict[str, Any]) -> bool:
    if state["current_state"] != route.target_state:
        return False
    hint = state.get("next_state_hint")
    if not hint or hint == "BLOCKED":
        return False
    if state.get("active_review_loop"):
        return False
    return True


def prompt_for_agent(
    *,
    workflow_id: str,
    agent: dict[str, Any],
    state_name: str,
    route: IntentRoute,
) -> str:
    workflow_root = control_plane.workflow_root(workflow_id)
    workspace = control_plane.resolve_workspace(workflow=workflow_id)
    skill_path = control_plane.runtime_agent_file_path(agent["id"], "SKILL.md", workflow=workflow_id)
    intent_path = intent_lock_path(workflow_id)
    lines = [
        f"You are running inside the AEGIS automation runner as agent `{agent['id']}`.",
        f"Attached workspace root: `{workspace}`.",
        f"Current workflow: `{workflow_id}`.",
        f"Current state: `{state_name}`.",
        f"Locked workflow type: `{route.workflow_type}`.",
        f"Target stop state for this request: `{route.target_state}`.",
        "",
        "Read and follow these sources of truth before acting:",
        f"- `{skill_path}`",
        f"- `{workflow_root / 'project-lock.json'}`",
        f"- `{workflow_root / 'registry.lock.json'}`",
        f"- `{workflow_root / 'orchestrator.lock.json'}`",
        f"- `{workflow_root / 'state.json'}`",
        f"- `{intent_path}`",
    ]
    requirements_lock = workflow_root / "l2-planning" / "requirements-lock.json"
    if requirements_lock.exists():
        lines.append(f"- `{requirements_lock}`")
    task_breakdown = workflow_root / "l2-planning" / "task_breakdown.json"
    implementation_contracts = workflow_root / "l2-planning" / "implementation-contracts.json"
    if task_breakdown.exists():
        lines.append(f"- `{task_breakdown}`")
    if implementation_contracts.exists():
        lines.append(f"- `{implementation_contracts}`")
    lines.extend(
        [
            "",
            "Execution rules:",
            "1. Stay strictly inside the locked user request and do not silently expand scope.",
            "2. Only perform the responsibilities of your assigned agent and current state.",
            "3. Write every required artifact declared in the registry to the workflow directory.",
            "4. For review gates, emit review-loop artifacts and only create `review-passed.json` on LGTM.",
            "5. If you are in a fix loop, answer prior findings in `fix-response-round-N.md` instead of rewriting the direction.",
            "6. In L3, obey DRY-first reuse checks, owned write scopes, and implementation contracts before writing code.",
            "7. In L3, use host skills/tools only through the mapped abstract actions and record that usage in `reuse-audit.json`.",
            "8. Do not advance workflow state yourself. Stop after writing artifacts.",
            "",
            "Now execute your stage and write the required files.",
        ]
    )
    return "\n".join(lines)


class AutomationRunner:
    def __init__(
        self,
        *,
        adapter: RuntimeAdapter,
        stop_before: set[str] | None = None,
        max_steps: int = 30,
        allow_runtime_fallback: bool = False,
    ) -> None:
        self.adapter = adapter
        self.stop_before = set(stop_before or DEFAULT_STOP_BEFORE)
        self.max_steps = max_steps
        self.allow_runtime_fallback = allow_runtime_fallback

    def bootstrap(
        self,
        request: str,
        workflow_id: str | None = None,
        event_callback: EventCallback | None = None,
    ) -> tuple[str, IntentRoute]:
        control_plane.doctor()
        control_plane.ensure_workspace_layout()
        route = route_request(request)
        emit_event(
            event_callback,
            kind="workflow_routed",
            request=request,
            workflow_type=route.workflow_type,
            entry_state=route.entry_state,
            target_state=route.target_state,
            execution_plan=route.execution_plan or [],
            rationale=route.rationale,
            runtime=self.adapter.name,
        )
        if route.mode != "workflow":
            raise AutomationRunnerError("bootstrap() only supports workflow routes; use bootstrap_summary() for team-pack requests")
        ensure_route_enabled(route)
        workflow_id = workflow_id or workflow_id_from_request(request)
        if control_plane.state_path(workflow_id).exists():
            raise AutomationRunnerError(f"workflow already exists: {workflow_id}")
        emit_event(
            event_callback,
            kind="workflow_bootstrap_started",
            workflow_id=workflow_id,
            runtime=self.adapter.name,
            workflow_type=route.workflow_type,
            entry_state=route.entry_state,
            target_state=route.target_state,
            execution_plan=route.execution_plan or [],
        )
        control_plane.pre_agent_run("orchestrator", workflow_id)
        runner_dir(workflow_id).mkdir(parents=True, exist_ok=True)
        write_intent_lock(workflow_id, request, route, self.adapter.name)
        update_state_metadata(workflow_id, route, request, self.adapter.name)
        if route.entry_state == "L3_DEVELOP":
            synthesize_build_bootstrap_artifacts(workflow_id, request, route)
            emit_event(
                event_callback,
                kind="workflow_plan_generated",
                workflow_id=workflow_id,
                workflow_type=route.workflow_type,
                entry_state=route.entry_state,
                target_state=route.target_state,
                execution_plan=route.execution_plan or [],
            )
        state = control_plane.load_state(workflow_id)
        state.setdefault("history", []).append(
            {
                "from": "INIT",
                "to": route.entry_state,
                "transitioned_at": control_plane.utc_now(),
                "reason": "bootstrap_entry_state",
            }
        )
        state["current_state"] = route.entry_state
        state["next_state_hint"] = None
        control_plane.write_json(control_plane.state_path(workflow_id), state)
        control_plane.update_workflow_index(workflow_id, current_state=route.entry_state)
        emit_event(
            event_callback,
            kind="state_transition",
            workflow_id=workflow_id,
            from_state="INIT",
            to_state=route.entry_state,
            reason="bootstrap",
        )
        return workflow_id, route

    def bootstrap_summary(self, request: str, workflow_id: str | None = None) -> dict[str, Any]:
        control_plane.doctor()
        control_plane.ensure_workspace_layout()
        route = route_request(request)
        if route.mode == "team_pack":
            return self.handle_team_pack_request(route)
        workflow_id, route = self.bootstrap(request, workflow_id)
        return self.summary(workflow_id, route, "bootstrapped", steps=[])

    def run_request(self, request: str, workflow_id: str | None = None) -> dict[str, Any]:
        control_plane.doctor()
        control_plane.ensure_workspace_layout()
        route = route_request(request)
        if route.mode == "team_pack":
            return self.handle_team_pack_request(route)
        workflow_id, route = self.bootstrap(request, workflow_id)
        return self.resume(workflow_id, route=route)

    def handle_team_pack_request(self, route: IntentRoute) -> dict[str, Any]:
        workspace = control_plane.resolve_workspace()
        if route.team_action == "compose":
            install = route.team_scope != "session"
            if not route.team_id:
                raise AutomationRunnerError("team composition route is missing team_id")
            messages = control_plane.compose_team_pack_from_request(
                route.team_request or route.summary,
                team_id=route.team_id,
                display_name=None,
                scope=route.team_scope,
                install=install,
                explicit_workspace=workspace,
            )
            resolved_scope, team_dir, payload = control_plane.find_team_pack(
                route.team_id,
                route.team_scope or "all",
                workspace,
            )
            return {
                "status": "team_pack_ready",
                "mode": route.mode,
                "workflow_type": route.workflow_type,
                "target_state": route.target_state,
                "summary": route.summary,
                "rationale": route.rationale,
                "team_action": route.team_action,
                "team_id": payload["team_id"],
                "team_scope": resolved_scope,
                "workspace_root": str(control_plane.resolve_workspace()),
                "installed": payload["host_integration"]["installed"],
                "host_skill_name": payload["host_integration"]["skill_name"],
                "team_manifest": control_plane.display_path(team_dir / "team.json"),
                "team_skill": control_plane.display_path(team_dir / "SKILL.md"),
                "messages": messages,
            }
        if route.team_action == "invoke":
            if not route.team_id:
                raise AutomationRunnerError("team invocation route is missing team_id")
            messages = control_plane.invoke_team_pack(
                team_id=route.team_id,
                request=route.team_request or route.summary,
                scope=route.team_scope or "all",
                explicit_workspace=workspace,
            )
            run_id_line = next((line for line in messages if line.startswith("run_id: ")), None)
            if not run_id_line:
                raise AutomationRunnerError(f"team run did not return a run_id for {route.team_id}")
            run_id = run_id_line.split(": ", 1)[1]
            resolved_scope, _, payload = control_plane.find_team_pack(
                route.team_id,
                route.team_scope or "all",
                workspace,
            )
            return {
                "status": "team_run_prepared",
                "mode": route.mode,
                "workflow_type": route.workflow_type,
                "target_state": route.target_state,
                "summary": route.summary,
                "rationale": route.rationale,
                "team_action": route.team_action,
                "team_id": payload["team_id"],
                "team_scope": resolved_scope,
                "run_id": run_id,
                "workspace_root": str(control_plane.resolve_workspace()),
                "brief_json": control_plane.display_path(
                    control_plane.team_run_brief_path(
                        payload["team_id"],
                        resolved_scope,
                        run_id,
                        control_plane.resolve_workspace(),
                    )
                ),
                "brief_markdown": control_plane.display_path(
                    control_plane.team_run_brief_markdown_path(
                        payload["team_id"],
                        resolved_scope,
                        run_id,
                        control_plane.resolve_workspace(),
                    )
                ),
                "messages": messages,
            }
        raise AutomationRunnerError(f"unsupported team action: {route.team_action}")

    def resume(
        self,
        workflow_id: str,
        route: IntentRoute | None = None,
        event_callback: EventCallback | None = None,
    ) -> dict[str, Any]:
        route = route or self.load_route(workflow_id)
        _, registry, orchestrator, _ = control_plane.get_runtime_context(workflow_id)
        steps: list[dict[str, Any]] = []
        for _ in range(self.max_steps):
            state = control_plane.load_state(workflow_id)
            current_state = state["current_state"]
            emit_event(
                event_callback,
                kind="state_entered",
                workflow_id=workflow_id,
                state=current_state,
                target_state=route.target_state,
                runtime=self.adapter.name,
            )
            if current_state in {"DONE", "BLOCKED"}:
                return self.summary(workflow_id, route, "finished", steps)
            if current_state in self.stop_before or state_requires_human_input(registry, orchestrator, current_state):
                emit_event(
                    event_callback,
                    kind="workflow_paused",
                    workflow_id=workflow_id,
                    state=current_state,
                    reason="stop_before_or_human_input",
                )
                return self.summary(workflow_id, route, "paused_for_human", steps)

            step_agents = orchestrator["state_agents"].get(current_state, [])
            emit_event(
                event_callback,
                kind="state_agents_planned",
                workflow_id=workflow_id,
                state=current_state,
                agents=[agent_id for agent_id in step_agents if agent_id != "orchestrator"],
            )
            for agent_id in step_agents:
                if agent_id == "orchestrator":
                    continue
                steps.append(self.run_agent(workflow_id, route, current_state, agent_id, registry, event_callback=event_callback))

            state_after = control_plane.load_state(workflow_id)
            if target_satisfied(route, state_after):
                emit_event(
                    event_callback,
                    kind="workflow_target_completed",
                    workflow_id=workflow_id,
                    state=state_after["current_state"],
                    target_state=route.target_state,
                )
                return self.summary(workflow_id, route, "completed_target", steps)

            next_state = state_after.get("next_state_hint")
            if not next_state:
                next_state = orchestrator["transitions"].get(current_state, {}).get("next")
            if not next_state:
                raise AutomationRunnerError(
                    f"runner could not determine next state from {current_state} for workflow {workflow_id}"
                )
            if next_state in self.stop_before or state_requires_human_input(registry, orchestrator, next_state):
                emit_event(
                    event_callback,
                    kind="workflow_paused",
                    workflow_id=workflow_id,
                    state=next_state,
                    reason="next_state_requires_human_or_stop_before",
                )
                return self.summary(workflow_id, route, "paused_for_human", steps)
            control_plane.write_state_transition(workflow_id, next_state)
            emit_event(
                event_callback,
                kind="state_transition",
                workflow_id=workflow_id,
                from_state=current_state,
                to_state=next_state,
                reason="orchestrator_next_state",
            )
        raise AutomationRunnerError(f"runner exceeded max_steps={self.max_steps} for workflow {workflow_id}")

    def run_agent(
        self,
        workflow_id: str,
        route: IntentRoute,
        state_name: str,
        agent_id: str,
        registry: dict[str, Any],
        event_callback: EventCallback | None = None,
    ) -> dict[str, Any]:
        return self._run_agent_with_adapter(
            adapter=self.adapter,
            workflow_id=workflow_id,
            route=route,
            state_name=state_name,
            agent_id=agent_id,
            registry=registry,
            event_callback=event_callback,
            allow_fallback=self.allow_runtime_fallback,
        )

    def _run_agent_with_adapter(
        self,
        *,
        adapter: RuntimeAdapter,
        workflow_id: str,
        route: IntentRoute,
        state_name: str,
        agent_id: str,
        registry: dict[str, Any],
        event_callback: EventCallback | None = None,
        allow_fallback: bool,
    ) -> dict[str, Any]:
        agents = control_plane.registry_by_id(registry)
        agent = agents[agent_id]
        emit_event(
            event_callback,
            kind="agent_preparing",
            workflow_id=workflow_id,
            state=state_name,
            agent=agent_id,
            runtime=adapter.name,
        )
        control_plane.pre_agent_run(agent_id, workflow_id)
        log_path = runner_dir(workflow_id) / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{state_name}-{agent_id}.log"
        use_search = any(
            dependency in {"contract:search_web", "contract:fetch_source"}
            for dependency in agent.get("dependencies", [])
        )
        prompt = prompt_for_agent(workflow_id=workflow_id, agent=agent, state_name=state_name, route=route)
        try:
            result = adapter.run(
                agent_id=agent_id,
                workflow_id=workflow_id,
                state_name=state_name,
                prompt=prompt,
                log_path=log_path,
                use_search=use_search,
                event_callback=event_callback,
            )
        except RuntimeNoOutputError as exc:
            if not allow_fallback:
                raise
            fallback_runtime = alternate_runtime_name(adapter.name)
            if fallback_runtime is None:
                raise
            emit_event(
                event_callback,
                kind="runtime_fallback",
                workflow_id=workflow_id,
                state=state_name,
                agent=agent_id,
                from_runtime=adapter.name,
                to_runtime=fallback_runtime,
                reason=str(exc),
            )
            fallback_adapter = pick_adapter(fallback_runtime)
            return self._run_agent_with_adapter(
                adapter=fallback_adapter,
                workflow_id=workflow_id,
                route=route,
                state_name=state_name,
                agent_id=agent_id,
                registry=registry,
                event_callback=event_callback,
                allow_fallback=False,
            )
        emit_event(
            event_callback,
            kind="agent_validating",
            workflow_id=workflow_id,
            state=state_name,
            agent=agent_id,
            runtime=adapter.name,
        )
        post_messages = control_plane.post_agent_run(agent_id, workflow_id)
        for message in post_messages:
            emit_event(
                event_callback,
                kind="agent_post_run",
                workflow_id=workflow_id,
                state=state_name,
                agent=agent_id,
                runtime=adapter.name,
                message=message,
            )
        return {
            "state": state_name,
            "agent": agent_id,
            "runtime": adapter.name,
            "log_path": control_plane.display_path(result.output_path),
            "command": result.command,
        }

    def load_route(self, workflow_id: str) -> IntentRoute:
        payload = control_plane.load_json(intent_lock_path(workflow_id))
        validate_intent_lock(payload)
        return IntentRoute(
            mode="workflow",
            workflow_type=payload["workflow_type"],
            entry_state=payload.get("entry_state", "L1_RESEARCH"),
            target_state=payload["target_state"],
            summary=payload["normalized_goal"],
            rationale=payload["routing_rationale"],
            execution_plan=payload.get("execution_plan", []),
        )

    def dispatch_workers(
        self,
        workflow_id: str,
        *,
        route: IntentRoute | None = None,
        state_name: str | None = None,
        dry_run: bool = False,
        runtime_choice: RuntimeChoice | None = None,
        event_callback: EventCallback | None = None,
    ) -> dict[str, Any]:
        route = route or self.load_route(workflow_id)
        _, registry, orchestrator, _ = control_plane.get_runtime_context(workflow_id)
        active_state = control_plane.load_state(workflow_id)["current_state"]
        target_state = state_name or active_state
        emit_event(
            event_callback,
            kind="dispatch_started",
            workflow_id=workflow_id,
            state=target_state,
            runtime=self.adapter.name,
            rationale=runtime_choice.rationale if runtime_choice else None,
        )
        if target_state != active_state:
            raise AutomationRunnerError(
                f"dispatch state mismatch: workflow {workflow_id} is at {active_state}, not {target_state}"
            )
        if state_requires_human_input(registry, orchestrator, target_state):
            raise AutomationRunnerError(f"state {target_state} requires human input and cannot be worker-dispatched")
        step_agents = [agent_id for agent_id in orchestrator["state_agents"].get(target_state, []) if agent_id != "orchestrator"]
        if not step_agents:
            raise AutomationRunnerError(f"state {target_state} has no executable worker agents")
        emit_event(
            event_callback,
            kind="dispatch_planned",
            workflow_id=workflow_id,
            state=target_state,
            runtime=self.adapter.name,
            agents=step_agents,
        )

        agents = control_plane.registry_by_id(registry)
        invocations: list[tuple[str, Path, RuntimeInvocation]] = []
        shell_lines: list[str] = ["set -euo pipefail"]
        for agent_id in step_agents:
            agent = agents[agent_id]
            control_plane.pre_agent_run(agent_id, workflow_id)
            log_path = runner_dir(workflow_id) / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{target_state}-{agent_id}.log"
            use_search = any(
                dependency in {"contract:search_web", "contract:fetch_source"}
                for dependency in agent.get("dependencies", [])
            )
            prompt = prompt_for_agent(workflow_id=workflow_id, agent=agent, state_name=target_state, route=route)
            invocation = self.adapter.prepare(
                agent_id=agent_id,
                workflow_id=workflow_id,
                state_name=target_state,
                prompt=prompt,
                log_path=log_path,
                use_search=use_search,
            )
            write_log_stub(
                log_path,
                runtime=self.adapter.name,
                agent_id=agent_id,
                state_name=target_state,
                workflow_id=workflow_id,
                command=invocation.command,
                status="queued",
            )
            invocations.append((agent_id, log_path, invocation))
            shell_lines.append(subprocess.list2cmdline(invocation.command) + " &")
        shell_lines.append("wait")

        if dry_run:
            emit_event(
                event_callback,
                kind="dispatch_dry_run",
                workflow_id=workflow_id,
                state=target_state,
                runtime=self.adapter.name,
                shell_script="\n".join(shell_lines),
            )
            return {
                "workflow_id": workflow_id,
                "runtime": self.adapter.name,
                "runtime_rationale": runtime_choice.rationale if runtime_choice else None,
                "state": target_state,
                "agents": [
                    {
                        "agent": agent_id,
                        "log_path": control_plane.display_path(log_path),
                        "command": invocation.command,
                    }
                    for agent_id, log_path, invocation in invocations
                ],
                "shell_script": "\n".join(shell_lines),
                "dry_run": True,
            }

        processes: list[dict[str, Any]] = []
        failures: list[str] = []
        for agent_id, log_path, invocation in invocations:
            process = subprocess.Popen(
                invocation.command,
                cwd=invocation.cwd,
                env=invocation.env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            write_log_stub(
                log_path,
                runtime=self.adapter.name,
                agent_id=agent_id,
                state_name=target_state,
                workflow_id=workflow_id,
                command=invocation.command,
                status="running",
                note=f"pid={process.pid}",
            )
            stream_queue: queue.Queue[tuple[str, str | None]] = queue.Queue()
            stdout_done = process.stdout is None
            stderr_done = process.stderr is None
            stdout_thread = None if process.stdout is None else _start_reader_thread(process.stdout, source="stdout", target_queue=stream_queue)
            stderr_thread = None if process.stderr is None else _start_reader_thread(process.stderr, source="stderr", target_queue=stream_queue)
            processes.append(
                {
                    "agent_id": agent_id,
                    "log_path": log_path,
                    "process": process,
                    "queue": stream_queue,
                    "stdout_done": stdout_done,
                    "stderr_done": stderr_done,
                    "stdout_thread": stdout_thread,
                    "stderr_thread": stderr_thread,
                    "idle_deadline": time.monotonic() + DEFAULT_RUNTIME_IDLE_TIMEOUT_SECONDS,
                }
            )
            emit_event(
                event_callback,
                kind="agent_started",
                agent=agent_id,
                state=target_state,
                runtime=self.adapter.name,
                workflow_id=workflow_id,
                log_path=control_plane.display_path(log_path),
                pid=process.pid,
            )

        step_results: list[dict[str, Any]] = []
        pending = list(processes)
        while pending:
            next_pending: list[dict[str, Any]] = []
            for item in pending:
                agent_id = item["agent_id"]
                log_path = item["log_path"]
                process = item["process"]
                stream_queue = item["queue"]
                if time.monotonic() > item["idle_deadline"]:
                    process.kill()
                    append_log_note(log_path, "timeout", f"runtime became idle after {DEFAULT_RUNTIME_IDLE_TIMEOUT_SECONDS}s")
                    failures.append(f"{agent_id}: runtime became idle after {DEFAULT_RUNTIME_IDLE_TIMEOUT_SECONDS}s")
                    emit_event(
                        event_callback,
                        kind="agent_timeout",
                        agent=agent_id,
                        state=target_state,
                        runtime=self.adapter.name,
                        workflow_id=workflow_id,
                        timeout_seconds=DEFAULT_RUNTIME_IDLE_TIMEOUT_SECONDS,
                    )
                    item["stdout_done"] = True
                    item["stderr_done"] = True
                drained = False
                while True:
                    try:
                        source, chunk = stream_queue.get_nowait()
                    except queue.Empty:
                        break
                    drained = True
                    if chunk is None:
                        if source == "stdout":
                            item["stdout_done"] = True
                        elif source == "stderr":
                            item["stderr_done"] = True
                        continue
                    text = chunk.rstrip("\n")
                    item["idle_deadline"] = time.monotonic() + DEFAULT_RUNTIME_IDLE_TIMEOUT_SECONDS
                    _append_stream_chunk(log_path, source, text)
                    emit_event(
                        event_callback,
                        kind="agent_output",
                        agent=agent_id,
                        state=target_state,
                        runtime=self.adapter.name,
                        workflow_id=workflow_id,
                        source=source,
                        text=text,
                        log_path=control_plane.display_path(log_path),
                    )
                if process.poll() is None or not (item["stdout_done"] and item["stderr_done"]):
                    next_pending.append(item)
                    continue
                if item["stdout_thread"] is not None:
                    item["stdout_thread"].join(timeout=1)
                if item["stderr_thread"] is not None:
                    item["stderr_thread"].join(timeout=1)
                if process.returncode != 0 and not any(failure.startswith(f"{agent_id}:") for failure in failures):
                    failures.append(f"{agent_id}: process exited with {process.returncode}")
                elif not log_path.exists() or not log_path.read_text(encoding="utf-8").strip():
                    write_log_stub(
                        log_path,
                        runtime=self.adapter.name,
                        agent_id=agent_id,
                        state_name=target_state,
                        workflow_id=workflow_id,
                        command=process.args if isinstance(process.args, list) else [str(process.args)],
                        status="completed_without_runtime_log",
                        note="worker exited successfully but produced no log file",
                    )
                emit_event(
                    event_callback,
                    kind="agent_completed",
                    agent=agent_id,
                    state=target_state,
                    runtime=self.adapter.name,
                    workflow_id=workflow_id,
                    log_path=control_plane.display_path(log_path),
                )
                step_results.append(
                    {
                        "state": target_state,
                        "agent": agent_id,
                        "runtime": self.adapter.name,
                        "log_path": control_plane.display_path(log_path),
                        "command": process.args,
                    }
                )
            pending = next_pending
            if pending:
                time.sleep(0.05)
        if failures:
            raise AutomationRunnerError(
                "parallel codex worker dispatch failed:\n" + "\n".join(failures)
            )

        validation_messages: list[str] = []
        for agent_id, _, _ in invocations:
            validation_messages.extend(control_plane.finalize_agent_run(agent_id, workflow_id))
            emit_event(
                event_callback,
                kind="dispatch_agent_validated",
                workflow_id=workflow_id,
                state=target_state,
                agent=agent_id,
            )
        validation_messages.extend(control_plane.commit_workflow_changes(workflow_id, target_state, step_agents))
        for message in validation_messages:
            emit_event(
                event_callback,
                kind="dispatch_message",
                workflow_id=workflow_id,
                state=target_state,
                runtime=self.adapter.name,
                message=message,
            )
        state = control_plane.load_state(workflow_id)
        return {
            "workflow_id": workflow_id,
            "runtime": self.adapter.name,
            "runtime_rationale": runtime_choice.rationale if runtime_choice else None,
            "status": "workers_completed",
            "state": target_state,
            "current_state": state["current_state"],
            "next_state_hint": state.get("next_state_hint"),
            "steps": step_results,
            "messages": validation_messages,
        }

    def summary(self, workflow_id: str, route: IntentRoute, status: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
        state = control_plane.load_state(workflow_id)
        return {
            "workflow_id": workflow_id,
            "workspace_root": str(control_plane.resolve_workspace(workflow=workflow_id)),
            "status": status,
            "workflow_type": route.workflow_type,
            "target_state": route.target_state,
            "current_state": state["current_state"],
            "next_state_hint": state.get("next_state_hint"),
            "active_review_loop": state.get("active_review_loop"),
            "steps": steps,
            "intent_lock": control_plane.display_path(intent_lock_path(workflow_id)),
            "project_lock": control_plane.display_path(control_plane.project_lock_path(workflow_id)),
            "registry_lock": control_plane.display_path(control_plane.registry_lock_path(workflow_id)),
            "orchestrator_lock": control_plane.display_path(control_plane.orchestrator_lock_path(workflow_id)),
            "state_path": control_plane.display_path(control_plane.state_path(workflow_id)),
        }


def print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def summarize_with_runtime_choice(payload: dict[str, Any], runtime_choice: RuntimeChoice) -> dict[str, Any]:
    result = dict(payload)
    result.setdefault("runtime", runtime_choice.runtime)
    result["runtime_rationale"] = runtime_choice.rationale
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AEGIS automation runner")
    parser.add_argument("--workspace", help="Workspace root for the attached project")
    sub = parser.add_subparsers(dest="command", required=True)

    bootstrap_cmd = sub.add_parser("bootstrap")
    bootstrap_cmd.add_argument("request")
    bootstrap_cmd.add_argument("--workflow-id")
    bootstrap_cmd.add_argument("--runtime", default="auto", choices=["auto", "codex", "claude"])

    run_cmd = sub.add_parser("run")
    run_cmd.add_argument("request")
    run_cmd.add_argument("--workflow-id")
    run_cmd.add_argument("--runtime", default="auto", choices=["auto", "codex", "claude"])
    run_cmd.add_argument("--max-steps", type=int, default=30)
    run_cmd.add_argument("--stop-before", action="append", default=[])

    resume_cmd = sub.add_parser("resume")
    resume_cmd.add_argument("--workflow", required=True)
    resume_cmd.add_argument("--runtime", default="auto", choices=["auto", "codex", "claude"])
    resume_cmd.add_argument("--max-steps", type=int, default=30)
    resume_cmd.add_argument("--stop-before", action="append", default=[])

    dispatch_cmd = sub.add_parser("dispatch")
    dispatch_cmd.add_argument("--workflow", required=True)
    dispatch_cmd.add_argument("--runtime", default="auto", choices=["auto", "codex", "claude"])
    dispatch_cmd.add_argument("--state")
    dispatch_cmd.add_argument("--dry-run", action="store_true")

    route_cmd = sub.add_parser("route")
    route_cmd.add_argument("request")

    args = parser.parse_args(argv)
    try:
        if args.workspace:
            os.environ["AEGIS_WORKSPACE_ROOT"] = str(Path(args.workspace).expanduser().resolve())
        elif hasattr(args, "workflow"):
            inferred_workspace = control_plane.workspace_from_workflow_index(getattr(args, "workflow"))
            if inferred_workspace:
                os.environ["AEGIS_WORKSPACE_ROOT"] = str(inferred_workspace)
        if args.command == "route":
            route = route_request(args.request)
            print_json(
                {
                    "mode": route.mode,
                    "workflow_type": route.workflow_type,
                    "target_state": route.target_state,
                    "normalized_goal": route.summary,
                    "routing_rationale": route.rationale,
                    "team_action": route.team_action,
                    "team_id": route.team_id,
                    "team_scope": route.team_scope,
                    "team_request": route.team_request,
                }
            )
            return 0

        if args.command == "bootstrap":
            route = route_request(args.request)
            runtime_choice = choose_runtime_for_state(
                workflow_id=args.workflow_id,
                state_name="L1_RESEARCH",
                requested_runtime=args.runtime,
                for_dispatch=False,
            )
            adapter = pick_adapter(runtime_choice.runtime)
            runner = AutomationRunner(adapter=adapter, stop_before=set(DEFAULT_STOP_BEFORE), max_steps=30)
            result = summarize_with_runtime_choice(
                runner.bootstrap_summary(args.request, workflow_id=args.workflow_id),
                runtime_choice,
            )
        elif args.command == "run":
            route = route_request(args.request)
            runtime_choice = choose_runtime_for_state(
                workflow_id=args.workflow_id,
                state_name="L1_RESEARCH",
                requested_runtime=args.runtime,
                for_dispatch=False,
            )
            adapter = pick_adapter(runtime_choice.runtime)
            runner = AutomationRunner(
                adapter=adapter,
                stop_before=set(DEFAULT_STOP_BEFORE).union(set(args.stop_before)),
                max_steps=args.max_steps,
                allow_runtime_fallback=args.runtime == "auto",
            )
            result = summarize_with_runtime_choice(
                runner.run_request(args.request, workflow_id=args.workflow_id),
                runtime_choice,
            )
        elif args.command == "resume":
            state_name = control_plane.load_state(args.workflow)["current_state"]
            runtime_choice = choose_runtime_for_state(
                workflow_id=args.workflow,
                state_name=state_name,
                requested_runtime=args.runtime,
                for_dispatch=False,
            )
            adapter = pick_adapter(runtime_choice.runtime)
            runner = AutomationRunner(
                adapter=adapter,
                stop_before=set(DEFAULT_STOP_BEFORE).union(set(args.stop_before)),
                max_steps=args.max_steps,
                allow_runtime_fallback=args.runtime == "auto",
            )
            result = summarize_with_runtime_choice(runner.resume(args.workflow), runtime_choice)
        elif args.command == "dispatch":
            current_state = control_plane.load_state(args.workflow)["current_state"]
            runtime_choice = choose_runtime_for_state(
                workflow_id=args.workflow,
                state_name=args.state or current_state,
                requested_runtime=args.runtime,
                for_dispatch=True,
            )
            adapter = pick_adapter(runtime_choice.runtime)
            runner = AutomationRunner(adapter=adapter, stop_before=set(DEFAULT_STOP_BEFORE), max_steps=30)
            result = runner.dispatch_workers(
                args.workflow,
                state_name=args.state,
                dry_run=args.dry_run,
                runtime_choice=runtime_choice,
            )
        else:
            raise AutomationRunnerError(f"unsupported command: {args.command}")
        print_json(result)
        return 0
    except (AutomationRunnerError, control_plane.ControlPlaneError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
