from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from typing import Any, Callable

from .runtime import RuntimeManager
from .session import MultiModelSession
from .types import (
    ExecutionStep,
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
    return _review_verdict(output) == "APPROVED"


def _is_review_blocked(output: str) -> bool:
    return _review_verdict(output) == "BLOCKED"


def _review_verdict(output: str) -> str:
    first_line = next((line.strip().upper() for line in output.splitlines() if line.strip()), "")
    if first_line in {"APPROVED", "REVISE", "BLOCKED"}:
        return first_line
    if first_line == "LGTM":
        return "APPROVED"
    return "REVISE"


def _normalized_text(value: str) -> str:
    return " ".join(value.strip().split()).lower()


def _similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, _normalized_text(left), _normalized_text(right)).ratio()


import json
import re


def _parse_subtasks(output: str, count: int, request: str) -> list[str]:
    subtasks: list[str] = []

    # Try JSON array first
    trimmed = output.strip()
    if trimmed.startswith("["):
        # Find the matching closing bracket for the top-level array
        depth = 0
        end = -1
        for i, ch in enumerate(trimmed):
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end > 0:
            try:
                parsed = json.loads(trimmed[:end])
                if isinstance(parsed, list):
                    for item in parsed:
                        if isinstance(item, str) and item.strip():
                            subtasks.append(item.strip())
            except json.JSONDecodeError:
                pass

    # If JSON didn't yield enough, fall back to line-by-line parsing
    if len(subtasks) < count:
        subtasks = []
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            # Skip pure heading/intro lines
            lower = line.lower()
            if lower in {"subtasks:", "tasks:", "items:", "steps:", "list:", "results:", "output:", "here are the subtasks:", "here is the list:"}:
                continue
            if lower.startswith("here are") and lower.endswith(":"):
                continue

            # Markdown checkbox: - [ ] task or - [x] task
            checkbox_match = re.match(r"^[-*+]?\s*\[\s*[xX\s]\s*\]\s*(.+)", line)
            if checkbox_match:
                subtasks.append(checkbox_match.group(1).strip())
                continue

            # Markdown bullet: - item, * item, + item
            bullet_match = re.match(r"^[-*+]\s+(.+)", line)
            if bullet_match:
                subtasks.append(bullet_match.group(1).strip())
                continue

            # Numbered list: 1. item, 2) item, (1) item, 1) item
            numbered_match = re.match(r"^(?:\(\d+\)|\d+[.\)])\s*(.+)", line)
            if numbered_match:
                subtasks.append(numbered_match.group(1).strip())
                continue

            # If the line looks like a plain sentence/paragraph and we haven't collected anything yet,
            # treat non-empty meaningful lines as fallback subtasks when no list markers are present
            if len(subtasks) < count and len(line) > 10:
                # Avoid capturing trailing punctuation-only lines or parentheticals
                cleaned = re.sub(r"^\d+\s*[-.)]?\s*", "", line)
                if cleaned and len(cleaned) > 5:
                    subtasks.append(cleaned)

    # Deduplicate while preserving order
    deduped: list[str] = []
    seen: set[str] = set()
    for item in subtasks:
        key = _normalized_text(item)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) == count:
            break

    while len(deduped) < count:
        deduped.append(f"Subtask {len(deduped) + 1} for: {request}")
    return deduped


def _model_perspective(runtime: RuntimeManager, model_name: str) -> str:
    registry = getattr(runtime, "registry", None)
    if registry is None or model_name not in registry.names():
        return "general implementation perspective"
    spec = registry.get(model_name)
    if spec.specialties:
        return ", ".join(spec.specialties[:2])
    if spec.capabilities:
        return ", ".join(spec.capabilities[:2])
    return "general implementation perspective"


def _expert_role(step: ExecutionStep) -> tuple[str, str]:
    role_name = step.name.replace("expert-", "").replace("-", " ").strip() or "expert"
    role_prompt = step.prompt.strip()
    if not role_prompt:
        return role_name, "Provide an independent expert assessment."
    lines = [line.strip() for line in role_prompt.splitlines() if line.strip()]
    if len(lines) >= 2 and lines[0].lower().startswith("role:") and lines[1].lower().startswith("focus:"):
        return lines[0].split(":", 1)[1].strip() or role_name, lines[1].split(":", 1)[1].strip()
    return role_name, role_prompt


