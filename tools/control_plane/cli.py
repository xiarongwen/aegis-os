from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / ".aegis/core/registry.json"
REGISTRY_SCHEMA_PATH = ROOT / ".aegis/core/registry.schema.json"
ORCHESTRATOR_PATH = ROOT / ".aegis/core/orchestrator.yml"
CONTRACTS_PATH = ROOT / "shared-contexts/tool-contracts.yml"
HOST_CAPABILITY_MAP_PATH = ROOT / "shared-contexts/host-capability-map.yml"
EVOLUTION_LOG_PATH = ROOT / ".aegis/core/evolution.log"
REQUIREMENTS_LOCK_SCHEMA_PATH = ROOT / "shared-contexts/requirements-lock-schema.json"
REQUIREMENTS_TRACEABILITY_SCHEMA_PATH = ROOT / "shared-contexts/requirements-traceability-schema.json"
REVIEW_LOOP_SCHEMA_PATH = ROOT / "shared-contexts/review-loop-status-schema.json"
TASK_BREAKDOWN_SCHEMA_PATH = ROOT / "shared-contexts/task-breakdown-schema.json"
IMPLEMENTATION_CONTRACTS_SCHEMA_PATH = ROOT / "shared-contexts/implementation-contracts-schema.json"
REUSE_AUDIT_SCHEMA_PATH = ROOT / "shared-contexts/reuse-audit-schema.json"
SKILLS_DIR = Path.home() / ".claude/skills"
FORBIDDEN_TOKENS = ["WebSearch", "AskUserQuestion", "mcp__fetch__fetch", "superpowers:", "Agent({"]
WORKFLOW_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-_]{1,62}$")


class ControlPlaneError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def normalize(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True))


def render_template(value: str, workflow: str) -> Path:
    return ROOT / value.replace("{workflow}", workflow)


def get_context() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    return load_json(REGISTRY_PATH), load_json(ORCHESTRATOR_PATH), load_json(CONTRACTS_PATH)


