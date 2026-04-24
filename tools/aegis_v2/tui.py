from __future__ import annotations

import os
import select
import sys
import termios
import threading
import time
import tty
from dataclasses import dataclass, field
from typing import Any

from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn
from rich.table import Table
from rich.text import Text

from .executor import MultiModelExecutor
from .registry import ModelRegistry
from .router import TaskRouter
from .session import SessionStore
from .types import ModelHealth, SessionRecord


FINAL_STATUSES = {"completed", "failed", "cancelled"}


@dataclass(slots=True)
class TuiState:
    view: str = "dashboard"
    selected_index: int = 0
    selected_session_id: str | None = None
    show_help: bool = False
    last_action: str = ""
    input_buffer: str = ""
    model_health: dict[str, ModelHealth] = field(default_factory=dict)
    model_health_checked_at: float = 0.0
    health_ttl_seconds: float = 10.0

    def selected_session(self, sessions: list[SessionRecord]) -> SessionRecord | None:
        if not sessions:
            self.selected_index = 0
            self.selected_session_id = None
            return None
        self.selected_index = max(0, min(self.selected_index, len(sessions) - 1))
        selected = sessions[self.selected_index]
        self.selected_session_id = selected.session_id
        return selected


def _status_style(status: str) -> str:
    if status in {"completed", "passed", "APPROVED", "LGTM"}:
        return "green"
    if status in {"failed", "error", "BLOCKED", "FAILED"}:
        return "red"
    if status in {"running", "revise", "REVISE"}:
        return "yellow"
    return "dim"


def _status_icon(status: str) -> str:
    if status in {"completed", "passed", "APPROVED", "LGTM"}:
        return "✓"
    if status in {"failed", "error", "BLOCKED", "FAILED"}:
        return "✗"
    if status in {"running", "revise", "REVISE"}:
        return "◌"
    return "○"


def _truncate(value: str, width: int) -> str:
    if len(value) <= width:
        return value
    return value[: width - 1] + "…"


def _health_for_model(registry: ModelRegistry, model_name: str, state: TuiState | None = None) -> ModelHealth:
    if state is None:
        return registry.check_model(model_name)
    now = time.monotonic()
    cached = state.model_health.get(model_name)
    if cached is not None and now - state.model_health_checked_at < state.health_ttl_seconds:
        return cached
    health = registry.check_model(model_name)
    state.model_health[model_name] = health
    state.model_health_checked_at = now
    return health


def _session_progress(session: SessionRecord) -> tuple[int, int, int]:
    execution = session.metadata.get("execution", {})
    stage_results = execution.get("stage_results", [])
    plan_steps = session.metadata.get("execution_plan", {}).get("steps", [])
    total = len(plan_steps)
    done = min(len(stage_results), total) if total else len(stage_results)
    percent = int((done / total) * 100) if total else (100 if session.status in FINAL_STATUSES else 0)
    return done, total, percent


def _footer(*, view: str, state: TuiState | None = None) -> Text:
    if view == "dashboard":
        hint = "直接输入任务  Enter 提交/查看  ↑/↓ 选择  /models 模型  /simulate 模拟执行  /execute 真实执行  ? 帮助  q 退出"
    elif view == "watch":
        hint = "b 返回主面板  m 消息  c 检查点  r 刷新  ? 帮助  q 退出"
    elif view == "messages":
        hint = "b 返回运行详情  r 刷新  ? 帮助  q 退出"
    elif view == "checkpoints":
        hint = "b 返回运行详情  r 刷新  ? 帮助  q 退出"
    elif view == "models":
        hint = "b 返回主面板  r 刷新模型状态  ? 帮助  q 退出"
    else:
        hint = "q 退出"
    if state and state.last_action:
        hint = f"{hint}    {state.last_action}"
    return Text(hint, style="dim")


