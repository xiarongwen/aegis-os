from __future__ import annotations

import curses
import os
import queue
import textwrap
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from tools.control_plane import cli


@dataclass
class WorkflowSnapshot:
    workflow_id: str
    workspace_root: str | None
    workflow_type: str | None
    current_state: str
    next_state_hint: str | None
    updated_at: str | None
    started_at: str | None
    summary: str | None
    runtime: str | None
    runtime_rationale: str
    dispatch_runtime: str | None
    dispatch_rationale: str
    available_runtimes: list[str]
    artifacts: list[tuple[str, bool, str]]
    command_hints: list[str]
    issues: list[str]


@dataclass
class BackgroundTaskResult:
    kind: str
    payload: dict[str, Any] | None = None
    message: str | None = None
    workflow_id: str | None = None


@dataclass
class AppState:
    snapshots: list[WorkflowSnapshot] = field(default_factory=list)
    selected_index: int = 0
    status_message: str = "Ready."
    timeline_lines: list[str] = field(default_factory=lambda: ["AEGIS ready. Type a request below and press Enter."])
    input_buffer: str = ""
    input_cursor: int = 0
    running_task: str | None = None
    overlay: str | None = None
    overlay_index: int = 0
    current_workflow_id: str | None = None
    current_workflow_type: str | None = None
    current_target_state: str | None = None
    current_runtime: str | None = None
    current_entry_state: str | None = None
    current_execution_plan: list[str] = field(default_factory=list)
    event_counters: dict[str, int] = field(default_factory=dict)


def _safe_load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = cli.load_json(path)
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _workflow_state_payload(workflow_id: str, workspace_root: str | None) -> dict[str, Any]:
    try:
        return cli.load_state(workflow_id)
    except cli.ControlPlaneError:
        if not workspace_root:
            return {}
        fallback = Path(workspace_root) / ".aegis" / "runs" / workflow_id / "state.json"
        return _safe_load_json(fallback) or {}


def _artifact_status(workflow_id: str) -> list[tuple[str, bool, str]]:
    named_paths = [
        ("intent lock", cli.workflow_root(workflow_id) / "intent-lock.json"),
        ("project lock", cli.project_lock_path(workflow_id)),
        ("registry lock", cli.registry_lock_path(workflow_id)),
        ("orchestrator lock", cli.orchestrator_lock_path(workflow_id)),
        ("requirements lock", cli.requirements_lock_path(workflow_id)),
        ("task breakdown", cli.task_breakdown_path(workflow_id)),
        ("implementation contracts", cli.implementation_contracts_path(workflow_id)),
        ("traceability", cli.requirements_traceability_path(workflow_id)),
    ]
    return [(label, path.exists(), cli.display_path(path)) for label, path in named_paths]


def _runtime_choices(workflow_id: str, state_name: str) -> tuple[str | None, str, str | None, str, list[str]]:
    try:
        from tools.automation_runner import cli as runner_cli

        available = runner_cli.available_runtimes()
        orchestration = runner_cli.choose_runtime_for_state(
            workflow_id=workflow_id,
            state_name=state_name,
            requested_runtime="auto",
            for_dispatch=False,
        )
        dispatch = runner_cli.choose_runtime_for_state(
            workflow_id=workflow_id,
            state_name=state_name,
            requested_runtime="auto",
            for_dispatch=True,
        )
        return (
            orchestration.runtime,
            orchestration.rationale,
            dispatch.runtime,
            dispatch.rationale,
            available,
        )
    except Exception as exc:
        return (None, str(exc), None, str(exc), [])


def command_hints_for_workflow(workflow_id: str) -> list[str]:
    return [
        f"aegis resume --workflow {workflow_id} --runtime auto",
        f"aegis dispatch --workflow {workflow_id} --runtime auto --dry-run",
        f"aegis dispatch --workflow {workflow_id} --runtime auto",
        f"aegisctl run-doctor --workflow {workflow_id}",
    ]


def workflow_ids() -> list[str]:
    payload = cli.load_workflow_index()
    workflows = payload.get("workflows", {})
    items = list(workflows.items())
    items.sort(key=lambda item: (item[1].get("updated_at", ""), item[0]), reverse=True)
    return [workflow_id for workflow_id, _ in items]


