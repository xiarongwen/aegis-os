from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .config import build_paths, init_workspace_files
from .executor import MultiModelExecutor
from .registry import ModelRegistry
from .router import TaskRouter
from .session import SessionStore
from .types import RoutingStrategy


KNOWN_COMMANDS = {
    "run",
    "router",
    "session",
    "models",
    "config",
    "cost",
    "collaboration",
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

    run_cmd = sub.add_parser("run", parents=[shared])
    run_cmd.add_argument("request")
    run_cmd.add_argument("--mode", choices=["quality", "speed", "cost", "balanced"])
    run_cmd.add_argument("--models")
    run_cmd.add_argument("--strategy", choices=[item.value for item in RoutingStrategy])
    run_cmd.add_argument("--execute", action="store_true")
    run_cmd.add_argument("--simulate", action="store_true")
    run_cmd.add_argument("--bridge", action="store_true")

    router_cmd = sub.add_parser("router", parents=[shared])
    router_sub = router_cmd.add_subparsers(dest="router_command", required=True)
    router_dry_run = router_sub.add_parser("dry-run", parents=[shared])
    router_dry_run.add_argument("request")
    router_dry_run.add_argument("--mode", choices=["quality", "speed", "cost", "balanced"])
    router_dry_run.add_argument("--models")
    router_dry_run.add_argument("--strategy", choices=[item.value for item in RoutingStrategy])

    session_cmd = sub.add_parser("session", parents=[shared])
    session_sub = session_cmd.add_subparsers(dest="session_command", required=True)
    session_sub.add_parser("list", parents=[shared])
    show_cmd = session_sub.add_parser("show", parents=[shared])
    show_cmd.add_argument("session_id")

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

    collaboration_cmd = sub.add_parser("collaboration", parents=[shared])
    collaboration_sub = collaboration_cmd.add_subparsers(dest="collaboration_command", required=True)
    for strategy in ("pair", "swarm", "pipeline", "moa"):
        strategy_cmd = collaboration_sub.add_parser(strategy, parents=[shared])
        strategy_cmd.add_argument("request")
        strategy_cmd.add_argument("--mode", choices=["quality", "speed", "cost", "balanced"])
        strategy_cmd.add_argument("--models")
        strategy_cmd.add_argument("--execute", action="store_true")
        strategy_cmd.add_argument("--simulate", action="store_true")
        strategy_cmd.add_argument("--bridge", action="store_true")

    return parser


def resolve_run_context(args: argparse.Namespace) -> dict[str, Any]:
    context: dict[str, Any] = {}
    if getattr(args, "mode", None):
        context["mode"] = args.mode
    if getattr(args, "models", None):
        context["models"] = args.models
    if getattr(args, "strategy", None):
        context["strategy"] = args.strategy
    if getattr(args, "execute", False):
        context["execute"] = True
    if getattr(args, "simulate", False):
        context["simulate"] = True
    if getattr(args, "bridge", False):
        context["bridge"] = True
    return context


def run_cli(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        paths = build_paths(args.workspace)
        registry = ModelRegistry.from_workspace(paths)
        router = TaskRouter(registry)
        sessions = SessionStore(paths)
        executor = MultiModelExecutor(registry, router, sessions)

        if args.command == "run":
            result = executor.run(args.request, resolve_run_context(args))
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

        if args.command == "collaboration":
            context = resolve_run_context(args)
            context["strategy"] = args.collaboration_command
            result = executor.run(args.request, context)
            print_payload(result.to_dict() if args.format == "json" else render_run_result(result), output_format=args.format)
            return 0

        parser.print_help()
        return 1
    except Exception as exc:
        error_payload = {"error": str(exc)}
        print_payload(error_payload, output_format=args.format)
        return 1


def render_run_result(result: Any) -> str:
    routing = result.routing
    lines = [
        f"Session: {result.session.session_id}",
        f"Task Type: {routing.task_type.value}",
        f"Strategy: {routing.strategy.value}",
        f"Mode: {routing.mode}",
        f"Models: {', '.join(routing.models)}",
        f"Complexity: {routing.complexity}/10",
        f"Estimated Cost: ${routing.estimated_cost:.2f}",
        f"Estimated Time: {routing.estimated_time_seconds}s",
        "Plan:",
    ]
    for step in result.plan.steps:
        lines.append(f"  - {step.name}: {step.model} [{step.kind}]")
    if result.execution is not None:
        lines.append(f"Actual Cost: ${result.execution.approximate_cost:.4f}")
        lines.append(f"Completed Stages: {len(result.execution.stage_results)}")
        preview = result.execution.final_output.strip().replace("\n", " ")
        if preview:
            lines.append(f"Final Output: {preview[:220]}")
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
        build_parser().print_help()
        return 0
    return run_cli(normalized)