def _help_panel() -> Panel:
    body = Table.grid(padding=(0, 2))
    body.add_column(style="bold")
    body.add_column()
    body.add_row("直接输入", "在主面板输入一个新任务")
    body.add_row("Enter", "输入框非空时提交任务；为空时打开选中的会话")
    body.add_row("↑/↓ 或 j/k", "移动会话选择")
    body.add_row("/models", "打开模型状态页")
    body.add_row("/simulate", "后台模拟执行任务")
    body.add_row("/execute", "后台真实调用 runtime 执行任务")
    body.add_row("/pair /swarm /pipeline /moa", "强制指定协作策略")
    body.add_row("b", "返回上一级视图")
    body.add_row("m", "运行详情页打开消息")
    body.add_row("c", "运行详情页打开检查点")
    body.add_row("r", "刷新并清空模型状态缓存")
    body.add_row("q", "退出")
    return Panel(body, title="快捷键", box=box.ROUNDED, border_style="white")


def _input_panel(state: TuiState | None) -> Panel:
    value = state.input_buffer if state else ""
    prompt = Text()
    prompt.append("任务 > ", style="bold cyan")
    prompt.append(
        (value + "▌") if value else "输入任务，或使用 /models、/simulate、/execute、/pair、/swarm、/pipeline、/moa",
        style="white" if value else "dim",
    )
    return Panel(prompt, title="主输入框", box=box.ROUNDED, border_style="green")


def render_dashboard(store: SessionStore, registry: ModelRegistry, state: TuiState | None = None) -> Any:
    sessions = store.list_sessions(limit=10)
    cost = store.cost_summary()
    selected = state.selected_session(sessions) if state else None

    # Header panel
    header_text = Text()
    header_text.append("AEGIS v2 ", style="bold cyan")
    header_text.append(f"{store.paths.workspace_root.name}", style="dim")

    header_info = Table.grid(padding=(0, 2))
    header_info.add_column()
    header_info.add_column()
    header_info.add_row(
        Text(f"会话: {cost['session_count']}"),
        Text(f"预估成本: ${cost['estimated_total']:.2f}"),
    )
    header_info.add_row(
        Text(f"实际成本: ${cost['actual_total']:.2f}"),
        Text(f"预算: ${cost.get('budget', {}).get('daily_budget', 'N/A')}/day"),
    )

    header = Panel(
        Group(header_text, header_info),
        box=box.ROUNDED,
        border_style="cyan",
    )

    # Session list table
    session_table = Table(
        box=box.SIMPLE_HEAVY,
        expand=True,
        show_header=True,
        header_style="bold",
    )
    session_table.add_column("会话", width=22, no_wrap=True)
    session_table.add_column("任务", min_width=20, overflow="fold")
    session_table.add_column("策略", width=10)
    session_table.add_column("进度", width=10, justify="right")
    session_table.add_column("状态", width=10)
    session_table.add_column("成本", width=10, justify="right")

    for session in sessions:
        status_style = _status_style(session.status)
        est = float(session.metadata.get("estimated_cost", 0) or 0)
        actual = float(session.metadata.get("actual_cost", 0) or 0)
        cost_str = f"${actual:.4f}" if actual > 0 else f"${est:.2f}"
        done, total, percent = _session_progress(session)
        progress = f"{done}/{total}" if total else f"{percent}%"
        is_selected = selected is not None and session.session_id == selected.session_id
        row_style = "reverse" if is_selected else None
        session_table.add_row(
            Text(("> " if is_selected else "  ") + session.session_id, style=row_style),
            _truncate(session.request, 32),
            session.strategy,
            progress,
            Text(session.status, style=status_style),
            cost_str,
            style=row_style,
        )

    sessions_panel = Panel(
        session_table,
        title="最近会话",
        box=box.ROUNDED,
        border_style="blue",
    )

    grid = Table.grid(expand=True)
    grid.add_column(ratio=1)
    grid.add_row(header)
    grid.add_row(sessions_panel)
    grid.add_row(_input_panel(state))
    if state and state.show_help:
        grid.add_row(_help_panel())
    grid.add_row(_footer(view="dashboard", state=state))

    return grid