def registry_by_id(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {agent["id"]: agent for agent in registry["agents"]}


def validate_registry_schema(registry: dict[str, Any]) -> list[str]:
    schema = load_json(REGISTRY_SCHEMA_PATH)
    errors: list[str] = []
    for key in schema["required"]:
        if key not in registry:
            errors.append(f"registry missing required key: {key}")
    capability_ids = set()
    for capability in registry.get("capabilities", []):
        for key in schema["properties"]["capabilities"]["items"]["required"]:
            if key not in capability:
                errors.append(f"capability {capability.get('id', '<unknown>')} missing required key: {key}")
        capability_id = capability.get("id")
        if capability_id in capability_ids:
            errors.append(f"duplicate capability id: {capability_id}")
        capability_ids.add(capability_id)
    workflow_type_ids = set()
    for workflow_type in registry.get("workflow_types", []):
        for key in schema["properties"]["workflow_types"]["items"]["required"]:
            if key not in workflow_type:
                errors.append(f"workflow type {workflow_type.get('id', '<unknown>')} missing required key: {key}")
        workflow_type_id = workflow_type.get("id")
        if workflow_type_id in workflow_type_ids:
            errors.append(f"duplicate workflow type id: {workflow_type_id}")
        workflow_type_ids.add(workflow_type_id)
    agents = registry.get("agents", [])
    if not isinstance(agents, list) or not agents:
        errors.append("registry agents must be a non-empty list")
        return errors
    required_agent_keys = schema["properties"]["agents"]["items"]["required"]
    seen_ids: set[str] = set()
    for agent in agents:
        for key in required_agent_keys:
            if key not in agent:
                errors.append(f"agent {agent.get('id', '<unknown>')} missing required key: {key}")
        agent_id = agent.get("id")
        if not isinstance(agent_id, str) or not agent_id:
            errors.append("agent id must be a non-empty string")
            continue
        if agent_id in seen_ids:
            errors.append(f"duplicate agent id: {agent_id}")
        seen_ids.add(agent_id)
        for capability_id in agent.get("capabilities", []):
            if capability_id not in capability_ids:
                errors.append(f"agent {agent_id} references unknown capability: {capability_id}")
        for workflow_type_id in agent.get("workflow_types", []):
            if workflow_type_id not in workflow_type_ids:
                errors.append(f"agent {agent_id} references unknown workflow type: {workflow_type_id}")
    return errors


def validate_orchestrator(registry: dict[str, Any], orchestrator: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    agents = registry_by_id(registry)
    states = set(orchestrator.get("states", []))
    workflow_type_ids = {workflow_type["id"] for workflow_type in registry.get("workflow_types", [])}
    if orchestrator.get("initial_state") not in states:
        errors.append("orchestrator initial_state must be one of the declared states")
    for workflow_type_id, metadata in orchestrator.get("workflow_types", {}).items():
        if workflow_type_id not in workflow_type_ids:
            errors.append(f"orchestrator references unknown workflow type: {workflow_type_id}")
        for state in metadata.get("entry_states", []):
            if state not in states:
                errors.append(f"workflow type {workflow_type_id} references unknown state: {state}")
    for state, agent_ids in orchestrator.get("state_agents", {}).items():
        if state not in states:
            errors.append(f"state_agents references unknown state: {state}")
        for agent_id in agent_ids:
            if agent_id not in agents:
                errors.append(f"state_agents references unknown agent: {agent_id}")
    for state, transition in orchestrator.get("transitions", {}).items():
        if state not in states:
            errors.append(f"transition declared for unknown state: {state}")
        for key, value in transition.items():
            if key != "max_rounds" and isinstance(value, str) and value not in states:
                errors.append(f"transition {state}.{key} references unknown state: {value}")
    for gate_state, gate in orchestrator.get("gates", {}).items():
        reviewer = gate["reviewer"]
        if reviewer not in agents:
            errors.append(f"gate {gate_state} references missing reviewer: {reviewer}")
        for reviewed_agent in gate.get("reviews_agents", []):
            if reviewed_agent not in agents:
                errors.append(f"gate {gate_state} reviews missing agent: {reviewed_agent}")
            if reviewed_agent == reviewer:
                errors.append(f"gate {gate_state} reviewer {reviewer} is not independent")
        review_loop = gate.get("review_loop")
        if review_loop:
            fix_state = review_loop.get("fix_state")
            if fix_state and fix_state not in states:
                errors.append(f"gate {gate_state} review_loop references unknown fix_state: {fix_state}")
            for fixer in review_loop.get("fixer_agents", []):
                if fixer not in agents:
                    errors.append(f"gate {gate_state} review_loop references unknown fixer agent: {fixer}")
    return errors


def validate_contracts(registry: dict[str, Any], contracts: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    known = contracts.get("abstract_actions", {})
    for agent in registry["agents"]:
        for action in agent.get("contract_actions", []):
            if action not in known:
                errors.append(f"agent {agent['id']} references missing contract action: {action}")
        for dependency in agent.get("dependencies", []):
            if dependency.startswith("contract:") and dependency.split(":", 1)[1] not in known:
                errors.append(f"agent {agent['id']} depends on missing contract: {dependency}")
    for skill_path in ROOT.glob("agents/*/SKILL.md"):
        content = skill_path.read_text(encoding="utf-8")
        for token in FORBIDDEN_TOKENS:
            if token in content:
                errors.append(f"{skill_path.relative_to(ROOT)} contains forbidden runtime token: {token}")
    return errors


def validate_required_keys(payload: dict[str, Any], schema_path: Path, label: str) -> None:
    schema = load_json(schema_path)
    missing = [key for key in schema["required"] if key not in payload]
    if missing:
        raise ControlPlaneError(f"{label} missing required keys: {', '.join(missing)}")


def requirements_lock_path(workflow: str) -> Path:
    return ROOT / "workflows" / workflow / "l2-planning" / "requirements-lock.json"


def task_breakdown_path(workflow: str) -> Path:
    return ROOT / "workflows" / workflow / "l2-planning" / "task_breakdown.json"


def implementation_contracts_path(workflow: str) -> Path:
    return ROOT / "workflows" / workflow / "l2-planning" / "implementation-contracts.json"


def requirements_traceability_path(workflow: str) -> Path:
    return ROOT / "workflows" / workflow / "l4-validation" / "requirements-traceability.json"


def reuse_audit_path(workflow: str, agent_id: str) -> Path:
    if agent_id not in {"frontend-squad", "backend-squad"}:
        raise ControlPlaneError(f"reuse audit path is only defined for development agents, got {agent_id}")
    slug = "frontend" if agent_id == "frontend-squad" else "backend"
    return ROOT / "workflows" / workflow / "l3-dev" / slug / "reuse-audit.json"


def gate_artifact_dir(workflow: str, gate_state: str, orchestrator: dict[str, Any]) -> Path:
    gate = orchestrator["gates"][gate_state]
    return render_template(gate["artifact_dir"], workflow)


def compute_requirements_lock_hash(payload: dict[str, Any]) -> str:
    canonical = deepcopy(payload)
    canonical.pop("lock_hash", None)
    body = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def enforce_requirements_lock(state: dict[str, Any], workflow: str, state_name: str) -> None:
    guarded_states = {
        "L3_DEVELOP",
        "L3_CODE_REVIEW",
        "L3_SECURITY_AUDIT",
        "L4_VALIDATE",
        "L4_REVIEW",
        "L5_DEPLOY",
        "L5_REVIEW",
        "DONE"
    }
    if state_name not in guarded_states:
        return
    lock_path = requirements_lock_path(workflow)
    if not lock_path.exists():
        raise ControlPlaneError(f"missing locked requirements artifact: {lock_path.relative_to(ROOT)}")
    payload = load_json(lock_path)
    validate_required_keys(payload, REQUIREMENTS_LOCK_SCHEMA_PATH, lock_path.relative_to(ROOT).as_posix())
    computed_hash = compute_requirements_lock_hash(payload)
    state_hash = state.get("requirements_lock_hash")
    if not state_hash:
        raise ControlPlaneError("workflow state is missing requirements_lock_hash")
    if payload.get("lock_hash") != computed_hash:
        raise ControlPlaneError(f"{lock_path.relative_to(ROOT)} contains an invalid lock_hash")
    if state_hash != computed_hash:
        raise ControlPlaneError("workflow requirements_lock_hash does not match requirements-lock.json")


def validate_review_loop_status(path: Path, workflow: str, gate_state: str, gate: dict[str, Any]) -> dict[str, Any]:
    payload = load_json(path)
    validate_required_keys(payload, REVIEW_LOOP_SCHEMA_PATH, path.relative_to(ROOT).as_posix())
    review_loop = gate["review_loop"]
    if payload["workflow_id"] != workflow:
        raise ControlPlaneError(f"{path.relative_to(ROOT)} workflow_id mismatch")
    if payload["gate"] != gate_state:
        raise ControlPlaneError(f"{path.relative_to(ROOT)} gate mismatch: expected {gate_state}")
    if payload["status"] not in review_loop["allowed_statuses"]:
        raise ControlPlaneError(f"{path.relative_to(ROOT)} has invalid status {payload['status']}")
    if not isinstance(payload["round"], int) or payload["round"] < 1:
        raise ControlPlaneError(f"{path.relative_to(ROOT)} round must be a positive integer")
    if payload["round"] > review_loop["max_rounds"]:
        raise ControlPlaneError(f"{path.relative_to(ROOT)} round exceeds max_rounds")
    if payload["max_rounds"] != review_loop["max_rounds"]:
        raise ControlPlaneError(f"{path.relative_to(ROOT)} max_rounds does not match gate configuration")
    if payload["round"] == review_loop["max_rounds"] and payload["status"] == "changes_requested":
        raise ControlPlaneError(f"{path.relative_to(ROOT)} cannot request more changes at the max review round")
    if not isinstance(payload["open_issues"], list) or not isinstance(payload["closed_issues"], list):
        raise ControlPlaneError(f"{path.relative_to(ROOT)} open_issues and closed_issues must be lists")
    if payload["status"] == "changes_requested":
        if payload["lgtm"]:
            raise ControlPlaneError(f"{path.relative_to(ROOT)} changes_requested status cannot set lgtm=true")
        if not payload["open_issues"]:
            raise ControlPlaneError(f"{path.relative_to(ROOT)} changes_requested status requires open issues")
    if payload["status"] == "blocked" and not payload["open_issues"]:
        raise ControlPlaneError(f"{path.relative_to(ROOT)} blocked status requires open issues")
    if payload["status"] == "lgtm":
        if not payload["lgtm"]:
            raise ControlPlaneError(f"{path.relative_to(ROOT)} lgtm status must set lgtm=true")
        if payload["open_issues"]:
            raise ControlPlaneError(f"{path.relative_to(ROOT)} lgtm status cannot have open issues")
        if payload["verdict"] != "LGTM":
            raise ControlPlaneError(f"{path.relative_to(ROOT)} lgtm status must use verdict LGTM")
    return payload


def validate_fix_response_artifact(path: Path) -> None:
    if not path.exists():
        raise ControlPlaneError(f"missing fix response artifact: {path.relative_to(ROOT)}")
    if path.stat().st_size == 0:
        raise ControlPlaneError(f"empty fix response artifact: {path.relative_to(ROOT)}")


def validate_skill_contract_mentions(registry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for agent in registry["agents"]:
        skill_path = ROOT / agent["entrypoint"]
        if not skill_path.exists():
            errors.append(f"missing skill file for agent {agent['id']}: {skill_path.relative_to(ROOT)}")
            continue
        content = skill_path.read_text(encoding="utf-8")
        for action in agent.get("contract_actions", []):
            if f"`{action}`" not in content:
                errors.append(f"{skill_path.relative_to(ROOT)} does not mention required contract `{action}`")
    return errors


def validate_host_capability_map(contracts: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    capability_map = load_json(HOST_CAPABILITY_MAP_PATH)
    required_runtimes = {"codex", "claude"}
    runtimes = capability_map.get("runtimes", {})
    for runtime_name in required_runtimes:
        if runtime_name not in runtimes:
            errors.append(f"host capability map missing runtime profile: {runtime_name}")
            continue
        runtime_profile = runtimes[runtime_name]
        host_capabilities = runtime_profile.get("host_capabilities", {})
        action_bindings = runtime_profile.get("action_bindings", {})
        if not host_capabilities:
            errors.append(f"host capability map runtime {runtime_name} missing host_capabilities")
        for action_name in contracts.get("abstract_actions", {}):
            binding = action_bindings.get(action_name)
            if not binding:
                errors.append(f"host capability map runtime {runtime_name} missing action binding for {action_name}")
                continue
            capability_id = binding.get("capability")
            if capability_id not in host_capabilities:
                errors.append(
                    f"host capability map runtime {runtime_name} action {action_name} references unknown capability {capability_id}"
                )
            if "primary" not in binding or "fallback" not in binding:
                errors.append(f"host capability map runtime {runtime_name} action {action_name} missing primary/fallback")
    return errors


def overlaps_scope(left: str, right: str) -> bool:
    left_norm = left.rstrip("/")
    right_norm = right.rstrip("/")
    left_prefix = left_norm[:-3] if left_norm.endswith("/**") else left_norm
    right_prefix = right_norm[:-3] if right_norm.endswith("/**") else right_norm
    return (
        left_prefix == right_prefix
        or left_prefix.startswith(right_prefix + "/")
        or right_prefix.startswith(left_prefix + "/")
    )


def validate_task_breakdown(payload: dict[str, Any], workflow: str, registry: dict[str, Any], orchestrator: dict[str, Any]) -> None:
    validate_required_keys(payload, TASK_BREAKDOWN_SCHEMA_PATH, task_breakdown_path(workflow).relative_to(ROOT).as_posix())
    if payload["workflow_id"] != workflow:
        raise ControlPlaneError("task_breakdown workflow_id mismatch")
    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ControlPlaneError("task_breakdown tasks must be a non-empty list")
    controls = orchestrator.get("development_controls", {})
    required_principles = set(controls.get("required_principles", []))
    principles = set(payload.get("development_principles", []))
    missing_principles = required_principles - principles
    if missing_principles:
        raise ControlPlaneError(f"task_breakdown missing required development principles: {', '.join(sorted(missing_principles))}")
    parallel_execution = payload.get("parallel_execution", {})
    if parallel_execution.get("default_mode") != "parallel_by_default":
        raise ControlPlaneError("task_breakdown must declare parallel_execution.default_mode=parallel_by_default")
    agents = registry_by_id(registry)
    seen_ids: set[str] = set()
    parallel_groups: dict[str, list[dict[str, Any]]] = {}
    for task in tasks:
        required_keys = load_json(TASK_BREAKDOWN_SCHEMA_PATH)["task_required"]
        missing = [key for key in required_keys if key not in task]
        if missing:
            raise ControlPlaneError(f"task_breakdown task missing keys: {', '.join(missing)}")
        task_id = task["id"]
        if task_id in seen_ids:
            raise ControlPlaneError(f"duplicate task id in task_breakdown: {task_id}")
        seen_ids.add(task_id)
        if task["owner"] not in agents:
            raise ControlPlaneError(f"task {task_id} references unknown owner: {task['owner']}")
        if task["stage"] != "L3_DEVELOP":
            raise ControlPlaneError(f"task {task_id} must target L3_DEVELOP")
        if not isinstance(task["write_scope"], list) or not task["write_scope"]:
            raise ControlPlaneError(f"task {task_id} must declare a non-empty write_scope list")
        if not isinstance(task["acceptance_criteria"], list) or not task["acceptance_criteria"]:
            raise ControlPlaneError(f"task {task_id} must declare acceptance_criteria")
        if not isinstance(task["dry_reuse_targets"], list) or not task["dry_reuse_targets"]:
            raise ControlPlaneError(f"task {task_id} must declare dry_reuse_targets")
        if not isinstance(task["host_capability_needs"], list):
            raise ControlPlaneError(f"task {task_id} host_capability_needs must be a list")
        parallel_groups.setdefault(task["parallel_group"], []).append(task)
    if controls.get("parallel_scope_conflict_check"):
        for group_name, group_tasks in parallel_groups.items():
            for index, left in enumerate(group_tasks):
                for right in group_tasks[index + 1:]:
                    if left["owner"] == right["owner"]:
                        continue
                    if left["id"] in right["depends_on"] or right["id"] in left["depends_on"]:
                        continue
                    for left_scope in left["write_scope"]:
                        for right_scope in right["write_scope"]:
                            if overlaps_scope(left_scope, right_scope):
                                raise ControlPlaneError(
                                    f"parallel write scope conflict in group {group_name}: {left['id']} vs {right['id']}"
                                )


def validate_implementation_contracts(
    payload: dict[str, Any],
    workflow: str,
    registry: dict[str, Any],
    task_breakdown: dict[str, Any],
) -> None:
    validate_required_keys(
        payload,
        IMPLEMENTATION_CONTRACTS_SCHEMA_PATH,
        implementation_contracts_path(workflow).relative_to(ROOT).as_posix(),
    )
    if payload["workflow_id"] != workflow:
        raise ControlPlaneError("implementation contracts workflow_id mismatch")
    agents = registry_by_id(registry)
    owned_write_scopes = payload.get("owned_write_scopes", {})
    if not isinstance(owned_write_scopes, dict) or not owned_write_scopes:
        raise ControlPlaneError("implementation contracts must define owned_write_scopes")
    for owner, scopes in owned_write_scopes.items():
        if owner not in agents:
            raise ControlPlaneError(f"implementation contracts reference unknown owner: {owner}")
        if not isinstance(scopes, list) or not scopes:
            raise ControlPlaneError(f"implementation contracts owner {owner} must have at least one write scope")
    for task in task_breakdown["tasks"]:
        owner_scopes = owned_write_scopes.get(task["owner"], [])
        for task_scope in task["write_scope"]:
            if not any(overlaps_scope(task_scope, owner_scope) for owner_scope in owner_scopes):
                raise ControlPlaneError(
                    f"implementation contracts do not cover task {task['id']} scope {task_scope} for owner {task['owner']}"
                )


def validate_reuse_audit(
    payload: dict[str, Any],
    workflow: str,
    agent_id: str,
    requirements_hash: str,
    contracts: dict[str, Any],
) -> None:
    validate_required_keys(payload, REUSE_AUDIT_SCHEMA_PATH, reuse_audit_path(workflow, agent_id).relative_to(ROOT).as_posix())
    if not requirements_hash:
        raise ControlPlaneError(f"workflow is missing requirements_lock_hash before validating reuse audit for {agent_id}")
    if payload["workflow_id"] != workflow:
        raise ControlPlaneError(f"reuse audit workflow_id mismatch for {agent_id}")
    if payload["agent_id"] != agent_id:
        raise ControlPlaneError(f"reuse audit agent_id mismatch for {agent_id}")
    if payload["requirements_lock_hash"] != requirements_hash:
        raise ControlPlaneError(f"reuse audit requirements_lock_hash mismatch for {agent_id}")
    if not isinstance(payload["completed_tasks"], list) or not payload["completed_tasks"]:
        raise ControlPlaneError(f"reuse audit must list completed_tasks for {agent_id}")
    if not isinstance(payload["scanned_existing_assets"], list) or not payload["scanned_existing_assets"]:
        raise ControlPlaneError(f"reuse audit must list scanned_existing_assets for {agent_id}")
    if not isinstance(payload["duplication_risk_checks"], list) or not payload["duplication_risk_checks"]:
        raise ControlPlaneError(f"reuse audit must record duplication_risk_checks for {agent_id}")
    if not isinstance(payload["host_capabilities_used"], list):
        raise ControlPlaneError(f"reuse audit host_capabilities_used must be a list for {agent_id}")
    known_actions = set(contracts.get("abstract_actions", {}))
    for item in payload["host_capabilities_used"]:
        if "action" not in item or "resolution" not in item:
            raise ControlPlaneError(f"reuse audit host capability entries must include action and resolution for {agent_id}")
        if item["action"] not in known_actions:
            raise ControlPlaneError(f"reuse audit references unknown abstract action {item['action']} for {agent_id}")


def expected_agent_payload(agent: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(agent)


def sync_agent_metadata(check_only: bool = False) -> list[str]:
    registry, _, _ = get_context()
    messages: list[str] = []
    for agent in registry["agents"]:
        target_path = ROOT / "agents" / agent["id"] / "agent.json"
        if not target_path.parent.exists():
            messages.append(f"missing agent directory for {agent['id']}")
            continue
        desired = expected_agent_payload(agent)
        actual = load_json(target_path) if target_path.exists() else None
        if normalize(actual) != normalize(desired):
            if check_only:
                messages.append(f"derived metadata drift: {target_path.relative_to(ROOT)}")
            else:
                write_json(target_path, desired)
                messages.append(f"synced {target_path.relative_to(ROOT)}")
    return messages


def ensure_skill_symlinks() -> list[str]:
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    messages: list[str] = []
    for skill_dir in sorted((ROOT / "agents").iterdir()):
        if not skill_dir.is_dir() or not (skill_dir / "SKILL.md").exists():
            continue
        target = SKILLS_DIR / skill_dir.name
        if target.is_symlink() or target.exists():
            if target.is_symlink() and target.resolve() == skill_dir.resolve():
                messages.append(f"linked {skill_dir.name}")
                continue
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink()
        target.symlink_to(skill_dir)
        messages.append(f"linked {skill_dir.name}")
    return messages


def doctor() -> list[str]:
    registry, orchestrator, contracts = get_context()
    errors: list[str] = []
    errors.extend(validate_registry_schema(registry))
    errors.extend(validate_orchestrator(registry, orchestrator))
    errors.extend(validate_contracts(registry, contracts))
    errors.extend(validate_host_capability_map(contracts))
    errors.extend(validate_skill_contract_mentions(registry))
    errors.extend(sync_agent_metadata(check_only=True))
    if errors:
        raise ControlPlaneError("\n".join(errors))
    return [
        "registry schema valid",
        "orchestrator valid",
        "tool contracts valid",
        "host capability map valid",
        "skill contracts valid",
        "agent metadata synced",
    ]


def state_path(workflow: str) -> Path:
    return ROOT / "workflows" / workflow / "state.json"


def legal_next_states(state: dict[str, Any], orchestrator: dict[str, Any]) -> set[str]:
    transition = orchestrator["transitions"].get(state["current_state"], {})
    if state.get("next_state_hint"):
        return {state["next_state_hint"]}
    return {
        value
        for key, value in transition.items()
        if key != "max_rounds" and isinstance(value, str)
    }


def write_state_transition(workflow: str, target_state: str) -> list[str]:
    validate_workflow_id(workflow)
    _, orchestrator, _ = get_context()
    state = load_state(workflow)
    current_state = state["current_state"]
    declared_states = set(orchestrator.get("states", []))
    if target_state not in declared_states:
        raise ControlPlaneError(f"unknown target state: {target_state}")
    allowed = legal_next_states(state, orchestrator)
    if target_state not in allowed:
        allowed_display = ", ".join(sorted(allowed)) or "<none>"
        raise ControlPlaneError(
            f"illegal state transition for {workflow}: {current_state} -> {target_state} (allowed: {allowed_display})"
        )
    state.setdefault("history", []).append(
        {
            "from": current_state,
            "to": target_state,
            "transitioned_at": utc_now()
        }
    )
    state["current_state"] = target_state
    state["next_state_hint"] = None
    if target_state == "BLOCKED":
        state.setdefault("blockers", []).append(
            {
                "state": current_state,
                "blocked_at": utc_now(),
                "active_review_loop": deepcopy(state.get("active_review_loop"))
            }
        )
    write_json(state_path(workflow), state)
    return [f"advanced workflow {workflow}: {current_state} -> {target_state}"]


def initialize_workflow(workflow: str) -> dict[str, Any]:
    workflow_root = ROOT / "workflows" / workflow
    for path in [
        workflow_root / "l1-intelligence",
        workflow_root / "l2-planning",
        workflow_root / "l3-dev" / "frontend",
        workflow_root / "l3-dev" / "backend",
        workflow_root / "l4-validation",
        workflow_root / "l5-release"
    ]:
        path.mkdir(parents=True, exist_ok=True)
    payload = {
        "workflow_id": workflow,
        "current_state": "INIT",
        "started_at": utc_now(),
        "history": [],
        "blockers": [],
        "retries": {},
        "requirements_lock_hash": None,
        "review_loops": {},
        "active_review_loop": None,
        "next_state_hint": None,
        "workflow_type": None
    }
    write_json(state_path(workflow), payload)
    return payload


def load_state(workflow: str) -> dict[str, Any]:
    target = state_path(workflow)
    if not target.exists():
        raise ControlPlaneError(f"workflow state missing: {target.relative_to(ROOT)}")
    return load_json(target)


def validate_workflow_id(workflow: str) -> None:
    if not WORKFLOW_ID_PATTERN.fullmatch(workflow):
        raise ControlPlaneError("workflow id must match ^[a-z0-9][a-z0-9-_]{1,62}$")


def validate_inputs(agent: dict[str, Any], workflow: str) -> None:
    missing = []
    for item in agent.get("inputs", []):
        optional = item.endswith("?")
        raw = item[:-1] if optional else item
        if raw.startswith("human:"):
            continue
        if not render_template(raw, workflow).exists() and not optional:
            missing.append(item)
    if missing:
        raise ControlPlaneError(f"agent {agent['id']} missing required inputs: {', '.join(missing)}")


def validate_dependencies(agent: dict[str, Any], contracts: dict[str, Any]) -> None:
    known = contracts["abstract_actions"]
    for dependency in agent.get("dependencies", []):
        if dependency.startswith("contract:"):
            action = dependency.split(":", 1)[1]
            if action not in known:
                raise ControlPlaneError(f"agent {agent['id']} depends on unknown contract: {action}")


def pre_agent_run(agent_id: str, workflow: str) -> list[str]:
    validate_workflow_id(workflow)
    registry, orchestrator, contracts = get_context()
    agents = registry_by_id(registry)
    if agent_id not in agents:
        raise ControlPlaneError(f"agent {agent_id} not found in registry")
    if agent_id == "orchestrator" and not state_path(workflow).exists():
        state = initialize_workflow(workflow)
    else:
        state = load_state(workflow)
    enforce_requirements_lock(state, workflow, state["current_state"])
    if agents[agent_id]["allowed_states"] and state["current_state"] not in agents[agent_id]["allowed_states"]:
        raise ControlPlaneError(f"agent {agent_id} is not allowed in state {state['current_state']}")
    active_loop = state.get("active_review_loop")
    if active_loop and state["current_state"] == active_loop.get("fix_state"):
        if agent_id not in active_loop.get("fixer_agents", []):
            raise ControlPlaneError(
                f"agent {agent_id} is not allowed to respond to active review loop for {active_loop['gate']}"
            )
    validate_inputs(agents[agent_id], workflow)
    validate_dependencies(agents[agent_id], contracts)
    if state["current_state"] == "L3_DEVELOP":
        breakdown_path = task_breakdown_path(workflow)
        implementation_path = implementation_contracts_path(workflow)
        if not breakdown_path.exists():
            raise ControlPlaneError(f"missing L3 planning artifact: {breakdown_path.relative_to(ROOT)}")
        if not implementation_path.exists():
            raise ControlPlaneError(f"missing L3 planning artifact: {implementation_path.relative_to(ROOT)}")
        breakdown = load_json(breakdown_path)
        validate_task_breakdown(breakdown, workflow, registry, orchestrator)
        contracts_payload = load_json(implementation_path)
        validate_implementation_contracts(contracts_payload, workflow, registry, breakdown)
        if agent_id in {"frontend-squad", "backend-squad"}:
            assigned_tasks = [task for task in breakdown["tasks"] if task["owner"] == agent_id]
            if not assigned_tasks:
                raise ControlPlaneError(f"agent {agent_id} has no assigned L3 tasks in task_breakdown.json")
    return [f"pre-run validation passed for {agent_id} in workflow {workflow}"]


def validate_review_artifact(path: Path, expected_reviewer: str, min_score: float) -> None:
    payload = load_json(path)
    for key in ["score", "reviewer", "blockers", "suggestions", "approved_at"]:
        if key not in payload:
            raise ControlPlaneError(f"{path.relative_to(ROOT)} missing review key: {key}")
    if payload["reviewer"] != expected_reviewer:
        raise ControlPlaneError(f"{path.relative_to(ROOT)} reviewer mismatch: expected {expected_reviewer}, got {payload['reviewer']}")
    if not isinstance(payload["score"], (int, float)):
        raise ControlPlaneError(f"{path.relative_to(ROOT)} score must be numeric")
    if not isinstance(payload["blockers"], list) or not isinstance(payload["suggestions"], list):
        raise ControlPlaneError(f"{path.relative_to(ROOT)} blockers and suggestions must be lists")
    if payload["score"] < min_score and not payload["blockers"]:
        raise ControlPlaneError(f"{path.relative_to(ROOT)} score below threshold {min_score} without blockers")


def validate_outputs(agent_id: str, workflow: str, state_name: str) -> None:
    registry, orchestrator, _ = get_context()
    agents = registry_by_id(registry)
    if state_name in orchestrator["gates"]:
        gate = orchestrator["gates"][state_name]
        artifact_dir = gate_artifact_dir(workflow, state_name, orchestrator)
        for output_name in gate["required_outputs"]:
            target = artifact_dir / output_name
            if not target.exists():
                raise ControlPlaneError(f"missing gate output: {target.relative_to(ROOT)}")
        review_loop = gate.get("review_loop")
        if review_loop and review_loop.get("enabled"):
            loop_status_path = artifact_dir / review_loop["status_artifact"]
            if not loop_status_path.exists():
                raise ControlPlaneError(f"missing review loop status artifact: {loop_status_path.relative_to(ROOT)}")
            loop_status = validate_review_loop_status(loop_status_path, workflow, state_name, gate)
            round_report = artifact_dir / review_loop["round_report_pattern"].format(round=loop_status["round"])
            if not round_report.exists():
                raise ControlPlaneError(f"missing review round artifact: {round_report.relative_to(ROOT)}")
            if loop_status["status"] == "re_review":
                raise ControlPlaneError(
                    f"reviewer output cannot finish in re_review status: {loop_status_path.relative_to(ROOT)}"
                )
            review_passed_path = artifact_dir / "review-passed.json"
            if loop_status["status"] == "lgtm":
                if not review_passed_path.exists():
                    raise ControlPlaneError(f"missing review-passed.json for lgtm gate: {review_passed_path.relative_to(ROOT)}")
                validate_review_artifact(review_passed_path, gate["reviewer"], gate["min_score"])
            elif review_passed_path.exists():
                raise ControlPlaneError(
                    f"review-passed.json must only exist after LGTM: {review_passed_path.relative_to(ROOT)}"
                )
            return
        validate_review_artifact(artifact_dir / "review-passed.json", gate["reviewer"], gate["min_score"])
        return
    state = load_state(workflow)
    active_loop = state.get("active_review_loop")
    if active_loop and state_name == active_loop.get("fix_state"):
        artifact_dir = gate_artifact_dir(workflow, active_loop["gate"], orchestrator)
        fix_response = artifact_dir / active_loop["fix_response_pattern"].format(round=active_loop["round"])
        validate_fix_response_artifact(fix_response)
    for item in agents[agent_id]["outputs"]:
        target = render_template(item, workflow)
        if item.endswith("/"):
            if not target.exists() or not target.is_dir():
                raise ControlPlaneError(f"missing output directory: {target.relative_to(ROOT)}")
            if not any(target.iterdir()):
                raise ControlPlaneError(f"output directory is empty: {target.relative_to(ROOT)}")
        else:
            if not target.exists():
                raise ControlPlaneError(f"missing output file: {target.relative_to(ROOT)}")


def git(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(cwd or ROOT), check=check, text=True, capture_output=True)


def post_agent_run(agent_id: str, workflow: str) -> list[str]:
    registry, orchestrator, contracts = get_context()
    state = load_state(workflow)
    validate_outputs(agent_id, workflow, state["current_state"])
    active_loop = state.get("active_review_loop")
    if state["current_state"] == "L2_PLANNING":
        breakdown_path = task_breakdown_path(workflow)
        implementation_path = implementation_contracts_path(workflow)
        if not breakdown_path.exists():
            raise ControlPlaneError(f"missing planning artifact: {breakdown_path.relative_to(ROOT)}")
        if not implementation_path.exists():
            raise ControlPlaneError(f"missing planning artifact: {implementation_path.relative_to(ROOT)}")
        breakdown_payload = load_json(breakdown_path)
        validate_task_breakdown(breakdown_payload, workflow, registry, orchestrator)
        implementation_payload = load_json(implementation_path)
        validate_implementation_contracts(implementation_payload, workflow, registry, breakdown_payload)
        lock_path = requirements_lock_path(workflow)
        payload = load_json(lock_path)
        validate_required_keys(payload, REQUIREMENTS_LOCK_SCHEMA_PATH, lock_path.relative_to(ROOT).as_posix())
        lock_hash = compute_requirements_lock_hash(payload)
        payload["lock_hash"] = lock_hash
        write_json(lock_path, payload)
        state["requirements_lock_hash"] = lock_hash
        write_json(state_path(workflow), state)
    elif state["current_state"] == "L3_DEVELOP" and agent_id in {"frontend-squad", "backend-squad"}:
        audit_path = reuse_audit_path(workflow, agent_id)
        if not audit_path.exists():
            raise ControlPlaneError(f"missing development governance artifact: {audit_path.relative_to(ROOT)}")
        validate_reuse_audit(
            load_json(audit_path),
            workflow,
            agent_id,
            state.get("requirements_lock_hash"),
            contracts,
        )
    elif state["current_state"] == "L4_VALIDATE":
        traceability_path = requirements_traceability_path(workflow)
        payload = load_json(traceability_path)
        validate_required_keys(payload, REQUIREMENTS_TRACEABILITY_SCHEMA_PATH, traceability_path.relative_to(ROOT).as_posix())
        if payload["requirements_lock_hash"] != state.get("requirements_lock_hash"):
            raise ControlPlaneError("requirements traceability hash does not match the locked workflow requirements")
    elif state["current_state"] in orchestrator["gates"]:
        gate_state = state["current_state"]
        gate = orchestrator["gates"][gate_state]
        review_loop = gate.get("review_loop")
        if review_loop and review_loop.get("enabled"):
            artifact_dir = gate_artifact_dir(workflow, gate_state, orchestrator)
            loop_payload = validate_review_loop_status(
                artifact_dir / review_loop["status_artifact"],
                workflow,
                gate_state,
                gate,
            )
            state.setdefault("review_loops", {})[gate_state] = loop_payload
            transition = orchestrator["transitions"][gate_state]
            if loop_payload["status"] == "lgtm":
                state["active_review_loop"] = None
                state["next_state_hint"] = transition.get("pass")
            elif loop_payload["status"] == "blocked":
                state["active_review_loop"] = {
                    "gate": gate_state,
                    "round": loop_payload["round"],
                    "status": "blocked",
                    "fix_state": review_loop.get("fix_state"),
                    "fixer_agents": review_loop.get("fixer_agents", []),
                    "fix_response_pattern": review_loop["fix_response_pattern"]
                }
                state["next_state_hint"] = transition.get("blocked", "BLOCKED")
            else:
                state["active_review_loop"] = {
                    "gate": gate_state,
                    "round": loop_payload["round"],
                    "status": loop_payload["status"],
                    "fix_state": review_loop.get("fix_state"),
                    "fixer_agents": review_loop.get("fixer_agents", []),
                    "fix_response_pattern": review_loop["fix_response_pattern"]
                }
                state["next_state_hint"] = transition.get("changes_requested", review_loop.get("fix_state"))
            write_json(state_path(workflow), state)
    elif active_loop and state["current_state"] == active_loop.get("fix_state"):
        gate_state = active_loop["gate"]
        state["active_review_loop"]["status"] = "re_review"
        state.setdefault("review_loops", {})[gate_state] = deepcopy(state["active_review_loop"])
        state["next_state_hint"] = gate_state
        write_json(state_path(workflow), state)
    else:
        enforce_requirements_lock(state, workflow, state["current_state"])
    workflow_dir = ROOT / "workflows" / workflow
    git("add", str(workflow_dir))
    diff = git("diff", "--cached", "--quiet", check=False)
    if diff.returncode == 0:
        return [f"no workflow changes to commit for {workflow}"]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    git("commit", "-m", f"[AEGIS-RUN] agent={agent_id} workflow={workflow} state={state['current_state']} ts={stamp}")
    tag_name = f"workflow/{workflow}/{state['current_state']}-{stamp}"
    git("tag", tag_name)
    return [f"committed workflow changes for {workflow}", f"tagged {tag_name}"]


def workflow_dry_run() -> list[str]:
    _, orchestrator, _ = get_context()
    trace = [orchestrator["initial_state"]]
    state = trace[0]
    while state not in {"DONE", "BLOCKED"}:
        transition = orchestrator["transitions"][state]
        state = transition.get("next") or transition.get("pass")
        if not state:
            raise ControlPlaneError(f"cannot dry-run state {trace[-1]}")
        trace.append(state)
    return trace


def ensure_cron() -> list[str]:
    cron_line = f"0 2 * * * {ROOT}/.aegis/schedules/nightly-evolution.sh >> /tmp/aegis-evolution.log 2>&1"
    current = subprocess.run(["crontab", "-l"], text=True, capture_output=True, check=False)
    lines = [line for line in current.stdout.splitlines() if line.strip()]
    if cron_line not in lines:
        lines.append(cron_line)
        subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", text=True, check=True)
        return ["installed nightly evolution cron"]
    return ["nightly evolution cron already present"]


def evaluate_agent(agent: dict[str, Any], content: str) -> float:
    score = 5.0
    if "## Runtime Contracts" in content:
        score += 1.0
    if "## Inputs" in content:
        score += 0.75
    if "## Outputs" in content:
        score += 0.75
    if "mission" in content.lower():
        score += 0.5
    if "must not" in content.lower() or "Do not" in content:
        score += 0.5
    if all(f"`{action}`" in content for action in agent.get("contract_actions", [])):
        score += 1.0
    if not any(token in content for token in FORBIDDEN_TOKENS):
        score += 1.0
    return min(round(score, 2), 10.0)


def optimize_skill_content(agent: dict[str, Any], content: str) -> str:
    if "## Runtime Contracts" not in content:
        block = "\n## Runtime Contracts\n\nThis agent relies on the following abstract actions:\n" + "\n".join(f"- `{action}`" for action in agent.get("contract_actions", [])) + "\n"
        marker = "\n## Inputs"
        if marker in content:
            content = content.replace(marker, block + marker, 1)
    replacements = {
        "WebSearch": "`search_web`",
        "AskUserQuestion": "`ask_user`",
        "mcp__fetch__fetch": "`fetch_source`",
        "superpowers:writing-plans": "`write_plan`",
        "superpowers:test-driven-development": "`run_test_driven_cycle`",
        "superpowers:verification-before-completion": "`run_verification`",
        "Agent({": "`spawn_agent` contract payload"
    }
    for source, target in replacements.items():
        content = content.replace(source, target)
    return content


def append_evolution_log(entry: dict[str, Any]) -> None:
    payload = load_json(EVOLUTION_LOG_PATH)
    payload.setdefault("entries", []).append(entry)
    write_json(EVOLUTION_LOG_PATH, payload)


def run_doctor_in(path: Path) -> None:
    subprocess.run([sys.executable, "-m", "tools.control_plane", "doctor"], cwd=str(path), check=True)


def evolution_run() -> list[str]:
    doctor()
    registry = load_json(REGISTRY_PATH)
    branch = f"auto-evolve-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    worktree_base = Path(tempfile.gettempdir()) / "aegis-evolution"
    worktree_path = worktree_base / branch
    worktree_base.mkdir(parents=True, exist_ok=True)
    git("worktree", "add", str(worktree_path), "-b", branch)
    messages: list[str] = []
    try:
        run_doctor_in(worktree_path)
        work_registry = load_json(worktree_path / ".aegis/core/registry.json")
        for agent in work_registry["agents"]:
            if not agent.get("evolution"):
                continue
            skill_path = worktree_path / agent["entrypoint"]
            original = skill_path.read_text(encoding="utf-8")
            baseline = evaluate_agent(agent, original)
            candidate = optimize_skill_content(agent, original)
            if candidate == original:
                append_evolution_log({
                    "timestamp": utc_now(),
                    "agent_id": agent["id"],
                    "baseline_score": baseline,
                    "candidate_score": baseline,
                    "result": "no-op",
                    "reason": "optimizer found no deterministic improvement",
                    "commit": None,
                    "rubric": "shared-contexts/review-rubric-8dim.json"
                })
                messages.append(f"{agent['id']}: no deterministic improvement")
                continue
            skill_path.write_text(candidate, encoding="utf-8")
            subprocess.run([sys.executable, "-m", "tools.control_plane", "sync-agent-metadata"], cwd=str(worktree_path), check=True)
            candidate_score = evaluate_agent(agent, candidate)
            if candidate_score <= baseline:
                skill_path.write_text(original, encoding="utf-8")
                subprocess.run([sys.executable, "-m", "tools.control_plane", "sync-agent-metadata"], cwd=str(worktree_path), check=True)
                append_evolution_log({
                    "timestamp": utc_now(),
                    "agent_id": agent["id"],
                    "baseline_score": baseline,
                    "candidate_score": candidate_score,
                    "result": "revert",
                    "reason": "candidate score did not improve",
                    "commit": None,
                    "rubric": "shared-contexts/review-rubric-8dim.json"
                })
                messages.append(f"{agent['id']}: reverted candidate (score {candidate_score} <= {baseline})")
                continue
            run_doctor_in(worktree_path)
            subprocess.run(["git", "add", str(skill_path.relative_to(worktree_path)), "agents", ".aegis/core"], cwd=str(worktree_path), check=True)
            subprocess.run(["git", "commit", "-m", f"[AEGIS-EVOLVE] {agent['id']}: {baseline:.2f} -> {candidate_score:.2f}"], cwd=str(worktree_path), check=True)
            commit_hash = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(worktree_path), text=True, capture_output=True, check=True).stdout.strip()
            append_evolution_log({
                "timestamp": utc_now(),
                "agent_id": agent["id"],
                "baseline_score": baseline,
                "candidate_score": candidate_score,
                "result": "keep",
                "reason": "candidate improved score and passed doctor",
                "commit": commit_hash,
                "rubric": "shared-contexts/review-rubric-8dim.json"
            })
            messages.append(f"{agent['id']}: kept candidate {baseline:.2f} -> {candidate_score:.2f}")
        return messages or ["no evolvable agents changed"]
    finally:
        git("worktree", "remove", str(worktree_path), check=False)
        git("branch", "-D", branch, check=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AEGIS control-plane tooling")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    sub.add_parser("validate")
    sub.add_parser("sync-agent-metadata")
    sub.add_parser("sync-agents")
    sub.add_parser("workflow-dry-run")
    sub.add_parser("install-cron")
    write_state_cmd = sub.add_parser("write-state")
    write_state_cmd.add_argument("--workflow", required=True)
    write_state_cmd.add_argument("--state", required=True)
    pre = sub.add_parser("pre-agent-run")
    pre.add_argument("--agent", required=True)
    pre.add_argument("--workflow", required=True)
    post = sub.add_parser("post-agent-run")
    post.add_argument("--agent", required=True)
    post.add_argument("--workflow", required=True)
    sub.add_parser("evolution-run")
    args = parser.parse_args(argv)
    try:
        if args.command in {"doctor", "validate"}:
            result = doctor()
        elif args.command == "sync-agent-metadata":
            result = sync_agent_metadata(check_only=False)
        elif args.command == "sync-agents":
            result = ensure_skill_symlinks()
        elif args.command == "workflow-dry-run":
            result = workflow_dry_run()
        elif args.command == "install-cron":
            result = ensure_cron()
        elif args.command == "write-state":
            result = write_state_transition(args.workflow, args.state)
        elif args.command == "pre-agent-run":
            result = pre_agent_run(args.agent, args.workflow)
        elif args.command == "post-agent-run":
            result = post_agent_run(args.agent, args.workflow)
        elif args.command == "evolution-run":
            result = evolution_run()
        else:
            raise ControlPlaneError(f"unsupported command: {args.command}")
        for line in result:
            print(line)
        return 0
    except ControlPlaneError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(exc.stderr or str(exc), file=sys.stderr)
        return 1
