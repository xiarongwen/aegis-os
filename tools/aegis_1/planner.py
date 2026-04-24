from __future__ import annotations

from .models import ModelResolver
from .roles import ROLE_DEFAULTS, roles_for_strategy
from .types import RouteDecision, RunPlan, RunStep, Strategy


def _explicit_models(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


class RunPlanner:
    def __init__(self, resolver: ModelResolver | None = None) -> None:
        self.resolver = resolver or ModelResolver()

    def build(self, request: str, route: RouteDecision, *, models: str | None = None, workers: int | None = None) -> RunPlan:
        explicit = _explicit_models(models)
        roles = roles_for_strategy(route.strategy)

        def model_for(role: str) -> str:
            return self.resolver.resolve_for_role(role, explicit or None)

        steps: list[RunStep] = []
        if route.strategy == Strategy.SINGLE:
            steps.append(RunStep("S1", "builder", "single", model_for("builder"), request))
        elif route.strategy == Strategy.PAIR:
            steps.extend(
                [
                    RunStep("S1", "builder", "code", model_for("builder"), request, group="pair"),
                    RunStep(
                        "S2",
                        "reviewer",
                        "review",
                        model_for("reviewer"),
                        "Review the builder output and request fixes if needed.",
                        depends_on=["S1"],
                        group="pair",
                    ),
                ]
            )
        elif route.strategy == Strategy.SWARM:
            count = max(1, workers or 3)
            steps.append(RunStep("S1", "planner", "split", model_for("planner"), f"Split into {count} subtasks: {request}", group="split"))
            worker_names = []
            for index in range(count):
                name = f"S{index + 2}"
                worker_names.append(name)
                steps.append(
                    RunStep(
                        name,
                        "builder",
                        "worker",
                        model_for("builder"),
                        f"Execute subtask {index + 1}: {request}",
                        depends_on=["S1"],
                        group="workers",
                    )
                )
            aggregate_name = f"S{count + 2}"
            steps.append(
                RunStep(
                    aggregate_name,
                    "aggregator",
                    "aggregate",
                    model_for("aggregator"),
                    "Merge worker outputs.",
                    depends_on=worker_names,
                    group="fan_in",
                )
            )
        elif route.strategy == Strategy.PIPELINE:
            steps.extend(
                [
                    RunStep("S1", "planner", "plan_check", model_for("planner"), f"Check the plan and identify the safest execution path:\n{request}", group="planning"),
                    RunStep("S2", "planner", "story_split", model_for("planner"), f"Split the work into deliverable stories:\n{request}", depends_on=["S1"], group="planning"),
                    RunStep("S3", "planner", "spec", model_for("planner"), f"Write a concise implementation spec:\n{request}", depends_on=["S2"], group="planning"),
                    RunStep("S4", "builder", "build", model_for("builder"), f"Implement the requested change:\n{request}", depends_on=["S3"], group="implementation"),
                    RunStep("S5", "reviewer", "review", model_for("reviewer"), "Review the implementation. Start with APPROVED, REVISE, or BLOCKED.", depends_on=["S4"], group="review"),
                    RunStep("S6", "verifier", "verify", model_for("verifier"), "Verify the implementation with tests or concrete checks.", depends_on=["S5"], group="verification"),
                    RunStep("S7", "reviewer", "done_gate", model_for("reviewer"), "Decide if the work satisfies the done gate.", depends_on=["S6"], group="gate"),
                    RunStep("S8", "aggregator", "delivery", model_for("aggregator"), "Prepare the final delivery summary.", depends_on=["S7"], group="delivery"),
                ]
            )
        else:
            steps.extend(
                [
                    RunStep("S1", "planner", "candidate", model_for("planner"), request, group="candidates"),
                    RunStep("S2", "reviewer", "candidate", model_for("reviewer"), request, group="candidates"),
                    RunStep("S3", "aggregator", "aggregate", model_for("aggregator"), "Synthesize the strongest answer.", depends_on=["S1", "S2"], group="fan_in"),
                ]
            )

        used_models = []
        for step in steps:
            if step.model not in used_models:
                used_models.append(step.model)
        role_names = {role.name for role in roles}
        all_roles = roles + [ROLE_DEFAULTS[step.role] for step in steps if step.role not in role_names]
        return RunPlan(route.strategy, steps, all_roles, used_models, route.mode)