def render_watch(store: SessionStore, session_id: str, state: TuiState | None = None) -> Any:
    try:
        session = store.get_session(session_id)
    except KeyError:
        return Panel(
            Text(f"Session not found: {session_id}", style="red"),
            box=box.ROUNDED,
            border_style="red",
        )

    checkpoints = store.list_checkpoints(session_id)
    messages = store.list_messages(session_id)

    # Parse execution data from metadata
    execution = session.metadata.get("execution", {})
    stage_results = execution.get("stage_results", [])
    plan_steps = session.metadata.get("execution_plan", {}).get("steps", [])
    iterations = execution.get("iterations")

    # Calculate progress
    total_stages = len(plan_steps) if plan_steps else 1
    completed_stages = len(stage_results)
    percent = int((completed_stages / total_stages) * 100) if total_stages else 0

    # Header
    status_icon = _status_icon(session.status)
    status_style = _status_style(session.status)
    header_text = Text()
    header_text.append("AEGIS v2 ", style="bold cyan")
    header_text.append(f"· {session.session_id} · ", style="dim")
    header_text.append(f"{session.strategy} · ", style="dim")
    header_text.append(f"{status_icon} {session.status}", style=status_style)

    est_cost = float(session.metadata.get("estimated_cost", 0) or 0)
    actual_cost = float(session.metadata.get("actual_cost", 0) or 0)
    est_time = int(session.metadata.get("estimated_time_seconds", 0) or 0)
    actual_time_ms = sum(s.get("duration_ms", 0) for s in stage_results)
    actual_time_s = actual_time_ms / 1000

    info_table = Table.grid(padding=(0, 2))
    info_table.add_column()
    info_table.add_column()
    info_table.add_row(
        Text(f"Request: {_truncate(session.request, 40)}"),
        Text(f"Task: {session.task_type}"),
    )
    info_table.add_row(
        Text(f"模型: {', '.join(session.models)}"),
        Text(f"模式: {session.mode}"),
    )

    cost_line = f"${est_cost:.2f} (est)"
    if actual_cost > 0:
        cost_line += f"  →  ${actual_cost:.4f} (actual)"
    time_line = f"{est_time}s (est)"
    if actual_time_s > 0:
        time_line += f"  →  {actual_time_s:.1f}s (actual)"
    info_table.add_row(Text(cost_line), Text(time_line))

    progress = Progress(
        TextColumn("[bold]Progress[/bold]"),
        BarColumn(bar_width=28),
        TextColumn(f"{percent}%  ({completed_stages}/{total_stages} stages)"),
        expand=True,
    )
    progress.add_task("run", total=max(total_stages, 1), completed=completed_stages)

    header = Panel(
        Group(header_text, info_table, progress),
        box=box.ROUNDED,
        border_style="cyan",
    )

    # Stages table
    stage_table = Table(
        box=box.SIMPLE_HEAVY,
        expand=True,
        show_header=True,
        header_style="bold",
    )
    stage_table.add_column("", width=2)
    stage_table.add_column("阶段", min_width=12)
    stage_table.add_column("模型", min_width=14)
    stage_table.add_column("类型", width=10)
    stage_table.add_column("耗时", width=8, justify="right")
    stage_table.add_column("成本", width=10, justify="right")
    stage_table.add_column("状态", width=10)

    stage_lookup = {s.get("stage_name", ""): s for s in stage_results}
    for step in plan_steps:
        name = step.get("name", "")
        sr = stage_lookup.get(name, {})
        if sr:
            icon = _status_icon("completed" if sr.get("exit_code", 1) == 0 else "failed")
            status = "done" if sr.get("exit_code", 1) == 0 else "FAILED"
            style = _status_style(status)
            duration = f"{sr.get('duration_ms', 0)}ms"
            cost = f"${sr.get('approximate_cost', 0):.4f}" if sr.get("approximate_cost") else "--"
        else:
            icon = "○"
            status = "queued"
            style = "dim"
            duration = "--"
            cost = "--"

        stage_table.add_row(
            icon,
            name,
            step.get("model", ""),
            step.get("kind", ""),
            duration,
            cost,
            Text(status, style=style),
        )

    stages_panel = Panel(
        stage_table,
        title="阶段",
        box=box.ROUNDED,
        border_style="blue",
    )

    # Iterations info for pair/moa
    panels = [header, stages_panel]
    if iterations is not None:
        panels.append(
            Panel(
                Text(f"迭代次数: {iterations}", style="yellow"),
                box=box.ROUNDED,
                border_style="yellow",
            )
        )

    panels.append(
        Panel(
            Text(
                f"检查点: {len(checkpoints)}  消息: {len(messages)}  "
                f"最后阶段: {session.metadata.get('last_stage', 'n/a')}",
                style="dim",
            ),
            title="运行状态",
            box=box.ROUNDED,
            border_style="cyan",
        )
    )

    # Messages panel (last 10)
    if messages:
        msg_lines: list[Any] = []
        for msg in messages[-10:]:
            stamp = msg.created_at[11:16] if len(msg.created_at) > 16 else "--:--"
            channel_style = {
                "lifecycle": "cyan",
                "reviews": "yellow",
                "stages": "green",
                "errors": "red",
                "context": "dim",
            }.get(msg.channel, "white")
            line = Text()
            line.append(f"{stamp}  ", style="dim")
            line.append(f"[{msg.channel}] ", style=channel_style)
            line.append(f"{msg.sender}", style="bold")
            if msg.recipient:
                line.append(f" → {msg.recipient}", style="dim")
            line.append(f": {_truncate(msg.content, 60)}")
            msg_lines.append(line)

        messages_panel = Panel(
            Group(*msg_lines),
            title="消息",
            box=box.ROUNDED,
            border_style="white",
        )
        panels.append(messages_panel)

    # Error display
    if session.status == "failed":
        error = session.metadata.get("error", "Unknown error")
        failed = _failure_diagnostics(stage_results, messages, session.metadata)
        panels.append(
            Panel(
                Group(Text(error, style="red"), failed),
                title="错误",
                box=box.ROUNDED,
                border_style="red",
            )
        )

    # Footer
    if state and state.show_help:
        panels.append(_help_panel())
    panels.append(_footer(view="watch", state=state))

    grid = Table.grid(expand=True)
    grid.add_column(ratio=1)
    for panel in panels:
        grid.add_row(panel)

    return grid


