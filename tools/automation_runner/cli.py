from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.control_plane import cli as control_plane


ROOT = control_plane.ROOT
INTENT_LOCK_SCHEMA_PATH = ROOT / "shared-contexts/intent-lock-schema.json"
DEFAULT_STOP_BEFORE = {"L5_DEPLOY"}


class AutomationRunnerError(RuntimeError):
    pass


@dataclass
class IntentRoute:
    workflow_type: str
    target_state: str
    summary: str
    rationale: str


@dataclass
class RuntimeResult:
    command: list[str]
    output_path: Path


class RuntimeAdapter:
    name = "base"

    def run(
        self,
        *,
        agent_id: str,
        workflow_id: str,
        state_name: str,
        prompt: str,
        log_path: Path,
        use_search: bool,
    ) -> RuntimeResult:
        raise NotImplementedError


class CodexRuntimeAdapter(RuntimeAdapter):
    name = "codex"

    def run(
        self,
        *,
        agent_id: str,
        workflow_id: str,
        state_name: str,
        prompt: str,
        log_path: Path,
        use_search: bool,
    ) -> RuntimeResult:
        cmd = ["codex"]
        if use_search:
            cmd.append("--search")
        cmd.extend(
            [
                "exec",
                "--full-auto",
                "-C",
                str(ROOT),
                "-o",
                str(log_path),
                prompt,
            ]
        )
        completed = subprocess.run(cmd, text=True, capture_output=True, check=False)
        if completed.returncode != 0:
            raise AutomationRunnerError(
                f"runtime {self.name} failed for {agent_id} in {state_name}:\n"
                f"{completed.stderr or completed.stdout or 'unknown runtime error'}"
            )
        return RuntimeResult(command=cmd, output_path=log_path)


class ClaudeRuntimeAdapter(RuntimeAdapter):
    name = "claude"

    def run(
        self,
        *,
        agent_id: str,
        workflow_id: str,
        state_name: str,
        prompt: str,
        log_path: Path,
        use_search: bool,
    ) -> RuntimeResult:
        cmd = [
            "claude",
            "-p",
            "--permission-mode",
            "bypassPermissions",
            "--output-format",
            "text",
            "--add-dir",
            str(ROOT),
            prompt,
        ]
        completed = subprocess.run(cmd, text=True, capture_output=True, check=False)
        if completed.returncode != 0:
            raise AutomationRunnerError(
                f"runtime {self.name} failed for {agent_id} in {state_name}:\n"
                f"{completed.stderr or completed.stdout or 'unknown runtime error'}"
            )
        log_path.write_text(completed.stdout, encoding="utf-8")
        return RuntimeResult(command=cmd, output_path=log_path)


def load_intent_lock_schema() -> dict[str, Any]:
    return control_plane.load_json(INTENT_LOCK_SCHEMA_PATH)


def validate_intent_lock(payload: dict[str, Any]) -> None:
    schema = load_intent_lock_schema()
    missing = [key for key in schema["required"] if key not in payload]
    if missing:
        raise AutomationRunnerError(f"intent lock missing required keys: {', '.join(missing)}")


def route_request(request: str) -> IntentRoute:
    normalized = request.strip().lower()
    if not normalized:
        raise AutomationRunnerError("request cannot be empty")
    research_terms = ("调研", "研究", "research", "竞品", "市场", "分析")
    planning_terms = ("prd", "规划", "plan", "架构", "任务拆解", "需求")
    build_terms = ("开发", "实现", "build", "页面", "功能", "chat page", "聊天页面", "frontend", "backend")
    launch_terms = ("部署", "发布", "上线", "deploy", "launch", "release")
    audit_terms = ("审计", "review", "复盘", "security", "安全")

    has_research = any(term in normalized for term in research_terms)
    has_planning = any(term in normalized for term in planning_terms)
    has_build = any(term in normalized for term in build_terms)
    has_launch = any(term in normalized for term in launch_terms)
    has_audit = any(term in normalized for term in audit_terms)

    if has_launch:
        return IntentRoute("launch", "L5_REVIEW", "Launch approved work", "request explicitly asks for deployment or release")
    if has_build:
        return IntentRoute("build", "L4_REVIEW", "Build and validate a scoped deliverable", "request asks for implementation work")
    if has_research and has_planning:
        return IntentRoute("planning", "L2_REVIEW", "Research a topic and lock a PRD", "request asks for research plus PRD/planning output")
    if has_planning:
        return IntentRoute("planning", "L2_REVIEW", "Create a PRD and locked plan", "request asks for planning or PRD output")
    if has_audit:
        return IntentRoute("audit", "L4_REVIEW", "Audit existing implementation and close findings", "request asks for audit/review work")
    return IntentRoute("research", "L1_REVIEW", "Research a topic and produce reviewed findings", "default fallback is research-first execution")


def workflow_id_from_request(request: str) -> str:
    ascii_words = re.findall(r"[a-z0-9]+", request.lower())
    prefix = "-".join(ascii_words[:4]).strip("-")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if prefix:
        return f"{prefix[:40]}-{stamp}"
    return f"workflow-{stamp}"


