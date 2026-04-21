from __future__ import annotations

from typing import Any

from .runtime import RuntimeManager
from .session import MultiModelSession
from .types import (
    ExecutionPlan,
    MessageType,
    PatternExecutionResult,
    RoutingStrategy,
    RuntimeResult,
    StageResult,
)


def _stage_from_runtime(stage_name: str, kind: str, result: RuntimeResult) -> StageResult:
    return StageResult(
        stage_name=stage_name,
        model=result.model,
        kind=kind,
        output=result.output,
        exit_code=result.exit_code,
        duration_ms=result.duration_ms,
        approximate_cost=result.approximate_cost,
        metadata={
            "runtime": result.runtime,
            "command": result.command,
            "log_path": result.log_path,
            "response_path": result.response_path,
            **result.metadata,
        },
    )


def _is_review_approved(output: str) -> bool:
    normalized = output.upper()
    return "LGTM" in normalized or "APPROVE" in normalized or "APPROVED" in normalized


def _parse_subtasks(output: str, count: int, request: str) -> list[str]:
    subtasks: list[str] = []
    for raw_line in output.splitlines():
        line = raw_line.strip().lstrip("-").strip()
        if not line:
            continue
        if "." in line[:3]:
            line = line.split(".", 1)[1].strip()
        subtasks.append(line)
    if subtasks:
        return subtasks[:count]
    return [f"Subtask {index + 1} for: {request}" for index in range(count)]


class SinglePattern:
    def execute(
        self,
        *,
        request: str,
        plan: ExecutionPlan,
        runtime: RuntimeManager,
        session: MultiModelSession,
    ) -> PatternExecutionResult:
        step = plan.steps[0]
        session.publish(
            channel="lifecycle",
            sender="router",
            message_type=MessageType.STAGE_START,
            content=f"starting {step.name}",
            metadata={"model": step.model, "kind": step.kind},
        )
        result = runtime.complete(
            step.model,
            step.prompt,
            session_id=session.session_id,
            stage_name=step.name,
            metadata={"kind": step.kind},
        )
        stage_result = _stage_from_runtime(step.name, step.kind, result)
        session.record_stage_result(stage_result)
        session.share_context(step.name, stage_result.output, sender=step.model)
        return PatternExecutionResult(
            strategy=RoutingStrategy.SINGLE,
            final_output=stage_result.output,
            stage_results=[stage_result],
            approximate_cost=stage_result.approximate_cost,
            shared_context=session.shared_context.export(),
        )


class PipelinePattern:
    def execute(
        self,
        *,
        request: str,
        plan: ExecutionPlan,
        runtime: RuntimeManager,
        session: MultiModelSession,
    ) -> PatternExecutionResult:
        stage_results: list[StageResult] = []
        current_context = request
        for step in plan.steps:
            prompt = (
                f"{step.prompt}\n\nOriginal request:\n{request}\n\n"
                f"Previous context:\n{current_context}\n\n"
                f"Shared context:\n{session.shared_context.export()}"
            )
            session.publish(
                channel="lifecycle",
                sender="router",
                message_type=MessageType.STAGE_START,
                content=f"starting {step.name}",
                metadata={"model": step.model, "kind": step.kind},
            )
            result = runtime.complete(
                step.model,
                prompt,
                session_id=session.session_id,
                stage_name=step.name,
                metadata={"kind": step.kind},
            )
            stage_result = _stage_from_runtime(step.name, step.kind, result)
            stage_results.append(stage_result)
            session.record_stage_result(stage_result)
            session.share_context(step.name, stage_result.output, sender=step.model)
            current_context = stage_result.output
        return PatternExecutionResult(
            strategy=RoutingStrategy.PIPELINE,
            final_output=current_context,
            stage_results=stage_results,
            approximate_cost=round(sum(item.approximate_cost for item in stage_results), 4),
            shared_context=session.shared_context.export(),
        )