def build_workflow_snapshot(workflow_id: str) -> WorkflowSnapshot:
    payload = cli.load_workflow_index().get("workflows", {}).get(workflow_id, {})
    workspace_root = payload.get("workspace_root")
    state = _workflow_state_payload(workflow_id, workspace_root)
    current_state = str(state.get("current_state") or payload.get("current_state") or "UNKNOWN")
    intent_lock = _safe_load_json(cli.workflow_root(workflow_id) / "intent-lock.json") or {}
    runtime, runtime_rationale, dispatch_runtime, dispatch_rationale, available = _runtime_choices(
        workflow_id,
        current_state,
    )
    issues: list[str] = []
    if workspace_root and not Path(workspace_root).exists():
        issues.append(f"workspace missing: {workspace_root}")
    if not workspace_root:
        issues.append("workflow index has no workspace_root")
    return WorkflowSnapshot(
        workflow_id=workflow_id,
        workspace_root=workspace_root,
        workflow_type=(state.get("workflow_type") or payload.get("workflow_type")),
        current_state=current_state,
        next_state_hint=state.get("next_state_hint"),
        updated_at=payload.get("updated_at"),
        started_at=state.get("started_at"),
        summary=intent_lock.get("normalized_goal"),
        runtime=runtime,
        runtime_rationale=runtime_rationale,
        dispatch_runtime=dispatch_runtime,
        dispatch_rationale=dispatch_rationale,
        available_runtimes=available,
        artifacts=_artifact_status(workflow_id),
        command_hints=command_hints_for_workflow(workflow_id),
        issues=issues,
    )


def refresh_snapshots(state: AppState, preferred_workflow: str | None = None) -> None:
    ids = workflow_ids()
    state.snapshots = [build_workflow_snapshot(workflow_id) for workflow_id in ids]
    if not state.snapshots:
        state.selected_index = 0
        state.overlay_index = 0
        return
    if preferred_workflow:
        for index, snapshot in enumerate(state.snapshots):
            if snapshot.workflow_id == preferred_workflow:
                state.selected_index = index
                state.overlay_index = index
                _sync_current_context_from_snapshot(state)
                return
    state.selected_index = max(0, min(state.selected_index, len(state.snapshots) - 1))
    state.overlay_index = max(0, min(state.overlay_index, len(state.snapshots) - 1))
    _sync_current_context_from_snapshot(state)


def _selected_snapshot(state: AppState) -> WorkflowSnapshot | None:
    if not state.snapshots:
        return None
    state.selected_index = max(0, min(state.selected_index, len(state.snapshots) - 1))
    return state.snapshots[state.selected_index]


