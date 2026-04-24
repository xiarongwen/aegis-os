from __future__ import annotations

import sys
import time
from typing import Any

from .session import SessionStore
from .types import RunEvent, SessionRecord

try:
    from rich import box
    from rich.align import Align
    from rich.console import Group
    from rich.live import Live
    from rich.panel import Panel
    from rich.progress import BarColumn, Progress, TextColumn
    from rich.table import Table
    from rich.text import Text

    RICH_AVAILABLE = True
except Exception:
    RICH_AVAILABLE = False


def _bar(completed: int, total: int, width: int = 18) -> str:
    if total <= 0:
        return "░" * width
    filled = int(width * completed / total)
    return "█" * filled + "░" * (width - filled)


def _snapshot(store: SessionStore, session: SessionRecord) -> dict[str, Any]:
    events = store.events(session.session_id)
    steps = session.plan_json.get("steps", [])
    completed_stages = {
        event.stage_name
        for event in events
        if event.event_type == "stage_result" and event.status == "completed" and event.stage_name
    }
    total = len(steps)
    done = len(completed_stages)
    return {
        "events": events,
        "steps": steps,
        "done": done,
        "total": total,
        "percent": int((done / total) * 100) if total else 0,
        "dispatch": len([event for event in events if event.event_type == "stage_start"]),
        "reviews": len([event for event in events if event.role == "reviewer"]),
        "latest_by_stage": {event.stage_name: event for event in events if event.stage_name},
    }


def render_cockpit(store: SessionStore, session: SessionRecord) -> str:
    snap = _snapshot(store, session)
    events = snap["events"]
    steps = snap["steps"]
    total = snap["total"]
    done = snap["done"]
    percent = snap["percent"]
    dispatch = snap["dispatch"]
    reviews = snap["reviews"]
    lines = [
        f"┌─ AEGIS AUTOPILOT  {store.paths.workspace_root.name} / {session.session_id} ─────────────────────────",
        f"│ {_bar(done, total)}  {percent}%   {session.status}",
        f"│ {done}/{total} stages   dispatch x{dispatch}   review x{reviews}",
        "└────────────────────────────────────────────────────────────────────────",
        "",
        "┌─ 任务进展 ─────────────────────────────────────────────────────────────",
    ]
    latest_by_stage = snap["latest_by_stage"]
    for step in steps:
        stage = step["name"]
        event = latest_by_stage.get(stage)
        status = event.status if event and event.status else step.get("status", "queued")
        summary = event.summary if event else "waiting"
        lines.append(
            f"│ {stage:<3} {status:<9} {step['kind']:<10} {step['role']:<12} {step['model']:<18} {summary[:40]}"
        )
    lines.extend(
        [
            "└────────────────────────────────────────────────────────────────────────",
            "",
            *_render_capabilities(events),
            "",
            *_render_verification(events),
            "",
            *_render_council(events),
            "",
            *_render_evolution(events),
            "",
            *_render_personas(session, events),
            "",
            *_render_data_layer(store, session, events),
            "",
            *_render_principles(events),
            "",
            "┌─ 动态 ─────────────────────────────────────────────────────────────────",
        ]
    )
    for event in events[-12:]:
        stamp = event.created_at[11:16] if event.created_at else "--:--"
        lines.append(f"│ {stamp} {event.event_type:<15} {event.summary[:78]}")
    lines.append("└────────────────────────────────────────────────────────────────────────")
    return "\n".join(lines)


