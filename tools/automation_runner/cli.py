from __future__ import annotations

import argparse
import json
import os
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
    mode: str
    workflow_type: str
    target_state: str
    summary: str
    rationale: str
    team_action: str | None = None
    team_id: str | None = None
    team_scope: str | None = None
    team_request: str | None = None


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
                str(control_plane.workspace_root()),
                "-o",
                str(log_path),
                prompt,
            ]
        )
        env = os.environ.copy()
        existing_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = str(ROOT) if not existing_pythonpath else f"{ROOT}{os.pathsep}{existing_pythonpath}"
        env["AEGIS_CORE_ROOT"] = str(ROOT)
        env["AEGIS_WORKSPACE_ROOT"] = str(control_plane.workspace_root())
        completed = subprocess.run(cmd, text=True, capture_output=True, check=False, env=env)
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
        env = os.environ.copy()
        existing_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = str(ROOT) if not existing_pythonpath else f"{ROOT}{os.pathsep}{existing_pythonpath}"
        env["AEGIS_CORE_ROOT"] = str(ROOT)
        env["AEGIS_WORKSPACE_ROOT"] = str(control_plane.workspace_root())
        completed = subprocess.run(cmd, text=True, capture_output=True, check=False, env=env)
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
            target_state="TEAM_READY",
            summary="Create and install a reusable AEGIS Team Pack",
            rationale="request explicitly asks to create a long-lived team",
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
            target_state="TEAM_RUN_READY",
            summary=f"Prepare a Team Pack run for {invoked_team_id}",
            rationale="request targets an installed AEGIS Team Pack by name",
            team_action="invoke",
            team_id=invoked_team_id,
            team_scope=inferred_scope if inferred_scope != "global" else "all",
            team_request=team_request,
        )

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
        return IntentRoute(
            mode="workflow",
            workflow_type="launch",
            target_state="L5_REVIEW",
            summary="Launch approved work",
            rationale="request explicitly asks for deployment or release",
        )
    if has_build:
        return IntentRoute(
            mode="workflow",
            workflow_type="build",
            target_state="L4_REVIEW",
            summary="Build and validate a scoped deliverable",
            rationale="request asks for implementation work",
        )
    if has_research and has_planning:
        return IntentRoute(
            mode="workflow",
            workflow_type="planning",
            target_state="L2_REVIEW",
            summary="Research a topic and lock a PRD",
            rationale="request asks for research plus PRD/planning output",
        )
    if has_planning:
        return IntentRoute(
            mode="workflow",
            workflow_type="planning",
            target_state="L2_REVIEW",
            summary="Create a PRD and locked plan",
            rationale="request asks for planning or PRD output",
        )
    if has_audit:
        return IntentRoute(
            mode="workflow",
            workflow_type="audit",
            target_state="L4_REVIEW",
            summary="Audit existing implementation and close findings",
            rationale="request asks for audit/review work",
        )
    return IntentRoute(
        mode="workflow",
        workflow_type="research",
        target_state="L1_REVIEW",
        summary="Research a topic and produce reviewed findings",
        rationale="default fallback is research-first execution",
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
        "target_state": route.target_state,
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
    manifest = control_plane.load_json(control_plane.project_manifest_path())
    control_plane.validate_project_manifest(manifest)
    enabled_workflows = manifest.get("enabled_workflows", [])
    if enabled_workflows and route.workflow_type not in enabled_workflows:
        raise AutomationRunnerError(
            f"workflow type `{route.workflow_type}` is disabled for workspace `{manifest['project_id']}`"
        )


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
    control_plane.ensure_runtime_snapshot(workflow_id, workflow_type=route.workflow_type, refresh=True)
    control_plane.update_workflow_index(
        workflow_id,
        workspace=control_plane.workspace_root(),
        workflow_type=route.workflow_type,
        current_state=state["current_state"],
    )


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
    workflow_root = control_plane.workflow_root(workflow_id)
    skill_path = ROOT / agent["entrypoint"]
    intent_path = intent_lock_path(workflow_id)
    lines = [
        f"You are running inside the AEGIS automation runner as agent `{agent['id']}`.",
        f"Attached workspace root: `{control_plane.workspace_root()}`.",
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
    ) -> None:
        self.adapter = adapter
        self.stop_before = set(stop_before or DEFAULT_STOP_BEFORE)
        self.max_steps = max_steps

    def bootstrap(self, request: str, workflow_id: str | None = None) -> tuple[str, IntentRoute]:
        control_plane.doctor()
        control_plane.ensure_workspace_layout()
        route = route_request(request)
        if route.mode != "workflow":
            raise AutomationRunnerError("bootstrap() only supports workflow routes; use bootstrap_summary() for team-pack requests")
        ensure_route_enabled(route)
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
                explicit_workspace=control_plane.workspace_root(),
            )
            resolved_scope, team_dir, payload = control_plane.find_team_pack(
                route.team_id,
                route.team_scope or "all",
                control_plane.workspace_root(),
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
                "workspace_root": str(control_plane.workspace_root()),
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
                explicit_workspace=control_plane.workspace_root(),
            )
            run_id_line = next((line for line in messages if line.startswith("run_id: ")), None)
            if not run_id_line:
                raise AutomationRunnerError(f"team run did not return a run_id for {route.team_id}")
            run_id = run_id_line.split(": ", 1)[1]
            resolved_scope, _, payload = control_plane.find_team_pack(
                route.team_id,
                route.team_scope or "all",
                control_plane.workspace_root(),
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
                "workspace_root": str(control_plane.workspace_root()),
                "brief_json": control_plane.display_path(
                    control_plane.team_run_brief_path(payload["team_id"], resolved_scope, run_id, control_plane.workspace_root())
                ),
                "brief_markdown": control_plane.display_path(
                    control_plane.team_run_brief_markdown_path(
                        payload["team_id"], resolved_scope, run_id, control_plane.workspace_root()
                    )
                ),
                "messages": messages,
            }
        raise AutomationRunnerError(f"unsupported team action: {route.team_action}")

    def resume(self, workflow_id: str, route: IntentRoute | None = None) -> dict[str, Any]:
        route = route or self.load_route(workflow_id)
        _, registry, orchestrator, _ = control_plane.get_runtime_context(workflow_id)
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
            "log_path": control_plane.display_path(result.output_path),
            "command": result.command,
        }

    def load_route(self, workflow_id: str) -> IntentRoute:
        payload = control_plane.load_json(intent_lock_path(workflow_id))
        validate_intent_lock(payload)
        return IntentRoute(
            mode="workflow",
            workflow_type=payload["workflow_type"],
            target_state=payload["target_state"],
            summary=payload["normalized_goal"],
            rationale=payload["routing_rationale"],
        )

    def summary(self, workflow_id: str, route: IntentRoute, status: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
        state = control_plane.load_state(workflow_id)
        return {
            "workflow_id": workflow_id,
            "workspace_root": str(control_plane.workspace_root()),
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AEGIS automation runner")
    parser.add_argument("--workspace", help="Workspace root for the attached project")
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
