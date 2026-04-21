from __future__ import annotations

import re
from typing import Any

from .collaboration import pattern_for_strategy
from .registry import ModelRegistry
from .router import TaskRouter
from .runtime import RuntimeManager
from .session import MultiModelSession, SessionStore
from .types import ExecutionPlan, ExecutionStep, RoutingDecision, RoutingStrategy, RunResult


def _condition_matches(condition: str | None, *, complexity: int) -> bool:
    if not condition:
        return True
    text = condition.strip()
    match = re.fullmatch(r"complexity\s*(>=|<=|>|<|==)\s*(\d+)", text)
    if not match:
        return True
    operator, raw_value = match.groups()
    value = int(raw_value)
    if operator == ">":
        return complexity > value
    if operator == ">=":
        return complexity >= value
    if operator == "<":
        return complexity < value
    if operator == "<=":
        return complexity <= value
    return complexity == value


class MultiModelExecutor:
    def __init__(self, registry: ModelRegistry, router: TaskRouter, sessions: SessionStore) -> None:
        self.registry = registry
        self.router = router
        self.sessions = sessions

    def build_plan(self, request: str, decision: RoutingDecision) -> ExecutionPlan:
        collaboration = self.registry.config.get("collaboration", {})
        if decision.strategy == RoutingStrategy.SINGLE:
            return ExecutionPlan(
                strategy=decision.strategy,
                steps=[
                    ExecutionStep(
                        name="single",
                        model=decision.models[0],
                        kind="single",
                        prompt=request,
                    )
                ],
            )
        if decision.strategy == RoutingStrategy.PAIR_PROGRAMMING:
            pair_cfg = collaboration.get("pair_programming", {})
            coder = str(pair_cfg.get("coder_model", decision.models[0]))
            reviewer = str(pair_cfg.get("reviewer_model", decision.models[-1]))
            return ExecutionPlan(
                strategy=decision.strategy,
                max_iterations=int(pair_cfg.get("max_iterations", 3)),
                steps=[
                    ExecutionStep(name="code", model=coder, kind="coder", prompt=request),
                    ExecutionStep(
                        name="review",
                        model=reviewer,
                        kind="reviewer",
                        prompt="Review the generated implementation and request fixes when needed.",
                    ),
                ],
            )
        if decision.strategy == RoutingStrategy.SWARM:
            swarm_cfg = collaboration.get("swarm", {})
            worker_model = str(swarm_cfg.get("worker_model", decision.models[0]))
            worker_count = int(swarm_cfg.get("default_workers", len(decision.models) or 3))
            aggregator_model = str(
                swarm_cfg.get("aggregator_model", decision.models[-1] if decision.models else worker_model)
            )
            steps = [
                ExecutionStep(
                    name="split",
                    model=aggregator_model,
                    kind="splitter",
                    prompt=f"Split this task into {worker_count} independent subtasks:\n{request}",
                )
            ]
            for index in range(worker_count):
                steps.append(
                    ExecutionStep(
                        name=f"worker-{index + 1}",
                        model=worker_model,
                        kind="worker",
                        prompt=f"Execute the assigned subtask for:\n{request}",
                    )
                )
            steps.append(
                ExecutionStep(
                    name="aggregate",
                    model=aggregator_model,
                    kind="aggregator",
                    prompt="Merge the worker results into one cohesive output.",
                )
            )
            return ExecutionPlan(
                strategy=decision.strategy,
                steps=steps,
                worker_count=worker_count,
                aggregator_model=aggregator_model,
            )
        if decision.strategy == RoutingStrategy.PIPELINE:
            pipeline_cfg = collaboration.get("pipeline", {})
            steps: list[ExecutionStep] = []
            for stage in pipeline_cfg.get("stages", []):
                if not isinstance(stage, dict):
                    continue
                condition = stage.get("condition")
                if not _condition_matches(str(condition), complexity=decision.complexity):
                    continue
                steps.append(
                    ExecutionStep(
                        name=str(stage.get("name", "stage")),
                        model=str(stage.get("model", decision.models[0])),
                        kind="stage",
                        prompt=f"Pipeline stage '{stage.get('name', 'stage')}' for request: {request}",
                        condition=str(condition) if condition else None,
                    )
                )
            if not steps:
                steps.append(
                    ExecutionStep(
                        name="pipeline",
                        model=decision.models[0],
                        kind="stage",
                        prompt=request,
                    )
                )
            return ExecutionPlan(strategy=decision.strategy, steps=steps)
        steps = [
            ExecutionStep(name=f"candidate-{index + 1}", model=name, kind="expert", prompt=request)
            for index, name in enumerate(decision.models)
        ]
        aggregator = "claude-opus-4-7" if "claude-opus-4-7" in self.registry.names() else decision.models[0]
        steps.append(
            ExecutionStep(
                name="aggregate",
                model=aggregator,
                kind="aggregator",
                prompt="Synthesize the strongest answer from all experts.",
            )
        )
        return ExecutionPlan(strategy=decision.strategy, steps=steps, aggregator_model=aggregator)

    def _build_runtime(self, context: dict[str, Any]) -> RuntimeManager:
        return RuntimeManager(
            self.registry,
            simulate=bool(context.get("simulate")),
            use_bridge=bool(context.get("bridge")),
        )

    def run(self, request: str, context: dict[str, Any] | None = None) -> RunResult:
        ctx = context or {}
        decision = self.router.route(request, ctx)
        plan = self.build_plan(request, decision)
        session_record = self.sessions.create_session(
            request=request,
            decision=decision,
            metadata={
                "estimated_cost": decision.estimated_cost,
                "estimated_time_seconds": decision.estimated_time_seconds,
                "execution_plan": plan.to_dict(),
                "actual_cost": 0.0,
                "requested_execute": bool(ctx.get("execute")),
            },
        )
        session = MultiModelSession(session_record, self.sessions)
        session.checkpoint(
            "routed",
            {
                "routing": decision.to_dict(),
                "plan": plan.to_dict(),
            },
        )
        if not ctx.get("execute"):
            session.set_status("planned", execution_state="phase1-foundation")
            return RunResult(
                session=self.sessions.get_session(session.session_id),
                routing=decision,
                plan=plan,
                executed=False,
                message=(
                    "Phase 1 foundation is active: routing, session persistence, and execution planning are wired up. "
                    "Pass --execute to run the selected collaboration pattern."
                ),
            )

        runtime = self._build_runtime(ctx)
        try:
            session.set_status(
                "running",
                execution_state="executing",
                run_mode=runtime.mode_label(),
                use_bridge=runtime.use_bridge,
            )
            session.publish(
                channel="lifecycle",
                sender="router",
                message_type="execution_start",
                content=f"executing {decision.strategy.value} with {', '.join(decision.models)}",
                metadata={"mode": runtime.mode_label()},
            )
            pattern = pattern_for_strategy(decision.strategy)
            execution = pattern.execute(
                request=request,
                plan=plan,
                runtime=runtime,
                session=session,
            )
            session.complete(
                execution.final_output,
                metadata={
                    "execution": execution.to_dict(),
                    "actual_cost": execution.approximate_cost,
                    "run_mode": runtime.mode_label(),
                },
            )
            return RunResult(
                session=self.sessions.get_session(session.session_id),
                routing=decision,
                plan=plan,
                executed=True,
                message=f"Execution completed via {decision.strategy.value} ({runtime.mode_label()}).",
                execution=execution,
            )
        except Exception as exc:
            session.fail(str(exc), metadata={"run_mode": runtime.mode_label()})
            raise