def render_rich_cockpit(store: SessionStore, session: SessionRecord) -> Any:
    if not RICH_AVAILABLE:
        return render_cockpit(store, session)
    snap = _snapshot(store, session)
    events: list[RunEvent] = snap["events"]
    steps = snap["steps"]

    progress = Progress(
        TextColumn("[bold]Progress[/bold]"),
        BarColumn(bar_width=28),
        TextColumn(f"{snap['percent']}%  {session.status}"),
        expand=True,
    )
    progress.add_task("run", total=max(snap["total"], 1), completed=snap["done"])
    header = Panel(
        Group(
            Text(f"AEGIS AUTOPILOT  {store.paths.workspace_root.name} / {session.session_id}", style="bold cyan"),
            progress,
            Text(
                f"{snap['done']}/{snap['total']} stages   dispatch x{snap['dispatch']}   review x{snap['reviews']}",
                style="dim",
            ),
        ),
        box=box.ROUNDED,
        border_style="cyan",
    )

    task_table = Table(box=box.SIMPLE_HEAVY, expand=True, show_header=True, header_style="bold")
    for column in ("Stage", "Status", "Kind", "Role", "Model", "Summary"):
        task_table.add_column(column, overflow="fold")
    latest_by_stage = snap["latest_by_stage"]
    for step in steps:
        event = latest_by_stage.get(step["name"])
        status = event.status if event and event.status else step.get("status", "queued")
        style = "green" if status in {"completed", "passed"} else "yellow" if status in {"running", "revise"} else "dim"
        task_table.add_row(
            step["name"],
            Text(str(status), style=style),
            step["kind"],
            step["role"],
            step["model"],
            (event.summary if event else "waiting")[:52],
        )
    tasks = Panel(task_table, title="任务进展", box=box.ROUNDED, border_style="blue")

    grid = Table.grid(expand=True)
    grid.add_column(ratio=1)
    grid.add_column(ratio=1)
    grid.add_row(
        Panel(_rich_capabilities(events), title="八大底层能力", box=box.ROUNDED, border_style="magenta"),
        Panel(_rich_verification(events), title="双向共验证", box=box.ROUNDED, border_style="green"),
    )
    grid.add_row(
        Panel(_rich_council(events), title="方圆会议", box=box.ROUNDED, border_style="yellow"),
        Panel(_rich_evolution(events), title="自动复盘", box=box.ROUNDED, border_style="cyan"),
    )
    grid.add_row(
        Panel(_rich_personas(session, events), title="七业大师协同在场", box=box.ROUNDED, border_style="blue"),
        Panel(_rich_data_layer(store, session, events), title="三层一致的共识层", box=box.ROUNDED, border_style="magenta"),
    )
    grid.add_row(
        Panel(_rich_principles(events), title="十二铁律", box=box.ROUNDED, border_style="red"),
        Panel(_rich_activity(events), title="动态", box=box.ROUNDED, border_style="white"),
    )
    return Group(header, tasks, grid)


def _latest(events: list[RunEvent], event_type: str) -> RunEvent | None:
    matches = [event for event in events if event.event_type == event_type]
    return matches[-1] if matches else None


def _render_capabilities(events: list[RunEvent]) -> list[str]:
    reviews = len([event for event in events if event.event_type == "review_feedback"])
    verify = len([event for event in events if event.event_type == "verification"])
    retry = len([event for event in events if event.event_type == "retry"])
    return [
        "┌─ 八大底层能力 ─────────────────────────────────────────────────────────",
        f"│ 01 多Agent执行   02 角色计划   03 八段流水线   04 审查返修 x{retry}",
        f"│ 05 Session Resume   06 实时事件   07 安全降级   08 验证闭环 x{verify} / review x{reviews}",
        "└────────────────────────────────────────────────────────────────────────",
    ]


def _render_verification(events: list[RunEvent]) -> list[str]:
    verification = _latest(events, "verification")
    status = verification.status if verification else "waiting"
    detail = verification.detail if verification else "waiting for verification stage"
    return [
        "┌─ 双向共验证 ───────────────────────────────────────────────────────────",
        f"│ Backend 自问自检: {status:<10}  Forward 合问实证: {status:<10}",
        f"│ {detail[:86]}",
        "└────────────────────────────────────────────────────────────────────────",
    ]


def _render_council(events: list[RunEvent]) -> list[str]:
    council = _latest(events, "council")
    if not council:
        return [
            "┌─ 方圆会议 ─────────────────────────────────────────────────────────────",
            "│ waiting",
            "└────────────────────────────────────────────────────────────────────────",
        ]
    participants = ", ".join(council.metadata.get("participants", []))
    return [
        "┌─ 方圆会议 ─────────────────────────────────────────────────────────────",
        f"│ {council.status or 'recorded'}  participants: {participants}",
        f"│ {council.detail[:86]}",
        "└────────────────────────────────────────────────────────────────────────",
    ]


def _render_evolution(events: list[RunEvent]) -> list[str]:
    evolution = _latest(events, "evolution")
    if not evolution:
        return [
            "┌─ 自动复盘 ─────────────────────────────────────────────────────────────",
            "│ waiting for post-run review",
            "└────────────────────────────────────────────────────────────────────────",
        ]
    signals = ", ".join(evolution.metadata.get("signals", []))
    return [
        "┌─ 自动复盘 ─────────────────────────────────────────────────────────────",
        f"│ {evolution.status or 'recorded'}  signals: {signals}",
        f"│ {evolution.metadata.get('recommendation', '')[:86]}",
        "└────────────────────────────────────────────────────────────────────────",
    ]


def _render_personas(session: SessionRecord, events: list[RunEvent]) -> list[str]:
    persona = _latest(events, "persona")
    roles = persona.metadata.get("roles", []) if persona else session.plan_json.get("roles", [])
    chips = []
    for role in roles[:8]:
        chips.append(f"{role.get('name', '?')}:{role.get('default_model', '?')}")
    return [
        "┌─ 七业大师协同在场 ─────────────────────────────────────────────────────",
        f"│ {'  '.join(chips)[:96] if chips else 'waiting'}",
        "└────────────────────────────────────────────────────────────────────────",
    ]