def _trim_block(text: str, limit: int = 420) -> str:
    normalized = " ".join(text.strip().split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1] + "…"


def _peer_digest(
    *,
    current_index: int,
    expert_steps: list[ExecutionStep],
    expert_roles: list[tuple[str, str]],
    expert_outputs: list[str],
    max_items: int,
) -> str:
    digest_items: list[str] = []
    for index, output in enumerate(expert_outputs):
        if index == current_index:
            continue
        digest_items.append(
            f"- {expert_roles[index][0]} / {expert_steps[index].model}: {_trim_block(output)}"
        )
        if len(digest_items) >= max_items:
            break
    return "\n".join(digest_items) if digest_items else "- No peer findings available."


def _publish_stage_start(session: MultiModelSession, step: ExecutionStep) -> None:
    session.publish(
        channel="lifecycle",
        sender="router",
        message_type=MessageType.STAGE_START,
        content=f"starting {step.name}",
        metadata={"model": step.model, "kind": step.kind},
    )


def _parallel_workers(runtime: RuntimeManager, task_count: int) -> int:
    performance = getattr(getattr(runtime, "registry", None), "config", {}).get("performance", {})
    if not bool(performance.get("parallel_execution", True)):
        return 1
    configured = int(performance.get("max_concurrent_models", task_count) or task_count)
    return max(1, min(task_count, configured))


