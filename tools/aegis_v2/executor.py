from __future__ import annotations

import re
from typing import Any

from .collaboration import pattern_for_strategy
from .registry import ModelRegistry
from .router import TaskRouter
from .runtime import RuntimeManager
from .session import MultiModelSession, SessionStore
from .types import ExecutionPlan, ExecutionStep, RoutingDecision, RoutingStrategy, RunResult, SessionRecord


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


def _slug_role(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return normalized or "expert"


class MultiModelExecutor:
    def __init__(self, registry: ModelRegistry, router: TaskRouter, sessions: SessionStore) -> None:
        self.registry = registry
        self.router = router
        self.sessions = sessions

    def _explicit_models(self, context: dict[str, Any] | None = None) -> list[str]:
        raw_models = (context or {}).get("models")
        if not raw_models:
            return []
        return [item.strip() for item in str(raw_models).split(",") if item.strip()]

    def build_plan(self, request: str, decision: RoutingDecision, context: dict[str, Any] | None = None) -> ExecutionPlan:
        collaboration = self.registry.config.get("collaboration", {})
        explicit_models = self._explicit_models(context)
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
            # Use explicit models if provided, otherwise fall back to decision.models
            if explicit_models:
                coder = explicit_models[0]
                reviewer = explicit_models[1] if len(explicit_models) > 1 else explicit_models[0]
            else:
                coder = decision.models[0]
                reviewer = decision.models[1] if len(decision.models) > 1 else decision.models[0]
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
            # Check for explicit workers in context
            explicit_workers = (context or {}).get("workers")
            if explicit_models:
                if len(decision.models) == 1:
                    worker_models = [decision.models[0]]
                    aggregator_model = decision.models[0]
                else:
                    worker_models = decision.models[:-1]
                    aggregator_model = decision.models[-1]
                worker_count = len(worker_models)
            else:
                worker_models = [decision.models[0]]
                worker_count = explicit_workers if explicit_workers else int(swarm_cfg.get("default_workers", 3))
                aggregator_model = decision.models[-1]
            steps = [
                ExecutionStep(
                    name="split",
                    model=aggregator_model,
                    kind="splitter",
                    prompt=f"Split this task into {worker_count} independent subtasks:\n{request}",
                )
            ]
            for index in range(worker_count):
                worker_model = worker_models[index] if index < len(worker_models) else worker_models[-1]
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
            stage_models = decision.models or ["claude-sonnet-4-6"]
            for stage in pipeline_cfg.get("stages", []):
                if not isinstance(stage, dict):
                    continue
                condition = stage.get("condition")
                if not _condition_matches(str(condition), complexity=decision.complexity):
                    continue
                step_index = len(steps)
                steps.append(
                    ExecutionStep(
                        name=str(stage.get("name", "stage")),
                        model=stage_models[min(step_index, len(stage_models) - 1)],
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
        moa_cfg = collaboration.get("moa", {})
        configured_roles = moa_cfg.get("expert_roles", [])
        if len(decision.models) > 1:
            expert_models = decision.models[:-1]
            aggregator = decision.models[-1]
        else:
            expert_models = decision.models
            aggregator = decision.models[0]
        steps: list[ExecutionStep] = []
        for index, model_name in enumerate(expert_models):
            role_payload = configured_roles[index] if index < len(configured_roles) and isinstance(configured_roles[index], dict) else {}
            role_name = str(role_payload.get("name") or f"expert-{index + 1}")
            role_focus = str(role_payload.get("focus") or "Provide an independent expert assessment.")
            steps.append(
                ExecutionStep(
                    name=f"expert-{_slug_role(role_name)}",
                    model=model_name,
                    kind="expert",
                    prompt=f"Role: {role_name}\nFocus: {role_focus}",
                )
            )
        steps.append(
            ExecutionStep(
                name="aggregate",
                model=aggregator,
                kind="aggregator",
                prompt=(
                    "Produce a structured arbitration with sections: Agreements, Disagreements, "
                    "Discarded Points, Final Decision, and Rationale."
                ),
            )
        )
        return ExecutionPlan(strategy=decision.strategy, steps=steps, aggregator_model=aggregator)

    def _build_runtime(self, context: dict[str, Any]) -> RuntimeManager:
        return RuntimeManager(
            self.registry,
            simulate=bool(context.get("simulate")),
            use_bridge=bool(context.get("bridge")),
            event_callback=context.get("runtime_event_callback"),
        )

    def _context_from_session(self, record: SessionRecord) -> dict[str, Any]:
        context: dict[str, Any] = {
            "mode": record.mode,
            "models": ",".join(record.models),
            "strategy": record.strategy,
            "task_type": record.task_type,
        }
        budget = record.metadata.get("budget")
        if budget is not None:
            context["budget"] = budget
        return context

    def replay(self, session_id: str, context: dict[str, Any] | None = None, *, recover: bool = False) -> RunResult:
        record = self.sessions.get_session(session_id)
        replay_context = self._context_from_session(record)
        replay_context.update(context or {})
        # Preserve original run mode from session metadata if not explicitly overridden
        original_run_mode = record.metadata.get("run_mode", "")
        if original_run_mode == "simulate":
            replay_context.setdefault("simulate", True)
            # If the original session was actually executed (not just planned), preserve execute intent
            if record.status in ("completed", "running", "failed"):
                replay_context.setdefault("execute", True)
        elif original_run_mode == "execute":
            replay_context.setdefault("execute", True)
        # If neither simulate nor execute explicitly set in context, default to execute for recovery
        if not replay_context.get("simulate") and not replay_context.get("execute"):
            replay_context["execute"] = True

        result = self.run(record.request, replay_context)
        lineage_metadata = {
            "resumed_from" if not recover else "recovered_from": session_id,
            "source_session_status": record.status,
        }
        self.sessions.update_status(result.session.session_id, result.session.status, metadata=lineage_metadata)
        result.session = self.sessions.get_session(result.session.session_id)
        return result

    def run(self, request: str, context: dict[str, Any] | None = None) -> RunResult:
        ctx = context or {}
        if ctx.get("simulate"):
            ctx = dict(ctx)
            ctx["execute"] = True
        decision, plan, session = self.prepare_run(request, ctx)
        if not ctx.get("execute"):
            session.set_status("planned", execution_state="phase1-foundation")
            return RunResult(
                session=self.sessions.get_session(session.session_id),
                routing=decision,
                plan=plan,
                executed=False,
                message=(
                    "Routing and execution planning are ready. Pass --execute to run the selected collaboration pattern."
                ),
            )
        return self.execute_prepared(request, decision, plan, session, ctx)

    def prepare_run(
        self,
        request: str,
        context: dict[str, Any] | None = None,
    ) -> tuple[RoutingDecision, ExecutionPlan, MultiModelSession]:
        ctx = context or {}
        decision = self.router.route(request, ctx)
        plan = self.build_plan(request, decision, ctx)
        session_record = self.sessions.create_session(
            request=request.strip(),
            decision=decision,
            metadata={
                "estimated_cost": decision.estimated_cost,
                "estimated_time_seconds": decision.estimated_time_seconds,
                "execution_plan": plan.to_dict(),
                "actual_cost": 0.0,
                "requested_execute": bool(ctx.get("execute") or ctx.get("simulate")),
                "budget": ctx.get("budget"),
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
        return decision, plan, session

    def execute_prepared(
        self,
        request: str,
        decision: RoutingDecision,
        plan: ExecutionPlan,
        session: MultiModelSession,
        context: dict[str, Any] | None = None,
    ) -> RunResult:
        ctx = context or {}
        ctx = dict(ctx)
        ctx["runtime_event_callback"] = lambda event: session.publish(
            channel="runtime",
            sender=str(event.get("model") or "runtime"),
            message_type="runtime_output",
            content=str(event.get("text") or ""),
            metadata={
                "stage": event.get("stage_name"),
                "source": event.get("source"),
            },
        )
        runtime = self._build_runtime(ctx)
        try:
            if hasattr(runtime, "preflight_plan"):
                runtime.preflight_plan(plan)
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