def _failure_diagnostics(stage_results: list[dict[str, Any]], messages: list[Any], metadata: dict[str, Any]) -> Any:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    failed_stage = next((stage for stage in reversed(stage_results) if int(stage.get("exit_code", 0) or 0) != 0), None)
    if failed_stage:
        table.add_row("阶段", str(failed_stage.get("stage_name", "unknown")))
        table.add_row("模型", str(failed_stage.get("model", "unknown")))
        table.add_row("退出码", str(failed_stage.get("exit_code", "unknown")))
        log_path = failed_stage.get("metadata", {}).get("log_path") or failed_stage.get("log_path")
        if log_path:
            table.add_row("日志", str(log_path))
    elif messages:
        table.add_row("最后消息", _truncate(messages[-1].content, 80))
    if metadata.get("recovery_hint"):
        table.add_row("恢复", str(metadata["recovery_hint"]))
    else:
        table.add_row("恢复", "aegis session recover <session_id> --simulate")
    return table


def render_messages(store: SessionStore, session_id: str, state: TuiState | None = None) -> Any:
    try:
        session = store.get_session(session_id)
    except KeyError:
        return Panel(Text(f"Session not found: {session_id}", style="red"), box=box.ROUNDED, border_style="red")
    messages = store.list_messages(session_id)
    table = Table(box=box.SIMPLE_HEAVY, expand=True, show_header=True, header_style="bold")
    table.add_column("时间", width=6)
    table.add_column("频道", width=12)
    table.add_column("发送者", width=18)
    table.add_column("类型", width=14)
    table.add_column("内容", overflow="fold")
    for msg in messages[-30:]:
        stamp = msg.created_at[11:16] if len(msg.created_at) > 16 else "--:--"
        table.add_row(stamp, msg.channel, msg.sender, msg.message_type, _truncate(msg.content.replace("\n", " "), 120))
    if not messages:
        table.add_row("--:--", "-", "-", "-", "暂无消息。")
    grid = Table.grid(expand=True)
    grid.add_column(ratio=1)
    grid.add_row(Panel(Text(f"{session.session_id} · {session.status}", style="bold cyan"), box=box.ROUNDED, border_style="cyan"))
    grid.add_row(Panel(table, title="消息", box=box.ROUNDED, border_style="white"))
    if state and state.show_help:
        grid.add_row(_help_panel())
    grid.add_row(_footer(view="messages", state=state))
    return grid


