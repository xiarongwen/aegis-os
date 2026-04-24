from __future__ import annotations

from .types import RoleSpec, Strategy


ROLE_DEFAULTS: dict[str, RoleSpec] = {
    "orchestrator": RoleSpec("orchestrator", "control the run and keep progress visible", "claude"),
    "planner": RoleSpec("planner", "break complex work into concrete steps", "claude"),
    "builder": RoleSpec("builder", "implement code changes or patch plans", "codex"),
    "reviewer": RoleSpec("reviewer", "review correctness, risk, and missing tests", "claude"),
    "researcher": RoleSpec("researcher", "inspect code and gather context", "codex"),
    "verifier": RoleSpec("verifier", "run or design validation checks", "codex"),
    "aggregator": RoleSpec("aggregator", "merge worker outputs into one result", "claude"),
}


def roles_for_strategy(strategy: Strategy) -> list[RoleSpec]:
    if strategy == Strategy.PAIR:
        return [ROLE_DEFAULTS["builder"], ROLE_DEFAULTS["reviewer"]]
    if strategy == Strategy.SWARM:
        return [ROLE_DEFAULTS["planner"], ROLE_DEFAULTS["builder"], ROLE_DEFAULTS["aggregator"]]
    if strategy == Strategy.PIPELINE:
        return [ROLE_DEFAULTS["planner"], ROLE_DEFAULTS["builder"], ROLE_DEFAULTS["verifier"], ROLE_DEFAULTS["reviewer"]]
    if strategy == Strategy.MOA:
        return [ROLE_DEFAULTS["planner"], ROLE_DEFAULTS["reviewer"], ROLE_DEFAULTS["aggregator"]]
    return [ROLE_DEFAULTS["builder"]]