def summarize_action_result(payload: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for key in [
        "status",
        "workflow_id",
        "workflow_type",
        "target_state",
        "current_state",
        "next_state_hint",
        "runtime",
        "runtime_rationale",
        "state",
    ]:
        value = payload.get(key)
        if value not in (None, "", [], {}):
            lines.append(f"{key}: {value}")
    if payload.get("messages"):
        lines.extend(f"message: {item}" for item in payload["messages"][:6])
    if payload.get("steps"):
        for step in payload["steps"][:6]:
            if isinstance(step, dict):
                agent = step.get("agent", "<unknown>")
                step_state = step.get("state", "<unknown>")
                runtime = step.get("runtime", "<unknown>")
                log_path = step.get("log_path")
                suffix = f" log={log_path}" if log_path else ""
                lines.append(f"step: {agent} @ {step_state} via {runtime}{suffix}")
            else:
                lines.append(f"step: {step}")
    if payload.get("agents"):
        for agent in payload["agents"][:6]:
            lines.append(f"agent: {agent.get('agent')} -> {agent.get('log_path')}")
    return lines or ["Action completed."]


def format_event_line(event: dict[str, Any]) -> str:
    kind = event.get("kind", "event")
    agent = event.get("agent", "?")
    runtime = event.get("runtime", "?")
    if kind == "runtime_selected":
        return f"runtime selected: {runtime} ({event.get('rationale', '')})"
    if kind == "workflow_routed":
        plan = " -> ".join(event.get("execution_plan", []))
        return (
            f"route: type={event.get('workflow_type')} entry={event.get('entry_state')} "
            f"target={event.get('target_state')} runtime={runtime} plan={plan}"
        )
    if kind == "workflow_bootstrap_started":
        return (
            f"bootstrap started: workflow={event.get('workflow_id')} entry={event.get('entry_state')} "
            f"target={event.get('target_state')} runtime={runtime}"
        )
    if kind == "workflow_plan_generated":
        return (
            f"generated workflow plan: entry={event.get('entry_state')} "
            f"target={event.get('target_state')} plan={' -> '.join(event.get('execution_plan', []))}"
        )
    if kind == "state_entered":
        return f"entered state: {event.get('state')} target={event.get('target_state')}"
    if kind == "state_agents_planned":
        return f"state plan: {event.get('state')} agents={', '.join(event.get('agents', []))}"
    if kind == "state_transition":
        return f"transition: {event.get('from_state')} -> {event.get('to_state')} ({event.get('reason')})"
    if kind == "agent_preparing":
        return f"preparing agent: {agent} state={event.get('state')} runtime={runtime}"
    if kind == "agent_started":
        return f"{agent} started via {runtime} pid={event.get('pid')}"
    if kind == "agent_validating":
        return f"validating agent output: {agent} state={event.get('state')}"
    if kind == "agent_post_run":
        return f"post-run: {agent} {event.get('message')}"
    if kind == "agent_completed":
        return f"{agent} completed via {runtime}"
    if kind == "agent_timeout":
        return f"{agent} became idle via {runtime} after {event.get('timeout_seconds')}s"
    if kind == "agent_silent_timeout":
        return f"{agent} produced no output via {runtime} after {event.get('timeout_seconds')}s"
    if kind == "runtime_fallback":
        return f"fallback: {event.get('agent')} {event.get('from_runtime')} -> {event.get('to_runtime')} ({event.get('reason')})"
    if kind == "runtime_bridge_unavailable":
        return f"bridge unavailable for {event.get('agent')} via {runtime}: {event.get('reason')}"
    if kind == "agent_output":
        return f"{agent} {event.get('source', '?')}: {event.get('text', '')}"
    if kind == "workflow_paused":
        return f"workflow paused at {event.get('state')} ({event.get('reason')})"
    if kind == "workflow_target_completed":
        return f"workflow target completed at {event.get('state')} target={event.get('target_state')}"
    if kind == "dispatch_started":
        return f"dispatch started: state={event.get('state')} runtime={runtime} rationale={event.get('rationale')}"
    if kind == "dispatch_planned":
        return f"dispatch plan: state={event.get('state')} agents={', '.join(event.get('agents', []))}"
    if kind == "dispatch_dry_run":
        return "dispatch dry-run generated shell script"
    if kind == "dispatch_agent_validated":
        return f"dispatch validated: {agent} state={event.get('state')}"
    if kind == "dispatch_message":
        return f"dispatch: {event.get('message')}"
    return str(event)


def append_timeline(state: AppState, role: str, text: str) -> None:
    prefix = f"{role}> "
    wrapped = textwrap.wrap(text, width=120) or [""]
    for index, line in enumerate(wrapped):
        state.timeline_lines.append(prefix + line if index == 0 else " " * len(prefix) + line)
    if len(state.timeline_lines) > 400:
        state.timeline_lines = state.timeline_lines[-400:]


def _increment_event_counter(state: AppState, key: str) -> int:
    count = state.event_counters.get(key, 0) + 1
    state.event_counters[key] = count
    return count


def _summarize_agent_output_for_tui(state: AppState, event: dict[str, Any]) -> tuple[str, str] | None:
    source = str(event.get("source") or "")
    text = str(event.get("text") or "").strip()
    agent = str(event.get("agent") or "?")
    if not text:
        return None
    if source != "stderr":
        return ("agent", format_event_line(event))

    lowered = text.lower()
    if lowered.startswith("web search:"):
        count = _increment_event_counter(state, f"{agent}:web-search")
        if count == 1 or count % 10 == 0:
            suffix = "" if count == 1 else f" ({count} queries)"
            return ("agent", f"{agent} searching web sources{suffix}")
        return None
    if lowered in {"exec", "codex"}:
        count = _increment_event_counter(state, f"{agent}:runtime-trace")
        if count == 1:
            return ("agent", f"{agent} running tool commands")
        return None
    if text.startswith("/bin/zsh -lc "):
        count = _increment_event_counter(state, f"{agent}:shell-command")
        if count == 1 or count % 5 == 0:
            suffix = "" if count == 1 else f" ({count} commands)"
            return ("agent", f"{agent} scanning workspace and executing checks{suffix}")
        return None
    if "succeeded in 0ms" in lowered or "exited 1 in 0ms" in lowered:
        _increment_event_counter(state, f"{agent}:command-result-noise")
        return None
    return ("stderr", format_event_line(event))


def _sync_current_context_from_snapshot(state: AppState) -> None:
    selected = _selected_snapshot(state)
    if selected is None:
        return
    state.current_workflow_id = selected.workflow_id
    state.current_workflow_type = selected.workflow_type
    state.current_entry_state = getattr(selected, "current_state", None)
    state.current_target_state = selected.next_state_hint or selected.current_state
    state.current_runtime = selected.runtime


def _runner_module() -> Any:
    from tools.automation_runner import cli as runner_cli

    return runner_cli


def execute_new_request(
    request: str,
    *,
    bootstrap_only: bool = False,
    event_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    runner_cli = _runner_module()
    runtime_choice = runner_cli.choose_runtime_for_state(
        workflow_id=None,
        state_name="L1_RESEARCH",
        requested_runtime="auto",
        for_dispatch=False,
    )
    if event_callback is not None:
        event_callback(
            {
                "kind": "runtime_selected",
                "runtime": runtime_choice.runtime,
                "rationale": runtime_choice.rationale,
                "state": "L1_RESEARCH",
            }
        )
    adapter = runner_cli.pick_adapter(runtime_choice.runtime)
    runner = runner_cli.AutomationRunner(
        adapter=adapter,
        stop_before=set(runner_cli.DEFAULT_STOP_BEFORE),
        max_steps=30,
        allow_runtime_fallback=True,
    )
    if bootstrap_only:
        payload = runner.bootstrap_summary(request)
    else:
        workflow_id, _ = runner.bootstrap(request, event_callback=event_callback)
        payload = runner.resume(workflow_id, event_callback=event_callback)
    return runner_cli.summarize_with_runtime_choice(payload, runtime_choice)


def execute_resume(
    workflow_id: str,
    *,
    event_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    runner_cli = _runner_module()
    state_name = cli.load_state(workflow_id)["current_state"]
    runtime_choice = runner_cli.choose_runtime_for_state(
        workflow_id=workflow_id,
        state_name=state_name,
        requested_runtime="auto",
        for_dispatch=False,
    )
    if event_callback is not None:
        event_callback(
            {
                "kind": "runtime_selected",
                "runtime": runtime_choice.runtime,
                "rationale": runtime_choice.rationale,
                "state": state_name,
            }
        )
    adapter = runner_cli.pick_adapter(runtime_choice.runtime)
    runner = runner_cli.AutomationRunner(
        adapter=adapter,
        stop_before=set(runner_cli.DEFAULT_STOP_BEFORE),
        max_steps=30,
        allow_runtime_fallback=True,
    )
    return runner_cli.summarize_with_runtime_choice(
        runner.resume(workflow_id, event_callback=event_callback),
        runtime_choice,
    )


def execute_dispatch(
    workflow_id: str,
    *,
    dry_run: bool,
    event_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    runner_cli = _runner_module()
    current_state = cli.load_state(workflow_id)["current_state"]
    runtime_choice = runner_cli.choose_runtime_for_state(
        workflow_id=workflow_id,
        state_name=current_state,
        requested_runtime="auto",
        for_dispatch=True,
    )
    if event_callback is not None:
        event_callback(
            {
                "kind": "runtime_selected",
                "runtime": runtime_choice.runtime,
                "rationale": runtime_choice.rationale,
                "state": current_state,
            }
        )
    adapter = runner_cli.pick_adapter(runtime_choice.runtime)
    runner = runner_cli.AutomationRunner(
        adapter=adapter,
        stop_before=set(runner_cli.DEFAULT_STOP_BEFORE),
        max_steps=30,
        allow_runtime_fallback=True,
    )
    return runner.dispatch_workers(
        workflow_id,
        dry_run=dry_run,
        runtime_choice=runtime_choice,
        event_callback=event_callback,
    )


def _trim(value: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(value) <= width:
        return value
    if width <= 3:
        return value[:width]
    return value[: width - 3] + "..."


def _visible_input_window(buffer: str, cursor: int, width: int) -> tuple[str, int]:
    if width <= 0:
        return ("", 0)
    if len(buffer) <= width:
        return (buffer, cursor)
    start = max(0, cursor - width + 1)
    end = start + width
    if end > len(buffer):
        end = len(buffer)
        start = max(0, end - width)
    visible = buffer[start:end]
    return (visible, cursor - start)


def _draw_wrapped_lines(
    stdscr: Any,
    *,
    y: int,
    x: int,
    width: int,
    max_y: int,
    lines: list[str],
) -> None:
    row = y
    usable_width = max(1, width)
    for raw_line in lines:
        for line in textwrap.wrap(raw_line, usable_width) or [""]:
            if row > max_y:
                return
            stdscr.addnstr(row, x, line, usable_width)
            row += 1


def _detail_lines(snapshot: WorkflowSnapshot) -> list[str]:
    lines = [
        f"workflow: {snapshot.workflow_id}",
        f"workspace: {snapshot.workspace_root or '<unknown>'}",
        f"type: {snapshot.workflow_type or '<unset>'}",
        f"state: {snapshot.current_state}",
        f"next: {snapshot.next_state_hint or '<none>'}",
        f"started: {snapshot.started_at or '<unknown>'}",
        f"updated: {snapshot.updated_at or '<unknown>'}",
        f"available runtimes: {', '.join(snapshot.available_runtimes) or '<none>'}",
        f"orchestrator runtime: {snapshot.runtime or '<unavailable>'}",
        f"dispatch runtime: {snapshot.dispatch_runtime or '<unavailable>'}",
        "",
        "summary:",
        snapshot.summary or "<no summary>",
        "",
        "runtime rationale:",
        snapshot.runtime_rationale,
        "",
        "dispatch rationale:",
        snapshot.dispatch_rationale,
        "",
        "artifacts:",
    ]
    for label, present, path in snapshot.artifacts:
        lines.append(f"[{'x' if present else ' '}] {label}: {path}")
    if snapshot.issues:
        lines.extend(["", "issues:"])
        lines.extend(snapshot.issues)
    lines.extend(["", "commands:"])
    lines.extend(snapshot.command_hints)
    return lines


def _draw_box(stdscr: Any, top: int, left: int, height: int, width: int, title: str) -> None:
    for row in range(top, top + height):
        if row in {top, top + height - 1}:
            stdscr.addnstr(row, left, "+" + "-" * max(0, width - 2) + "+", width)
        else:
            stdscr.addnstr(row, left, "|" + " " * max(0, width - 2) + "|", width)
    stdscr.addnstr(top, left + 2, f" {title} ", max(0, width - 4), curses.A_BOLD)


def _draw_overlay(stdscr: Any, state: AppState, height: int, width: int) -> None:
    if state.overlay is None:
        return
    box_width = min(width - 6, 96)
    box_height = min(height - 6, 24)
    top = max(2, (height - box_height) // 2)
    left = max(2, (width - box_width) // 2)
    _draw_box(stdscr, top, left, box_height, box_width, "Workflow Picker" if state.overlay == "picker" else "Inspector")
    inner_top = top + 2
    inner_left = left + 2
    inner_width = box_width - 4
    inner_bottom = top + box_height - 3
    if state.overlay == "picker":
        visible = state.snapshots[: max(1, inner_bottom - inner_top + 1)]
        for offset, snapshot in enumerate(visible):
            row = inner_top + offset
            marker = ">" if offset == state.overlay_index else " "
            line = f"{marker} {snapshot.workflow_id} [{snapshot.current_state}] {snapshot.summary or ''}"
            attr = curses.A_REVERSE if offset == state.overlay_index else curses.A_NORMAL
            stdscr.addnstr(row, inner_left, _trim(line, inner_width), inner_width, attr)
    else:
        snapshot = _selected_snapshot(state)
        if snapshot is not None:
            _draw_wrapped_lines(
                stdscr,
                y=inner_top,
                x=inner_left,
                width=inner_width,
                max_y=inner_bottom,
                lines=_detail_lines(snapshot),
            )


def _draw_ui(stdscr: Any, state: AppState) -> None:
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    if height < 14 or width < 70:
        stdscr.addnstr(0, 0, "Terminal too small for AEGIS UI. Resize and retry.", max(0, width - 1))
        stdscr.refresh()
        return

    selected = _selected_snapshot(state)
    host_runtime = os.environ.get("AEGIS_HOST_RUNTIME") or "<unset>"
    active_workflow = state.current_workflow_id or (selected.workflow_id if selected else "<none>")
    active_state = selected.current_state if selected else "<none>"
    active_type = state.current_workflow_type or (selected.workflow_type if selected else "<none>")
    active_entry = state.current_entry_state or "<none>"
    active_target = state.current_target_state or (selected.next_state_hint if selected else None) or "<none>"
    active_runtime = state.current_runtime or (selected.runtime if selected else None) or "<none>"
    active_plan = " -> ".join(state.current_execution_plan) if state.current_execution_plan else "<none>"
    header = (
        f"AEGIS Console  workflow={active_workflow}  type={active_type}  "
        f"entry={active_entry}  state={active_state}  target={active_target}  runtime={active_runtime}"
    )
    subheader = f"plan={active_plan}  host={host_runtime}  commands: /bootstrap /resume /dispatch /dispatch-dry /workflows /inspect"
    stdscr.addnstr(0, 0, _trim(header, width - 1), max(0, width - 1), curses.A_BOLD)
    stdscr.addnstr(1, 0, _trim(subheader, width - 1), max(0, width - 1))
    stdscr.hline(2, 0, "-", width)

    body_top = 3
    body_bottom = height - 4
    _draw_wrapped_lines(
        stdscr,
        y=body_top,
        x=0,
        width=max(1, width - 1),
        max_y=body_bottom,
        lines=state.timeline_lines[-max(1, body_bottom - body_top + 1) :],
    )

    stdscr.hline(height - 3, 0, "-", width)
    task_label = state.running_task or "idle"
    prompt = "input> "
    input_width = max(0, width - len(prompt) - 1)
    visible_input, cursor_x = _visible_input_window(state.input_buffer, state.input_cursor, input_width)
    stdscr.addnstr(height - 2, 0, prompt + (" " * max(0, width - len(prompt) - 1)), max(0, width - 1), curses.A_REVERSE)
    stdscr.addnstr(height - 2, 0, prompt, len(prompt), curses.A_REVERSE)
    if input_width > 0:
        stdscr.addnstr(height - 2, len(prompt), visible_input.ljust(input_width), input_width, curses.A_REVERSE)
    footer = f"status: {state.status_message}  task: {task_label}  selected={selected.workflow_id if selected else '<none>'}"
    stdscr.addnstr(height - 1, 0, _trim(footer, width - 1), max(0, width - 1), curses.A_DIM)
    _draw_overlay(stdscr, state, height, width)
    if state.overlay is None:
        try:
            curses.curs_set(1)
        except curses.error:
            pass
        stdscr.move(height - 2, min(width - 1, len(prompt) + cursor_x))
    else:
        try:
            curses.curs_set(0)
        except curses.error:
            pass
    stdscr.refresh()


def _spawn_task(
    state: AppState,
    result_queue: queue.Queue[BackgroundTaskResult],
    *,
    label: str,
    func: Callable[..., dict[str, Any]],
    args: tuple[Any, ...],
    workflow_id: str | None = None,
) -> None:
    if state.running_task is not None:
        state.status_message = f"Task already running: {state.running_task}"
        return
    state.running_task = label
    state.status_message = f"Running {label}..."
    append_timeline(state, "system", f"started {label}")

    def _target() -> None:
        try:
            payload = func(*args)
            result_queue.put(
                BackgroundTaskResult(
                    kind="success",
                    payload=payload,
                    workflow_id=payload.get("workflow_id") or workflow_id,
                )
            )
        except Exception as exc:
            result_queue.put(BackgroundTaskResult(kind="error", message=str(exc), workflow_id=workflow_id))

    threading.Thread(target=_target, daemon=True).start()


def _handle_task_result(state: AppState, result: BackgroundTaskResult) -> None:
    state.running_task = None
    if result.kind == "success" and result.payload is not None:
        for line in summarize_action_result(result.payload):
            append_timeline(state, "result", line)
        state.status_message = result.payload.get("status", "Action completed.")
        if result.payload.get("workflow_id"):
            state.current_workflow_id = result.payload.get("workflow_id")
        if result.payload.get("workflow_type"):
            state.current_workflow_type = result.payload.get("workflow_type")
        if result.payload.get("target_state"):
            state.current_target_state = result.payload.get("target_state")
        if result.payload.get("runtime"):
            state.current_runtime = result.payload.get("runtime")
        refresh_snapshots(state, preferred_workflow=result.workflow_id)
        return
    append_timeline(state, "error", result.message or "Action failed.")
    state.status_message = "Action failed."
    refresh_snapshots(state, preferred_workflow=result.workflow_id)


def _handle_stream_event(state: AppState, event: dict[str, Any]) -> None:
    if event.get("workflow_id"):
        state.current_workflow_id = str(event.get("workflow_id"))
    if event.get("workflow_type"):
        state.current_workflow_type = str(event.get("workflow_type"))
    if event.get("target_state"):
        state.current_target_state = str(event.get("target_state"))
    if event.get("entry_state"):
        state.current_entry_state = str(event.get("entry_state"))
    if event.get("execution_plan"):
        state.current_execution_plan = [str(item) for item in event.get("execution_plan", [])]
    if event.get("runtime"):
        state.current_runtime = str(event.get("runtime"))
    if event.get("kind") == "runtime_fallback":
        state.current_runtime = str(event.get("to_runtime"))
        state.status_message = f"Fallback to {event.get('to_runtime')}"
    elif event.get("kind") == "workflow_routed":
        state.status_message = f"Routed to {event.get('workflow_type')} -> {event.get('target_state')}"
    elif event.get("kind") == "state_transition":
        state.status_message = f"{event.get('from_state')} -> {event.get('to_state')}"
    if event.get("kind") == "agent_output":
        summarized = _summarize_agent_output_for_tui(state, event)
        if summarized is None:
            return
        role, text = summarized
        append_timeline(state, role, text)
        return
    append_timeline(state, "agent", format_event_line(event))


def _submit_input(
    state: AppState,
    result_queue: queue.Queue[BackgroundTaskResult],
    stream_queue: queue.Queue[dict[str, Any]],
    request: str,
) -> None:
    trimmed = request.strip()
    if not trimmed:
        state.status_message = "Request cannot be empty."
        return
    if state.running_task is not None:
        state.status_message = f"Wait for current task to finish: {state.running_task}"
        return
    append_timeline(state, "you", trimmed)
    if trimmed.startswith("/bootstrap "):
        payload = trimmed[len("/bootstrap ") :].strip()
        state.status_message = "Bootstrap request submitted."
        _spawn_task(
            state,
            result_queue,
            label="bootstrap request",
            func=lambda value: execute_new_request(value, bootstrap_only=True),
            args=(payload,),
        )
        state.input_cursor = len(state.input_buffer)
        return
    if trimmed == "/inspect":
        state.overlay = "inspector"
        state.status_message = "Opened inspector."
        state.input_cursor = len(state.input_buffer)
        return
    if trimmed == "/workflows":
        state.overlay = "picker"
        state.overlay_index = state.selected_index
        state.status_message = "Opened workflow picker."
        state.input_cursor = len(state.input_buffer)
        return
    if trimmed == "/resume":
        selected = _selected_snapshot(state)
        if selected is None:
            state.status_message = "No workflow selected."
            return
        _spawn_task(
            state,
            result_queue,
            label=f"resume {selected.workflow_id}",
            func=lambda workflow: execute_resume(workflow, event_callback=stream_queue.put),
            args=(selected.workflow_id,),
            workflow_id=selected.workflow_id,
        )
        state.input_cursor = len(state.input_buffer)
        return
    if trimmed == "/dispatch":
        selected = _selected_snapshot(state)
        if selected is None:
            state.status_message = "No workflow selected."
            return
        _spawn_task(
            state,
            result_queue,
            label=f"dispatch {selected.workflow_id}",
            func=lambda workflow: execute_dispatch(workflow, dry_run=False, event_callback=stream_queue.put),
            args=(selected.workflow_id,),
            workflow_id=selected.workflow_id,
        )
        state.input_cursor = len(state.input_buffer)
        return
    if trimmed == "/dispatch-dry":
        selected = _selected_snapshot(state)
        if selected is None:
            state.status_message = "No workflow selected."
            return
        _spawn_task(
            state,
            result_queue,
            label=f"dispatch dry-run {selected.workflow_id}",
            func=lambda workflow: execute_dispatch(workflow, dry_run=True, event_callback=stream_queue.put),
            args=(selected.workflow_id,),
            workflow_id=selected.workflow_id,
        )
        state.input_cursor = len(state.input_buffer)
        return
    _spawn_task(
        state,
        result_queue,
        label="run request",
        func=lambda value: execute_new_request(value, event_callback=stream_queue.put),
        args=(trimmed,),
    )
    state.status_message = "Run request submitted."
    state.input_cursor = len(state.input_buffer)


def _handle_input_key(
    state: AppState,
    key: str | int,
    result_queue: queue.Queue[BackgroundTaskResult],
    stream_queue: queue.Queue[dict[str, Any]],
) -> bool:
    if key in {curses.KEY_ENTER, 10, 13, "\n"}:
        request = state.input_buffer
        state.input_buffer = ""
        state.input_cursor = 0
        _submit_input(state, result_queue, stream_queue, request)
        return True
    if key in {curses.KEY_LEFT}:
        state.input_cursor = max(0, state.input_cursor - 1)
        return True
    if key in {curses.KEY_RIGHT}:
        state.input_cursor = min(len(state.input_buffer), state.input_cursor + 1)
        return True
    if key in {curses.KEY_HOME}:
        state.input_cursor = 0
        return True
    if key in {curses.KEY_END}:
        state.input_cursor = len(state.input_buffer)
        return True
    if key in {curses.KEY_DC}:
        if state.input_cursor < len(state.input_buffer):
            state.input_buffer = state.input_buffer[: state.input_cursor] + state.input_buffer[state.input_cursor + 1 :]
        return True
    if key in {curses.KEY_BACKSPACE, 127, 8, "\b", "\x7f"}:
        if state.input_cursor > 0:
            state.input_buffer = (
                state.input_buffer[: state.input_cursor - 1] + state.input_buffer[state.input_cursor :]
            )
            state.input_cursor -= 1
        return True
    if key in {27, "\x1b"}:
        state.input_buffer = ""
        state.input_cursor = 0
        state.status_message = "Cleared input."
        return True
    if isinstance(key, str) and key.isprintable():
        state.input_buffer = state.input_buffer[: state.input_cursor] + key + state.input_buffer[state.input_cursor :]
        state.input_cursor += len(key)
        return True
    return False


def _handle_overlay_key(state: AppState, key: int) -> bool:
    if state.overlay is None:
        return False
    if key in {27, ord("q"), ord("i"), ord("w")}:
        state.overlay = None
        state.status_message = "Closed overlay."
        return True
    if state.overlay == "picker":
        if key in {curses.KEY_UP, ord("k")} and state.snapshots:
            state.overlay_index = max(0, state.overlay_index - 1)
            return True
        if key in {curses.KEY_DOWN, ord("j")} and state.snapshots:
            state.overlay_index = min(len(state.snapshots) - 1, state.overlay_index + 1)
            return True
        if key in {curses.KEY_ENTER, 10, 13} and state.snapshots:
            state.selected_index = state.overlay_index
            state.overlay = None
            state.status_message = f"Selected {state.snapshots[state.selected_index].workflow_id}"
            return True
        return True
    return True


def launch(initial_workflow: str | None = None) -> int:
    def _run(stdscr: Any) -> int:
        curses.curs_set(0)
        stdscr.keypad(True)
        stdscr.timeout(200)
        state = AppState()
        result_queue: queue.Queue[BackgroundTaskResult] = queue.Queue()
        stream_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        refresh_snapshots(state, preferred_workflow=initial_workflow)
        if state.snapshots:
            append_timeline(state, "system", f"selected workflow {state.snapshots[state.selected_index].workflow_id}")

        while True:
            try:
                while True:
                    _handle_stream_event(state, stream_queue.get_nowait())
            except queue.Empty:
                pass
            try:
                while True:
                    _handle_task_result(state, result_queue.get_nowait())
            except queue.Empty:
                pass

            _draw_ui(stdscr, state)
            try:
                key = stdscr.get_wch()
            except KeyboardInterrupt:
                return 130
            except curses.error:
                continue
            if _handle_overlay_key(state, key):
                continue
            if _handle_input_key(state, key, result_queue, stream_queue):
                continue
            if key in {ord("q"), 27}:
                return 0
            if key == ord("r"):
                refresh_snapshots(state, preferred_workflow=_selected_snapshot(state).workflow_id if _selected_snapshot(state) else None)
                state.status_message = f"Refreshed {len(state.snapshots)} workflow(s)."
                append_timeline(state, "system", state.status_message)
                continue
            if key == ord("w"):
                state.overlay = "picker"
                state.overlay_index = state.selected_index
                continue
            if key == ord("i"):
                state.overlay = "inspector"
                continue

            selected = _selected_snapshot(state)
            if key == ord("u"):
                if selected is None:
                    state.status_message = "No workflow selected."
                    continue
                append_timeline(state, "you", f"resume {selected.workflow_id}")
                _spawn_task(
                    state,
                    result_queue,
                    label=f"resume {selected.workflow_id}",
                    func=lambda workflow: execute_resume(workflow, event_callback=stream_queue.put),
                    args=(selected.workflow_id,),
                    workflow_id=selected.workflow_id,
                )
                continue
            if key == ord("d"):
                if selected is None:
                    state.status_message = "No workflow selected."
                    continue
                append_timeline(state, "you", f"dispatch dry-run {selected.workflow_id}")
                _spawn_task(
                    state,
                    result_queue,
                    label=f"dispatch dry-run {selected.workflow_id}",
                    func=lambda workflow: execute_dispatch(workflow, dry_run=True, event_callback=stream_queue.put),
                    args=(selected.workflow_id,),
                    workflow_id=selected.workflow_id,
                )
                continue
            if key == ord("x"):
                if selected is None:
                    state.status_message = "No workflow selected."
                    continue
                append_timeline(state, "you", f"dispatch {selected.workflow_id}")
                _spawn_task(
                    state,
                    result_queue,
                    label=f"dispatch {selected.workflow_id}",
                    func=lambda workflow: execute_dispatch(workflow, dry_run=False, event_callback=stream_queue.put),
                    args=(selected.workflow_id,),
                    workflow_id=selected.workflow_id,
                )
                continue
            state.status_message = "Keys: n run, b bootstrap, u resume, d dry-dispatch, x dispatch, w workflows, i inspect, r refresh, q quit."
        return 0

    return curses.wrapper(_run)
