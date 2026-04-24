from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from tools.host_runtime import HostCliRequest, get_host_cli_adapter

from .config import build_paths, init_workspace_files
from .executor import MultiModelExecutor
from .registry import ModelRegistry
from .router import TaskRouter
from .session import SessionStore
from .tui import render_dashboard, render_watch, run_dashboard, run_watch
from .types import RoutingStrategy, RunResult


KNOWN_COMMANDS = {
    "run",
    "pair",
    "swarm",
    "pipeline",
    "moa",
    "router",
    "session",
    "models",
    "config",
    "cost",
}


def _json_default(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    raise TypeError(f"Object of type {type(value)!r} is not JSON serializable")


def print_payload(payload: Any, *, output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
        return
    if isinstance(payload, dict):
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
        return
    print(str(payload))


def build_parser() -> argparse.ArgumentParser:
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--workspace", help="Workspace root for the current project")
    shared.add_argument("--format", choices=["text", "json"], default="text")

    parser = argparse.ArgumentParser(description="AEGIS v2 multi-model collaboration CLI")
    parser.add_argument("--workspace", help="Workspace root for the current project")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_request_command(name: str, *, include_strategy: bool = False, include_workers: bool = False) -> argparse.ArgumentParser:
        command = sub.add_parser(name, parents=[shared])
        command.add_argument("request")
        command.add_argument("--mode", choices=["quality", "speed", "cost", "balanced"])
        command.add_argument("--models")
        command.add_argument("--budget", type=float)
        if include_strategy:
            command.add_argument("--strategy", choices=[item.value for item in RoutingStrategy])
        if include_workers:
            command.add_argument("--workers", type=int, help="Number of parallel workers (for swarm mode)")
        command.add_argument("--execute", action="store_true")
        command.add_argument("--simulate", action="store_true")
        command.add_argument("--bridge", action="store_true")
        command.add_argument("--stream-jsonl", action="store_true", help=argparse.SUPPRESS)
        return command

    add_request_command("run", include_strategy=True)
    add_request_command("pair")
    add_request_command("swarm", include_workers=True)
    add_request_command("pipeline")
    add_request_command("moa")

    router_cmd = sub.add_parser("router", parents=[shared])
    router_sub = router_cmd.add_subparsers(dest="router_command", required=True)
    router_dry_run = router_sub.add_parser("dry-run", parents=[shared])
    router_dry_run.add_argument("request")
    router_dry_run.add_argument("--mode", choices=["quality", "speed", "cost", "balanced"])
    router_dry_run.add_argument("--models")
    router_dry_run.add_argument("--strategy", choices=[item.value for item in RoutingStrategy])
    router_dry_run.add_argument("--budget", type=float)

    session_cmd = sub.add_parser("session", parents=[shared])
    session_sub = session_cmd.add_subparsers(dest="session_command", required=True)
    session_sub.add_parser("list", parents=[shared])
    show_cmd = session_sub.add_parser("show", parents=[shared])
    show_cmd.add_argument("session_id")
    for action in ("resume", "recover"):
        action_cmd = session_sub.add_parser(action, parents=[shared])
        action_cmd.add_argument("session_id")
        action_cmd.add_argument("--mode", choices=["quality", "speed", "cost", "balanced"])
        action_cmd.add_argument("--models")
        action_cmd.add_argument("--budget", type=float)
        action_cmd.add_argument("--strategy", choices=[item.value for item in RoutingStrategy])
        action_cmd.add_argument("--simulate", action="store_true")
        action_cmd.add_argument("--bridge", action="store_true")

    models_cmd = sub.add_parser("models", parents=[shared])
    models_sub = models_cmd.add_subparsers(dest="models_command", required=True)
    list_cmd = models_sub.add_parser("list", parents=[shared])
    list_cmd.add_argument("--enabled-only", action="store_true")
    test_cmd = models_sub.add_parser("test", parents=[shared])
    test_cmd.add_argument("name", nargs="?")

    config_cmd = sub.add_parser("config", parents=[shared])
    config_sub = config_cmd.add_subparsers(dest="config_command", required=True)
    config_sub.add_parser("show", parents=[shared])
    init_cmd = config_sub.add_parser("init", parents=[shared])
    init_cmd.add_argument("--force", action="store_true")

    cost_cmd = sub.add_parser("cost", parents=[shared])
    cost_sub = cost_cmd.add_subparsers(dest="cost_command", required=True)
    cost_sub.add_parser("report", parents=[shared])

    watch_cmd = sub.add_parser("watch", parents=[shared])
    watch_cmd.add_argument("session_id", nargs="?")
    watch_cmd.add_argument("--live", action="store_true")
    watch_cmd.add_argument("--interval", type=float, default=1.0)

    return parser


def resolve_run_context(args: argparse.Namespace) -> dict[str, Any]:
    context: dict[str, Any] = {}
    if getattr(args, "mode", None):
        context["mode"] = args.mode
    if getattr(args, "models", None):
        context["models"] = args.models
    if getattr(args, "strategy", None):
        context["strategy"] = args.strategy
    if getattr(args, "budget", None) is not None:
        context["budget"] = float(args.budget)
    if getattr(args, "workers", None) is not None:
        context["workers"] = int(args.workers)
    if getattr(args, "execute", False):
        context["execute"] = True
    if getattr(args, "simulate", False):
        context["simulate"] = True
    if getattr(args, "bridge", False):
        context["bridge"] = True
    return context


def build_router_classifier(paths: Any, *, event_callback: Any | None = None) -> Any:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None

    def _run_host_classifier(adapter_name: str, prompt: str) -> dict[str, Any] | None:
        adapter = get_host_cli_adapter(adapter_name)
        if not adapter.available():
            if event_callback is not None:
                event_callback({"event": "startup_progress", "stage": "advisor_skip", "runtime": adapter_name, "message": f"{adapter_name} advisor unavailable"})
            return None
        if event_callback is not None:
            event_callback({"event": "startup_progress", "stage": "advisor_start", "runtime": adapter_name, "message": f"using {adapter_name} advisor"})
        request = HostCliRequest(
            prompt=prompt,
            workspace_root=paths.workspace_root,
            core_root=Path(__file__).resolve().parents[2],
            output_path=paths.responses_dir / "routing-advisor.txt" if adapter_name == "codex" else None,
        )
        invocation = adapter.build_invocation(request)
        completed = subprocess.run(
            invocation.command,
            cwd=invocation.cwd,
            env=invocation.env,
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
        if completed.returncode != 0:
            if event_callback is not None:
                event_callback(
                    {
                        "event": "startup_progress",
                        "stage": "advisor_failed",
                        "runtime": adapter_name,
                        "message": f"{adapter_name} advisor failed with exit code {completed.returncode}",
                    }
                )
            return None
        raw = completed.stdout.strip()
        if not raw and adapter_name == "codex" and request.output_path and request.output_path.exists():
            raw = request.output_path.read_text(encoding="utf-8", errors="replace").strip()
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            end = raw.rfind("}")
            if start < 0 or end <= start:
                return None
            try:
                payload = json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                return None
        if event_callback is not None:
            event_callback(
                {
                    "event": "startup_progress",
                    "stage": "advisor_done",
                    "runtime": adapter_name,
                    "message": f"{adapter_name} advisor suggested {payload.get('task_type', 'unknown')} / {payload.get('strategy', 'unknown')}",
                    "advisor": payload,
                }
            )
        return payload if isinstance(payload, dict) else None

    def _classifier(request: str, context: dict[str, Any]) -> dict[str, Any] | None:
        del context
        prompt = (
            "You are AEGIS route advisor.\n"
            "Classify the user request for scheduling.\n"
            "Return JSON only with keys: task_type, strategy, models, rationale.\n"
            "Allowed task_type: architecture, code_gen, code_review, debugging, testing, refactoring, documentation, research.\n"
            "Allowed strategy: single, pair, swarm, pipeline, moa.\n"
            "If the request is about fresh external information, market/news lookup, or time-sensitive research, classify it as research.\n"
            "If the request clearly benefits from multiple viewpoints, choose moa.\n"
            "models should be a short list chosen from: codex, claude-sonnet-4-6, claude-opus-4-7.\n\n"
            f"User request:\n{request}"
        )
        return _run_host_classifier("claude", prompt) or _run_host_classifier("codex", prompt)

    return _classifier


def run_cli(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        paths = build_paths(args.workspace)
        registry = ModelRegistry.from_workspace(paths)
        sessions = SessionStore(paths)
        router = TaskRouter(registry, classifier=build_router_classifier(paths))
        executor = MultiModelExecutor(registry, router, sessions)

        if args.command in {"run", "pair", "swarm", "pipeline", "moa"}:
            context = resolve_run_context(args)
            if args.command != "run":
                context["strategy"] = args.command
            if getattr(args, "stream_jsonl", False):
                def emit_stream(payload: dict[str, Any]) -> None:
                    print(json.dumps(payload, ensure_ascii=False), flush=True)

                emit_stream(
                    {
                        "event": "startup_progress",
                        "stage": "bootstrap",
                        "message": "initializing routing context",
                    }
                )
                stream_router = TaskRouter(registry, classifier=build_router_classifier(paths, event_callback=emit_stream))
                stream_executor = MultiModelExecutor(registry, stream_router, sessions)
                emit_stream(
                    {
                        "event": "startup_progress",
                        "stage": "routing",
                        "message": "building routing decision",
                    }
                )
                decision, plan, session = stream_executor.prepare_run(args.request, context)
                emit_stream(
                    {
                        "event": "startup_progress",
                        "stage": "planning",
                        "message": f"prepared {decision.strategy.value} with {', '.join(decision.models)}",
                        "routing": decision.to_dict(),
                        "plan": plan.to_dict(),
                    }
                )
                print(
                    json.dumps(
                        {
                            "event": "session_started",
                            "session": session.record.to_dict(),
                            "routing": decision.to_dict(),
                            "plan": plan.to_dict(),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                if not context.get("execute"):
                    session.set_status("planned", execution_state="phase1-foundation")
                    result = RunResult(
                        session=sessions.get_session(session.session_id),
                        routing=decision,
                        plan=plan,
                        executed=False,
                        message="Routing and execution planning are ready.",
                    )
                else:
                    emit_stream(
                        {
                            "event": "startup_progress",
                            "stage": "dispatch",
                            "message": "starting execution",
                        }
                    )
                    result = stream_executor.execute_prepared(args.request, decision, plan, session, context)
                print(
                    json.dumps(
                        {
                            "event": "session_finished",
                            "result": result.to_dict(),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                return 0
            result = executor.run(args.request, context)
            print_payload(result.to_dict() if args.format == "json" else render_run_result(result), output_format=args.format)
            return 0

        if args.command == "router" and args.router_command == "dry-run":
            decision = router.route(args.request, resolve_run_context(args))
            print_payload(decision.to_dict(), output_format=args.format)
            return 0

        if args.command == "session" and args.session_command == "list":
            sessions_payload = [record.to_dict() for record in sessions.list_sessions()]
            print_payload(sessions_payload, output_format=args.format)
            return 0

        if args.command == "session" and args.session_command == "show":
            record = sessions.get_session(args.session_id)
            payload = record.to_dict()
            payload["checkpoints"] = sessions.list_checkpoints(args.session_id)
            payload["messages"] = [message.to_dict() for message in sessions.list_messages(args.session_id)]
            print_payload(payload, output_format=args.format)
            return 0

        if args.command == "session" and args.session_command in {"resume", "recover"}:
            result = executor.replay(
                args.session_id,
                resolve_run_context(args),
                recover=args.session_command == "recover",
            )
            print_payload(result.to_dict() if args.format == "json" else render_run_result(result), output_format=args.format)
            return 0

        if args.command == "models" and args.models_command == "list":
            models = [item.to_dict() for item in registry.list_models(enabled_only=args.enabled_only)]
            print_payload(models, output_format=args.format)
            return 0

        if args.command == "models" and args.models_command == "test":
            if args.name:
                payload: Any = registry.check_model(args.name).to_dict()
            else:
                payload = [registry.check_model(name).to_dict() for name in registry.bundle.enabled_model_names()]
            print_payload(payload, output_format=args.format)
            return 0

        if args.command == "config" and args.config_command == "show":
            payload = {
                "workspace_root": str(paths.workspace_root),
                "config_path": str(paths.config_path),
                "registry_path": str(paths.registry_path),
                "logs_dir": str(paths.logs_dir),
                "responses_dir": str(paths.responses_dir),
                "config": registry.config,
            }
            print_payload(payload, output_format=args.format)
            return 0

        if args.command == "config" and args.config_command == "init":
            written = init_workspace_files(paths, force=args.force)
            payload = {"written": [str(path) for path in written]}
            print_payload(payload, output_format=args.format)
            return 0

        if args.command == "cost" and args.cost_command == "report":
            cost_summary = sessions.cost_summary()
            cost_summary["budget"] = registry.config.get("cost_control", {})
            print_payload(cost_summary, output_format=args.format)
            return 0

        if args.command == "watch":
            if args.live:
                if args.session_id:
                    run_watch(sessions, args.session_id, interval=max(0.5, float(args.interval)))
                else:
                    run_dashboard(sessions, registry, interval=max(0.5, float(args.interval)))
                return 0
            # Non-live: render once
            if args.session_id:
                from rich.console import Console
                Console().print(render_watch(sessions, args.session_id))
            else:
                from rich.console import Console
                Console().print(render_dashboard(sessions, registry))
            return 0

        parser.print_help()
        return 1
    except Exception as exc:
        error_payload = {"error": str(exc)}
        print_payload(error_payload, output_format=args.format)
        return 1


def _use_color() -> bool:
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _c(text: str, code: str, *, colorize: bool = True) -> str:
    if not colorize:
        return text
    return f"\033[{code}m{text}\033[0m"


def _bold(text: str, *, colorize: bool = True) -> str:
    return _c(text, "1", colorize=colorize)


def _dim(text: str, *, colorize: bool = True) -> str:
    return _c(text, "2", colorize=colorize)


def _cyan(text: str, *, colorize: bool = True) -> str:
    return _c(text, "36", colorize=colorize)


def _green(text: str, *, colorize: bool = True) -> str:
    return _c(text, "32", colorize=colorize)


def _yellow(text: str, *, colorize: bool = True) -> str:
    return _c(text, "33", colorize=colorize)


def _red(text: str, *, colorize: bool = True) -> str:
    return _c(text, "31", colorize=colorize)


def render_run_result(result: Any) -> str:
    use_color = _use_color()
    routing = result.routing
    session = result.session

    status_icon = ""
    if session.status == "completed":
        status_icon = _green("✓", colorize=use_color) + " "
    elif session.status == "failed":
        status_icon = _red("✗", colorize=use_color) + " "
    elif session.status == "running":
        status_icon = _yellow("◌", colorize=use_color) + " "

    header = f"AEGIS v2 · {session.session_id}"
    if session.status != "planned":
        header += f" · {status_icon}{session.status}"

    def row(label: str, value: str, width: int = 12) -> str:
        return f"  {_dim(label + ':', colorize=use_color):<{width}} {value}"

    lines: list[str] = [
        _cyan("╭─ " + header + " ─" + "─" * max(0, 46 - len(header)) + "╮", colorize=use_color),
        row("Task", routing.task_type.value),
        row("Strategy", routing.strategy.value),
        row("Mode", routing.mode),
        row("Models", ", ".join(routing.models)),
        row("Complexity", f"{routing.complexity}/10"),
    ]

    if result.execution is not None:
        actual_cost = result.execution.approximate_cost
        actual_time = sum(s.duration_ms for s in result.execution.stage_results)
        cost_line = f"${routing.estimated_cost:.2f}"
        if actual_cost > 0:
            cost_line += f"    → Actual: ${_green(f'${actual_cost:.4f}', colorize=use_color) if use_color else f'${actual_cost:.4f}'}"
        lines.append(row("Est. Cost", cost_line))
        time_line = f"{routing.estimated_time_seconds}s"
        if actual_time > 0:
            time_line += f"    → Actual: {(actual_time / 1000):.1f}s"
        lines.append(row("Est. Time", time_line))
    else:
        lines.append(row("Est. Cost", f"${routing.estimated_cost:.2f}"))
        lines.append(row("Est. Time", f"{routing.estimated_time_seconds}s"))

    lines.append(_cyan("├─ Plan " + "─" * 40 + "┤", colorize=use_color))

    for index, step in enumerate(result.plan.steps, start=1):
        status = "  "
        if result.execution is not None:
            stage_names = {s.stage_name for s in result.execution.stage_results}
            if step.name in stage_names:
                status = _green("✓ ", colorize=use_color) if use_color else "✓ "
            else:
                status = _dim("○ ", colorize=use_color) if use_color else "○ "
        lines.append(f"  {status}{index}. {step.name:<18} {step.model}")

    if result.execution is not None:
        stage_count = len(result.execution.stage_results)
        lines.append(_cyan("├─ Stages " + "─" * 38 + "┤", colorize=use_color))
        for stage in result.execution.stage_results:
            icon = _green("✓", colorize=use_color) if stage.exit_code == 0 else _red("✗", colorize=use_color)
            cost = f"${stage.approximate_cost:.4f}" if stage.approximate_cost > 0 else ""
            duration = f"{stage.duration_ms}ms" if stage.duration_ms > 0 else ""
            meta = ", ".join(m for m in (cost, duration) if m)
            meta_str = f"  ({meta})" if meta else ""
            lines.append(f"  {icon} {stage.stage_name:<18} {stage.model}{meta_str}")
        if result.execution.iterations is not None:
            lines.append(row("Iterations", str(result.execution.iterations)))

        preview = result.execution.final_output.strip().replace("\n", " ")
        if preview:
            lines.append(_cyan("├─ Output " + "─" * 38 + "┤", colorize=use_color))
            snippet = preview[:240] + "..." if len(preview) > 240 else preview
            lines.append(f"  {snippet}")

    lines.append(_cyan("╰" + "─" * 48 + "╯", colorize=use_color))
    lines.append(result.message)
    return "\n".join(lines)


def normalize_argv(argv: list[str] | None = None) -> list[str]:
    raw = list(sys.argv[1:] if argv is None else argv)
    if not raw:
        return raw
    first = raw[0]
    if first.startswith("-"):
        return raw
    if first in KNOWN_COMMANDS:
        return raw
    return ["run", *raw]


def main(argv: list[str] | None = None) -> int:
    normalized = normalize_argv(argv)
    if not normalized:
        # Launch dashboard TUI when no arguments are provided
        try:
            paths = build_paths()
            registry = ModelRegistry.from_workspace(paths)
            sessions = SessionStore(paths)
            run_dashboard(sessions, registry)
            return 0
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            print(f"Error starting dashboard: {exc}", file=sys.stderr)
            return 1
    return run_cli(normalized)