def intent_lock_path(workflow_id: str) -> Path:
    return ROOT / "workflows" / workflow_id / "intent-lock.json"


def runner_dir(workflow_id: str) -> Path:
    return ROOT / "workflows" / workflow_id / "runner"


def write_intent_lock(workflow_id: str, request: str, route: IntentRoute, runtime_name: str) -> dict[str, Any]:
    payload = {
        "version": "1.0.0",
        "workflow_id": workflow_id,
        "created_at": control_plane.utc_now(),
        "original_request": request,
        "normalized_goal": route.summary,
        "workflow_type": route.workflow_type,
        "target_state": route.target_state,
        "routing_rationale": route.rationale,
        "runtime": runtime_name,
        "status": "locked",
    }
    validate_intent_lock(payload)
    control_plane.write_json(intent_lock_path(workflow_id), payload)
    return payload


def update_state_metadata(workflow_id: str, route: IntentRoute, request: str, runtime_name: str) -> None:
    state = control_plane.load_state(workflow_id)
    state["workflow_type"] = route.workflow_type
    state["intent_summary"] = route.summary
    state["target_state"] = route.target_state
    state["automation"] = {
        "enabled": True,
        "runtime": runtime_name,
        "original_request": request,
        "last_updated": control_plane.utc_now(),
    }
    control_plane.write_json(control_plane.state_path(workflow_id), state)