def render_checkpoints(store: SessionStore, session_id: str, state: TuiState | None = None) -> Any:
    try:
        session = store.get_session(session_id)
    except KeyError:
        return Panel(Text(f"Session not found: {session_id}", style="red"), box=box.ROUNDED, border_style="red")
    checkpoints = store.list_checkpoints(session_id)
    table = Table(box=box.SIMPLE_HEAVY, expand=True, show_header=True, header_style="bold")
    table.add_column("时间", width=6)
    table.add_column("阶段", width=18)
    table.add_column("载荷", overflow="fold")
    for checkpoint in checkpoints[-30:]:
        stamp = checkpoint["created_at"][11:16] if len(checkpoint["created_at"]) > 16 else "--:--"
        payload = _truncate(str(checkpoint["payload"]).replace("\n", " "), 120)
        table.add_row(stamp, checkpoint["stage"], payload)
    if not checkpoints:
        table.add_row("--:--", "-", "暂无检查点。")
    grid = Table.grid(expand=True)
    grid.add_column(ratio=1)
    grid.add_row(Panel(Text(f"{session.session_id} · {session.status}", style="bold cyan"), box=box.ROUNDED, border_style="cyan"))
    grid.add_row(Panel(table, title="检查点", box=box.ROUNDED, border_style="cyan"))
    if state and state.show_help:
        grid.add_row(_help_panel())
    grid.add_row(_footer(view="checkpoints", state=state))
    return grid


def render_models(registry: ModelRegistry, state: TuiState | None = None) -> Any:
    table = Table(box=box.SIMPLE_HEAVY, expand=True, show_header=True, header_style="bold")
    table.add_column("模型", min_width=20)
    table.add_column("供应商", width=12)
    table.add_column("运行时", width=16)
    table.add_column("状态", width=12)
    table.add_column("详情", overflow="fold")
    for model in registry.list_models():
        health = _health_for_model(registry, model.name, state)
        table.add_row(
            model.name,
            model.provider,
            model.runtime,
            Text("可用" if health.available else "不可用", style="green" if health.available else "red"),
            health.details,
        )
    grid = Table.grid(expand=True)
    grid.add_column(ratio=1)
    grid.add_row(Panel(Text("AEGIS v2 模型", style="bold cyan"), box=box.ROUNDED, border_style="cyan"))
    grid.add_row(Panel(table, title="模型状态", box=box.ROUNDED, border_style="magenta"))
    if state and state.show_help:
        grid.add_row(_help_panel())
    grid.add_row(_footer(view="models", state=state))
    return grid


def _read_key(timeout: float) -> str | None:
    readable, _, _ = select.select([sys.stdin], [], [], timeout)
    if not readable:
        return None
    char = sys.stdin.read(1)
    if char == "\x1b":
        tail = sys.stdin.read(2)
        if tail == "[A":
            return "up"
        if tail == "[B":
            return "down"
        return "escape"
    if char in {"\r", "\n"}:
        return "enter"
    if char == "\x03":
        raise KeyboardInterrupt
    return char


def _render_current(store: SessionStore, registry: ModelRegistry, state: TuiState) -> Any:
    if state.view == "watch" and state.selected_session_id:
        return render_watch(store, state.selected_session_id, state)
    if state.view == "messages" and state.selected_session_id:
        return render_messages(store, state.selected_session_id, state)
    if state.view == "checkpoints" and state.selected_session_id:
        return render_checkpoints(store, state.selected_session_id, state)
    if state.view == "models":
        return render_models(registry, state)
    state.view = "dashboard"
    return render_dashboard(store, registry, state)


def _parse_input(raw: str) -> tuple[str, dict[str, Any]]:
    text = raw.strip()
    context: dict[str, Any] = {}
    command_map = {
        "/simulate": {"execute": True, "simulate": True},
        "/execute": {"execute": True},
        "/plan": {},
        "/pair": {"strategy": "pair"},
        "/swarm": {"strategy": "swarm"},
        "/pipeline": {"strategy": "pipeline"},
        "/moa": {"strategy": "moa"},
    }
    for prefix, payload in command_map.items():
        if text == prefix:
            return "", {}
        if text.startswith(prefix + " "):
            context.update(payload)
            return text[len(prefix) :].strip(), context
    return text, context


