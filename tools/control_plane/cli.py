from __future__ import annotations

import argparse
import hashlib
import json
import os
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
PROJECT_MANIFEST_SCHEMA_PATH = ROOT / "shared-contexts/project-manifest-schema.json"
AGENT_OVERRIDES_SCHEMA_PATH = ROOT / "shared-contexts/agent-overrides-schema.json"
WORKSPACE_POLICY_SCHEMA_PATH = ROOT / "shared-contexts/workspace-policy-schema.json"
TEAM_PACK_SCHEMA_PATH = ROOT / "shared-contexts/team-pack-schema.json"
TEAM_RUN_SCHEMA_PATH = ROOT / "shared-contexts/team-run-schema.json"
TEAM_RUN_BRIEF_SCHEMA_PATH = ROOT / "shared-contexts/team-run-brief-schema.json"
WORKFLOW_INDEX_PATH = ROOT / ".aegis/core/workflow-index.json"
SKILLS_DIR = Path.home() / ".claude/skills"
CLAUDE_COMMANDS_DIR = Path.home() / ".claude/commands"
SHIM_INSTALL_DIR = Path(os.environ.get("AEGIS_SHIM_DIR", Path.home() / ".local/bin"))
FORBIDDEN_TOKENS = ["WebSearch", "AskUserQuestion", "mcp__fetch__fetch", "superpowers:", "Agent({"]
WORKFLOW_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-_]{1,62}$")
TEAM_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-_]{1,62}$")
HOST_SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
PREFERENCE_STRONG_PATTERNS = [
    re.compile(r"(?:默认|以后都|以后统一|以后默认|后续都|今后都|从现在开始|请记住|记住|一律|始终|固定使用|固定输出|以后不要|别再|永远不要)"),
    re.compile(r"\b(?:default to|from now on|going forward|always|remember|every time|stick to|never again)\b", re.IGNORECASE),
]
PREFERENCE_WEAK_PATTERNS = [
    re.compile(r"(?:优先|尽量|最好|偏向|保持|继续用|先给|先出|多用|少用)"),
    re.compile(r"\b(?:prefer|preferably|focus on|start with|use more|use less)\b", re.IGNORECASE),
]
PREFERENCE_STOPWORDS = {
    "aegis",
    "agent",
    "agents",
    "team",
    "teams",
    "project",
    "please",
    "help",
    "with",
    "that",
    "this",
    "then",
    "later",
    "again",
    "still",
    "using",
    "into",
    "from",
    "给我",
    "帮我",
    "一下",
    "这个",
    "那个",
    "当前",
    "本次",
    "这次",
    "那个",
    "还有",
    "以及",
    "我们",
    "你们",
    "需要",
    "先把",
    "然后",
    "继续",
    "后续",
}
ALLOWED_AGENT_OVERRIDE_KEYS = {
    "project_context",
    "extra_instructions",
    "inputs_add",
    "outputs_add",
    "dependencies_add",
    "contract_actions_add",
}