def pick_adapter(name: str) -> RuntimeAdapter:
    if name == "codex":
        return CodexRuntimeAdapter()
    if name == "claude":
        return ClaudeRuntimeAdapter()
    raise AutomationRunnerError(f"unsupported runtime: {name}")


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
    workflow_root = ROOT / "workflows" / workflow_id
    skill_path = ROOT / agent["entrypoint"]
    intent_path = intent_lock_path(workflow_id)
    lines = [
        f"You are running inside the AEGIS automation runner as agent `{agent['id']}`.",
        f"Current workflow: `{workflow_id}`.",
        f"Current state: `{state_name}`.",
        f"Locked workflow type: `{route.workflow_type}`.",
        f"Target stop state for this request: `{route.target_state}`.",
        "",
        "Read and follow these sources of truth before acting:",
        f"- `{skill_path}`",
        f"- `{ROOT / '.aegis/core/registry.json'}`",
        f"- `{ROOT / '.aegis/core/orchestrator.yml'}`",
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
    ) -> None:
        self.adapter = adapter
        self.stop_before = set(stop_before or DEFAULT_STOP_BEFORE)
        self.max_steps = max_steps

    def bootstrap(self, request: str, workflow_id: str | None = None) -> tuple[str, IntentRoute]:
        control_plane.doctor()
        route = route_request(request)
        workflow_id = workflow_id or workflow_id_from_request(request)
        if control_plane.state_path(workflow_id).exists():
            raise AutomationRunnerError(f"workflow already exists: {workflow_id}")
        control_plane.pre_agent_run("orchestrator", workflow_id)
        runner_dir(workflow_id).mkdir(parents=True, exist_ok=True)
        write_intent_lock(workflow_id, request, route, self.adapter.name)
        update_state_metadata(workflow_id, route, request, self.adapter.name)
        control_plane.write_state_transition(workflow_id, "L1_RESEARCH")
        return workflow_id, route

    def bootstrap_summary(self, request: str, workflow_id: str | None = None) -> dict[str, Any]:
        workflow_id, route = self.bootstrap(request, workflow_id)
        return self.summary(workflow_id, route, "bootstrapped", steps=[])

    def run_request(self, request: str, workflow_id: str | None = None) -> dict[str, Any]:
        workflow_id, route = self.bootstrap(request, workflow_id)
        return self.resume(workflow_id, route=route)

    def resume(self, workflow_id: str, route: IntentRoute | None = None) -> dict[str, Any]:
        route = route or self.load_route(workflow_id)
        registry, orchestrator, _ = control_plane.get_context()
        steps: list[dict[str, Any]] = []
        for _ in range(self.max_steps):
            state = control_plane.load_state(workflow_id)
            current_state = state["current_state"]
            if current_state in {"DONE", "BLOCKED"}:
                return self.summary(workflow_id, route, "finished", steps)
            if current_state in self.stop_before or state_requires_human_input(registry, orchestrator, current_state):
                return self.summary(workflow_id, route, "paused_for_human", steps)

            step_agents = orchestrator["state_agents"].get(current_state, [])
            for agent_id in step_agents:
                if agent_id == "orchestrator":
                    continue
                steps.append(self.run_agent(workflow_id, route, current_state, agent_id, registry))

            state_after = control_plane.load_state(workflow_id)
            if target_satisfied(route, state_after):
                return self.summary(workflow_id, route, "completed_target", steps)

            next_state = state_after.get("next_state_hint")
            if not next_state:
                next_state = orchestrator["transitions"].get(current_state, {}).get("next")
            if not next_state:
                raise AutomationRunnerError(
                    f"runner could not determine next state from {current_state} for workflow {workflow_id}"
                )
            if next_state in self.stop_before or state_requires_human_input(registry, orchestrator, next_state):
                return self.summary(workflow_id, route, "paused_for_human", steps)
            control_plane.write_state_transition(workflow_id, next_state)
        raise AutomationRunnerError(f"runner exceeded max_steps={self.max_steps} for workflow {workflow_id}")

    def run_agent(
        self,
        workflow_id: str,
        route: IntentRoute,
        state_name: str,
        agent_id: str,
        registry: dict[str, Any],
    ) -> dict[str, Any]:
        agents = control_plane.registry_by_id(registry)
        agent = agents[agent_id]
        control_plane.pre_agent_run(agent_id, workflow_id)
        log_path = runner_dir(workflow_id) / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{state_name}-{agent_id}.log"
        use_search = any(
            dependency in {"contract:search_web", "contract:fetch_source"}
            for dependency in agent.get("dependencies", [])
        )
        prompt = prompt_for_agent(workflow_id=workflow_id, agent=agent, state_name=state_name, route=route)
        result = self.adapter.run(
            agent_id=agent_id,
            workflow_id=workflow_id,
            state_name=state_name,
            prompt=prompt,
            log_path=log_path,
            use_search=use_search,
        )
        control_plane.post_agent_run(agent_id, workflow_id)
        return {
            "state": state_name,
            "agent": agent_id,
            "runtime": self.adapter.name,
            "log_path": str(result.output_path.relative_to(ROOT)),
            "command": result.command,
        }

    def load_route(self, workflow_id: str) -> IntentRoute:
        payload = control_plane.load_json(intent_lock_path(workflow_id))
        validate_intent_lock(payload)
        return IntentRoute(
            workflow_type=payload["workflow_type"],
            target_state=payload["target_state"],
            summary=payload["normalized_goal"],
            rationale=payload["routing_rationale"],
        )

    def summary(self, workflow_id: str, route: IntentRoute, status: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
        state = control_plane.load_state(workflow_id)
        return {
            "workflow_id": workflow_id,
            "status": status,
            "workflow_type": route.workflow_type,
            "target_state": route.target_state,
            "current_state": state["current_state"],
            "next_state_hint": state.get("next_state_hint"),
            "active_review_loop": state.get("active_review_loop"),
            "steps": steps,
            "intent_lock": str(intent_lock_path(workflow_id).relative_to(ROOT)),
            "state_path": str(control_plane.state_path(workflow_id).relative_to(ROOT)),
        }


def print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AEGIS automation runner")
    sub = parser.add_subparsers(dest="command", required=True)

    bootstrap_cmd = sub.add_parser("bootstrap")
    bootstrap_cmd.add_argument("request")
    bootstrap_cmd.add_argument("--workflow-id")
    bootstrap_cmd.add_argument("--runtime", default="codex", choices=["codex", "claude"])

    run_cmd = sub.add_parser("run")
    run_cmd.add_argument("request")
    run_cmd.add_argument("--workflow-id")
    run_cmd.add_argument("--runtime", default="codex", choices=["codex", "claude"])
    run_cmd.add_argument("--max-steps", type=int, default=30)
    run_cmd.add_argument("--stop-before", action="append", default=[])

    resume_cmd = sub.add_parser("resume")
    resume_cmd.add_argument("--workflow", required=True)
    resume_cmd.add_argument("--runtime", default="codex", choices=["codex", "claude"])
    resume_cmd.add_argument("--max-steps", type=int, default=30)
    resume_cmd.add_argument("--stop-before", action="append", default=[])

    route_cmd = sub.add_parser("route")
    route_cmd.add_argument("request")

    args = parser.parse_args(argv)
    try:
        if args.command == "route":
            route = route_request(args.request)
            print_json(
                {
                    "workflow_type": route.workflow_type,
                    "target_state": route.target_state,
                    "normalized_goal": route.summary,
                    "routing_rationale": route.rationale,
                }
            )
            return 0

        if args.command == "bootstrap":
            adapter = pick_adapter(args.runtime)
            runner = AutomationRunner(adapter=adapter, stop_before=set(DEFAULT_STOP_BEFORE), max_steps=30)
            result = runner.bootstrap_summary(args.request, workflow_id=args.workflow_id)
        elif args.command == "run":
            adapter = pick_adapter(args.runtime)
            runner = AutomationRunner(
                adapter=adapter,
                stop_before=set(DEFAULT_STOP_BEFORE).union(set(args.stop_before)),
                max_steps=args.max_steps,
            )
            result = runner.run_request(args.request, workflow_id=args.workflow_id)
        elif args.command == "resume":
            adapter = pick_adapter(args.runtime)
            runner = AutomationRunner(
                adapter=adapter,
                stop_before=set(DEFAULT_STOP_BEFORE).union(set(args.stop_before)),
                max_steps=args.max_steps,
            )
            result = runner.resume(args.workflow)
        else:
            raise AutomationRunnerError(f"unsupported command: {args.command}")
        print_json(result)
        return 0
    except (AutomationRunnerError, control_plane.ControlPlaneError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