def _run_parallel_steps(
    *,
    steps: list[ExecutionStep],
    prompts: list[str],
    runtime: RuntimeManager,
    session: MultiModelSession,
    metadata_factory: Callable[[int, ExecutionStep], dict[str, Any]],
) -> list[StageResult]:
    if len(steps) != len(prompts):
        raise ValueError("parallel execution requires one prompt per step")
    if not steps:
        return []

    for step in steps:
        _publish_stage_start(session, step)

    max_workers = _parallel_workers(runtime, len(steps))
    submitted = []
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="aegis-v2") as executor:
        for index, (step, prompt) in enumerate(zip(steps, prompts)):
            metadata = metadata_factory(index, step)
            future = executor.submit(
                runtime.complete,
                step.model,
                prompt,
                session_id=session.session_id,
                stage_name=step.name,
                metadata=metadata,
            )
            submitted.append((step, future))

    stage_results: list[StageResult] = []
    for step, future in submitted:
        try:
            result = future.result()
        except Exception as exc:
            raise RuntimeError(f"parallel stage '{step.name}' failed: {exc}") from exc
        stage_results.append(_stage_from_runtime(step.name, step.kind, result))
    return stage_results


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
        _publish_stage_start(session, step)
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
            _publish_stage_start(session, step)
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
        registry = getattr(runtime, "registry", None)
        pair_cfg = registry.config.get("collaboration", {}).get("pair_programming", {}) if registry is not None else {}
        max_stagnant_rounds = int(pair_cfg.get("max_stagnant_rounds", 2))
        completed_rounds = 0
        stagnant_rounds = 0
        previous_implementation = ""
        previous_review = ""
        review_verdict = "REVISE"
        round_history: list[dict[str, Any]] = []
        for iteration in range(iterations):
            completed_rounds = iteration + 1
            coder_prompt = (
                "You are the implementation lead in a pair-programming session.\n"
                "Return the best updated code or patch-oriented implementation plan.\n"
                "Respect the project language, existing conventions, error handling, and test expectations.\n\n"
                f"Original request:\n{request}\n\nCurrent implementation:\n{implementation}\n\n"
                f"Reviewer feedback:\n{review_output}\n\n"
                "Address every reviewer issue explicitly. If feedback is empty, produce the first strong implementation."
                if iteration > 0
                else (
                    "You are the implementation lead in a pair-programming session.\n"
                    "Produce the first strong implementation draft with explicit attention to correctness, maintainability, and testability.\n\n"
                    f"Original request:\n{request}"
                )
            )
            _publish_stage_start(session, coder_step)
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
                "You are the reviewer in a pair-programming session.\n"
                "Judge the implementation against the request.\n"
                "The first non-empty line must be exactly one token: APPROVED, REVISE, or BLOCKED.\n"
                "After that, return sections for Correctness, Security, Performance, Maintainability, Test Coverage, and Concrete Fixes.\n"
                "If format is violated, the verdict will default to REVISE.\n\n"
                f"Request:\n{request}\n\nImplementation:\n{implementation}\n\n"
                "Approve only when the implementation is ready to ship."
            )
            _publish_stage_start(session, reviewer_step)
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
            review_verdict = _review_verdict(review_output)
            round_history.append(
                {
                    "round": iteration + 1,
                    "code": implementation,
                    "review": review_output,
                    "verdict": review_verdict,
                }
            )
            session.share_context("pair_round_history", round_history, sender="system")
            if _is_review_approved(review_output):
                break
            if _is_review_blocked(review_output):
                session.share_context("pair_blocker_reason", review_output, sender="system")
                break
            implementation_stalled = _similarity(implementation, previous_implementation) >= 0.95 if previous_implementation else False
            review_stalled = _similarity(review_output, previous_review) >= 0.95 if previous_review else False
            stagnant_rounds = stagnant_rounds + 1 if implementation_stalled or review_stalled else 0
            if stagnant_rounds >= max_stagnant_rounds:
                session.share_context(
                    "pair_stop_reason",
                    "stagnated_after_repeated_feedback",
                    sender="system",
                )
                break
            previous_implementation = implementation
            previous_review = review_output
        final_output = implementation
        if review_verdict == "BLOCKED":
            final_output = f"BLOCKED: {review_output}\n\nLatest draft:\n{implementation}"
        return PatternExecutionResult(
            strategy=RoutingStrategy.PAIR_PROGRAMMING,
            final_output=final_output,
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
        split_prompt = (
            "Break this coding task into independent parallel subtasks.\n"
            f"Return exactly {plan.worker_count or 1} numbered items.\n"
            "Each item should be concrete, non-overlapping, and executable by one model.\n\n"
            f"Original request:\n{request}"
        )
        _publish_stage_start(session, splitter_step)
        split_result = runtime.complete(
            splitter_step.model,
            split_prompt,
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
        worker_prompts = [
            "You are one worker in a multi-model coding swarm.\n"
            "Focus only on your assigned scope and return concrete code-oriented output.\n\n"
            f"Original request:\n{request}\n\nAssigned subtask:\n"
            f"{subtasks[index] if index < len(subtasks) else f'Subtask {index + 1}: {request}'}"
            for index, step in enumerate(worker_steps)
        ]
        worker_stages = _run_parallel_steps(
            steps=worker_steps,
            prompts=worker_prompts,
            runtime=runtime,
            session=session,
            metadata_factory=lambda index, step: {
                "kind": step.kind,
                "subtask": subtasks[index] if index < len(subtasks) else f"Subtask {index + 1}: {request}",
            },
        )
        for worker_stage in worker_stages:
            stage_results.append(worker_stage)
            session.record_stage_result(worker_stage)
            worker_outputs.append(worker_stage.output)

        aggregator_step = plan.steps[-1]
        aggregator_prompt = (
            "You are the swarm aggregator.\n"
            "Merge the worker outputs into one cohesive coding answer.\n"
            "Preserve strong ideas, resolve overlaps, call out conflicts briefly, and end with the recommended final result.\n\n"
            f"Original request:\n{request}\n\n"
            "Subtasks and worker results:\n"
            + "\n\n".join(
                f"Worker {index + 1} subtask: {subtasks[index] if index < len(subtasks) else f'Subtask {index + 1}'}\n"
                f"Output:\n{output}"
                for index, output in enumerate(worker_outputs)
            )
        )
        _publish_stage_start(session, aggregator_step)
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
        expert_steps = [step for step in plan.steps if step.kind == "expert"]
        expert_roles = [_expert_role(step) for step in expert_steps]
        moa_cfg = getattr(runtime, "registry", None).config.get("collaboration", {}).get("moa", {}) if getattr(runtime, "registry", None) is not None else {}
        discussion_rounds = max(1, int(moa_cfg.get("discussion_rounds", 2) or 2))
        max_peer_findings = max(1, int(moa_cfg.get("max_peer_findings", 2) or 2))
        expert_prompts = [
            (
                "You are one expert in a mixture-of-agents technical review.\n"
                f"Your role: {expert_roles[index][0]}.\n"
                f"Your focus: {expert_roles[index][1]}\n"
                f"Model perspective: {_model_perspective(runtime, step.model)}.\n"
                "Work independently. Do not assume consensus. Return a structured response with sections:\n"
                "1. Verdict\n2. Key Findings\n3. Risks\n4. Recommendation\n\n"
                f"Original request:\n{request}"
            )
            for index, step in enumerate(expert_steps)
        ]
        expert_stages = _run_parallel_steps(
            steps=expert_steps,
            prompts=expert_prompts,
            runtime=runtime,
            session=session,
            metadata_factory=lambda index, step: {
                "kind": step.kind,
                "role": expert_roles[index][0],
                "focus": expert_roles[index][1],
                "round": 1,
                "perspective": _model_perspective(runtime, step.model),
            },
        )
        round_one_outputs: list[str] = []
        expert_findings: list[dict[str, Any]] = []
        for stage_result in expert_stages:
            stage_results.append(stage_result)
            session.record_stage_result(stage_result)
            round_one_outputs.append(stage_result.output)
            role = next(
                (
                    role_name
                    for step, (role_name, _focus) in zip(expert_steps, expert_roles)
                    if step.name == stage_result.stage_name
                ),
                stage_result.stage_name,
            )
            expert_findings.append(
                {
                    "stage": stage_result.stage_name,
                    "model": stage_result.model,
                    "role": role,
                    "round": 1,
                    "output": stage_result.output,
                }
            )
        expert_outputs = round_one_outputs
        if discussion_rounds > 1 and len(expert_steps) > 1:
            discussion_steps = [
                ExecutionStep(
                    name=f"{step.name}-deliberate",
                    model=step.model,
                    kind="expert",
                    prompt=step.prompt,
                )
                for step in expert_steps
            ]
            discussion_prompts = [
                (
                    "You are continuing a team-based expert review.\n"
                    f"Your role: {expert_roles[index][0]}.\n"
                    f"Your focus: {expert_roles[index][1]}\n"
                    "You have now seen peer feedback. Update your stance without surrendering your specialty.\n"
                    "Return a structured response with sections:\n"
                    "1. Confirmed Points\n2. Revisions After Team Discussion\n3. Remaining Disagreements\n4. Final Recommendation\n\n"
                    f"Original request:\n{request}\n\n"
                    f"Your previous assessment:\n{round_one_outputs[index]}\n\n"
                    "Peer findings:\n"
                    f"{_peer_digest(current_index=index, expert_steps=expert_steps, expert_roles=expert_roles, expert_outputs=round_one_outputs, max_items=max_peer_findings)}"
                )
                for index, _step in enumerate(expert_steps)
            ]
            discussion_results = _run_parallel_steps(
                steps=discussion_steps,
                prompts=discussion_prompts,
                runtime=runtime,
                session=session,
                metadata_factory=lambda index, step: {
                    "kind": step.kind,
                    "role": expert_roles[index][0],
                    "focus": expert_roles[index][1],
                    "round": 2,
                    "perspective": _model_perspective(runtime, step.model),
                },
            )
            expert_outputs = []
            for index, stage_result in enumerate(discussion_results):
                stage_results.append(stage_result)
                session.record_stage_result(stage_result)
                expert_outputs.append(stage_result.output)
                expert_findings.append(
                    {
                        "stage": stage_result.stage_name,
                        "model": stage_result.model,
                        "role": expert_roles[index][0],
                        "round": 2,
                        "output": stage_result.output,
                    }
                )
        session.share_context("moa_expert_findings", expert_findings, sender="system")
        aggregator_step = next(step for step in plan.steps if step.kind == "aggregator")
        aggregate_prompt = (
            "You are the MoA aggregator.\n"
            "You are an independent arbiter, not another expert restating your own view.\n"
            "Treat the experts as a team that has already discussed the problem.\n"
            "Read all expert outputs and produce a structured arbitration.\n"
            "Use exactly these sections in order:\n"
            "Agreements\nDisagreements\nDiscarded Points\nFinal Decision\nRationale\n\n"
            f"Original request:\n{request}\n\nExpert results:\n"
            + "\n\n".join(
                f"Expert {index + 1} role={expert_roles[index][0]} model={expert_steps[index].model} "
                f"perspective={_model_perspective(runtime, expert_steps[index].model)} "
                f"round={'2' if discussion_rounds > 1 and len(expert_steps) > 1 else '1'}:\n{output}"
                for index, output in enumerate(expert_outputs)
            )
        )
        _publish_stage_start(session, aggregator_step)
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
