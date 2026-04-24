from __future__ import annotations

import argparse
import json
import sys
import threading
from typing import Any

from .cockpit import render_cockpit, watch_cockpit
from .config import build_paths, init_config, load_config
from .doctor import run_doctor
from .engine import CollaborationEngine
from .models import ModelResolver
from .planner import RunPlanner
from .runtime import RuntimeManager
from .router import IntentRouter
from .session import SessionStore
from .types import Strategy


KNOWN_COMMANDS = {
    "run",
    "ulw",
    "ultrawork",
    "watch",
    "pair",
    "swarm",
    "pipeline",
    "moa",
    "router",
    "session",
    "agents",
    "models",
    "bridge",
    "doctor",
    "config",
    "cost",
}


def print_payload(payload: Any, *, output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if isinstance(payload, str):
        print(payload)
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AEGIS 1.0 agent-CLI coding autopilot")
    parser.add_argument("--workspace")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    sub = parser.add_subparsers(dest="command", required=True)

    def request_cmd(name: str) -> argparse.ArgumentParser:
        command = sub.add_parser(name)
        command.add_argument("request")
        command.add_argument("--workspace")
        command.add_argument("--format", choices=["text", "json"], default="text")
        command.add_argument("--mode", choices=["quality", "speed", "cost", "balanced"], default="balanced")
        command.add_argument("--agents", dest="models")
        command.add_argument("--models", dest="models")
        command.add_argument("--workers", type=int)
        command.add_argument("--execute", action="store_true")
        command.add_argument("--simulate", action="store_true")
        command.add_argument("--bridge", action="store_true")
        command.add_argument("--watch", action="store_true")
        command.add_argument("--live", action="store_true")
        command.add_argument("--interval", type=float, default=0.4)
        command.add_argument("--step-delay", type=float, default=0.25)
        return command

    for name in ("run", "ulw", "ultrawork", "pair", "swarm", "pipeline", "moa"):
        request_cmd(name)

    watch = sub.add_parser("watch")
    watch.add_argument("session_id")
    watch.add_argument("--workspace")
    watch.add_argument("--format", choices=["text", "json"], default="text")
    watch.add_argument("--live", action="store_true")
    watch.add_argument("--interval", type=float, default=1.0)

    bridge = sub.add_parser("bridge")
    bridge.add_argument("--workspace")
    bridge.add_argument("--format", choices=["text", "json"], default="text")
    bridge_sub = bridge.add_subparsers(dest="bridge_command", required=True)
    bridge_up = bridge_sub.add_parser("up")
    bridge_up.add_argument("--workspace")
    bridge_up.add_argument("--format", choices=["text", "json"], default="text")
    bridge_up.add_argument("--model", action="append", default=[])
    bridge_status = bridge_sub.add_parser("status")
    bridge_status.add_argument("--workspace")
    bridge_status.add_argument("--format", choices=["text", "json"], default="text")
    bridge_stop = bridge_sub.add_parser("stop")
    bridge_stop.add_argument("--workspace")
    bridge_stop.add_argument("--format", choices=["text", "json"], default="text")

    router = sub.add_parser("router")
    router_sub = router.add_subparsers(dest="router_command", required=True)
    dry = router_sub.add_parser("dry-run")
    dry.add_argument("request")
    dry.add_argument("--workspace")
    dry.add_argument("--format", choices=["text", "json"], default="text")
    dry.add_argument("--mode", choices=["quality", "speed", "cost", "balanced"], default="balanced")

    session = sub.add_parser("session")
    session.add_argument("--workspace")
    session.add_argument("--format", choices=["text", "json"], default="text")
    session_sub = session.add_subparsers(dest="session_command", required=True)
    session_list = session_sub.add_parser("list")
    session_list.add_argument("--workspace")
    session_list.add_argument("--format", choices=["text", "json"], default="text")
    show = session_sub.add_parser("show")
    show.add_argument("session_id")
    show.add_argument("--workspace")
    show.add_argument("--format", choices=["text", "json"], default="text")
    for action in ("resume", "recover"):
        replay = session_sub.add_parser(action)
        replay.add_argument("session_id")
        replay.add_argument("--workspace")
        replay.add_argument("--format", choices=["text", "json"], default="text")
        replay.add_argument("--simulate", action="store_true")
        replay.add_argument("--watch", action="store_true")

    for registry_command in ("agents", "models"):
        registry = sub.add_parser(registry_command)
        registry.add_argument("--workspace")
        registry.add_argument("--format", choices=["text", "json"], default="text")
        registry_sub = registry.add_subparsers(dest="models_command", required=True)
        registry_list = registry_sub.add_parser("list")
        registry_list.add_argument("--workspace")
        registry_list.add_argument("--format", choices=["text", "json"], default="text")
        test = registry_sub.add_parser("test")
        test.add_argument("name", nargs="?")
        test.add_argument("--workspace")
        test.add_argument("--format", choices=["text", "json"], default="text")

    config = sub.add_parser("config")
    config.add_argument("--workspace")
    config.add_argument("--format", choices=["text", "json"], default="text")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    config_show = config_sub.add_parser("show")
    config_show.add_argument("--workspace")
    config_show.add_argument("--format", choices=["text", "json"], default="text")
    config_init = config_sub.add_parser("init")
    config_init.add_argument("--workspace")
    config_init.add_argument("--format", choices=["text", "json"], default="text")
    config_init.add_argument("--force", action="store_true")

    cost = sub.add_parser("cost")
    cost.add_argument("--workspace")
    cost.add_argument("--format", choices=["text", "json"], default="text")
    cost_sub = cost.add_subparsers(dest="cost_command", required=True)
    cost_report = cost_sub.add_parser("report")
    cost_report.add_argument("--workspace")
    cost_report.add_argument("--format", choices=["text", "json"], default="text")

    doctor = sub.add_parser("doctor")
    doctor.add_argument("--workspace")
    doctor.add_argument("--format", choices=["text", "json"], default="text")
    return parser


def _strategy_for_command(command: str) -> str | None:
    if command == "pair":
        return Strategy.PAIR.value
    if command == "swarm":
        return Strategy.SWARM.value
    if command == "pipeline":
        return Strategy.PIPELINE.value
    if command == "moa":
        return Strategy.MOA.value
    return None


def _run_request(args: argparse.Namespace) -> dict[str, Any] | str:
    paths = build_paths(getattr(args, "workspace", None))
    router = IntentRouter()
    planner = RunPlanner()
    store = SessionStore(paths)
    context = {"mode": args.mode}
    forced = _strategy_for_command(args.command)
    if forced:
        context["strategy"] = forced
    route = router.route(args.request, context)
    plan = planner.build(args.request.strip(), route, models=args.models, workers=args.workers)
    session = store.create(args.request.strip(), route, plan, {"command": args.command})

    should_execute = args.execute or args.simulate or args.command in {"ulw", "ultrawork"}
    simulate = bool(args.simulate or (args.command in {"ulw", "ultrawork"} and not args.execute))
    if should_execute:
        runtime = None if simulate else RuntimeManager(paths, use_bridge=bool(args.bridge))
        engine = CollaborationEngine(store)
        if getattr(args, "live", False):
            thread = threading.Thread(
                target=engine.execute,
                kwargs={
                    "session_id": session.session_id,
                    "plan": plan,
                    "simulate": simulate,
                    "runtime": runtime,
                    "step_delay": max(0.0, float(getattr(args, "step_delay", 0.25))),
                },
                daemon=False,
            )
            thread.start()
            watch_cockpit(store, session.session_id, live=True, interval=max(0.05, float(getattr(args, "interval", 0.4))))
            thread.join()
            return ""
        engine.execute(session.session_id, plan, simulate=simulate, runtime=runtime)
        session = store.get(session.session_id)

    if getattr(args, "live", False):
        watch_cockpit(store, session.session_id, live=True)
        return ""
    if args.watch or args.command in {"ulw", "ultrawork"}:
        return render_cockpit(store, session)

    return {
        "session": session.to_dict(),
        "route": route.to_dict(),
        "plan": plan.to_dict(),
        "executed": should_execute,
    }


def run_cli(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    output_format = getattr(args, "format", "text")
    try:
        paths = build_paths(getattr(args, "workspace", None))
        store = SessionStore(paths)
        if args.command in {"run", "ulw", "ultrawork", "pair", "swarm", "pipeline", "moa"}:
            print_payload(_run_request(args), output_format=output_format)
            return 0
        if args.command == "watch":
            rendered = watch_cockpit(store, args.session_id, live=args.live, interval=args.interval)
            if rendered is not None:
                print_payload(rendered, output_format=output_format)
            return 0
        if args.command == "bridge":
            print_payload(_run_bridge(args), output_format=output_format)
            return 0
        if args.command == "doctor":
            print_payload(run_doctor(paths), output_format=output_format)
            return 0
        if args.command == "config" and args.config_command == "show":
            print_payload(
                {
                    "workspace_root": str(paths.workspace_root),
                    "config_path": str(paths.config_path),
                    "config": load_config(paths),
                },
                output_format=output_format,
            )
            return 0
        if args.command == "config" and args.config_command == "init":
            written = init_config(paths, force=args.force)
            print_payload({"written": [str(path) for path in written], "config_path": str(paths.config_path)}, output_format=output_format)
            return 0
        if args.command == "cost" and args.cost_command == "report":
            print_payload(store.cost_summary(), output_format=output_format)
            return 0
        if args.command == "router" and args.router_command == "dry-run":
            route = IntentRouter().route(args.request, {"mode": args.mode})
            plan = RunPlanner().build(args.request, route)
            print_payload({"route": route.to_dict(), "plan": plan.to_dict()}, output_format=output_format)
            return 0
        if args.command == "session" and args.session_command == "list":
            print_payload([record.to_dict() for record in store.list()], output_format=output_format)
            return 0
        if args.command == "session" and args.session_command == "show":
            record = store.get(args.session_id)
            print_payload({**record.to_dict(), "events": [event.to_dict() for event in store.events(args.session_id)]}, output_format=output_format)
            return 0
        if args.command == "session" and args.session_command in {"resume", "recover"}:
            source = store.get(args.session_id)
            replay_args = argparse.Namespace(
                command="ulw" if args.watch else "run",
                request=source.request,
                workspace=None,
                format=output_format,
                mode=source.mode,
                models=None,
                workers=None,
                execute=args.simulate,
                simulate=args.simulate,
                bridge=False,
                watch=args.watch,
                live=False,
            )
            print_payload(_run_request(replay_args), output_format=output_format)
            return 0
        if args.command in {"agents", "models"} and args.models_command == "list":
            print_payload([model.to_dict() for model in ModelResolver().list_models()], output_format=output_format)
            return 0
        if args.command in {"agents", "models"} and args.models_command == "test":
            resolver = ModelResolver()
            if args.name:
                print_payload(resolver.check(args.name), output_format=output_format)
            else:
                print_payload([resolver.check(name) for name in resolver.names()], output_format=output_format)
            return 0
    except Exception as exc:
        print_payload({"error": str(exc)}, output_format=output_format)
        return 1
    parser.print_help()
    return 1


def _run_bridge(args: argparse.Namespace) -> dict[str, Any]:
    from tools.runtime_bridge import cli as bridge

    paths = build_paths(getattr(args, "workspace", None))
    if args.bridge_command == "up":
        models = args.model or ["aegis", "codex", "claude"]
        session = bridge.ensure_bridge_session(workspace=paths.workspace_root, models=models)
        return {
            "session_name": session.session_name,
            "workspace_root": session.workspace_root,
            "panes": session.panes,
            "active": session.active,
        }
    if args.bridge_command == "status":
        sessions = bridge.list_bridge_sessions(workspace=paths.workspace_root)
        return {
            "sessions": [
                {
                    "session_name": item.session_name,
                    "workspace_root": item.workspace_root,
                    "panes": item.panes,
                    "active": item.active,
                }
                for item in sessions
            ]
        }
    if args.bridge_command == "stop":
        return {"stopped": bridge.stop_bridge_session(workspace=paths.workspace_root)}
    raise ValueError(f"unknown bridge command: {args.bridge_command}")


def normalize_argv(argv: list[str] | None = None) -> list[str]:
    raw = list(sys.argv[1:] if argv is None else argv)
    if not raw:
        return raw
    if raw[0].startswith("-") or raw[0] in KNOWN_COMMANDS:
        return raw
    return ["run", *raw]


def main(argv: list[str] | None = None) -> int:
    normalized = normalize_argv(argv)
    if not normalized:
        build_parser().print_help()
        return 0
    return run_cli(normalized)