class ControlPlaneError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(json.dumps(payload, indent=2, ensure_ascii=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
        temp_path = Path(handle.name)
    temp_path.replace(path)


def normalize(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True))


def find_git_root(start: Path) -> Path | None:
    current = start.resolve()
    while True:
        if (current / ".git").exists():
            return current
        if current.parent == current:
            return None
        current = current.parent


def workspace_root(explicit: str | Path | None = None) -> Path:
    candidate = explicit or os.environ.get("AEGIS_WORKSPACE_ROOT")
    if candidate:
        return Path(candidate).expanduser().resolve()
    discovered = find_git_root(Path.cwd())
    if discovered:
        return discovered
    return Path.cwd().resolve()


def validate_workspace_root(explicit_workspace: str | Path | None = None) -> Path:
    target_workspace = workspace_root(explicit_workspace)
    if not target_workspace.exists():
        raise ControlPlaneError(f"workspace root does not exist: {target_workspace}")
    if not target_workspace.is_dir():
        raise ControlPlaneError(f"workspace root must be a directory: {target_workspace}")
    git_root = find_git_root(target_workspace)
    if git_root is None:
        raise ControlPlaneError(
            f"workspace root must be a git repository root: {target_workspace} is not inside a git repository"
        )
    if git_root != target_workspace:
        raise ControlPlaneError(
            f"workspace root must equal the git repository root: expected {git_root}, got {target_workspace}"
        )
    return target_workspace


def load_workflow_index() -> dict[str, Any]:
    default_payload = {"version": "1.0.0", "workflows": {}}
    try:
        payload = load_optional_json(WORKFLOW_INDEX_PATH, default_payload)
    except (OSError, json.JSONDecodeError):
        write_json(WORKFLOW_INDEX_PATH, default_payload)
        return deepcopy(default_payload)
    if not isinstance(payload, dict) or not isinstance(payload.get("workflows", {}), dict):
        write_json(WORKFLOW_INDEX_PATH, default_payload)
        return deepcopy(default_payload)
    return payload


def save_workflow_index(payload: dict[str, Any]) -> None:
    WORKFLOW_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_json(WORKFLOW_INDEX_PATH, payload)


def update_workflow_index(
    workflow: str,
    *,
    workspace: Path | None = None,
    workflow_type: str | None = None,
    current_state: str | None = None,
) -> None:
    payload = load_workflow_index()
    workflows = payload.setdefault("workflows", {})
    target = workflows.setdefault(workflow, {})
    if workspace is not None:
        target["workspace_root"] = str(workspace.resolve())
    if workflow_type is not None:
        target["workflow_type"] = workflow_type
    if current_state is not None:
        target["current_state"] = current_state
    target["updated_at"] = utc_now()
    save_workflow_index(payload)


def workspace_from_workflow_index(workflow: str) -> Path | None:
    payload = load_workflow_index()
    workflow_entry = payload.get("workflows", {}).get(workflow)
    if not workflow_entry:
        return None
    workspace_value = workflow_entry.get("workspace_root")
    if not workspace_value:
        return None
    return Path(workspace_value).expanduser().resolve()


def workspace_aegis_dir(explicit: str | Path | None = None) -> Path:
    return workspace_root(explicit) / ".aegis"


def workspace_runs_dir(explicit: str | Path | None = None) -> Path:
    return workspace_aegis_dir(explicit) / "runs"


def workflow_root(workflow: str, explicit_workspace: str | Path | None = None) -> Path:
    return workspace_runs_dir(explicit_workspace) / workflow


def project_manifest_path(explicit_workspace: str | Path | None = None) -> Path:
    return workspace_aegis_dir(explicit_workspace) / "project.yml"


def agent_overrides_path(explicit_workspace: str | Path | None = None) -> Path:
    return workspace_aegis_dir(explicit_workspace) / "overrides" / "agent-overrides.json"


def workflow_policy_path(explicit_workspace: str | Path | None = None) -> Path:
    return workspace_aegis_dir(explicit_workspace) / "policies" / "workflow-policy.json"


def display_path(path: Path) -> str:
    resolved = path.resolve()
    for base in (workspace_root(), ROOT):
        try:
            return resolved.relative_to(base.resolve()).as_posix()
        except ValueError:
            continue
    return str(resolved)


def render_template(value: str, workflow: str) -> Path:
    return workspace_root() / value.replace("{workflow}", workflow)


def default_project_manifest(explicit_workspace: str | Path | None = None) -> dict[str, Any]:
    target_workspace = workspace_root(explicit_workspace)
    return {
        "version": "1.0.0",
        "project_id": target_workspace.name,
        "project_type": "application",
        "project_root": str(target_workspace),
        "core_root": str(ROOT),
        "artifact_root": ".aegis/runs",
        "enabled_workflows": ["research", "planning", "build", "launch"],
        "review_policy": {
            "mode": "review_fix_lgtm",
            "max_rounds": 3,
        },
        "stack": [],
        "test_commands": [],
        "build_commands": [],
        "default_output_policy": {
            "artifact_root": ".aegis/runs",
        },
        "artifact_retention": {
            "keep_latest_runs": 20,
        },
        "deploy_policy": {
            "mode": "manual_approval",
        },
        "agent_overrides": {},
        "created_at": utc_now(),
    }


def validate_project_manifest(payload: dict[str, Any], explicit_workspace: str | Path | None = None) -> None:
    validate_required_keys(payload, PROJECT_MANIFEST_SCHEMA_PATH, display_path(project_manifest_path(explicit_workspace)))
    target_workspace = workspace_root(explicit_workspace)
    if Path(payload["project_root"]).resolve() != target_workspace:
        raise ControlPlaneError("project manifest project_root does not match resolved workspace_root")
    if payload["artifact_root"] != ".aegis/runs":
        raise ControlPlaneError("project manifest artifact_root must be .aegis/runs")
    enabled_workflows = payload.get("enabled_workflows", [])
    if enabled_workflows and (not isinstance(enabled_workflows, list) or not all(isinstance(item, str) for item in enabled_workflows)):
        raise ControlPlaneError("project manifest enabled_workflows must be a list of strings")
    review_policy = payload.get("review_policy")
    if review_policy is not None and not isinstance(review_policy, dict):
        raise ControlPlaneError("project manifest review_policy must be an object when provided")
    if review_policy:
        if review_policy.get("mode") != "review_fix_lgtm":
            raise ControlPlaneError("project manifest review_policy.mode must remain review_fix_lgtm")
        if "max_rounds" in review_policy and (
            not isinstance(review_policy["max_rounds"], int) or review_policy["max_rounds"] < 1
        ):
            raise ControlPlaneError("project manifest review_policy.max_rounds must be a positive integer")
    stack = payload.get("stack", [])
    if stack and (not isinstance(stack, list) or not all(isinstance(item, str) for item in stack)):
        raise ControlPlaneError("project manifest stack must be a list of strings")
    for list_field in ["test_commands", "build_commands"]:
        values = payload.get(list_field, [])
        if values and (not isinstance(values, list) or not all(isinstance(item, str) for item in values)):
            raise ControlPlaneError(f"project manifest {list_field} must be a list of strings")
    for object_field in ["default_output_policy", "artifact_retention", "deploy_policy", "agent_overrides"]:
        value = payload.get(object_field)
        if value is not None and not isinstance(value, dict):
            raise ControlPlaneError(f"project manifest {object_field} must be an object when provided")


def ensure_workspace_layout(explicit_workspace: str | Path | None = None) -> list[str]:
    target_workspace = validate_workspace_root(explicit_workspace)
    aegis_dir = workspace_aegis_dir(target_workspace)
    messages: list[str] = []
    for path in [
        aegis_dir,
        aegis_dir / "runs",
        aegis_dir / "cache",
        aegis_dir / "cache" / "session-teams",
        aegis_dir / "teams",
        aegis_dir / "overrides",
        aegis_dir / "policies",
    ]:
        path.mkdir(parents=True, exist_ok=True)
    manifest = project_manifest_path(target_workspace)
    if manifest.exists():
        payload = load_json(manifest)
        validate_project_manifest(payload, target_workspace)
        messages.append(f"workspace manifest valid: {display_path(manifest)}")
    else:
        write_json(manifest, default_project_manifest(target_workspace))
        messages.append(f"created workspace manifest: {display_path(manifest)}")
    return messages


def load_optional_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return deepcopy(default)
    return load_json(path)


def resolve_workspace(explicit_workspace: str | Path | None = None, workflow: str | None = None) -> Path:
    if explicit_workspace:
        return validate_workspace_root(explicit_workspace)
    env_workspace = os.environ.get("AEGIS_WORKSPACE_ROOT")
    if env_workspace:
        return validate_workspace_root(env_workspace)
    if workflow:
        indexed_workspace = workspace_from_workflow_index(workflow)
        if indexed_workspace:
            return validate_workspace_root(indexed_workspace)
        discovered_workspace = validate_workspace_root()
        if state_path(workflow, discovered_workspace).exists():
            return discovered_workspace
        raise ControlPlaneError(
            f"unable to resolve workspace for workflow {workflow}: provide --workspace, "
            "set AEGIS_WORKSPACE_ROOT, or attach the workspace first"
        )
    return validate_workspace_root()


def team_home_root() -> Path:
    override = os.environ.get("AEGIS_TEAM_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".aegis"


def team_pack_store_root(scope: str, explicit_workspace: str | Path | None = None) -> Path:
    if scope == "global":
        return team_home_root() / "teams" / "global"
    workspace = resolve_workspace(explicit_workspace)
    if scope == "project":
        return workspace / ".aegis" / "teams"
    if scope == "session":
        return workspace / ".aegis" / "cache" / "session-teams"
    raise ControlPlaneError(f"unsupported team pack scope: {scope}")


def team_pack_dir(team_id: str, scope: str, explicit_workspace: str | Path | None = None) -> Path:
    return team_pack_store_root(scope, explicit_workspace) / team_id


def team_pack_manifest_path(team_id: str, scope: str, explicit_workspace: str | Path | None = None) -> Path:
    return team_pack_dir(team_id, scope, explicit_workspace) / "team.json"


def team_pack_skill_path(team_id: str, scope: str, explicit_workspace: str | Path | None = None) -> Path:
    return team_pack_dir(team_id, scope, explicit_workspace) / "SKILL.md"


def team_pack_command_path(team_id: str, scope: str, explicit_workspace: str | Path | None = None) -> Path:
    return team_pack_dir(team_id, scope, explicit_workspace) / "COMMAND.md"


def validate_team_id(team_id: str) -> str:
    if not TEAM_ID_PATTERN.match(team_id):
        raise ControlPlaneError(
            f"invalid team id `{team_id}`: use 2-63 letters, numbers, dashes, or underscores"
        )
    return team_id


def normalize_team_scope(scope: str) -> str:
    normalized_scope = scope.lower()
    if normalized_scope not in {"global", "project", "session", "all"}:
        raise ControlPlaneError(f"unsupported team scope: {scope}")
    return normalized_scope


def humanize_identifier(value: str) -> str:
    return re.sub(r"[-_]+", " ", value).strip().title()


def host_skill_name_for_team_id(team_id: str) -> str:
    normalized = re.sub(r"[_\s]+", "-", team_id.strip())
    normalized = slugify_text(normalized)
    if not HOST_SKILL_NAME_PATTERN.match(normalized):
        raise ControlPlaneError(f"could not derive a valid host skill name from team id `{team_id}`")
    return normalized


def parse_role_spec(spec: str) -> dict[str, str]:
    parts = [part.strip() for part in spec.split("|")]
    if len(parts) == 2:
        role_id, summary = parts
        title = humanize_identifier(role_id)
    elif len(parts) == 3:
        role_id, title, summary = parts
    else:
        raise ControlPlaneError(
            "role specs must use `role_id|summary` or `role_id|title|summary`"
        )
    if not role_id or not summary:
        raise ControlPlaneError("role specs must include a non-empty role id and summary")
    return {
        "id": role_id,
        "title": title,
        "summary": summary,
    }


def default_team_blueprint(domain: str) -> dict[str, Any]:
    lowered = domain.lower()
    if any(token in lowered for token in {"reverse", "nx", "reversing", "binary", "frida", "ida"}):
        return {
            "roles": [
                {
                    "id": "reverse-researcher",
                    "title": "Reverse Researcher",
                    "summary": "Search public references, related writeups, and ecosystem clues before deep analysis.",
                },
                {
                    "id": "static-analyst",
                    "title": "Static Analyst",
                    "summary": "Map bundles, strings, symbols, endpoints, and likely implementation seams.",
                },
                {
                    "id": "behavior-mapper",
                    "title": "Behavior Mapper",
                    "summary": "Trace the user-facing feature path and connect observations to likely runtime behavior.",
                },
                {
                    "id": "conclusion-reviewer",
                    "title": "Conclusion Reviewer",
                    "summary": "Challenge weak assumptions, score confidence, and tighten the final explanation.",
                },
            ],
            "playbook_steps": [
                "Clarify the target application, feature, and expected deliverable.",
                "Search for public references and prior analyses when useful.",
                "Break the investigation into static analysis, behavior mapping, and conclusion review tracks.",
                "Synthesize likely implementation details with explicit confidence notes.",
                "Run an internal review/fix loop before presenting final findings.",
            ],
            "review_mode": "strict",
            "tooling_policy": {
                "search_policy": "required_when_external_context_is_missing",
                "repo_context_policy": "scoped_when_project_bound",
                "parallelism_policy": "minimal_sufficient_parallel",
            },
        }
    if any(token in lowered for token in {"video", "editing", "editor", "short-video", "clip"}):
        return {
            "roles": [
                {
                    "id": "trend-researcher",
                    "title": "Trend Researcher",
                    "summary": "Collect reference styles, pacing patterns, and current creative conventions.",
                },
                {
                    "id": "structure-planner",
                    "title": "Structure Planner",
                    "summary": "Shape the hook, narrative rhythm, scene order, and content structure.",
                },
                {
                    "id": "editing-director",
                    "title": "Editing Director",
                    "summary": "Define transitions, timing, emphasis, and the final edit direction.",
                },
                {
                    "id": "caption-specialist",
                    "title": "Caption Specialist",
                    "summary": "Refine on-screen copy, hooks, subtitles, and conversion-oriented phrasing.",
                },
                {
                    "id": "quality-reviewer",
                    "title": "Quality Reviewer",
                    "summary": "Review the concept for clarity, style fit, and audience impact before delivery.",
                },
            ],
            "playbook_steps": [
                "Clarify the video objective, audience, style references, and delivery format.",
                "Research trend references and competitive patterns when needed.",
                "Split the work into concept structure, edit direction, and copy refinement tracks.",
                "Assemble the final creative direction with a clear production-ready recommendation.",
                "Run an internal review/fix loop before presenting the final package.",
            ],
            "review_mode": "standard",
            "tooling_policy": {
                "search_policy": "required_for_reference_work",
                "repo_context_policy": "not_required_by_default",
                "parallelism_policy": "parallel_when_structure_is_clear",
            },
        }
    if any(token in lowered for token in {"mvp", "product", "build", "app", "startup"}):
        return {
            "roles": [
                {
                    "id": "opportunity-researcher",
                    "title": "Opportunity Researcher",
                    "summary": "Search the market, identify comparable products, and frame the MVP edge.",
                },
                {
                    "id": "product-planner",
                    "title": "Product Planner",
                    "summary": "Define the MVP scope, user flow, and execution priorities.",
                },
                {
                    "id": "implementation-lead",
                    "title": "Implementation Lead",
                    "summary": "Translate the scoped plan into a delivery-ready implementation path.",
                },
                {
                    "id": "quality-reviewer",
                    "title": "Quality Reviewer",
                    "summary": "Review the proposal or implementation plan for gaps and practical risks.",
                },
            ],
            "playbook_steps": [
                "Clarify the user goal, target audience, and MVP success bar.",
                "Research comparable patterns and likely product expectations.",
                "Split the work into research, scope definition, and implementation planning tracks.",
                "Assemble a first-version MVP plan or output with explicit tradeoffs.",
                "Run an internal review/fix loop before presenting the final result.",
            ],
            "review_mode": "standard",
            "tooling_policy": {
                "search_policy": "recommended",
                "repo_context_policy": "required_when_attached_to_codebase",
                "parallelism_policy": "parallel_when_subtasks_are_independent",
            },
        }
    if any(token in lowered for token in {"bug", "incident", "fix", "debug"}):
        return {
            "roles": [
                {
                    "id": "triage-lead",
                    "title": "Triage Lead",
                    "summary": "Reproduce the issue, tighten the scope, and identify the likeliest failure zone.",
                },
                {
                    "id": "root-cause-analyst",
                    "title": "Root Cause Analyst",
                    "summary": "Inspect the codebase and runtime evidence to identify the real cause.",
                },
                {
                    "id": "fix-implementer",
                    "title": "Fix Implementer",
                    "summary": "Apply the smallest reliable fix and explain the tradeoffs.",
                },
                {
                    "id": "reviewer",
                    "title": "Reviewer",
                    "summary": "Review the fix, verify confidence, and call out follow-up risks.",
                },
            ],
            "playbook_steps": [
                "Clarify the bug report, expected behavior, and impact.",
                "Split work into triage, root-cause analysis, fix, and review tracks.",
                "Implement the smallest reliable fix that addresses the true cause.",
                "Run validation and an internal review/fix loop before closing the task.",
            ],
            "review_mode": "strict",
            "tooling_policy": {
                "search_policy": "disabled_by_default",
                "repo_context_policy": "required",
                "parallelism_policy": "parallel_when_investigation_and_fix_can_separate",
            },
        }
    if "research" in lowered:
        return {
            "roles": [
                {
                    "id": "researcher",
                    "title": "Researcher",
                    "summary": "Collect primary evidence and current external references.",
                },
                {
                    "id": "analyst",
                    "title": "Analyst",
                    "summary": "Synthesize findings into conclusions, tradeoffs, and recommendations.",
                },
                {
                    "id": "reviewer",
                    "title": "Reviewer",
                    "summary": "Review evidence quality, unsupported claims, and final recommendation strength.",
                },
            ],
            "playbook_steps": [
                "Clarify the research goal and the form of the final deliverable.",
                "Collect the most relevant external evidence and organize it by theme.",
                "Synthesize findings into a clear recommendation.",
                "Run an internal review/fix loop before presenting the final result.",
            ],
            "review_mode": "standard",
            "tooling_policy": {
                "search_policy": "required",
                "repo_context_policy": "not_required_by_default",
                "parallelism_policy": "parallel_when_sources_can_be_split",
            },
        }
    return {
        "roles": [
            {
                "id": "team-lead",
                "title": "Team Lead",
                "summary": "Clarify the goal, organize the work, and own the final synthesis.",
            },
            {
                "id": "specialist",
                "title": "Specialist",
                "summary": "Execute the core domain work for this task.",
            },
            {
                "id": "reviewer",
                "title": "Reviewer",
                "summary": "Review the result for quality, risks, and missing detail.",
            },
        ],
        "playbook_steps": [
            "Clarify the requested outcome and constraints.",
            "Split the work into the smallest useful set of specialist tracks.",
            "Execute the core work and synthesize the result.",
            "Run an internal review/fix loop before delivery.",
        ],
        "review_mode": "standard",
        "tooling_policy": {
            "search_policy": "when_useful",
            "repo_context_policy": "scoped_when_applicable",
            "parallelism_policy": "minimal_sufficient_parallel",
        },
    }


def build_team_pack_payload(
    *,
    team_id: str,
    display_name: str,
    mission: str,
    domain: str,
    scope: str,
    role_specs: list[str],
    playbook_steps: list[str],
    review_mode: str | None,
) -> dict[str, Any]:
    validate_team_id(team_id)
    if not display_name.strip():
        raise ControlPlaneError("display name must not be empty")
    if not mission.strip():
        raise ControlPlaneError("mission must not be empty")
    if not domain.strip():
        raise ControlPlaneError("domain must not be empty")
    blueprint = default_team_blueprint(domain)
    roles = [parse_role_spec(spec) for spec in role_specs] if role_specs else deepcopy(blueprint["roles"])
    if not roles:
        raise ControlPlaneError("team packs must define at least one role")
    effective_playbook = [step.strip() for step in playbook_steps if step.strip()] if playbook_steps else deepcopy(
        blueprint["playbook_steps"]
    )
    if not effective_playbook:
        raise ControlPlaneError("team packs must define at least one playbook step")
    effective_review_mode = review_mode or blueprint["review_mode"]
    return {
        "version": "1.0.0",
        "team_id": team_id,
        "display_name": display_name,
        "mission": mission,
        "domain": domain,
        "lifecycle_scope": scope,
        "roles": roles,
        "playbook_steps": effective_playbook,
        "review_mode": {
            "mode": effective_review_mode,
            "auto_fix_loop": True,
        },
        "tooling_policy": deepcopy(blueprint["tooling_policy"]),
        "memory_policy": {
            "retain_run_summaries": True,
            "store_team_learnings": scope != "session",
            "store_preference_memory": True,
            "store_project_memory": scope != "session",
            "semantic_recall": True,
        },
        "evolution_policy": {
            "enabled": scope != "session",
            "mode": "manual_plus_periodic_review",
        },
        "host_integration": {
            "skill_name": host_skill_name_for_team_id(team_id),
            "slash_command": f"/{host_skill_name_for_team_id(team_id)}",
            "installed": False,
        },
        "run_count": 0,
        "created_at": utc_now(),
    }


def render_team_pack_skill(payload: dict[str, Any]) -> str:
    description = payload["mission"].replace('"', '\\"')
    role_lines = "\n".join(
        [
            f"- `{role['id']}`: {role['title']} - {role['summary']}"
            for role in payload["roles"]
        ]
    )
    playbook_lines = "\n".join(
        [f"{index}. {step}" for index, step in enumerate(payload["playbook_steps"], start=1)]
    )
    scope = payload["lifecycle_scope"]
    review_mode = payload["review_mode"]["mode"]
    tooling = payload["tooling_policy"]
    return f"""---
name: {payload['host_integration']['skill_name']}
description: "{description}"
---

# {payload['display_name']}

You are {payload['display_name']}, an AEGIS Team Pack running inside Claude Code / Codex.

## Mission

{payload['mission']}

## Core Rules

- You are the single user-facing lead for this team.
- Keep user communication unified and concise instead of exposing every internal role by default.
- Use the host's existing tools, skills, and sub-agent capabilities instead of recreating them.
- Activate the smallest sufficient internal team for the task, then expand only when complexity requires it.
- Preserve a built-in review/fix loop before presenting final output for medium and high-value work.

## Lifecycle Scope

- `{scope}`

## Team Roles

{role_lines}

## Default Playbook

{playbook_lines}

## Built-in Review

- review mode: `{review_mode}`
- auto fix loop: `enabled`

## Tooling Policy

- search policy: `{tooling['search_policy']}`
- repo context policy: `{tooling['repo_context_policy']}`
- parallelism policy: `{tooling['parallelism_policy']}`

## Direct Invocation

When this team is called directly from Claude Code, the user arguments should be treated as the active task.

If direct invocation arguments are present, use them as the run request.

## Memory Discipline

Before substantial work, read the team's persistent memory:

```bash
aegis ctl show-team-memory --team {payload['team_id']} --scope {scope}
```

Treat that memory as active operating context, not as optional history.

AEGIS now auto-observes preference signals from the user's request and only promotes them into stable team memory conservatively:

- strong signals like `默认` / `以后都` / `记住` / `always` can promote in the same completed run
- weaker signals like `优先` / `先给` / `prefer` stay as observations until they repeat
- one-off weak phrasing should not be treated as permanent team memory

```bash
aegis ctl show-team-memory --team {payload['team_id']} --scope {scope}
```

If you need to force a preference into stable memory immediately, you can still record it explicitly:

```bash
aegis ctl record-team-preference --team {payload['team_id']} --scope {scope} --note "<stable preference>"
```

When the team learns something durable about a project or codebase that is not already obvious from the run summary, record it explicitly:

```bash
aegis ctl record-team-project-memory --team {payload['team_id']} --scope {scope} --note "<project memory>"
```

## Execution Guidance

Before substantial work, prepare a run brief:

```bash
aegis ctl invoke-team-pack --team {payload['team_id']} --scope {scope} --request "<user request>"
```

This returns a `run_id` plus the selected internal roles and brief paths.

After delivering the result, complete the run and record any learnings:

```bash
aegis ctl complete-team-run --team {payload['team_id']} --scope {scope} --run-id "<run_id>" --summary "<final summary>" --learning "<team learning>"
```

1. Clarify the goal, constraints, and expected output.
2. Decide which internal roles need to activate for this run.
3. Split work into the minimum useful parallel tracks.
4. Execute, synthesize, review, fix, and then deliver.
5. When confidence is weak, say so explicitly and explain what is still unknown.
"""


def render_team_pack_command(payload: dict[str, Any]) -> str:
    scope = payload["lifecycle_scope"]
    slash_command = payload["host_integration"]["slash_command"]
    role_lines = "\n".join(
        [f"- `{role['id']}`: {role['summary']}" for role in payload["roles"]]
    )
    return f"""---
description: {payload['mission']}
argument-hint: [task]
---

You are invoking the AEGIS Team Pack `{payload['team_id']}` via `{slash_command}`.

Use the team's mission, roles, and review standards to handle the user's task.

Team:

- team id: `{payload['team_id']}`
- display name: `{payload['display_name']}`
- scope: `{scope}`
- review mode: `{payload['review_mode']['mode']}`

Roles:

{role_lines}

User request:

$ARGUMENTS

Before substantial work, first load the team's persistent memory:

```bash
aegis ctl show-team-memory --team {payload['team_id']} --scope {scope}
```

Preference signals in the request are learned automatically when the run is completed. Do not write the whole request into stable preference memory by default.

Use manual recording only when you intentionally want to force a stable preference:

```bash
aegis ctl record-team-preference --team {payload['team_id']} --scope {scope} --note "<stable preference>"
```

Then prepare the run brief:

```bash
aegis ctl invoke-team-pack --team {payload['team_id']} --scope {scope} --request "$ARGUMENTS"
```

Read the generated `team-memory.md` and team run brief markdown before doing major work.

Then execute the task with the current host session, run the built-in review/fix loop, and after delivery record the run:

```bash
aegis ctl complete-team-run --team {payload['team_id']} --scope {scope} --run-id "<run_id>" --summary "<final summary>" --learning "<team learning>"
```
"""


def validate_team_pack_manifest(payload: dict[str, Any], label: str) -> None:
    validate_required_keys(payload, TEAM_PACK_SCHEMA_PATH, label)
    validate_team_id(payload["team_id"])
    scope = normalize_team_scope(payload["lifecycle_scope"])
    if scope == "all":
        raise ControlPlaneError(f"{label} lifecycle_scope cannot be `all`")
    if not isinstance(payload["roles"], list) or not payload["roles"]:
        raise ControlPlaneError(f"{label} roles must be a non-empty list")
    schema = load_json(TEAM_PACK_SCHEMA_PATH)
    role_required = schema["role_required"]
    for role in payload["roles"]:
        missing = [key for key in role_required if key not in role]
        if missing:
            raise ControlPlaneError(f"{label} role missing required keys: {', '.join(missing)}")
        if not all(isinstance(role[key], str) and role[key].strip() for key in role_required):
            raise ControlPlaneError(f"{label} role fields must be non-empty strings")
    if not isinstance(payload["playbook_steps"], list) or not payload["playbook_steps"]:
        raise ControlPlaneError(f"{label} playbook_steps must be a non-empty list")
    if not all(isinstance(step, str) and step.strip() for step in payload["playbook_steps"]):
        raise ControlPlaneError(f"{label} playbook_steps must contain non-empty strings")
    for key_group, key_name in [
        ("review_mode", "review_mode_required"),
        ("tooling_policy", "tooling_policy_required"),
        ("memory_policy", "memory_policy_required"),
        ("evolution_policy", "evolution_policy_required"),
        ("host_integration", "host_integration_required"),
    ]:
        nested = payload.get(key_group)
        if not isinstance(nested, dict):
            raise ControlPlaneError(f"{label} {key_group} must be an object")
        missing = [key for key in schema[key_name] if key not in nested]
        if missing:
            raise ControlPlaneError(f"{label} {key_group} missing required keys: {', '.join(missing)}")
    if payload["review_mode"]["mode"] not in {"lite", "standard", "strict"}:
        raise ControlPlaneError(f"{label} review_mode.mode must be one of lite, standard, strict")
    if not isinstance(payload["review_mode"]["auto_fix_loop"], bool):
        raise ControlPlaneError(f"{label} review_mode.auto_fix_loop must be a boolean")
    for key in [
        "retain_run_summaries",
        "store_team_learnings",
        "store_preference_memory",
        "store_project_memory",
        "semantic_recall",
    ]:
        if not isinstance(payload["memory_policy"][key], bool):
            raise ControlPlaneError(f"{label} memory_policy.{key} must be a boolean")
    skill_name = payload["host_integration"].get("skill_name")
    if not isinstance(skill_name, str) or not HOST_SKILL_NAME_PATTERN.match(skill_name):
        raise ControlPlaneError(
            f"{label} host_integration.skill_name must use lowercase letters, numbers, and hyphens only"
        )
    if not isinstance(payload["host_integration"]["installed"], bool):
        raise ControlPlaneError(f"{label} host_integration.installed must be a boolean")
    slash_command = payload["host_integration"].get("slash_command")
    if slash_command is not None and (
        not isinstance(slash_command, str)
        or slash_command != f"/{skill_name}"
    ):
        raise ControlPlaneError(f"{label} host_integration.slash_command must equal `/{skill_name}`")


def slugify_text(value: str) -> str:
    lowered = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return lowered or "team"


def load_optional_list(path: Path) -> list[Any]:
    if not path.exists():
        return []
    payload = load_json(path)
    if not isinstance(payload, list):
        raise ControlPlaneError(f"{display_path(path)} must contain a JSON list")
    return payload


def team_memory_dir(team_id: str, scope: str, explicit_workspace: str | Path | None = None) -> Path:
    return team_pack_dir(team_id, scope, explicit_workspace) / "memory"


def team_runs_dir(team_id: str, scope: str, explicit_workspace: str | Path | None = None) -> Path:
    return team_pack_dir(team_id, scope, explicit_workspace) / "runs"


def team_run_index_path(team_id: str, scope: str, explicit_workspace: str | Path | None = None) -> Path:
    return team_memory_dir(team_id, scope, explicit_workspace) / "run-summaries.json"


def team_learning_path(team_id: str, scope: str, explicit_workspace: str | Path | None = None) -> Path:
    return team_memory_dir(team_id, scope, explicit_workspace) / "team-learnings.json"


def team_preferences_path(team_id: str, scope: str, explicit_workspace: str | Path | None = None) -> Path:
    return team_memory_dir(team_id, scope, explicit_workspace) / "preferences.json"


def team_preference_observations_path(
    team_id: str, scope: str, explicit_workspace: str | Path | None = None
) -> Path:
    return team_memory_dir(team_id, scope, explicit_workspace) / "preference-observations.json"


def team_project_memory_path(team_id: str, scope: str, explicit_workspace: str | Path | None = None) -> Path:
    return team_memory_dir(team_id, scope, explicit_workspace) / "project-memory.json"


def team_memory_cards_path(team_id: str, scope: str, explicit_workspace: str | Path | None = None) -> Path:
    return team_memory_dir(team_id, scope, explicit_workspace) / "memory-cards.json"


def team_memory_markdown_path(team_id: str, scope: str, explicit_workspace: str | Path | None = None) -> Path:
    return team_memory_dir(team_id, scope, explicit_workspace) / "team-memory.md"


def team_run_brief_path(
    team_id: str, scope: str, run_id: str, explicit_workspace: str | Path | None = None
) -> Path:
    return team_runs_dir(team_id, scope, explicit_workspace) / f"{run_id}.brief.json"


def team_run_brief_markdown_path(
    team_id: str, scope: str, run_id: str, explicit_workspace: str | Path | None = None
) -> Path:
    return team_runs_dir(team_id, scope, explicit_workspace) / f"{run_id}.brief.md"


def team_run_record_path(
    team_id: str, scope: str, run_id: str, explicit_workspace: str | Path | None = None
) -> Path:
    return team_runs_dir(team_id, scope, explicit_workspace) / f"{run_id}.json"


def team_run_summary_markdown_path(
    team_id: str, scope: str, run_id: str, explicit_workspace: str | Path | None = None
) -> Path:
    return team_runs_dir(team_id, scope, explicit_workspace) / f"{run_id}.summary.md"


def next_team_run_id(team_id: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    return f"{slugify_text(team_id)}-{stamp}"


def next_memory_item_id(prefix: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    return f"{prefix}-{stamp}"


def default_team_preferences_payload(team_id: str) -> dict[str, Any]:
    return {
        "version": "1.0.0",
        "team_id": team_id,
        "preferences": [],
        "updated_at": utc_now(),
    }


def default_team_preference_observations_payload(team_id: str) -> dict[str, Any]:
    return {
        "version": "1.0.0",
        "team_id": team_id,
        "observations": [],
        "updated_at": utc_now(),
    }


def default_team_project_memory_payload(
    team_id: str,
    scope: str,
    explicit_workspace: str | Path | None = None,
) -> dict[str, Any]:
    workspace_value = str(workspace_root(explicit_workspace)) if scope != "global" else None
    return {
        "version": "1.0.0",
        "team_id": team_id,
        "scope": scope,
        "workspace_root": workspace_value,
        "notes": [],
        "updated_at": utc_now(),
    }


def default_team_memory_cards_payload(team_id: str) -> dict[str, Any]:
    return {
        "version": "1.0.0",
        "team_id": team_id,
        "cards": [],
        "updated_at": utc_now(),
    }


def load_optional_memory_object(path: Path, default_payload: dict[str, Any]) -> dict[str, Any]:
    payload = load_optional_json(path, default_payload)
    if not isinstance(payload, dict):
        raise ControlPlaneError(f"{display_path(path)} must contain a JSON object")
    return payload


def summarize_memory_tags(tokens: set[str], limit: int = 20) -> list[str]:
    return sorted(tokens, key=lambda item: (-len(item), item))[:limit]


def tokenize_memory_text(text: str) -> set[str]:
    lowered = text.lower()
    tokens = set(re.findall(r"[a-z0-9]{2,}", lowered))
    for sequence in re.findall(r"[\u4e00-\u9fff]+", text):
        if len(sequence) <= 4:
            tokens.add(sequence)
        for index in range(len(sequence)):
            tokens.add(sequence[index])
            if index + 1 < len(sequence):
                tokens.add(sequence[index : index + 2])
            if index + 2 < len(sequence):
                tokens.add(sequence[index : index + 3])
    return {token for token in tokens if token.strip()}


def preference_similarity_tokens(text: str) -> set[str]:
    filtered: set[str] = set()
    for token in tokenize_memory_text(text):
        normalized_token = token.lower().strip()
        if len(normalized_token) < 2:
            continue
        if normalized_token in PREFERENCE_STOPWORDS:
            continue
        filtered.add(normalized_token)
    return filtered


def normalize_memory_note(item: dict[str, Any], *, kind: str) -> dict[str, Any]:
    content = item.get("content", "")
    tags = item.get("tags", [])
    if not isinstance(content, str) or not content.strip():
        raise ControlPlaneError(f"{kind} memory content must be a non-empty string")
    if not isinstance(tags, list) or not all(isinstance(tag, str) and tag.strip() for tag in tags):
        raise ControlPlaneError(f"{kind} memory tags must be a list of non-empty strings")
    return {
        "id": item.get("id", next_memory_item_id(kind)),
        "kind": kind,
        "content": content.strip(),
        "tags": sorted(set(tags)),
        "updated_at": item.get("updated_at", utc_now()),
    }


def sentence_segments(text: str) -> list[str]:
    segments = re.split(r"[。\n\r!?！？;；]+", text)
    return [re.sub(r"\s+", " ", segment).strip(" -:") for segment in segments if segment and segment.strip()]


def detect_preference_markers(text: str) -> tuple[str | None, list[str]]:
    markers: list[str] = []
    for pattern in PREFERENCE_STRONG_PATTERNS:
        matches = [match.group(0).strip() for match in pattern.finditer(text)]
        markers.extend(matches)
    if markers:
        return "strong", sorted(set(markers))
    for pattern in PREFERENCE_WEAK_PATTERNS:
        matches = [match.group(0).strip() for match in pattern.finditer(text)]
        markers.extend(matches)
    if markers:
        return "weak", sorted(set(markers))
    return None, []


def preference_strength_rank(value: str | None) -> int:
    if value == "strong":
        return 2
    if value == "weak":
        return 1
    return 0


def preference_items_match(
    left_content: str,
    left_tags: list[str] | set[str],
    right_content: str,
    right_tags: list[str] | set[str],
) -> bool:
    normalized_left = re.sub(r"\s+", " ", left_content).strip().lower()
    normalized_right = re.sub(r"\s+", " ", right_content).strip().lower()
    if normalized_left == normalized_right:
        return True
    left_tokens = set(left_tags) if left_tags else preference_similarity_tokens(left_content)
    right_tokens = set(right_tags) if right_tags else preference_similarity_tokens(right_content)
    overlap = left_tokens.intersection(right_tokens)
    if len(overlap) < 2:
        return False
    ratio = len(overlap) / float(min(len(left_tokens), len(right_tokens)))
    return ratio >= 0.55


def extract_preference_candidates(request: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for segment in sentence_segments(request):
        if len(segment) < 6 or len(segment) > 220:
            continue
        signal_strength, signal_markers = detect_preference_markers(segment)
        if signal_strength is None:
            continue
        tags = summarize_memory_tags(preference_similarity_tokens(segment))
        if signal_strength != "strong" and not tags:
            continue
        candidate = {
            "content": segment,
            "tags": tags,
            "signal_strength": signal_strength,
            "signal_markers": signal_markers,
        }
        duplicate = next(
            (
                item
                for item in candidates
                if preference_items_match(item["content"], item.get("tags", []), segment, tags)
            ),
            None,
        )
        if duplicate:
            merged_tags = summarize_memory_tags(set(duplicate.get("tags", [])).union(tags))
            duplicate["tags"] = merged_tags
            duplicate["signal_markers"] = sorted(set(duplicate.get("signal_markers", []) + signal_markers))
            if preference_strength_rank(signal_strength) > preference_strength_rank(duplicate.get("signal_strength")):
                duplicate["signal_strength"] = signal_strength
                duplicate["content"] = segment
            continue
        candidates.append(candidate)
    return candidates


def normalize_preference_observation(
    item: dict[str, Any],
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    now = utc_now()
    normalized_note = normalize_memory_note(item, kind="preference-observation")
    source_run_ids = item.get("source_run_ids", [])
    if not isinstance(source_run_ids, list) or not all(isinstance(entry, str) and entry.strip() for entry in source_run_ids):
        raise ControlPlaneError("preference observation source_run_ids must be a list of non-empty strings")
    if run_id and run_id not in source_run_ids:
        source_run_ids.append(run_id)
    signal_markers = item.get("signal_markers", [])
    if not isinstance(signal_markers, list) or not all(isinstance(marker, str) and marker.strip() for marker in signal_markers):
        raise ControlPlaneError("preference observation signal_markers must be a list of non-empty strings")
    occurrences = item.get("occurrences", 1)
    if not isinstance(occurrences, int) or occurrences < 1:
        raise ControlPlaneError("preference observation occurrences must be a positive integer")
    status = item.get("status", "observed")
    if status not in {"observed", "promoted"}:
        raise ControlPlaneError("preference observation status must be `observed` or `promoted`")
    signal_strength = item.get("signal_strength", "weak")
    if signal_strength not in {"weak", "strong"}:
        raise ControlPlaneError("preference observation signal_strength must be `weak` or `strong`")
    return {
        **normalized_note,
        "signal_strength": signal_strength,
        "signal_markers": sorted(set(signal_markers)),
        "occurrences": occurrences,
        "status": status,
        "source_run_ids": source_run_ids[-10:],
        "first_seen_at": item.get("first_seen_at", now),
        "last_seen_at": item.get("last_seen_at", now),
        "promotion_reason": item.get("promotion_reason"),
        "promoted_at": item.get("promoted_at"),
    }


def ensure_memory_card(
    cards_payload: dict[str, Any],
    *,
    kind: str,
    content: str,
    tags: list[str],
    source_run_id: str | None = None,
) -> None:
    if not isinstance(content, str) or not content.strip():
        return
    normalized_tags = sorted(set(tag for tag in tags if tag.strip()))
    cards = cards_payload.setdefault("cards", [])
    for item in cards:
        if item.get("kind") == kind and item.get("content") == content.strip():
            merged = sorted(set(item.get("tags", []) + normalized_tags))
            item["tags"] = merged
            item["updated_at"] = utc_now()
            if source_run_id:
                item["source_run_id"] = source_run_id
            return
    cards.append(
        {
            "id": next_memory_item_id("memory"),
            "kind": kind,
            "content": content.strip(),
            "tags": normalized_tags,
            "source_run_id": source_run_id,
            "updated_at": utc_now(),
        }
    )


def score_memory_item(request_tokens: set[str], item: dict[str, Any], *, base_weight: float) -> float:
    content_tokens = tokenize_memory_text(item.get("content", ""))
    tag_tokens = set()
    for tag in item.get("tags", []):
        tag_tokens.update(tokenize_memory_text(tag))
    overlap = len(request_tokens.intersection(content_tokens))
    tag_overlap = len(request_tokens.intersection(tag_tokens))
    freshness = 0.05 if item.get("updated_at") else 0.0
    return base_weight + (overlap * 1.2) + (tag_overlap * 1.5) + freshness


def retrieve_relevant_team_memory(
    request: str,
    *,
    preferences_payload: dict[str, Any],
    project_payload: dict[str, Any],
    cards_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    request_tokens = tokenize_memory_text(request)
    scored: list[tuple[float, dict[str, Any]]] = []
    for item in preferences_payload.get("preferences", []):
        score = score_memory_item(request_tokens, item, base_weight=3.0)
        scored.append((score, {"kind": "preference", **item}))
    for item in project_payload.get("notes", []):
        score = score_memory_item(request_tokens, item, base_weight=2.4)
        scored.append((score, {"kind": "project", **item}))
    for item in cards_payload.get("cards", []):
        kind = item.get("kind", "memory")
        weight = {"learning": 2.6, "run_summary": 2.0, "feedback": 1.6}.get(kind, 1.8)
        score = score_memory_item(request_tokens, item, base_weight=weight)
        scored.append((score, item))
    ranked = [item for score, item in sorted(scored, key=lambda pair: pair[0], reverse=True) if score > 0.5]
    return ranked[:8]


def infer_domain_from_request(request: str) -> str:
    normalized = request.lower()
    if any(token in normalized for token in ["逆向", "reverse", "reversing", "frida", "ida", "app"]):
        if "视频" not in normalized and "video" not in normalized:
            return "reverse-engineering"
    if any(token in normalized for token in ["视频", "剪辑", "video", "editing", "short-video"]):
        return "video-editing"
    if any(token in normalized for token in ["bug", "修复", "排障", "debug", "incident"]):
        return "bug-fix"
    if any(token in normalized for token in ["mvp", "产品", "product", "功能", "开发", "build"]):
        return "mvp-delivery"
    if any(token in normalized for token in ["调研", "研究", "research", "分析"]):
        return "research"
    return "general"


def default_team_id_for_domain(domain: str) -> str:
    mapping = {
        "reverse-engineering": "AEGIS-nx",
        "video-editing": "AEGIS-video",
        "bug-fix": "AEGIS-bugfix",
        "mvp-delivery": "AEGIS-mvp",
        "research": "AEGIS-research",
        "general": "AEGIS-team",
    }
    return mapping.get(domain, "AEGIS-team")


def extract_named_team_id(request: str) -> str | None:
    patterns = [
        r"(?:名字叫|叫)\s*([A-Za-z0-9_-]{2,63})",
        r"(?:named|called)\s+([A-Za-z0-9_-]{2,63})",
    ]
    for pattern in patterns:
        matched = re.search(pattern, request, flags=re.IGNORECASE)
        if matched:
            return matched.group(1)
    return None


def infer_scope_from_request(request: str, explicit_scope: str | None = None) -> str:
    if explicit_scope:
        return normalize_team_scope(explicit_scope)
    normalized = request.lower()
    if any(token in normalized for token in ["当前项目", "this project", "current project", "这个项目"]):
        return "project"
    if any(token in normalized for token in ["一次性", "临时", "session", "temporary"]):
        return "session"
    return "global"


def build_team_mission_from_request(request: str, domain: str) -> str:
    cleaned = request.strip()
    prefixes = [
        "aegis",
        "帮我",
        "请帮我",
        "请",
    ]
    lowered = cleaned.lower()
    for prefix in prefixes:
        if lowered.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip(" :,-")
            lowered = cleaned.lower()
    if cleaned:
        return cleaned[0].upper() + cleaned[1:]
    return f"Long-lived {domain} team generated by AEGIS."


def compose_team_pack_from_request(
    request: str,
    *,
    team_id: str | None,
    display_name: str | None,
    scope: str | None,
    install: bool,
    explicit_workspace: str | Path | None = None,
) -> list[str]:
    normalized_request = request.strip()
    if not normalized_request:
        raise ControlPlaneError("team composition request must not be empty")
    inferred_domain = infer_domain_from_request(normalized_request)
    resolved_scope = infer_scope_from_request(normalized_request, scope)
    resolved_team_id = team_id or extract_named_team_id(normalized_request) or default_team_id_for_domain(inferred_domain)
    resolved_display_name = display_name or humanize_identifier(resolved_team_id)
    mission = build_team_mission_from_request(normalized_request, inferred_domain)
    return create_team_pack(
        team_id=resolved_team_id,
        display_name=resolved_display_name,
        mission=mission,
        domain=inferred_domain,
        scope=resolved_scope,
        role_specs=[],
        playbook_steps=[],
        review_mode=None,
        install=install,
        explicit_workspace=explicit_workspace,
    )


def validate_team_run_record(payload: dict[str, Any], label: str) -> None:
    validate_required_keys(payload, TEAM_RUN_SCHEMA_PATH, label)
    validate_team_id(payload["team_id"])
    if normalize_team_scope(payload["scope"]) == "all":
        raise ControlPlaneError(f"{label} scope cannot be `all`")
    if not isinstance(payload["request"], str) or not payload["request"].strip():
        raise ControlPlaneError(f"{label} request must be a non-empty string")
    if not isinstance(payload["summary"], str) or not payload["summary"].strip():
        raise ControlPlaneError(f"{label} summary must be a non-empty string")
    if not isinstance(payload["status"], str) or not payload["status"].strip():
        raise ControlPlaneError(f"{label} status must be a non-empty string")
    if not isinstance(payload["artifacts"], list):
        raise ControlPlaneError(f"{label} artifacts must be a list")
    if not isinstance(payload["feedback"], list):
        raise ControlPlaneError(f"{label} feedback must be a list")
    if not isinstance(payload["learnings"], list):
        raise ControlPlaneError(f"{label} learnings must be a list")


def validate_team_run_brief(payload: dict[str, Any], label: str) -> None:
    validate_required_keys(payload, TEAM_RUN_BRIEF_SCHEMA_PATH, label)
    validate_team_id(payload["team_id"])
    if normalize_team_scope(payload["scope"]) == "all":
        raise ControlPlaneError(f"{label} scope cannot be `all`")
    if not isinstance(payload["selected_roles"], list) or not payload["selected_roles"]:
        raise ControlPlaneError(f"{label} selected_roles must be a non-empty list")
    if not all(isinstance(item, dict) and "id" in item and "title" in item for item in payload["selected_roles"]):
        raise ControlPlaneError(f"{label} selected_roles entries must include id and title")
    if not isinstance(payload["playbook_steps"], list) or not payload["playbook_steps"]:
        raise ControlPlaneError(f"{label} playbook_steps must be a non-empty list")
    if not isinstance(payload["recent_run_summaries"], list):
        raise ControlPlaneError(f"{label} recent_run_summaries must be a list")
    if not isinstance(payload["recent_learnings"], list):
        raise ControlPlaneError(f"{label} recent_learnings must be a list")
    if not isinstance(payload["preference_memory"], list):
        raise ControlPlaneError(f"{label} preference_memory must be a list")
    if not isinstance(payload["project_memory"], list):
        raise ControlPlaneError(f"{label} project_memory must be a list")
    if not isinstance(payload["relevant_memories"], list):
        raise ControlPlaneError(f"{label} relevant_memories must be a list")
    if "observed_preference_candidates" in payload:
        if not isinstance(payload["observed_preference_candidates"], list):
            raise ControlPlaneError(f"{label} observed_preference_candidates must be a list when provided")
        for item in payload["observed_preference_candidates"]:
            if not isinstance(item, dict) or "content" not in item or "signal_strength" not in item:
                raise ControlPlaneError(
                    f"{label} observed_preference_candidates entries must include content and signal_strength"
                )


def role_is_reviewer(role: dict[str, Any]) -> bool:
    marker = f"{role.get('id', '')} {role.get('title', '')}".lower()
    return "review" in marker


def render_team_run_brief_markdown(payload: dict[str, Any]) -> str:
    role_lines = "\n".join(
        [
            f"- `{role['id']}`: {role['title']}"
            for role in payload["selected_roles"]
        ]
    )
    playbook_lines = "\n".join(
        [f"{index}. {step}" for index, step in enumerate(payload["playbook_steps"], start=1)]
    )
    preference_lines = (
        "\n".join([f"- {item['content']}" for item in payload.get("preference_memory", [])])
        if payload.get("preference_memory")
        else "- none"
    )
    project_lines = (
        "\n".join([f"- {item['content']}" for item in payload.get("project_memory", [])])
        if payload.get("project_memory")
        else "- none"
    )
    relevant_memory_lines = (
        "\n".join(
            [
                f"- `{item.get('kind', 'memory')}`: {item['content']}"
                for item in payload.get("relevant_memories", [])
            ]
        )
        if payload.get("relevant_memories")
        else "- none"
    )
    observation_lines = (
        "\n".join(
            [
                f"- `{item['signal_strength']}`: {item['content']}"
                for item in payload.get("observed_preference_candidates", [])
            ]
        )
        if payload.get("observed_preference_candidates")
        else "- none"
    )
    learnings = payload.get("recent_learnings", [])
    recent_runs = payload.get("recent_run_summaries", [])
    learning_lines = "\n".join([f"- {item}" for item in learnings]) if learnings else "- none"
    run_lines = (
        "\n".join(
            [f"- `{item['run_id']}`: {item['summary']}" for item in recent_runs]
        )
        if recent_runs
        else "- none"
    )
    return "\n".join(
        [
            f"# Team Run Brief: {payload['team_display_name']}",
            "",
            f"- run id: `{payload['run_id']}`",
            f"- team id: `{payload['team_id']}`",
            f"- scope: `{payload['scope']}`",
            f"- review mode: `{payload['review_mode']}`",
            "",
            "## Request",
            "",
            payload["request"],
            "",
            "## Selected Roles",
            "",
            role_lines,
            "",
            "## Default Playbook",
            "",
            playbook_lines,
            "",
            "## Preference Memory",
            "",
            preference_lines,
            "",
            "## Project Memory",
            "",
            project_lines,
            "",
            "## Relevant Recall",
            "",
            relevant_memory_lines,
            "",
            "## Preference Signals In This Request",
            "",
            observation_lines,
            "",
            "## Recent Runs",
            "",
            run_lines,
            "",
            "## Recent Learnings",
            "",
            learning_lines,
            "",
        ]
    )


def render_team_memory_markdown(
    payload: dict[str, Any],
    summaries: list[dict[str, Any]],
    learnings: list[str],
    preferences: list[dict[str, Any]],
    preference_observations: list[dict[str, Any]],
    project_notes: list[dict[str, Any]],
    cards: list[dict[str, Any]],
) -> str:
    run_lines = (
        "\n".join(
            [
                f"- `{item['run_id']}` | `{item['status']}` | {item['summary']}"
                for item in reversed(summaries[-10:])
            ]
        )
        if summaries
        else "- none"
    )
    learning_lines = "\n".join([f"- {item}" for item in learnings[-10:]]) if learnings else "- none"
    preference_lines = (
        "\n".join([f"- {item['content']}" for item in preferences[-10:]])
        if preferences
        else "- none"
    )
    observation_lines = (
        "\n".join(
            [
                f"- `{item.get('status', 'observed')}` x{item.get('occurrences', 1)} | {item['content']}"
                for item in reversed(preference_observations[-10:])
            ]
        )
        if preference_observations
        else "- none"
    )
    project_lines = (
        "\n".join([f"- {item['content']}" for item in project_notes[-10:]])
        if project_notes
        else "- none"
    )
    return "\n".join(
        [
            f"# Team Memory: {payload['display_name']}",
            "",
            f"- team id: `{payload['team_id']}`",
            f"- scope: `{payload['lifecycle_scope']}`",
            f"- run count: `{payload.get('run_count', 0)}`",
            f"- last run at: `{payload.get('last_run_at', 'n/a')}`",
            f"- preference items: `{len(preferences)}`",
            f"- preference observations: `{len(preference_observations)}`",
            f"- project memory notes: `{len(project_notes)}`",
            f"- retrievable memory cards: `{len(cards)}`",
            "",
            "## Recent Runs",
            "",
            run_lines,
            "",
            "## Preference Memory",
            "",
            preference_lines,
            "",
            "## Preference Observations",
            "",
            observation_lines,
            "",
            "## Project Memory",
            "",
            project_lines,
            "",
            "## Stable Learnings",
            "",
            learning_lines,
            "",
            "Read this file before substantial new work so the team behaves like a persistent specialist team instead of a stateless prompt.",
            "",
        ]
    )


def render_team_run_summary_markdown(payload: dict[str, Any]) -> str:
    artifact_lines = "\n".join([f"- {item}" for item in payload["artifacts"]]) if payload["artifacts"] else "- none"
    feedback_lines = "\n".join([f"- {item}" for item in payload["feedback"]]) if payload["feedback"] else "- none"
    learning_lines = "\n".join([f"- {item}" for item in payload["learnings"]]) if payload["learnings"] else "- none"
    return "\n".join(
        [
            f"# Team Run Summary: {payload['team_id']}",
            "",
            f"- run id: `{payload['run_id']}`",
            f"- status: `{payload['status']}`",
            f"- recorded at: `{payload['recorded_at']}`",
            "",
            "## Request",
            "",
            payload["request"],
            "",
            "## Summary",
            "",
            payload["summary"],
            "",
            "## Artifacts",
            "",
            artifact_lines,
            "",
            "## Feedback",
            "",
            feedback_lines,
            "",
            "## Learnings",
            "",
            learning_lines,
            "",
        ]
    )


def load_team_preferences(
    team_id: str,
    scope: str,
    explicit_workspace: str | Path | None = None,
) -> dict[str, Any]:
    return load_optional_memory_object(
        team_preferences_path(team_id, scope, explicit_workspace),
        default_team_preferences_payload(team_id),
    )


def load_team_preference_observations(
    team_id: str,
    scope: str,
    explicit_workspace: str | Path | None = None,
) -> dict[str, Any]:
    return load_optional_memory_object(
        team_preference_observations_path(team_id, scope, explicit_workspace),
        default_team_preference_observations_payload(team_id),
    )


def load_team_project_memory(
    team_id: str,
    scope: str,
    explicit_workspace: str | Path | None = None,
) -> dict[str, Any]:
    return load_optional_memory_object(
        team_project_memory_path(team_id, scope, explicit_workspace),
        default_team_project_memory_payload(team_id, scope, explicit_workspace),
    )


def load_team_memory_cards(
    team_id: str,
    scope: str,
    explicit_workspace: str | Path | None = None,
) -> dict[str, Any]:
    return load_optional_memory_object(
        team_memory_cards_path(team_id, scope, explicit_workspace),
        default_team_memory_cards_payload(team_id),
    )


def ensure_preference_memory_note(
    preferences_payload: dict[str, Any],
    *,
    content: str,
    tags: list[str],
) -> tuple[dict[str, Any], bool]:
    preferences = preferences_payload.setdefault("preferences", [])
    for item in preferences:
        if preference_items_match(item.get("content", ""), item.get("tags", []), content, tags):
            merged_tags = summarize_memory_tags(set(item.get("tags", [])).union(tags))
            item["tags"] = merged_tags
            item["updated_at"] = utc_now()
            if len(content.strip()) < len(item.get("content", "").strip()):
                item["content"] = content.strip()
            return item, False
    normalized_note = normalize_memory_note({"content": content, "tags": tags}, kind="preference")
    preferences.append(normalized_note)
    preferences_payload["updated_at"] = utc_now()
    return normalized_note, True


def upsert_preference_observation(
    observations_payload: dict[str, Any],
    *,
    candidate: dict[str, Any],
    run_id: str | None = None,
) -> dict[str, Any]:
    observations = observations_payload.setdefault("observations", [])
    now = utc_now()
    for item in observations:
        if preference_items_match(item.get("content", ""), item.get("tags", []), candidate["content"], candidate["tags"]):
            item["occurrences"] = int(item.get("occurrences", 1)) + 1
            item["last_seen_at"] = now
            item["updated_at"] = now
            item["tags"] = summarize_memory_tags(set(item.get("tags", [])).union(candidate.get("tags", [])))
            item["signal_markers"] = sorted(set(item.get("signal_markers", []) + candidate.get("signal_markers", [])))
            if run_id:
                item["source_run_ids"] = list(dict.fromkeys(item.get("source_run_ids", []) + [run_id]))[-10:]
            if preference_strength_rank(candidate.get("signal_strength")) > preference_strength_rank(item.get("signal_strength")):
                item["signal_strength"] = candidate["signal_strength"]
                item["content"] = candidate["content"]
            normalized_observation = normalize_preference_observation(item)
            item.clear()
            item.update(normalized_observation)
            observations_payload["updated_at"] = now
            return item
    observation = normalize_preference_observation(
        {
            "content": candidate["content"],
            "tags": candidate.get("tags", []),
            "signal_strength": candidate.get("signal_strength", "weak"),
            "signal_markers": candidate.get("signal_markers", []),
            "occurrences": 1,
            "status": "observed",
            "first_seen_at": now,
            "last_seen_at": now,
        },
        run_id=run_id,
    )
    observations.append(observation)
    observations_payload["updated_at"] = now
    return observation


def maybe_promote_preference_observation(
    observation: dict[str, Any],
    *,
    candidate: dict[str, Any],
) -> str | None:
    if observation.get("status") == "promoted":
        return None
    if candidate.get("signal_strength") == "strong" or observation.get("signal_strength") == "strong":
        return "explicit_signal"
    if int(observation.get("occurrences", 1)) >= 2:
        return "repeated_signal"
    return None


def mark_preference_observation_promoted(observation: dict[str, Any], promotion_reason: str) -> None:
    observation["status"] = "promoted"
    observation["promotion_reason"] = promotion_reason
    observation["promoted_at"] = utc_now()
    observation["updated_at"] = observation["promoted_at"]


def auto_learn_team_preferences(
    *,
    team_id: str,
    scope: str,
    request: str,
    run_id: str | None,
    cards_payload: dict[str, Any],
    explicit_workspace: str | Path | None = None,
    prepared_candidates: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, int]]:
    candidates = prepared_candidates if prepared_candidates is not None else extract_preference_candidates(request)
    preferences_payload = load_team_preferences(team_id, scope, explicit_workspace)
    observations_payload = load_team_preference_observations(team_id, scope, explicit_workspace)
    observed_count = 0
    promoted_count = 0
    for candidate in candidates:
        observation = upsert_preference_observation(
            observations_payload,
            candidate=candidate,
            run_id=run_id,
        )
        observed_count += 1
        promotion_reason = maybe_promote_preference_observation(observation, candidate=candidate)
        if promotion_reason is None:
            continue
        preference_note, created = ensure_preference_memory_note(
            preferences_payload,
            content=observation["content"],
            tags=observation.get("tags", []),
        )
        mark_preference_observation_promoted(observation, promotion_reason)
        ensure_memory_card(
            cards_payload,
            kind="preference",
            content=preference_note["content"],
            tags=preference_note.get("tags", []),
            source_run_id=run_id,
        )
        if created:
            promoted_count += 1
    if observed_count:
        observations_payload["updated_at"] = utc_now()
        write_json(team_preference_observations_path(team_id, scope, explicit_workspace), observations_payload)
    if observed_count or promoted_count:
        write_json(team_preferences_path(team_id, scope, explicit_workspace), preferences_payload)
    return preferences_payload, observations_payload, {
        "candidates": len(candidates),
        "observed": observed_count,
        "promoted": promoted_count,
    }


def record_team_preference(
    *,
    team_id: str,
    note: str,
    scope: str = "all",
    tags: list[str],
    explicit_workspace: str | Path | None = None,
) -> list[str]:
    item_scope, _, payload = find_team_pack(team_id, scope, explicit_workspace)
    preferences_payload = load_team_preferences(payload["team_id"], item_scope, explicit_workspace)
    preferences = preferences_payload.setdefault("preferences", [])
    normalized_note = normalize_memory_note({"content": note, "tags": tags}, kind="preference")
    preferences.append(normalized_note)
    preferences_payload["updated_at"] = utc_now()
    write_json(team_preferences_path(payload["team_id"], item_scope, explicit_workspace), preferences_payload)
    ensure_team_pack_assets(team_pack_dir(payload["team_id"], item_scope, explicit_workspace), payload)
    return [
        f"recorded team preference: {normalized_note['id']}",
        f"preferences_path: {display_path(team_preferences_path(payload['team_id'], item_scope, explicit_workspace))}",
    ]


def record_team_project_memory(
    *,
    team_id: str,
    note: str,
    scope: str = "all",
    tags: list[str],
    explicit_workspace: str | Path | None = None,
) -> list[str]:
    item_scope, _, payload = find_team_pack(team_id, scope, explicit_workspace)
    project_payload = load_team_project_memory(payload["team_id"], item_scope, explicit_workspace)
    notes = project_payload.setdefault("notes", [])
    normalized_note = normalize_memory_note({"content": note, "tags": tags}, kind="project")
    notes.append(normalized_note)
    project_payload["updated_at"] = utc_now()
    write_json(team_project_memory_path(payload["team_id"], item_scope, explicit_workspace), project_payload)
    ensure_team_pack_assets(team_pack_dir(payload["team_id"], item_scope, explicit_workspace), payload)
    return [
        f"recorded team project memory: {normalized_note['id']}",
        f"project_memory_path: {display_path(team_project_memory_path(payload['team_id'], item_scope, explicit_workspace))}",
    ]


def select_team_roles(payload: dict[str, Any], request: str) -> list[dict[str, Any]]:
    roles = deepcopy(payload["roles"])
    if len(roles) <= 4:
        return roles
    lowered = request.lower()
    selected: list[dict[str, Any]] = []
    reviewer_roles = [role for role in roles if role_is_reviewer(role)]
    non_review_roles = [role for role in roles if not role_is_reviewer(role)]

    keyword_map = {
        "search": ["research", "trend", "analyst"],
        "research": ["research", "trend", "analyst"],
        "调研": ["research", "trend", "analyst"],
        "style": ["editing", "caption", "trend"],
        "风格": ["editing", "caption", "trend"],
        "hook": ["caption", "structure"],
        "字幕": ["caption"],
        "脚本": ["structure", "planner"],
        "结构": ["structure", "planner"],
        "bug": ["triage", "root-cause", "fix"],
        "修复": ["triage", "root-cause", "fix"],
        "reverse": ["reverse", "static", "behavior"],
        "逆向": ["reverse", "static", "behavior"],
    }
    matched_tokens: list[str] = []
    for token, fragments in keyword_map.items():
        if token in lowered:
            matched_tokens.extend(fragments)
    for role in non_review_roles:
        role_marker = f"{role['id']} {role['title']}".lower()
        if any(fragment in role_marker for fragment in matched_tokens):
            selected.append(role)
    for role in non_review_roles:
        if len(selected) >= 3:
            break
        if role not in selected:
            selected.append(role)
    if reviewer_roles:
        selected.append(reviewer_roles[0])
    return selected


def prepare_team_run(
    *,
    team_id: str,
    request: str,
    scope: str = "all",
    explicit_workspace: str | Path | None = None,
) -> list[str]:
    item_scope, _, payload = find_team_pack(team_id, scope, explicit_workspace)
    run_id = next_team_run_id(team_id)
    summaries = load_optional_list(team_run_index_path(payload["team_id"], item_scope, explicit_workspace))
    learnings = load_optional_list(team_learning_path(payload["team_id"], item_scope, explicit_workspace))
    preferences_payload = load_team_preferences(payload["team_id"], item_scope, explicit_workspace)
    observations_payload = load_team_preference_observations(payload["team_id"], item_scope, explicit_workspace)
    project_payload = load_team_project_memory(payload["team_id"], item_scope, explicit_workspace)
    cards_payload = load_team_memory_cards(payload["team_id"], item_scope, explicit_workspace)
    preference_candidates = extract_preference_candidates(request)
    relevant_memories = retrieve_relevant_team_memory(
        request,
        preferences_payload=preferences_payload,
        project_payload=project_payload,
        cards_payload=cards_payload,
    )
    selected_roles = select_team_roles(payload, request)
    brief_payload = {
        "version": "1.0.0",
        "run_id": run_id,
        "team_id": payload["team_id"],
        "scope": item_scope,
        "request": request,
        "team_display_name": payload["display_name"],
        "mission": payload["mission"],
        "selected_roles": selected_roles,
        "review_mode": payload["review_mode"]["mode"],
        "playbook_steps": payload["playbook_steps"],
        "recent_run_summaries": summaries[-5:],
        "recent_learnings": learnings[-5:],
        "preference_memory": preferences_payload.get("preferences", [])[-5:],
        "project_memory": project_payload.get("notes", [])[-5:],
        "relevant_memories": relevant_memories,
        "observed_preference_candidates": preference_candidates,
        "prepared_at": utc_now(),
    }
    validate_team_run_brief(brief_payload, f"team run brief {run_id}")
    brief_path = team_run_brief_path(payload["team_id"], item_scope, run_id, explicit_workspace)
    brief_markdown_path = team_run_brief_markdown_path(payload["team_id"], item_scope, run_id, explicit_workspace)
    memory_markdown = team_memory_markdown_path(payload["team_id"], item_scope, explicit_workspace)
    write_json(brief_path, brief_payload)
    brief_markdown_path.write_text(render_team_run_brief_markdown(brief_payload), encoding="utf-8")
    return [
        f"prepared team run: {display_path(brief_path)}",
        f"wrote team run brief markdown: {display_path(brief_markdown_path)}",
        f"team_memory_markdown: {display_path(memory_markdown)}",
        f"run_id: {run_id}",
        f"selected_roles: {', '.join(role['id'] for role in selected_roles)}",
        f"recent_runs_loaded: {len(brief_payload['recent_run_summaries'])}",
        f"recent_learnings_loaded: {len(brief_payload['recent_learnings'])}",
        f"preferences_loaded: {len(brief_payload['preference_memory'])}",
        f"preference_observations_loaded: {len(observations_payload.get('observations', []))}",
        f"preference_signals_detected: {len(preference_candidates)}",
        f"project_memory_loaded: {len(brief_payload['project_memory'])}",
        f"relevant_memories_loaded: {len(brief_payload['relevant_memories'])}",
        f"review_mode: {payload['review_mode']['mode']}",
    ]


def record_team_run(
    *,
    team_id: str,
    scope: str = "all",
    request: str,
    summary: str,
    status: str,
    artifacts: list[str],
    feedback: list[str],
    learnings: list[str],
    run_id: str | None = None,
    explicit_workspace: str | Path | None = None,
) -> list[str]:
    item_scope, team_dir, payload = find_team_pack(team_id, scope, explicit_workspace)
    resolved_run_id = run_id or next_team_run_id(team_id)
    brief_candidates: list[dict[str, Any]] | None = None
    brief_path = team_run_brief_path(payload["team_id"], item_scope, resolved_run_id, explicit_workspace)
    if brief_path.exists():
        brief_payload = load_json(brief_path)
        validate_team_run_brief(brief_payload, display_path(brief_path))
        raw_candidates = brief_payload.get("observed_preference_candidates")
        if isinstance(raw_candidates, list):
            brief_candidates = raw_candidates
    run_payload = {
        "version": "1.0.0",
        "run_id": resolved_run_id,
        "team_id": payload["team_id"],
        "scope": item_scope,
        "request": request,
        "summary": summary,
        "status": status,
        "artifacts": artifacts,
        "feedback": feedback,
        "learnings": learnings,
        "recorded_at": utc_now(),
    }
    validate_team_run_record(run_payload, f"team run {resolved_run_id}")
    runs_dir = team_dir / "runs"
    memory_dir = team_dir / "memory"
    runs_dir.mkdir(parents=True, exist_ok=True)
    memory_dir.mkdir(parents=True, exist_ok=True)
    run_record_path = team_run_record_path(payload["team_id"], item_scope, resolved_run_id, explicit_workspace)
    run_summary_markdown_path = team_run_summary_markdown_path(
        payload["team_id"], item_scope, resolved_run_id, explicit_workspace
    )
    write_json(run_record_path, run_payload)
    run_summary_markdown_path.write_text(render_team_run_summary_markdown(run_payload), encoding="utf-8")
    brief_markdown_path = team_run_brief_markdown_path(payload["team_id"], item_scope, resolved_run_id, explicit_workspace)
    messages = [f"recorded team run: {display_path(run_record_path)}"]
    if brief_path.exists():
        brief_path.unlink()
        messages.append(f"removed team run brief: {display_path(brief_path)}")
    if brief_markdown_path.exists():
        brief_markdown_path.unlink()
        messages.append(f"removed team run brief markdown: {display_path(brief_markdown_path)}")
    messages.append(f"wrote team run summary markdown: {display_path(run_summary_markdown_path)}")

    summaries = load_optional_list(memory_dir / "run-summaries.json")
    summaries.append(
        {
            "run_id": resolved_run_id,
            "summary": summary,
            "status": status,
            "recorded_at": run_payload["recorded_at"],
        }
    )
    write_json(memory_dir / "run-summaries.json", summaries)

    stored_learnings = load_optional_list(memory_dir / "team-learnings.json")
    for item in learnings:
        if item not in stored_learnings:
            stored_learnings.append(item)
    write_json(memory_dir / "team-learnings.json", stored_learnings)

    cards_payload = load_team_memory_cards(payload["team_id"], item_scope, explicit_workspace)
    request_tags = sorted(tokenize_memory_text(f"{request} {summary}"))
    ensure_memory_card(
        cards_payload,
        kind="run_summary",
        content=summary,
        tags=request_tags,
        source_run_id=resolved_run_id,
    )
    for item in learnings:
        ensure_memory_card(
            cards_payload,
            kind="learning",
            content=item,
            tags=sorted(tokenize_memory_text(f"{request} {item}")),
            source_run_id=resolved_run_id,
        )
    for item in feedback:
        ensure_memory_card(
            cards_payload,
            kind="feedback",
            content=item,
            tags=sorted(tokenize_memory_text(f"{request} {item}")),
            source_run_id=resolved_run_id,
        )

    preference_metrics = {"candidates": 0, "observed": 0, "promoted": 0}
    preferences_payload = load_team_preferences(payload["team_id"], item_scope, explicit_workspace)
    observations_payload = load_team_preference_observations(payload["team_id"], item_scope, explicit_workspace)
    if payload.get("memory_policy", {}).get("store_preference_memory", True):
        preferences_payload, observations_payload, preference_metrics = auto_learn_team_preferences(
            team_id=payload["team_id"],
            scope=item_scope,
            request=request,
            run_id=resolved_run_id,
            cards_payload=cards_payload,
            explicit_workspace=explicit_workspace,
            prepared_candidates=brief_candidates,
        )
    cards_payload["updated_at"] = utc_now()
    write_json(team_memory_cards_path(payload["team_id"], item_scope, explicit_workspace), cards_payload)

    next_payload = deepcopy(payload)
    next_payload["last_run_at"] = run_payload["recorded_at"]
    next_payload["run_count"] = int(payload.get("run_count", 0)) + 1
    write_json(team_dir / "team.json", next_payload)
    project_payload = load_team_project_memory(payload["team_id"], item_scope, explicit_workspace)
    memory_markdown_path = team_memory_markdown_path(payload["team_id"], item_scope, explicit_workspace)
    memory_markdown_path.write_text(
        render_team_memory_markdown(
            next_payload,
            summaries,
            stored_learnings,
            preferences_payload.get("preferences", []),
            observations_payload.get("observations", []),
            project_payload.get("notes", []),
            cards_payload.get("cards", []),
        ),
        encoding="utf-8",
    )
    messages.extend(
        [
            f"updated team summaries: {display_path(memory_dir / 'run-summaries.json')}",
            f"updated team learnings: {display_path(memory_dir / 'team-learnings.json')}",
            f"updated team preference observations: {display_path(team_preference_observations_path(payload['team_id'], item_scope, explicit_workspace))}",
            f"updated team memory cards: {display_path(team_memory_cards_path(payload['team_id'], item_scope, explicit_workspace))}",
            f"updated team memory markdown: {display_path(memory_markdown_path)}",
            f"auto_preference_candidates: {preference_metrics['candidates']}",
            f"auto_preference_observations: {preference_metrics['observed']}",
            f"auto_promoted_preferences: {preference_metrics['promoted']}",
        ]
    )
    return messages


def show_team_run(
    team_id: str,
    run_id: str,
    scope: str = "all",
    explicit_workspace: str | Path | None = None,
) -> list[str]:
    item_scope, team_dir, payload = find_team_pack(team_id, scope, explicit_workspace)
    brief_path = team_run_brief_path(payload["team_id"], item_scope, run_id, explicit_workspace)
    record_path = team_run_record_path(payload["team_id"], item_scope, run_id, explicit_workspace)
    if brief_path.exists():
        brief_payload = load_json(brief_path)
        validate_team_run_brief(brief_payload, display_path(brief_path))
        return [
            f"team_id: {payload['team_id']}",
            f"run_id: {run_id}",
            "status: prepared",
            f"request: {brief_payload['request']}",
            f"selected_roles: {', '.join(role['id'] for role in brief_payload['selected_roles'])}",
            f"brief_json: {display_path(brief_path)}",
            f"brief_markdown: {display_path(team_run_brief_markdown_path(payload['team_id'], item_scope, run_id, explicit_workspace))}",
        ]
    if record_path.exists():
        run_payload = load_json(record_path)
        validate_team_run_record(run_payload, display_path(record_path))
        return [
            f"team_id: {payload['team_id']}",
            f"run_id: {run_id}",
            f"status: {run_payload['status']}",
            f"summary: {run_payload['summary']}",
            f"artifacts: {', '.join(run_payload['artifacts']) if run_payload['artifacts'] else 'none'}",
            f"record_json: {display_path(record_path)}",
            f"summary_markdown: {display_path(team_run_summary_markdown_path(payload['team_id'], item_scope, run_id, explicit_workspace))}",
        ]
    raise ControlPlaneError(f"team run not found: {team_id}::{run_id}")


def complete_team_run(
    *,
    team_id: str,
    run_id: str,
    scope: str = "all",
    summary: str,
    status: str,
    artifacts: list[str],
    feedback: list[str],
    learnings: list[str],
    request: str | None,
    explicit_workspace: str | Path | None = None,
) -> list[str]:
    item_scope, _, payload = find_team_pack(team_id, scope, explicit_workspace)
    brief_path = team_run_brief_path(payload["team_id"], item_scope, run_id, explicit_workspace)
    resolved_request = request
    if brief_path.exists():
        brief_payload = load_json(brief_path)
        validate_team_run_brief(brief_payload, display_path(brief_path))
        if resolved_request is None:
            resolved_request = brief_payload["request"]
    if not resolved_request:
        raise ControlPlaneError("complete-team-run requires --request when no prepared run brief exists")
    return record_team_run(
        team_id=team_id,
        scope=item_scope,
        request=resolved_request,
        summary=summary,
        status=status,
        artifacts=artifacts,
        feedback=feedback,
        learnings=learnings,
        run_id=run_id,
        explicit_workspace=explicit_workspace,
    )


def invoke_team_pack(
    *,
    team_id: str,
    request: str,
    scope: str = "all",
    explicit_workspace: str | Path | None = None,
) -> list[str]:
    prepared = prepare_team_run(
        team_id=team_id,
        request=request,
        scope=scope,
        explicit_workspace=explicit_workspace,
    )
    run_id_line = next((line for line in prepared if line.startswith("run_id: ")), None)
    if not run_id_line:
        raise ControlPlaneError("prepared team run did not return a run_id")
    run_id = run_id_line.split(": ", 1)[1]
    shown = show_team_run(team_id, run_id, scope, explicit_workspace)
    return prepared + ["ready_for_execution"] + shown


def show_team_memory(
    team_id: str,
    scope: str = "all",
    limit: int = 5,
    explicit_workspace: str | Path | None = None,
) -> list[str]:
    item_scope, team_dir, payload = find_team_pack(team_id, scope, explicit_workspace)
    memory_dir = team_dir / "memory"
    summaries = load_optional_list(memory_dir / "run-summaries.json")
    learnings = load_optional_list(memory_dir / "team-learnings.json")
    preferences_payload = load_team_preferences(payload["team_id"], item_scope, explicit_workspace)
    observations_payload = load_team_preference_observations(payload["team_id"], item_scope, explicit_workspace)
    project_payload = load_team_project_memory(payload["team_id"], item_scope, explicit_workspace)
    cards_payload = load_team_memory_cards(payload["team_id"], item_scope, explicit_workspace)
    lines = [
        f"team_id: {payload['team_id']}",
        f"scope: {item_scope}",
        f"run_count: {payload.get('run_count', 0)}",
        f"last_run_at: {payload.get('last_run_at', 'n/a')}",
        f"memory_markdown: {display_path(team_memory_markdown_path(payload['team_id'], item_scope, explicit_workspace))}",
        f"preferences_path: {display_path(team_preferences_path(payload['team_id'], item_scope, explicit_workspace))}",
        f"preference_observations_path: {display_path(team_preference_observations_path(payload['team_id'], item_scope, explicit_workspace))}",
        f"project_memory_path: {display_path(team_project_memory_path(payload['team_id'], item_scope, explicit_workspace))}",
        f"memory_cards_path: {display_path(team_memory_cards_path(payload['team_id'], item_scope, explicit_workspace))}",
        f"preference_count: {len(preferences_payload.get('preferences', []))}",
        f"preference_observation_count: {len(observations_payload.get('observations', []))}",
        f"project_note_count: {len(project_payload.get('notes', []))}",
        f"memory_card_count: {len(cards_payload.get('cards', []))}",
        "recent_runs:",
    ]
    recent = summaries[-limit:] if summaries else []
    if recent:
        for item in reversed(recent):
            lines.append(f"- {item['run_id']} :: {item['status']} :: {item['summary']}")
    else:
        lines.append("- none")
    lines.append("team_learnings:")
    if learnings:
        for item in learnings[-limit:]:
            lines.append(f"- {item}")
    else:
        lines.append("- none")
    lines.append("preferences:")
    preferences = preferences_payload.get("preferences", [])
    if preferences:
        for item in preferences[-limit:]:
            lines.append(f"- {item['content']}")
    else:
        lines.append("- none")
    lines.append("preference_observations:")
    observations = observations_payload.get("observations", [])
    if observations:
        for item in observations[-limit:]:
            lines.append(f"- {item.get('status', 'observed')} x{item.get('occurrences', 1)} :: {item['content']}")
    else:
        lines.append("- none")
    lines.append("project_memory:")
    project_notes = project_payload.get("notes", [])
    if project_notes:
        for item in project_notes[-limit:]:
            lines.append(f"- {item['content']}")
    else:
        lines.append("- none")
    return lines


def iter_team_pack_records(
    scope: str = "all", explicit_workspace: str | Path | None = None
) -> list[tuple[str, Path, dict[str, Any]]]:
    normalized_scope = normalize_team_scope(scope)
    scopes = ["global", "project", "session"] if normalized_scope == "all" else [normalized_scope]
    records: list[tuple[str, Path, dict[str, Any]]] = []
    for item_scope in scopes:
        root = team_pack_store_root(item_scope, explicit_workspace)
        if not root.exists():
            continue
        for team_dir in sorted(root.iterdir()):
            if not team_dir.is_dir():
                continue
            manifest_path = team_dir / "team.json"
            if not manifest_path.exists():
                continue
            payload = ensure_team_pack_assets(team_dir, load_json(manifest_path))
            validate_team_pack_manifest(payload, display_path(manifest_path))
            records.append((item_scope, team_dir, payload))
    return records


def find_team_pack(
    team_id: str, scope: str = "all", explicit_workspace: str | Path | None = None
) -> tuple[str, Path, dict[str, Any]]:
    validate_team_id(team_id)
    matches = [record for record in iter_team_pack_records(scope, explicit_workspace) if record[2]["team_id"] == team_id]
    if not matches:
        raise ControlPlaneError(f"team pack not found: {team_id}")
    if len(matches) > 1:
        locations = ", ".join([item[0] for item in matches])
        raise ControlPlaneError(f"team pack `{team_id}` exists in multiple scopes: {locations}; specify --scope")
    return matches[0]


def link_skill_directory(skill_name: str, source_dir: Path) -> str:
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    target = SKILLS_DIR / skill_name
    if target.is_symlink() or target.exists():
        if target.is_symlink() and target.resolve() == source_dir.resolve():
            return f"linked {skill_name}"
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        else:
            target.unlink()
    target.symlink_to(source_dir)
    return f"linked {skill_name}"


def link_command_file(command_name: str, source_file: Path) -> str:
    CLAUDE_COMMANDS_DIR.mkdir(parents=True, exist_ok=True)
    target = CLAUDE_COMMANDS_DIR / f"{command_name}.md"
    if target.is_symlink() or target.exists():
        if target.is_symlink() and target.resolve() == source_file.resolve():
            return f"linked /{command_name}"
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    target.symlink_to(source_file)
    return f"linked /{command_name}"


def normalize_team_pack_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    normalized = deepcopy(payload)
    memory_policy = normalized.setdefault("memory_policy", {})
    memory_policy.setdefault("retain_run_summaries", True)
    memory_policy.setdefault("store_team_learnings", normalized.get("lifecycle_scope") != "session")
    memory_policy.setdefault("store_preference_memory", True)
    memory_policy.setdefault("store_project_memory", normalized.get("lifecycle_scope") != "session")
    memory_policy.setdefault("semantic_recall", True)
    host = normalized.setdefault("host_integration", {})
    previous_skill_name = host.get("skill_name") if isinstance(host.get("skill_name"), str) else None
    host_skill_name = host_skill_name_for_team_id(normalized["team_id"])
    host["skill_name"] = host_skill_name
    host["slash_command"] = f"/{host_skill_name}"
    return normalized, previous_skill_name


def remove_legacy_host_links(previous_skill_name: str | None, team_dir: Path) -> None:
    normalized_skill_name = host_skill_name_for_team_id(team_dir.name)
    if not previous_skill_name or previous_skill_name == normalized_skill_name:
        return
    legacy_skill_target = SKILLS_DIR / previous_skill_name
    if legacy_skill_target.is_symlink() and legacy_skill_target.resolve() == team_dir.resolve():
        legacy_skill_target.unlink()
    legacy_command_target = CLAUDE_COMMANDS_DIR / f"{previous_skill_name}.md"
    if legacy_command_target.is_symlink() and legacy_command_target.resolve() == (team_dir / "COMMAND.md").resolve():
        legacy_command_target.unlink()


def ensure_team_pack_assets(team_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    normalized_payload, previous_skill_name = normalize_team_pack_payload(payload)
    manifest_path = team_dir / "team.json"
    skill_path = team_dir / "SKILL.md"
    command_path = team_dir / "COMMAND.md"
    memory_dir = team_dir / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    runs_dir = team_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    summaries = load_optional_list(memory_dir / "run-summaries.json")
    learnings = load_optional_list(memory_dir / "team-learnings.json")
    preferences_path = memory_dir / "preferences.json"
    preference_observations_path = memory_dir / "preference-observations.json"
    project_memory_path = memory_dir / "project-memory.json"
    memory_cards_path = memory_dir / "memory-cards.json"
    preferences_payload = load_optional_memory_object(
        preferences_path,
        default_team_preferences_payload(normalized_payload["team_id"]),
    )
    observations_payload = load_optional_memory_object(
        preference_observations_path,
        default_team_preference_observations_payload(normalized_payload["team_id"]),
    )
    project_payload = load_optional_memory_object(
        project_memory_path,
        default_team_project_memory_payload(
            normalized_payload["team_id"],
            normalized_payload["lifecycle_scope"],
        ),
    )
    cards_payload = load_optional_memory_object(
        memory_cards_path,
        default_team_memory_cards_payload(normalized_payload["team_id"]),
    )
    if not cards_payload.get("cards"):
        for item in summaries:
            ensure_memory_card(
                cards_payload,
                kind="run_summary",
                content=item.get("summary", ""),
                tags=sorted(tokenize_memory_text(item.get("summary", ""))),
                source_run_id=item.get("run_id"),
            )
        for item in learnings:
            ensure_memory_card(
                cards_payload,
                kind="learning",
                content=item,
                tags=sorted(tokenize_memory_text(item)),
            )
        cards_payload["updated_at"] = utc_now()
    memory_markdown_path = memory_dir / "team-memory.md"

    write_manifest = not manifest_path.exists() or normalize(load_json(manifest_path)) != normalize(normalized_payload)
    expected_skill = render_team_pack_skill(normalized_payload)
    write_skill = not skill_path.exists() or skill_path.read_text(encoding="utf-8") != expected_skill
    expected_command = render_team_pack_command(normalized_payload)
    write_command = not command_path.exists() or command_path.read_text(encoding="utf-8") != expected_command
    expected_memory_markdown = render_team_memory_markdown(
        normalized_payload,
        summaries,
        learnings,
        preferences_payload.get("preferences", []),
        observations_payload.get("observations", []),
        project_payload.get("notes", []),
        cards_payload.get("cards", []),
    )
    write_preferences = not preferences_path.exists() or normalize(load_json(preferences_path)) != normalize(preferences_payload)
    write_preference_observations = (
        not preference_observations_path.exists()
        or normalize(load_json(preference_observations_path)) != normalize(observations_payload)
    )
    write_project_memory = (
        not project_memory_path.exists()
        or normalize(load_json(project_memory_path)) != normalize(project_payload)
    )
    write_memory_cards = not memory_cards_path.exists() or normalize(load_json(memory_cards_path)) != normalize(cards_payload)
    write_memory_markdown = (
        not memory_markdown_path.exists()
        or memory_markdown_path.read_text(encoding="utf-8") != expected_memory_markdown
    )

    if write_manifest:
        write_json(manifest_path, normalized_payload)
    if write_preferences:
        write_json(preferences_path, preferences_payload)
    if write_preference_observations:
        write_json(preference_observations_path, observations_payload)
    if write_project_memory:
        write_json(project_memory_path, project_payload)
    if write_memory_cards:
        write_json(memory_cards_path, cards_payload)
    if write_skill:
        skill_path.write_text(expected_skill, encoding="utf-8")
    if write_command:
        command_path.write_text(expected_command, encoding="utf-8")
    if write_memory_markdown:
        memory_markdown_path.write_text(expected_memory_markdown, encoding="utf-8")

    if normalized_payload["host_integration"]["installed"]:
        remove_legacy_host_links(previous_skill_name, team_dir)
        link_skill_directory(normalized_payload["host_integration"]["skill_name"], team_dir)
        link_command_file(normalized_payload["host_integration"]["skill_name"], command_path)
        normalized_payload["host_integration"]["skill_path"] = str(SKILLS_DIR / normalized_payload["host_integration"]["skill_name"])
        normalized_payload["host_integration"]["command_path"] = str(CLAUDE_COMMANDS_DIR / f"{normalized_payload['host_integration']['skill_name']}.md")
        write_json(manifest_path, normalized_payload)

    return normalized_payload


def create_team_pack(
    *,
    team_id: str,
    display_name: str,
    mission: str,
    domain: str,
    scope: str,
    role_specs: list[str],
    playbook_steps: list[str],
    review_mode: str | None,
    install: bool,
    explicit_workspace: str | Path | None = None,
) -> list[str]:
    normalized_scope = normalize_team_scope(scope)
    if normalized_scope == "all":
        raise ControlPlaneError("create-team-pack requires a concrete scope")
    if normalized_scope in {"project", "session"}:
        ensure_workspace_layout(explicit_workspace)
    target_dir = team_pack_dir(team_id, normalized_scope, explicit_workspace)
    if target_dir.exists():
        raise ControlPlaneError(f"team pack already exists: {display_path(target_dir)}")
    payload = build_team_pack_payload(
        team_id=team_id,
        display_name=display_name,
        mission=mission,
        domain=domain,
        scope=normalized_scope,
        role_specs=role_specs,
        playbook_steps=playbook_steps,
        review_mode=review_mode,
    )
    validate_team_pack_manifest(payload, team_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "memory").mkdir(parents=True, exist_ok=True)
    (target_dir / "runs").mkdir(parents=True, exist_ok=True)
    write_json(target_dir / "team.json", payload)
    payload = ensure_team_pack_assets(target_dir, payload)
    (target_dir / "README.md").write_text(
        "\n".join(
            [
                f"# {payload['display_name']}",
                "",
                payload["mission"],
                "",
                f"- team id: `{payload['team_id']}`",
                f"- scope: `{payload['lifecycle_scope']}`",
                f"- domain: `{payload['domain']}`",
                "",
                "Created by AEGIS Team Pack scaffolding.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    messages = [
        f"created team pack: {display_path(target_dir)}",
        f"wrote team manifest: {display_path(target_dir / 'team.json')}",
        f"wrote team skill: {display_path(target_dir / 'SKILL.md')}",
        f"wrote team command: {display_path(target_dir / 'COMMAND.md')}",
    ]
    if install:
        messages.extend(install_team_pack(team_id, normalized_scope, explicit_workspace))
    return messages


def install_team_pack(
    team_id: str, scope: str = "all", explicit_workspace: str | Path | None = None
) -> list[str]:
    matched_scope, team_dir, payload = find_team_pack(team_id, scope, explicit_workspace)
    if matched_scope == "session":
        raise ControlPlaneError("session team packs cannot be installed as persistent host skills")
    payload = deepcopy(payload)
    payload["host_integration"]["installed"] = True
    payload["host_integration"]["skill_path"] = str(SKILLS_DIR / payload["host_integration"]["skill_name"])
    payload["host_integration"]["command_path"] = str(
        CLAUDE_COMMANDS_DIR / f"{payload['host_integration']['skill_name']}.md"
    )
    payload["host_integration"]["installed_at"] = utc_now()
    payload = ensure_team_pack_assets(team_dir, payload)
    messages = [
        link_skill_directory(payload["host_integration"]["skill_name"], team_dir),
        link_command_file(payload["host_integration"]["skill_name"], team_dir / "COMMAND.md"),
        f"installed team pack: {payload['team_id']}",
    ]
    return messages


def list_team_packs(scope: str = "all", explicit_workspace: str | Path | None = None) -> list[str]:
    records = iter_team_pack_records(scope, explicit_workspace)
    if not records:
        return ["no team packs found"]
    return [
        f"{item_scope} :: {payload['team_id']} :: {payload['domain']} :: "
        f"{'installed' if payload['host_integration']['installed'] else 'not-installed'}"
        for item_scope, _, payload in records
    ]


def show_team_pack(team_id: str, scope: str = "all", explicit_workspace: str | Path | None = None) -> list[str]:
    item_scope, team_dir, payload = find_team_pack(team_id, scope, explicit_workspace)
    slash_command = payload["host_integration"].get("slash_command", f"/{payload['host_integration']['skill_name']}")
    return [
        f"team_id: {payload['team_id']}",
        f"display_name: {payload['display_name']}",
        f"scope: {item_scope}",
        f"domain: {payload['domain']}",
        f"mission: {payload['mission']}",
        f"roles: {', '.join(role['id'] for role in payload['roles'])}",
        f"review_mode: {payload['review_mode']['mode']}",
        f"installed: {payload['host_integration']['installed']}",
        f"host_skill: {payload['host_integration']['skill_name']}",
        f"slash_command: {slash_command}",
        f"run_count: {payload.get('run_count', 0)}",
        f"path: {display_path(team_dir)}",
    ]


def team_doctor(scope: str = "all", explicit_workspace: str | Path | None = None) -> list[str]:
    records = iter_team_pack_records(scope, explicit_workspace)
    if not records:
        return ["no team packs found"]
    messages: list[str] = []
    for item_scope, team_dir, payload in records:
        manifest_path = team_dir / "team.json"
        validate_team_pack_manifest(payload, display_path(manifest_path))
        skill_path = team_dir / "SKILL.md"
        if not skill_path.exists():
            raise ControlPlaneError(f"team pack skill missing: {display_path(skill_path)}")
        command_path = team_dir / "COMMAND.md"
        if not command_path.exists():
            raise ControlPlaneError(f"team pack command missing: {display_path(command_path)}")
        if payload["host_integration"]["installed"]:
            expected_target = SKILLS_DIR / payload["host_integration"]["skill_name"]
            if not expected_target.is_symlink() or expected_target.resolve() != team_dir.resolve():
                raise ControlPlaneError(
                    f"installed team pack `{payload['team_id']}` is not correctly linked in {display_path(expected_target)}"
                )
            expected_command = CLAUDE_COMMANDS_DIR / f"{payload['host_integration']['skill_name']}.md"
            if not expected_command.is_symlink() or expected_command.resolve() != command_path.resolve():
                raise ControlPlaneError(
                    f"installed team pack `{payload['team_id']}` is not correctly linked in {display_path(expected_command)}"
                )
        summaries_path = team_dir / "memory" / "run-summaries.json"
        learnings_path = team_dir / "memory" / "team-learnings.json"
        preferences_path = team_dir / "memory" / "preferences.json"
        preference_observations_path = team_dir / "memory" / "preference-observations.json"
        project_memory_path = team_dir / "memory" / "project-memory.json"
        memory_cards_path = team_dir / "memory" / "memory-cards.json"
        summaries = load_optional_list(summaries_path)
        learnings = load_optional_list(learnings_path)
        preferences_payload = load_optional_memory_object(
            preferences_path,
            default_team_preferences_payload(payload["team_id"]),
        )
        observations_payload = load_optional_memory_object(
            preference_observations_path,
            default_team_preference_observations_payload(payload["team_id"]),
        )
        project_payload = load_optional_memory_object(
            project_memory_path,
            default_team_project_memory_payload(payload["team_id"], item_scope),
        )
        cards_payload = load_optional_memory_object(
            memory_cards_path,
            default_team_memory_cards_payload(payload["team_id"]),
        )
        if not all(isinstance(item, dict) for item in summaries):
            raise ControlPlaneError(f"{display_path(summaries_path)} must contain summary objects")
        if not all(isinstance(item, str) for item in learnings):
            raise ControlPlaneError(f"{display_path(learnings_path)} must contain strings")
        if not isinstance(preferences_payload.get("preferences", []), list):
            raise ControlPlaneError(f"{display_path(preferences_path)} preferences must be a list")
        if not isinstance(observations_payload.get("observations", []), list):
            raise ControlPlaneError(f"{display_path(preference_observations_path)} observations must be a list")
        for item in observations_payload.get("observations", []):
            normalize_preference_observation(item)
        if not isinstance(project_payload.get("notes", []), list):
            raise ControlPlaneError(f"{display_path(project_memory_path)} notes must be a list")
        if not isinstance(cards_payload.get("cards", []), list):
            raise ControlPlaneError(f"{display_path(memory_cards_path)} cards must be a list")
        run_files = sorted((team_dir / "runs").glob("*.json")) if (team_dir / "runs").exists() else []
        for run_file in run_files:
            run_payload = load_json(run_file)
            if run_file.name.endswith(".brief.json"):
                validate_team_run_brief(run_payload, display_path(run_file))
            else:
                validate_team_run_record(run_payload, display_path(run_file))
        messages.append(f"team pack valid: {item_scope} :: {payload['team_id']}")
    return messages


def merge_unique_strings(existing: list[str], additions: list[str]) -> list[str]:
    merged = list(existing)
    for item in additions:
        if item not in merged:
            merged.append(item)
    return merged


def merge_override_text(current: str | None, addition: str | None) -> str | None:
    if not addition:
        return current
    if not current:
        return addition
    if addition in current:
        return current
    return f"{current}\n\n{addition}"


def validate_agent_override_map(agent_map: dict[str, Any], registry: dict[str, Any], label: str) -> None:
    agents = registry_by_id(registry)
    for agent_id, override in agent_map.items():
        if agent_id not in agents:
            raise ControlPlaneError(f"{label} references unknown agent: {agent_id}")
        if not isinstance(override, dict):
            raise ControlPlaneError(f"{label} override for {agent_id} must be an object")
        unknown = sorted(set(override) - ALLOWED_AGENT_OVERRIDE_KEYS)
        if unknown:
            raise ControlPlaneError(
                f"{label} override for {agent_id} uses forbidden keys: {', '.join(unknown)}"
            )
        for key in ["project_context", "extra_instructions"]:
            value = override.get(key)
            if value is not None and not isinstance(value, str):
                raise ControlPlaneError(f"{label} override {agent_id}.{key} must be a string")
        for key in ["inputs_add", "outputs_add", "dependencies_add", "contract_actions_add"]:
            value = override.get(key, [])
            if value and (not isinstance(value, list) or not all(isinstance(item, str) for item in value)):
                raise ControlPlaneError(f"{label} override {agent_id}.{key} must be a list of strings")


def load_project_agent_overrides(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    manifest = load_json(project_manifest_path())
    manifest_overrides = manifest.get("agent_overrides", {})
    validate_agent_override_map(manifest_overrides, registry, "project manifest agent_overrides")

    payload = load_optional_json(agent_overrides_path(), {"version": "1.0.0", "agents": {}})
    validate_required_keys(payload, AGENT_OVERRIDES_SCHEMA_PATH, display_path(agent_overrides_path()))
    file_overrides = payload.get("agents", {})
    if not isinstance(file_overrides, dict):
        raise ControlPlaneError("agent-overrides.json agents must be an object")
    validate_agent_override_map(file_overrides, registry, display_path(agent_overrides_path()))

    merged: dict[str, dict[str, Any]] = {}
    for source in [manifest_overrides, file_overrides]:
        for agent_id, override in source.items():
            target = merged.setdefault(agent_id, {})
            target["project_context"] = merge_override_text(target.get("project_context"), override.get("project_context"))
            target["extra_instructions"] = merge_override_text(
                target.get("extra_instructions"),
                override.get("extra_instructions"),
            )
            for key in ["inputs_add", "outputs_add", "dependencies_add", "contract_actions_add"]:
                target[key] = merge_unique_strings(target.get(key, []), override.get(key, []))
    return merged


def validate_workspace_policy_payload(payload: dict[str, Any], orchestrator: dict[str, Any], label: str) -> None:
    validate_required_keys(payload, WORKSPACE_POLICY_SCHEMA_PATH, label)
    gate_overrides = payload.get("gate_overrides", {})
    if gate_overrides and not isinstance(gate_overrides, dict):
        raise ControlPlaneError(f"{label} gate_overrides must be an object")
    for gate_state, override in gate_overrides.items():
        if gate_state not in orchestrator.get("gates", {}):
            raise ControlPlaneError(f"{label} references unknown gate: {gate_state}")
        if not isinstance(override, dict):
            raise ControlPlaneError(f"{label} override for gate {gate_state} must be an object")
        unknown = sorted(set(override) - {"min_score", "max_rounds", "required_outputs_add"})
        if unknown:
            raise ControlPlaneError(
                f"{label} gate {gate_state} uses forbidden keys: {', '.join(unknown)}"
            )
        base_gate = orchestrator["gates"][gate_state]
        base_review_loop = base_gate.get("review_loop", {})
        if "min_score" in override:
            min_score = override["min_score"]
            if not isinstance(min_score, (int, float)):
                raise ControlPlaneError(f"{label} gate {gate_state}.min_score must be numeric")
            if min_score < base_gate["min_score"]:
                raise ControlPlaneError(f"{label} gate {gate_state}.min_score cannot be lower than the core minimum")
        if "max_rounds" in override:
            max_rounds = override["max_rounds"]
            if not isinstance(max_rounds, int) or max_rounds < 1:
                raise ControlPlaneError(f"{label} gate {gate_state}.max_rounds must be a positive integer")
            if not base_review_loop:
                raise ControlPlaneError(f"{label} gate {gate_state} cannot override max_rounds without a review loop")
            if max_rounds > base_review_loop["max_rounds"]:
                raise ControlPlaneError(f"{label} gate {gate_state}.max_rounds cannot exceed the core maximum")
        outputs = override.get("required_outputs_add", [])
        if outputs and (not isinstance(outputs, list) or not all(isinstance(item, str) for item in outputs)):
            raise ControlPlaneError(f"{label} gate {gate_state}.required_outputs_add must be a list of strings")


def build_effective_workspace_policy(manifest: dict[str, Any], orchestrator: dict[str, Any]) -> dict[str, Any]:
    max_rounds = manifest.get("review_policy", {}).get("max_rounds")
    gate_overrides: dict[str, dict[str, Any]] = {}
    if max_rounds is not None:
        for gate_state, gate in orchestrator.get("gates", {}).items():
            review_loop = gate.get("review_loop")
            if not review_loop:
                continue
            effective_rounds = min(max_rounds, review_loop["max_rounds"])
            gate_overrides[gate_state] = {"max_rounds": effective_rounds}

    payload = load_optional_json(workflow_policy_path(), {"version": "1.0.0", "gate_overrides": {}})
    validate_workspace_policy_payload(payload, orchestrator, display_path(workflow_policy_path()))
    for gate_state, override in payload.get("gate_overrides", {}).items():
        merged = gate_overrides.setdefault(gate_state, {})
        merged.update(override)
    return {"version": "1.0.0", "gate_overrides": gate_overrides}


def apply_agent_overrides(registry: dict[str, Any], agent_overrides: dict[str, dict[str, Any]]) -> dict[str, Any]:
    payload = deepcopy(registry)
    agents = registry_by_id(payload)
    for agent_id, override in agent_overrides.items():
        agent = agents[agent_id]
        agent["project_context"] = merge_override_text(agent.get("project_context"), override.get("project_context"))
        agent["extra_instructions"] = merge_override_text(
            agent.get("extra_instructions"),
            override.get("extra_instructions"),
        )
        if override.get("inputs_add"):
            agent["inputs"] = merge_unique_strings(agent.get("inputs", []), override["inputs_add"])
        if override.get("outputs_add"):
            agent["outputs"] = merge_unique_strings(agent.get("outputs", []), override["outputs_add"])
        if override.get("dependencies_add"):
            agent["dependencies"] = merge_unique_strings(agent.get("dependencies", []), override["dependencies_add"])
        if override.get("contract_actions_add"):
            agent["contract_actions"] = merge_unique_strings(
                agent.get("contract_actions", []),
                override["contract_actions_add"],
            )
    return payload


def apply_workspace_policy(orchestrator: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(orchestrator)
    for gate_state, override in policy.get("gate_overrides", {}).items():
        gate = payload["gates"][gate_state]
        transition = payload["transitions"][gate_state]
        review_loop = gate.get("review_loop")
        if "min_score" in override:
            gate["min_score"] = override["min_score"]
        if "required_outputs_add" in override:
            gate["required_outputs"] = merge_unique_strings(gate.get("required_outputs", []), override["required_outputs_add"])
        if "max_rounds" in override and review_loop:
            review_loop["max_rounds"] = override["max_rounds"]
            transition["max_rounds"] = override["max_rounds"]
    return payload


def get_context() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    return load_json(REGISTRY_PATH), load_json(ORCHESTRATOR_PATH), load_json(CONTRACTS_PATH)


def project_lock_path(workflow: str) -> Path:
    return workflow_root(workflow) / "project-lock.json"


def registry_lock_path(workflow: str) -> Path:
    return workflow_root(workflow) / "registry.lock.json"


def orchestrator_lock_path(workflow: str) -> Path:
    return workflow_root(workflow) / "orchestrator.lock.json"


def build_project_lock(workflow: str, workflow_type: str | None = None) -> dict[str, Any]:
    payload = deepcopy(load_json(project_manifest_path()))
    validate_project_manifest(payload)
    payload["_workspace_sources"] = {
        "project_manifest": display_path(project_manifest_path()),
        "agent_overrides": display_path(agent_overrides_path()) if agent_overrides_path().exists() else None,
        "workflow_policy": display_path(workflow_policy_path()) if workflow_policy_path().exists() else None,
    }
    payload["_runtime"] = {
        "layer": "runtime_snapshot",
        "workflow_id": workflow,
        "workflow_type": workflow_type,
        "locked_at": utc_now(),
        "workspace_root": str(workspace_root()),
        "source_project_manifest": display_path(project_manifest_path()),
    }
    return payload


def build_registry_lock(workflow: str, workflow_type: str | None = None) -> dict[str, Any]:
    base_registry = load_json(REGISTRY_PATH)
    agent_overrides = load_project_agent_overrides(base_registry)
    payload = apply_agent_overrides(base_registry, agent_overrides)
    payload["_runtime"] = {
        "layer": "runtime_snapshot",
        "workflow_id": workflow,
        "workflow_type": workflow_type,
        "locked_at": utc_now(),
        "workspace_root": str(workspace_root()),
        "source_registry": display_path(REGISTRY_PATH),
        "source_project_manifest": display_path(project_manifest_path()),
        "source_agent_overrides": display_path(agent_overrides_path()) if agent_overrides_path().exists() else None,
    }
    return payload


def build_orchestrator_lock(workflow: str, workflow_type: str | None = None) -> dict[str, Any]:
    manifest = load_json(project_manifest_path())
    validate_project_manifest(manifest)
    base_orchestrator = load_json(ORCHESTRATOR_PATH)
    effective_policy = build_effective_workspace_policy(manifest, base_orchestrator)
    payload = apply_workspace_policy(base_orchestrator, effective_policy)
    payload["_runtime"] = {
        "layer": "runtime_snapshot",
        "workflow_id": workflow,
        "workflow_type": workflow_type,
        "locked_at": utc_now(),
        "workspace_root": str(workspace_root()),
        "source_orchestrator": display_path(ORCHESTRATOR_PATH),
        "source_project_manifest": display_path(project_manifest_path()),
        "source_workflow_policy": display_path(workflow_policy_path()) if workflow_policy_path().exists() else None,
        "effective_workspace_policy": effective_policy,
    }
    return payload


def ensure_runtime_snapshot(workflow: str, workflow_type: str | None = None, refresh: bool = False) -> list[str]:
    validate_workflow_id(workflow)
    ensure_workspace_layout()
    target_root = workflow_root(workflow)
    target_root.mkdir(parents=True, exist_ok=True)
    messages: list[str] = []
    runtime_files = [
        (project_lock_path(workflow), build_project_lock(workflow, workflow_type)),
        (registry_lock_path(workflow), build_registry_lock(workflow, workflow_type)),
        (orchestrator_lock_path(workflow), build_orchestrator_lock(workflow, workflow_type)),
    ]
    for path, payload in runtime_files:
        if not path.exists() or refresh:
            existing = load_json(path) if path.exists() else None
            if normalize(existing) == normalize(payload):
                continue
            write_json(path, payload)
            action = "refreshed" if path.exists() and existing is not None and refresh else "created"
            messages.append(f"{action} runtime snapshot: {display_path(path)}")
    return messages


def get_runtime_context(workflow: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    validate_workflow_id(workflow)
    workflow_state = load_state(workflow) if state_path(workflow).exists() else None
    ensure_runtime_snapshot(workflow, workflow_state.get("workflow_type") if workflow_state else None)
    project_lock = load_json(project_lock_path(workflow))
    validate_project_manifest(project_lock)
    registry = load_json(registry_lock_path(workflow))
    orchestrator = load_json(orchestrator_lock_path(workflow))
    contracts = load_json(CONTRACTS_PATH)
    runtime_errors: list[str] = []
    runtime_errors.extend(validate_registry_schema(registry))
    runtime_errors.extend(validate_orchestrator(registry, orchestrator))
    runtime_errors.extend(validate_contracts(registry, contracts))
    if runtime_errors:
        raise ControlPlaneError("\n".join(runtime_errors))
    enabled_workflows = project_lock.get("enabled_workflows", [])
    if workflow_state and workflow_state.get("workflow_type") and enabled_workflows:
        if workflow_state["workflow_type"] not in enabled_workflows:
            raise ControlPlaneError(
                f"workflow type {workflow_state['workflow_type']} is not enabled for workspace {project_lock['project_id']}"
            )
    return project_lock, registry, orchestrator, contracts


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
                errors.append(f"{display_path(skill_path)} contains forbidden runtime token: {token}")
    return errors


def validate_required_keys(payload: dict[str, Any], schema_path: Path, label: str) -> None:
    schema = load_json(schema_path)
    missing = [key for key in schema["required"] if key not in payload]
    if missing:
        raise ControlPlaneError(f"{label} missing required keys: {', '.join(missing)}")


def requirements_lock_path(workflow: str) -> Path:
    return workflow_root(workflow) / "l2-planning" / "requirements-lock.json"


def task_breakdown_path(workflow: str) -> Path:
    return workflow_root(workflow) / "l2-planning" / "task_breakdown.json"


def implementation_contracts_path(workflow: str) -> Path:
    return workflow_root(workflow) / "l2-planning" / "implementation-contracts.json"


def requirements_traceability_path(workflow: str) -> Path:
    return workflow_root(workflow) / "l4-validation" / "requirements-traceability.json"


def reuse_audit_path(workflow: str, agent_id: str) -> Path:
    if agent_id not in {"frontend-squad", "backend-squad"}:
        raise ControlPlaneError(f"reuse audit path is only defined for development agents, got {agent_id}")
    slug = "frontend" if agent_id == "frontend-squad" else "backend"
    return workflow_root(workflow) / "l3-dev" / slug / "reuse-audit.json"


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
        raise ControlPlaneError(f"missing locked requirements artifact: {display_path(lock_path)}")
    payload = load_json(lock_path)
    validate_required_keys(payload, REQUIREMENTS_LOCK_SCHEMA_PATH, display_path(lock_path))
    computed_hash = compute_requirements_lock_hash(payload)
    state_hash = state.get("requirements_lock_hash")
    if not state_hash:
        raise ControlPlaneError("workflow state is missing requirements_lock_hash")
    if payload.get("lock_hash") != computed_hash:
        raise ControlPlaneError(f"{display_path(lock_path)} contains an invalid lock_hash")
    if state_hash != computed_hash:
        raise ControlPlaneError("workflow requirements_lock_hash does not match requirements-lock.json")


def validate_review_loop_status(path: Path, workflow: str, gate_state: str, gate: dict[str, Any]) -> dict[str, Any]:
    payload = load_json(path)
    validate_required_keys(payload, REVIEW_LOOP_SCHEMA_PATH, display_path(path))
    review_loop = gate["review_loop"]
    if payload["workflow_id"] != workflow:
        raise ControlPlaneError(f"{display_path(path)} workflow_id mismatch")
    if payload["gate"] != gate_state:
        raise ControlPlaneError(f"{display_path(path)} gate mismatch: expected {gate_state}")
    if payload["status"] not in review_loop["allowed_statuses"]:
        raise ControlPlaneError(f"{display_path(path)} has invalid status {payload['status']}")
    if not isinstance(payload["round"], int) or payload["round"] < 1:
        raise ControlPlaneError(f"{display_path(path)} round must be a positive integer")
    if payload["round"] > review_loop["max_rounds"]:
        raise ControlPlaneError(f"{display_path(path)} round exceeds max_rounds")
    if payload["max_rounds"] != review_loop["max_rounds"]:
        raise ControlPlaneError(f"{display_path(path)} max_rounds does not match gate configuration")
    if payload["round"] == review_loop["max_rounds"] and payload["status"] == "changes_requested":
        raise ControlPlaneError(f"{display_path(path)} cannot request more changes at the max review round")
    if not isinstance(payload["open_issues"], list) or not isinstance(payload["closed_issues"], list):
        raise ControlPlaneError(f"{display_path(path)} open_issues and closed_issues must be lists")
    if payload["status"] == "changes_requested":
        if payload["lgtm"]:
            raise ControlPlaneError(f"{display_path(path)} changes_requested status cannot set lgtm=true")
        if not payload["open_issues"]:
            raise ControlPlaneError(f"{display_path(path)} changes_requested status requires open issues")
    if payload["status"] == "blocked" and not payload["open_issues"]:
        raise ControlPlaneError(f"{display_path(path)} blocked status requires open issues")
    if payload["status"] == "lgtm":
        if not payload["lgtm"]:
            raise ControlPlaneError(f"{display_path(path)} lgtm status must set lgtm=true")
        if payload["open_issues"]:
            raise ControlPlaneError(f"{display_path(path)} lgtm status cannot have open issues")
        if payload["verdict"] != "LGTM":
            raise ControlPlaneError(f"{display_path(path)} lgtm status must use verdict LGTM")
    return payload


def validate_fix_response_artifact(path: Path) -> None:
    if not path.exists():
        raise ControlPlaneError(f"missing fix response artifact: {display_path(path)}")
    if path.stat().st_size == 0:
        raise ControlPlaneError(f"empty fix response artifact: {display_path(path)}")


def validate_skill_contract_mentions(registry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for agent in registry["agents"]:
        skill_path = ROOT / agent["entrypoint"]
        if not skill_path.exists():
            errors.append(f"missing skill file for agent {agent['id']}: {display_path(skill_path)}")
            continue
        content = skill_path.read_text(encoding="utf-8")
        for action in agent.get("contract_actions", []):
            if f"`{action}`" not in content:
                errors.append(f"{display_path(skill_path)} does not mention required contract `{action}`")
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
    validate_required_keys(payload, TASK_BREAKDOWN_SCHEMA_PATH, display_path(task_breakdown_path(workflow)))
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
        display_path(implementation_contracts_path(workflow)),
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
    validate_required_keys(payload, REUSE_AUDIT_SCHEMA_PATH, display_path(reuse_audit_path(workflow, agent_id)))
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
                messages.append(f"derived metadata drift: {display_path(target_path)}")
            else:
                write_json(target_path, desired)
                messages.append(f"synced {display_path(target_path)}")
    return messages


def ensure_skill_symlinks() -> list[str]:
    messages: list[str] = []
    for skill_dir in sorted((ROOT / "agents").iterdir()):
        if not skill_dir.is_dir() or not (skill_dir / "SKILL.md").exists():
            continue
        messages.append(link_skill_directory(skill_dir.name, skill_dir))
        command_path = skill_dir / "COMMAND.md"
        if command_path.exists():
            messages.append(link_command_file(skill_dir.name, command_path))
    for _, team_dir, payload in iter_team_pack_records("global"):
        if payload["host_integration"]["installed"]:
            messages.append(link_skill_directory(payload["host_integration"]["skill_name"], team_dir))
            command_path = team_dir / "COMMAND.md"
            if command_path.exists():
                messages.append(link_command_file(payload["host_integration"]["skill_name"], command_path))
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


def workspace_doctor() -> list[str]:
    messages = ensure_workspace_layout()
    payload = load_json(project_manifest_path())
    validate_project_manifest(payload)
    registry = load_json(REGISTRY_PATH)
    orchestrator = load_json(ORCHESTRATOR_PATH)
    load_project_agent_overrides(registry)
    build_effective_workspace_policy(payload, orchestrator)
    return messages + [f"workspace ready: {workspace_root()}"]


def run_doctor(workflow: str) -> list[str]:
    validate_workflow_id(workflow)
    if not state_path(workflow).exists():
        raise ControlPlaneError(f"workflow state missing: {display_path(state_path(workflow))}")
    project_lock, registry, orchestrator, _ = get_runtime_context(workflow)
    state = load_state(workflow)
    runtime_state = project_lock.get("_runtime", {})
    if runtime_state.get("workflow_id") != workflow:
        raise ControlPlaneError("project-lock.json workflow_id does not match requested workflow")
    if state["current_state"] not in set(orchestrator.get("states", [])):
        raise ControlPlaneError(f"workflow state references unknown state: {state['current_state']}")
    if state.get("workflow_type"):
        workflow_types = {item["id"] for item in registry.get("workflow_types", [])}
        if state["workflow_type"] not in workflow_types:
            raise ControlPlaneError(f"workflow state references unknown workflow_type: {state['workflow_type']}")
    return [
        f"runtime snapshot valid: {display_path(project_lock_path(workflow))}",
        f"runtime snapshot valid: {display_path(registry_lock_path(workflow))}",
        f"runtime snapshot valid: {display_path(orchestrator_lock_path(workflow))}",
        f"workflow state valid: {display_path(state_path(workflow))}",
    ]


def state_path(workflow: str) -> Path:
    return workflow_root(workflow) / "state.json"


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
    _, _, orchestrator, _ = get_runtime_context(workflow)
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
    update_workflow_index(workflow, current_state=target_state)
    return [f"advanced workflow {workflow}: {current_state} -> {target_state}"]


def initialize_workflow(workflow: str) -> dict[str, Any]:
    ensure_workspace_layout()
    workflow_root_path = workflow_root(workflow)
    for path in [
        workflow_root_path / "l1-intelligence",
        workflow_root_path / "l2-planning",
        workflow_root_path / "l3-dev" / "frontend",
        workflow_root_path / "l3-dev" / "backend",
        workflow_root_path / "l4-validation",
        workflow_root_path / "l5-release"
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
    ensure_runtime_snapshot(workflow)
    update_workflow_index(workflow, workspace=workspace_root(), current_state="INIT")
    return payload


def load_state(workflow: str) -> dict[str, Any]:
    target = state_path(workflow)
    if not target.exists():
        raise ControlPlaneError(f"workflow state missing: {display_path(target)}")
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
    _, registry, orchestrator, contracts = get_runtime_context(workflow)
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
            raise ControlPlaneError(f"missing L3 planning artifact: {display_path(breakdown_path)}")
        if not implementation_path.exists():
            raise ControlPlaneError(f"missing L3 planning artifact: {display_path(implementation_path)}")
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
            raise ControlPlaneError(f"{display_path(path)} missing review key: {key}")
    if payload["reviewer"] != expected_reviewer:
        raise ControlPlaneError(f"{display_path(path)} reviewer mismatch: expected {expected_reviewer}, got {payload['reviewer']}")
    if not isinstance(payload["score"], (int, float)):
        raise ControlPlaneError(f"{display_path(path)} score must be numeric")
    if not isinstance(payload["blockers"], list) or not isinstance(payload["suggestions"], list):
        raise ControlPlaneError(f"{display_path(path)} blockers and suggestions must be lists")
    if payload["score"] < min_score and not payload["blockers"]:
        raise ControlPlaneError(f"{display_path(path)} score below threshold {min_score} without blockers")


def validate_outputs(agent_id: str, workflow: str, state_name: str) -> None:
    _, registry, orchestrator, _ = get_runtime_context(workflow)
    agents = registry_by_id(registry)
    if state_name in orchestrator["gates"]:
        gate = orchestrator["gates"][state_name]
        artifact_dir = gate_artifact_dir(workflow, state_name, orchestrator)
        for output_name in gate["required_outputs"]:
            target = artifact_dir / output_name
            if not target.exists():
                raise ControlPlaneError(f"missing gate output: {display_path(target)}")
        review_loop = gate.get("review_loop")
        if review_loop and review_loop.get("enabled"):
            loop_status_path = artifact_dir / review_loop["status_artifact"]
            if not loop_status_path.exists():
                raise ControlPlaneError(f"missing review loop status artifact: {display_path(loop_status_path)}")
            loop_status = validate_review_loop_status(loop_status_path, workflow, state_name, gate)
            round_report = artifact_dir / review_loop["round_report_pattern"].format(round=loop_status["round"])
            if not round_report.exists():
                raise ControlPlaneError(f"missing review round artifact: {display_path(round_report)}")
            if loop_status["status"] == "re_review":
                raise ControlPlaneError(
                    f"reviewer output cannot finish in re_review status: {display_path(loop_status_path)}"
                )
            review_passed_path = artifact_dir / "review-passed.json"
            if loop_status["status"] == "lgtm":
                if not review_passed_path.exists():
                    raise ControlPlaneError(f"missing review-passed.json for lgtm gate: {display_path(review_passed_path)}")
                validate_review_artifact(review_passed_path, gate["reviewer"], gate["min_score"])
            elif review_passed_path.exists():
                raise ControlPlaneError(
                    f"review-passed.json must only exist after LGTM: {display_path(review_passed_path)}"
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
                raise ControlPlaneError(f"missing output directory: {display_path(target)}")
            if not any(target.iterdir()):
                raise ControlPlaneError(f"output directory is empty: {display_path(target)}")
        else:
            if not target.exists():
                raise ControlPlaneError(f"missing output file: {display_path(target)}")


def git(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(cwd or ROOT), check=check, text=True, capture_output=True)


def workspace_git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return git(*args, cwd=workspace_root(), check=check)


def post_agent_run(agent_id: str, workflow: str) -> list[str]:
    _, registry, orchestrator, contracts = get_runtime_context(workflow)
    state = load_state(workflow)
    validate_outputs(agent_id, workflow, state["current_state"])
    active_loop = state.get("active_review_loop")
    if state["current_state"] == "L2_PLANNING":
        breakdown_path = task_breakdown_path(workflow)
        implementation_path = implementation_contracts_path(workflow)
        if not breakdown_path.exists():
            raise ControlPlaneError(f"missing planning artifact: {display_path(breakdown_path)}")
        if not implementation_path.exists():
            raise ControlPlaneError(f"missing planning artifact: {display_path(implementation_path)}")
        breakdown_payload = load_json(breakdown_path)
        validate_task_breakdown(breakdown_payload, workflow, registry, orchestrator)
        implementation_payload = load_json(implementation_path)
        validate_implementation_contracts(implementation_payload, workflow, registry, breakdown_payload)
        lock_path = requirements_lock_path(workflow)
        payload = load_json(lock_path)
        validate_required_keys(payload, REQUIREMENTS_LOCK_SCHEMA_PATH, display_path(lock_path))
        lock_hash = compute_requirements_lock_hash(payload)
        payload["lock_hash"] = lock_hash
        write_json(lock_path, payload)
        state["requirements_lock_hash"] = lock_hash
        write_json(state_path(workflow), state)
    elif state["current_state"] == "L3_DEVELOP" and agent_id in {"frontend-squad", "backend-squad"}:
        audit_path = reuse_audit_path(workflow, agent_id)
        if not audit_path.exists():
            raise ControlPlaneError(f"missing development governance artifact: {display_path(audit_path)}")
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
        validate_required_keys(payload, REQUIREMENTS_TRACEABILITY_SCHEMA_PATH, display_path(traceability_path))
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
    workflow_dir = workflow_root(workflow)
    workspace_git("add", str(workflow_dir))
    diff = workspace_git("diff", "--cached", "--quiet", check=False)
    if diff.returncode == 0:
        return [f"no workflow changes to commit for {workflow}"]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    workspace_git("commit", "-m", f"[AEGIS-RUN] agent={agent_id} workflow={workflow} state={state['current_state']} ts={stamp}")
    tag_name = f"workflow/{workflow}/{state['current_state']}-{stamp}"
    workspace_git("tag", tag_name)
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


def ensure_cli_shims() -> list[str]:
    SHIM_INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    shims = {
        "aegis": [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            f'export AEGIS_CORE_ROOT="{ROOT}"',
            f'export PYTHONPATH="{ROOT}${{PYTHONPATH:+:${{PYTHONPATH}}}}"',
            f'exec "{ROOT / "aegis"}" "$@"',
            "",
        ],
        "aegisctl": [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            f'export AEGIS_CORE_ROOT="{ROOT}"',
            f'export PYTHONPATH="{ROOT}${{PYTHONPATH:+:${{PYTHONPATH}}}}"',
            f'exec "{ROOT / "aegisctl"}" "$@"',
            "",
        ],
    }
    messages: list[str] = []
    for name, lines in shims.items():
        target = SHIM_INSTALL_DIR / name
        content = "\n".join(lines)
        target.write_text(content, encoding="utf-8")
        target.chmod(0o755)
        messages.append(f"installed shim: {target}")
    messages.append(f"ensure `{SHIM_INSTALL_DIR}` is on your PATH")
    return messages


def write_gate_review(
    *,
    workflow: str,
    gate_state: str,
    reviewer: str,
    status: str,
    round_number: int,
    score: float | None,
    open_issues: list[str],
    closed_issues: list[str],
    blockers: list[str],
    suggestions: list[str],
) -> list[str]:
    _, _, orchestrator, _ = get_runtime_context(workflow)
    if gate_state not in orchestrator.get("gates", {}):
        raise ControlPlaneError(f"unknown gate: {gate_state}")
    gate = orchestrator["gates"][gate_state]
    if reviewer != gate["reviewer"]:
        raise ControlPlaneError(f"reviewer mismatch for {gate_state}: expected {gate['reviewer']}, got {reviewer}")
    review_loop = gate.get("review_loop")
    if not review_loop:
        raise ControlPlaneError(f"gate {gate_state} does not use a review loop")
    artifact_dir = gate_artifact_dir(workflow, gate_state, orchestrator)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    gate_report_path = artifact_dir / "gate-review-report.md"
    round_report_path = artifact_dir / review_loop["round_report_pattern"].format(round=round_number)
    status_path = artifact_dir / review_loop["status_artifact"]
    review_passed_path = artifact_dir / "review-passed.json"
    gate_report_lines = [
        f"# Gate Review Report: {gate_state}",
        "",
        f"- Workflow: `{workflow}`",
        f"- Reviewer: `{reviewer}`",
        f"- Status: `{status}`",
        f"- Round: `{round_number}`",
        f"- Score: `{score if score is not None else 'n/a'}`",
        "",
        "## Open Issues",
    ]
    gate_report_lines.extend([f"- {item}" for item in open_issues] or ["- None"])
    gate_report_lines.extend(["", "## Closed Issues"])
    gate_report_lines.extend([f"- {item}" for item in closed_issues] or ["- None"])
    gate_report_lines.extend(["", "## Blockers"])
    gate_report_lines.extend([f"- {item}" for item in blockers] or ["- None"])
    gate_report_lines.extend(["", "## Suggestions"])
    gate_report_lines.extend([f"- {item}" for item in suggestions] or ["- None"])
    gate_report_path.write_text("\n".join(gate_report_lines) + "\n", encoding="utf-8")
    round_report_path.write_text(
        "\n".join(
            [
                f"# Review Round {round_number}: {gate_state}",
                "",
                f"Reviewer: `{reviewer}`",
                f"Status: `{status}`",
                f"Generated at: `{utc_now()}`",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    loop_payload = {
        "workflow_id": workflow,
        "gate": gate_state,
        "round": round_number,
        "status": status,
        "verdict": "LGTM" if status == "lgtm" else status,
        "open_issues": open_issues,
        "closed_issues": closed_issues,
        "lgtm": status == "lgtm",
        "max_rounds": review_loop["max_rounds"],
        "updated_at": utc_now(),
    }
    write_json(status_path, loop_payload)
    messages = [
        f"wrote gate review report: {display_path(gate_report_path)}",
        f"wrote review round report: {display_path(round_report_path)}",
        f"wrote review loop status: {display_path(status_path)}",
    ]
    if status == "lgtm":
        final_score = score if score is not None else gate["min_score"]
        if final_score < gate["min_score"]:
            raise ControlPlaneError(f"lgtm score must be at least {gate['min_score']} for gate {gate_state}")
        write_json(
            review_passed_path,
            {
                "score": final_score,
                "reviewer": reviewer,
                "blockers": blockers,
                "suggestions": suggestions,
                "approved_at": utc_now(),
            },
        )
        messages.append(f"wrote review pass artifact: {display_path(review_passed_path)}")
    elif review_passed_path.exists():
        review_passed_path.unlink()
        messages.append(f"removed stale review pass artifact: {display_path(review_passed_path)}")
    return messages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AEGIS control-plane tooling")
    parser.add_argument("--workspace", help="Workspace root for the attached project")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    sub.add_parser("workspace-doctor")
    run_doctor_cmd = sub.add_parser("run-doctor")
    run_doctor_cmd.add_argument("--workflow", required=True)
    sub.add_parser("validate")
    sub.add_parser("sync-agent-metadata")
    sub.add_parser("sync-agents")
    sub.add_parser("attach-workspace")
    workflow_workspace_cmd = sub.add_parser("workflow-workspace")
    workflow_workspace_cmd.add_argument("--workflow", required=True)
    sub.add_parser("workflow-dry-run")
    sub.add_parser("install-cron")
    sub.add_parser("install-shims")
    team_compose_cmd = sub.add_parser("compose-team-pack")
    team_compose_cmd.add_argument("--request", required=True)
    team_compose_cmd.add_argument("--id")
    team_compose_cmd.add_argument("--name")
    team_compose_cmd.add_argument("--scope", choices=["global", "project", "session"])
    team_compose_cmd.add_argument("--install", action="store_true")
    team_create_cmd = sub.add_parser("create-team-pack")
    team_create_cmd.add_argument("--id", required=True)
    team_create_cmd.add_argument("--name", required=True)
    team_create_cmd.add_argument("--mission", required=True)
    team_create_cmd.add_argument("--domain", required=True)
    team_create_cmd.add_argument("--scope", default="global", choices=["global", "project", "session"])
    team_create_cmd.add_argument("--role", action="append", default=[])
    team_create_cmd.add_argument("--playbook-step", action="append", default=[])
    team_create_cmd.add_argument("--review-mode", choices=["lite", "standard", "strict"])
    team_create_cmd.add_argument("--install", action="store_true")
    team_list_cmd = sub.add_parser("list-team-packs")
    team_list_cmd.add_argument("--scope", default="all", choices=["all", "global", "project", "session"])
    team_show_cmd = sub.add_parser("show-team-pack")
    team_show_cmd.add_argument("--team", required=True)
    team_show_cmd.add_argument("--scope", default="all", choices=["all", "global", "project", "session"])
    team_install_cmd = sub.add_parser("install-team-pack")
    team_install_cmd.add_argument("--team", required=True)
    team_install_cmd.add_argument("--scope", default="all", choices=["all", "global", "project", "session"])
    team_doctor_cmd = sub.add_parser("team-doctor")
    team_doctor_cmd.add_argument("--scope", default="all", choices=["all", "global", "project", "session"])
    team_prepare_cmd = sub.add_parser("prepare-team-run")
    team_prepare_cmd.add_argument("--team", required=True)
    team_prepare_cmd.add_argument("--request", required=True)
    team_prepare_cmd.add_argument("--scope", default="all", choices=["all", "global", "project", "session"])
    team_invoke_cmd = sub.add_parser("invoke-team-pack")
    team_invoke_cmd.add_argument("--team", required=True)
    team_invoke_cmd.add_argument("--request", required=True)
    team_invoke_cmd.add_argument("--scope", default="all", choices=["all", "global", "project", "session"])
    team_show_run_cmd = sub.add_parser("show-team-run")
    team_show_run_cmd.add_argument("--team", required=True)
    team_show_run_cmd.add_argument("--run-id", required=True)
    team_show_run_cmd.add_argument("--scope", default="all", choices=["all", "global", "project", "session"])
    team_record_cmd = sub.add_parser("record-team-run")
    team_record_cmd.add_argument("--team", required=True)
    team_record_cmd.add_argument("--scope", default="all", choices=["all", "global", "project", "session"])
    team_record_cmd.add_argument("--request", required=True)
    team_record_cmd.add_argument("--summary", required=True)
    team_record_cmd.add_argument("--status", default="completed")
    team_record_cmd.add_argument("--artifact", action="append", default=[])
    team_record_cmd.add_argument("--feedback-item", action="append", default=[])
    team_record_cmd.add_argument("--learning", action="append", default=[])
    team_record_cmd.add_argument("--run-id")
    team_complete_cmd = sub.add_parser("complete-team-run")
    team_complete_cmd.add_argument("--team", required=True)
    team_complete_cmd.add_argument("--run-id", required=True)
    team_complete_cmd.add_argument("--scope", default="all", choices=["all", "global", "project", "session"])
    team_complete_cmd.add_argument("--summary", required=True)
    team_complete_cmd.add_argument("--status", default="completed")
    team_complete_cmd.add_argument("--artifact", action="append", default=[])
    team_complete_cmd.add_argument("--feedback-item", action="append", default=[])
    team_complete_cmd.add_argument("--learning", action="append", default=[])
    team_complete_cmd.add_argument("--request")
    team_memory_cmd = sub.add_parser("show-team-memory")
    team_memory_cmd.add_argument("--team", required=True)
    team_memory_cmd.add_argument("--scope", default="all", choices=["all", "global", "project", "session"])
    team_memory_cmd.add_argument("--limit", type=int, default=5)
    team_pref_cmd = sub.add_parser("record-team-preference")
    team_pref_cmd.add_argument("--team", required=True)
    team_pref_cmd.add_argument("--scope", default="all", choices=["all", "global", "project", "session"])
    team_pref_cmd.add_argument("--note", required=True)
    team_pref_cmd.add_argument("--tag", action="append", default=[])
    team_project_memory_cmd = sub.add_parser("record-team-project-memory")
    team_project_memory_cmd.add_argument("--team", required=True)
    team_project_memory_cmd.add_argument("--scope", default="all", choices=["all", "global", "project", "session"])
    team_project_memory_cmd.add_argument("--note", required=True)
    team_project_memory_cmd.add_argument("--tag", action="append", default=[])
    gate_review_cmd = sub.add_parser("write-gate-review")
    gate_review_cmd.add_argument("--workflow", required=True)
    gate_review_cmd.add_argument("--gate", required=True)
    gate_review_cmd.add_argument("--reviewer", required=True)
    gate_review_cmd.add_argument("--status", required=True, choices=["changes_requested", "lgtm", "blocked"])
    gate_review_cmd.add_argument("--round", required=True, type=int)
    gate_review_cmd.add_argument("--score", type=float)
    gate_review_cmd.add_argument("--open-issue", action="append", default=[])
    gate_review_cmd.add_argument("--closed-issue", action="append", default=[])
    gate_review_cmd.add_argument("--blocker", action="append", default=[])
    gate_review_cmd.add_argument("--suggestion", action="append", default=[])
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
        if args.workspace:
            os.environ["AEGIS_WORKSPACE_ROOT"] = str(Path(args.workspace).expanduser().resolve())
        elif hasattr(args, "workflow"):
            inferred_workspace = workspace_from_workflow_index(getattr(args, "workflow"))
            if inferred_workspace:
                os.environ["AEGIS_WORKSPACE_ROOT"] = str(inferred_workspace)
        if args.command in {"doctor", "validate"}:
            result = doctor()
        elif args.command == "workspace-doctor":
            result = workspace_doctor()
        elif args.command == "run-doctor":
            result = run_doctor(args.workflow)
        elif args.command == "sync-agent-metadata":
            result = sync_agent_metadata(check_only=False)
        elif args.command == "sync-agents":
            result = ensure_skill_symlinks()
        elif args.command == "attach-workspace":
            result = ensure_workspace_layout()
        elif args.command == "workflow-workspace":
            resolved_workspace = resolve_workspace(workflow=args.workflow)
            result = [str(resolved_workspace)]
        elif args.command == "workflow-dry-run":
            result = workflow_dry_run()
        elif args.command == "install-cron":
            result = ensure_cron()
        elif args.command == "install-shims":
            result = ensure_cli_shims()
        elif args.command == "compose-team-pack":
            result = compose_team_pack_from_request(
                args.request,
                team_id=args.id,
                display_name=args.name,
                scope=args.scope,
                install=args.install,
                explicit_workspace=args.workspace,
            )
        elif args.command == "create-team-pack":
            result = create_team_pack(
                team_id=args.id,
                display_name=args.name,
                mission=args.mission,
                domain=args.domain,
                scope=args.scope,
                role_specs=args.role,
                playbook_steps=args.playbook_step,
                review_mode=args.review_mode,
                install=args.install,
                explicit_workspace=args.workspace,
            )
        elif args.command == "list-team-packs":
            result = list_team_packs(args.scope, args.workspace)
        elif args.command == "show-team-pack":
            result = show_team_pack(args.team, args.scope, args.workspace)
        elif args.command == "install-team-pack":
            result = install_team_pack(args.team, args.scope, args.workspace)
        elif args.command == "team-doctor":
            result = team_doctor(args.scope, args.workspace)
        elif args.command == "prepare-team-run":
            result = prepare_team_run(
                team_id=args.team,
                request=args.request,
                scope=args.scope,
                explicit_workspace=args.workspace,
            )
        elif args.command == "invoke-team-pack":
            result = invoke_team_pack(
                team_id=args.team,
                request=args.request,
                scope=args.scope,
                explicit_workspace=args.workspace,
            )
        elif args.command == "show-team-run":
            result = show_team_run(
                args.team,
                args.run_id,
                args.scope,
                args.workspace,
            )
        elif args.command == "record-team-run":
            result = record_team_run(
                team_id=args.team,
                scope=args.scope,
                request=args.request,
                summary=args.summary,
                status=args.status,
                artifacts=args.artifact,
                feedback=args.feedback_item,
                learnings=args.learning,
                run_id=args.run_id,
                explicit_workspace=args.workspace,
            )
        elif args.command == "complete-team-run":
            result = complete_team_run(
                team_id=args.team,
                run_id=args.run_id,
                scope=args.scope,
                summary=args.summary,
                status=args.status,
                artifacts=args.artifact,
                feedback=args.feedback_item,
                learnings=args.learning,
                request=args.request,
                explicit_workspace=args.workspace,
            )
        elif args.command == "show-team-memory":
            result = show_team_memory(args.team, args.scope, args.limit, args.workspace)
        elif args.command == "record-team-preference":
            result = record_team_preference(
                team_id=args.team,
                scope=args.scope,
                note=args.note,
                tags=args.tag,
                explicit_workspace=args.workspace,
            )
        elif args.command == "record-team-project-memory":
            result = record_team_project_memory(
                team_id=args.team,
                scope=args.scope,
                note=args.note,
                tags=args.tag,
                explicit_workspace=args.workspace,
            )
        elif args.command == "write-gate-review":
            result = write_gate_review(
                workflow=args.workflow,
                gate_state=args.gate,
                reviewer=args.reviewer,
                status=args.status,
                round_number=args.round,
                score=args.score,
                open_issues=args.open_issue,
                closed_issues=args.closed_issue,
                blockers=args.blocker,
                suggestions=args.suggestion,
            )
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