class PairProgrammingPattern:
    def execute(
        self,
        *,
        request: str,
        plan: ExecutionPlan,
        runtime: RuntimeManager,
        session: MultiModelSession,
    ) -> PatternExecutionResult:
        stage_results: list[StageResult] = []
        coder_step = next(step for step in plan.steps if step.kind == "coder")
        reviewer_step = next(step for step in plan.steps if step.kind == "reviewer")
        implementation = ""
        review_output = ""
        iterations = plan.max_iterations or 3
        completed_rounds = 0
        for iteration in range(iterations):
            completed_rounds = iteration + 1
            coder_prompt = (
                f"{request}\n\nCurrent implementation:\n{implementation}\n\n"
                f"Reviewer feedback:\n{review_output}\n\n"
                "Produce the updated implementation or patch-oriented guidance."
                if iteration > 0
                else request
            )
            coder_result = runtime.complete(
                coder_step.model,
                coder_prompt,
                session_id=session.session_id,
                stage_name=f"code-round-{iteration + 1}",
                metadata={"kind": "coder", "iteration": iteration + 1},
            )
            coder_stage = _stage_from_runtime(f"code-round-{iteration + 1}", "coder", coder_result)
            stage_results.append(coder_stage)
            session.record_stage_result(coder_stage)
            implementation = coder_stage.output
            session.share_context("latest_code", implementation, sender=coder_step.model)

            review_prompt = (
                f"Review this implementation for bugs, regressions, style, and edge cases.\n\n"
                f"Request:\n{request}\n\nImplementation:\n{implementation}\n\n"
                "Respond with LGTM if acceptable, otherwise list required fixes."
            )
            reviewer_result = runtime.complete(
                reviewer_step.model,
                review_prompt,
                session_id=session.session_id,
                stage_name=f"review-round-{iteration + 1}",
                metadata={"kind": "reviewer", "iteration": iteration + 1},
            )
            reviewer_stage = _stage_from_runtime(f"review-round-{iteration + 1}", "reviewer", reviewer_result)
            stage_results.append(reviewer_stage)
            session.record_stage_result(reviewer_stage)
            review_output = reviewer_stage.output
            session.publish(
                channel="reviews",
                sender=reviewer_step.model,
                message_type=MessageType.REVIEW_FEEDBACK,
                content=review_output,
                recipient=coder_step.model,
                metadata={"iteration": iteration + 1},
            )
            if _is_review_approved(review_output):
                break
        return PatternExecutionResult(
            strategy=RoutingStrategy.PAIR_PROGRAMMING,
            final_output=implementation,
            stage_results=stage_results,
            iterations=completed_rounds,
            approximate_cost=round(sum(item.approximate_cost for item in stage_results), 4),
            shared_context=session.shared_context.export(),
        )