def _submit_input(store: SessionStore, registry: ModelRegistry, state: TuiState) -> None:
    raw = state.input_buffer.strip()
    state.input_buffer = ""
    if raw in {"/models", "/model"}:
        state.view = "models"
        return
    if raw in {"/help", "help"}:
        state.show_help = True
        return
    request, context = _parse_input(raw)
    if not request:
        state.last_action = "empty task"
        return

    def run() -> None:
        try:
            executor = MultiModelExecutor(registry, TaskRouter(registry), store)
            result = executor.run(request, context)
            sessions = store.list_sessions(limit=20)
            for index, session in enumerate(sessions):
                if session.session_id == result.session.session_id:
                    state.selected_index = index
                    state.selected_session_id = session.session_id
                    break
            state.view = "watch"
            mode = "executed" if result.executed else "planned"
            state.last_action = f"{mode} {result.session.session_id}"
        except Exception as exc:
            state.last_action = f"error: {_truncate(str(exc), 80)}"

    if context.get("execute"):
        state.last_action = "running task in background"
        threading.Thread(target=run, daemon=True).start()
    else:
        run()


def _handle_key(key: str | None, store: SessionStore, registry: ModelRegistry, state: TuiState) -> bool:
    if key is None:
        return True
    sessions = store.list_sessions(limit=20)
    if key == "?":
        state.show_help = not state.show_help
        return True
    if state.view == "dashboard":
        if key in {"\x7f", "\b"}:
            state.input_buffer = state.input_buffer[:-1]
            return True
        if len(key) == 1 and key.isprintable() and not (not state.input_buffer and key in {"q", "Q", "?"}):
            state.input_buffer += key
            return True
        if key in {"q", "Q"} and not state.input_buffer:
            return False
        if key in {"up", "k"}:
            state.selected_index = max(0, state.selected_index - 1)
            state.selected_session(sessions)
        elif key in {"down", "j"}:
            state.selected_index = min(max(len(sessions) - 1, 0), state.selected_index + 1)
            state.selected_session(sessions)
        elif key == "enter":
            if state.input_buffer.strip():
                _submit_input(store, registry, state)
            else:
                selected = state.selected_session(sessions)
                if selected:
                    state.view = "watch"
                    state.last_action = f"watching {selected.session_id}"
                else:
                    state.last_action = "type a task to start"
        return True
    if key in {"r", "R"}:
        state.model_health.clear()
        state.model_health_checked_at = 0.0
        state.last_action = "refreshed"
        return True
    if key in {"q", "Q"}:
        return False
    if state.view == "watch":
        if key in {"b", "B"}:
            state.view = "dashboard"
        elif key in {"m", "M"}:
            state.view = "messages"
        elif key in {"c", "C"}:
            state.view = "checkpoints"
        return True
    if state.view in {"messages", "checkpoints"}:
        if key in {"b", "B", "enter"}:
            state.view = "watch"
        return True
    if state.view == "models":
        if key in {"b", "B", "enter"}:
            state.view = "dashboard"
        return True
    return True


def _run_tui(
    store: SessionStore,
    registry: ModelRegistry,
    state: TuiState,
    *,
    interval: float,
) -> None:
    console = Console()
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        console.print(_render_current(store, registry, state))
        return

    old_settings = termios.tcgetattr(sys.stdin)
    try:
        tty.setcbreak(sys.stdin.fileno())
        with Live(
            _render_current(store, registry, state),
            console=console,
            refresh_per_second=max(1, int(1 / interval)),
            screen=True,
        ) as live:
            running = True
            while running:
                key = _read_key(interval)
                running = _handle_key(key, store, registry, state)
                live.update(_render_current(store, registry, state))
    except KeyboardInterrupt:
        return
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)


def run_dashboard(
    store: SessionStore,
    registry: ModelRegistry,
    *,
    interval: float = 1.0,
) -> None:
    _run_tui(store, registry, TuiState(view="dashboard"), interval=interval)


def run_watch(
    store: SessionStore,
    session_id: str,
    *,
    interval: float = 1.0,
) -> None:
    state = TuiState(view="watch", selected_session_id=session_id)
    _run_tui(store, ModelRegistry.from_workspace(store.paths), state, interval=interval)