def _render_data_layer(store: SessionStore, session: SessionRecord, events: list[RunEvent]) -> list[str]:
    run_dir = store.paths.runs_dir / session.session_id
    return [
        "┌─ 三层一致的共识层 ─────────────────────────────────────────────────────",
        f"│ sqlite: {store.paths.session_db_path.name}   events: {len(events)}",
        f"│ artifacts: {run_dir}",
        "└────────────────────────────────────────────────────────────────────────",
    ]


def _render_principles(events: list[RunEvent]) -> list[str]:
    policy = _latest(events, "policy")
    principles = policy.metadata.get("principles", []) if policy else []
    visible = "  ".join(principles[:6])
    return [
        "┌─ 十二铁律 ─────────────────────────────────────────────────────────────",
        f"│ {visible[:96] if visible else 'waiting'}",
        "└────────────────────────────────────────────────────────────────────────",
    ]


def _rich_capabilities(events: list[RunEvent]) -> Text:
    reviews = len([event for event in events if event.event_type == "review_feedback"])
    verify = len([event for event in events if event.event_type == "verification"])
    retry = len([event for event in events if event.event_type == "retry"])
    return Text.from_markup(
        f"[bold]01[/bold] 多Agent执行   [bold]02[/bold] 角色计划   [bold]03[/bold] 八段流水线\n"
        f"[bold]04[/bold] 审查返修 x{retry}   [bold]05[/bold] Session Resume   [bold]06[/bold] 实时事件\n"
        f"[bold]07[/bold] 安全降级   [bold]08[/bold] 验证闭环 x{verify} / review x{reviews}"
    )


def _rich_verification(events: list[RunEvent]) -> Text:
    verification = _latest(events, "verification")
    status = verification.status if verification else "waiting"
    detail = verification.detail if verification else "waiting for verification stage"
    return Text(f"Backend 自问自检: {status}\nForward 合问实证: {status}\n{detail[:90]}")


def _rich_council(events: list[RunEvent]) -> Text:
    council = _latest(events, "council")
    if not council:
        return Text("waiting")
    participants = ", ".join(council.metadata.get("participants", []))
    return Text(f"{council.status or 'recorded'}\nparticipants: {participants}\n{council.detail[:90]}")


def _rich_evolution(events: list[RunEvent]) -> Text:
    evolution = _latest(events, "evolution")
    if not evolution:
        return Text("waiting for post-run review")
    signals = ", ".join(evolution.metadata.get("signals", []))
    return Text(f"{evolution.status or 'recorded'}\nsignals: {signals}\n{evolution.metadata.get('recommendation', '')[:90]}")


def _rich_personas(session: SessionRecord, events: list[RunEvent]) -> Table:
    persona = _latest(events, "persona")
    roles = persona.metadata.get("roles", []) if persona else session.plan_json.get("roles", [])
    table = Table.grid(expand=True)
    table.add_column(ratio=1)
    table.add_column(ratio=1)
    for index in range(0, min(len(roles), 8), 2):
        left = roles[index]
        right = roles[index + 1] if index + 1 < len(roles) else None
        table.add_row(
            f"{left.get('name', '?')}\n[dim]{left.get('default_model', '?')}[/dim]",
            "" if right is None else f"{right.get('name', '?')}\n[dim]{right.get('default_model', '?')}[/dim]",
        )
    return table


def _rich_data_layer(store: SessionStore, session: SessionRecord, events: list[RunEvent]) -> Text:
    run_dir = store.paths.runs_dir / session.session_id
    return Text(f"sqlite: {store.paths.session_db_path.name}\nevents: {len(events)}\nartifacts: {run_dir}")


def _rich_principles(events: list[RunEvent]) -> Text:
    policy = _latest(events, "policy")
    principles = policy.metadata.get("principles", []) if policy else []
    return Text("\n".join(principles[:8]) if principles else "waiting")


def _rich_activity(events: list[RunEvent]) -> Text:
    lines = []
    for event in events[-10:]:
        stamp = event.created_at[11:16] if event.created_at else "--:--"
        lines.append(f"{stamp} {event.event_type:<15} {event.summary[:64]}")
    return Text("\n".join(lines))


def watch_cockpit(store: SessionStore, session_id: str, *, live: bool = False, interval: float = 1.0, rich_ui: bool = True) -> str | None:
    if not live:
        return render_cockpit(store, store.get(session_id))
    if rich_ui and RICH_AVAILABLE and sys.stdout.isatty():
        with Live(render_rich_cockpit(store, store.get(session_id)), refresh_per_second=max(1, int(1 / interval))) as live_view:
            while True:
                session = store.get(session_id)
                live_view.update(render_rich_cockpit(store, session))
                if session.status in {"completed", "failed", "recovered"}:
                    return None
                time.sleep(interval)
    while True:
        session = store.get(session_id)
        print("\033[2J\033[H", end="")
        print(render_cockpit(store, session), flush=True)
        if session.status in {"completed", "failed", "recovered"}:
            return None
        time.sleep(interval)