class SwarmPattern:
    def execute(
        self,
        *,
        request: str,
        plan: ExecutionPlan,
        runtime: RuntimeManager,
        session: MultiModelSession,
    ) -> PatternExecutionResult:
        stage_results: list[StageResult] = []
        splitter_step = plan.steps[0]
        split_result = runtime.complete(
            splitter_step.model,
            splitter_step.prompt,
            session_id=session.session_id,
            stage_name=splitter_step.name,
            metadata={"kind": splitter_step.kind},
        )
        split_stage = _stage_from_runtime(splitter_step.name, splitter_step.kind, split_result)
        stage_results.append(split_stage)
        session.record_stage_result(split_stage)
        subtasks = _parse_subtasks(split_stage.output, plan.worker_count or 1, request)
        session.share_context("swarm_subtasks", subtasks, sender=splitter_step.model)

        worker_outputs: list[str] = []
        worker_steps = [step for step in plan.steps if step.kind == "worker"]
        for index, step in enumerate(worker_steps):
            subtask = subtasks[index] if index < len(subtasks) else f"Subtask {index + 1}: {request}"
            result = runtime.complete(
                step.model,
                f"{step.prompt}\n\nAssigned subtask:\n{subtask}",
                session_id=session.session_id,
                stage_name=step.name,
                metadata={"kind": step.kind, "subtask": subtask},
            )
            worker_stage = _stage_from_runtime(step.name, step.kind, result)
            stage_results.append(worker_stage)
            session.record_stage_result(worker_stage)
            worker_outputs.append(worker_stage.output)

        aggregator_step = plan.steps[-1]
        aggregator_prompt = (
            f"{aggregator_step.prompt}\n\nOriginal request:\n{request}\n\n"
            f"Worker results:\n" + "\n\n".join(worker_outputs)
        )
        aggregate_result = runtime.complete(
            aggregator_step.model,
            aggregator_prompt,
            session_id=session.session_id,
            stage_name=aggregator_step.name,
            metadata={"kind": aggregator_step.kind},
        )
        aggregate_stage = _stage_from_runtime(aggregator_step.name, aggregator_step.kind, aggregate_result)
        stage_results.append(aggregate_stage)
        session.record_stage_result(aggregate_stage)
        session.share_context("swarm_output", aggregate_stage.output, sender=aggregator_step.model)
        return PatternExecutionResult(
            strategy=RoutingStrategy.SWARM,
            final_output=aggregate_stage.output,
            stage_results=stage_results,
            approximate_cost=round(sum(item.approximate_cost for item in stage_results), 4),
            shared_context=session.shared_context.export(),
        )


class MoAPattern:
    def execute(
        self,
        *,
        request: str,
        plan: ExecutionPlan,
        runtime: RuntimeManager,
        session: MultiModelSession,
    ) -> PatternExecutionResult:
        stage_results: list[StageResult] = []
        expert_outputs: list[str] = []
        expert_steps = [step for step in plan.steps if step.kind == "expert"]
        for step in expert_steps:
            result = runtime.complete(
                step.model,
                step.prompt,
                session_id=session.session_id,
                stage_name=step.name,
                metadata={"kind": step.kind},
            )
            stage_result = _stage_from_runtime(step.name, step.kind, result)
            stage_results.append(stage_result)
            session.record_stage_result(stage_result)
            expert_outputs.append(stage_result.output)
        aggregator_step = next(step for step in plan.steps if step.kind == "aggregator")
        aggregate_prompt = (
            f"{aggregator_step.prompt}\n\nOriginal request:\n{request}\n\n"
            "Expert results:\n"
            + "\n\n".join(f"Expert {index + 1}: {output}" for index, output in enumerate(expert_outputs))
        )
        aggregate_result = runtime.complete(
            aggregator_step.model,
            aggregate_prompt,
            session_id=session.session_id,
            stage_name=aggregator_step.name,
            metadata={"kind": aggregator_step.kind},
        )
        aggregate_stage = _stage_from_runtime(aggregator_step.name, aggregator_step.kind, aggregate_result)
        stage_results.append(aggregate_stage)
        session.record_stage_result(aggregate_stage)
        session.share_context("moa_output", aggregate_stage.output, sender=aggregator_step.model)
        return PatternExecutionResult(
            strategy=RoutingStrategy.MOA,
            final_output=aggregate_stage.output,
            stage_results=stage_results,
            approximate_cost=round(sum(item.approximate_cost for item in stage_results), 4),
            shared_context=session.shared_context.export(),
        )


PATTERN_MAP = {
    RoutingStrategy.SINGLE: SinglePattern,
    RoutingStrategy.PIPELINE: PipelinePattern,
    RoutingStrategy.PAIR_PROGRAMMING: PairProgrammingPattern,
    RoutingStrategy.SWARM: SwarmPattern,
    RoutingStrategy.MOA: MoAPattern,
}


def pattern_for_strategy(strategy: RoutingStrategy) -> Any:
    return PATTERN_MAP[strategy]()
