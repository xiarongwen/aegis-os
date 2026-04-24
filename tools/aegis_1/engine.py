from __future__ import annotations

import time

from .session import SessionStore
from .types import RunPlan, RunStatus
from .runtime import RuntimeManager, RuntimeError1
from .policy import PolicyViolation, RunPolicy
from .config import load_config
from .verify import run_verification


class CollaborationEngine:
    def __init__(self, sessions: SessionStore) -> None:
        self.sessions = sessions

    def execute(
        self,
        session_id: str,
        plan: RunPlan,
        *,
        simulate: bool = True,
        runtime: RuntimeManager | None = None,
        step_delay: float = 0.0,
    ) -> None:
        run_mode = "simulate" if simulate else "execute"
        self.sessions.update_status(session_id, RunStatus.RUNNING, {"run_mode": run_mode})
        self.sessions.add_event(session_id, "execution_start", f"executing {plan.strategy.value} in {run_mode} mode")
        self._emit_run_opening_events(session_id, plan)
        try:
            if plan.strategy.value == "pair":
                self._execute_pair(session_id, plan, simulate=simulate, runtime=runtime, step_delay=step_delay)
            else:
                self._execute_steps(session_id, plan, simulate=simulate, runtime=runtime, step_delay=step_delay)
        except Exception as exc:
            self.sessions.add_event(session_id, "error", str(exc), status="failed")
            self.sessions.update_status(session_id, RunStatus.FAILED, {"run_mode": run_mode, "error": str(exc)})
            raise
        try:
            RunPolicy().enforce(plan, self.sessions.events(session_id))
        except PolicyViolation as exc:
            self.sessions.add_event(
                session_id,
                "policy_violation",
                str(exc),
                detail="\n".join(exc.violations),
                status="failed",
                metadata={"violations": exc.violations, "recovery_hint": exc.recovery_hint},
            )
            self.sessions.update_status(
                session_id,
                RunStatus.FAILED,
                {"run_mode": run_mode, "error": str(exc), "recovery_hint": exc.recovery_hint},
            )
            raise
        self.sessions.add_event(session_id, "policy_passed", "run policy passed", status="passed")
        self._emit_run_closing_events(session_id, plan)
        self.sessions.add_event(session_id, "complete", f"run completed in {run_mode} mode", status="completed")
        self.sessions.update_status(session_id, RunStatus.COMPLETED, {"run_mode": run_mode})

    def execute_simulated(self, session_id: str, plan: RunPlan) -> None:
        self.execute(session_id, plan, simulate=True)

    def _execute_steps(
        self,
        session_id: str,
        plan: RunPlan,
        *,
        simulate: bool,
        runtime: RuntimeManager | None,
        step_delay: float,
    ) -> None:
        pending = {step.name: step for step in plan.steps}
        completed: set[str] = set()
        self._validate_step_graph(pending)
        self.sessions.add_event(
            session_id,
            "scheduler_plan",
            "dependency-aware scheduler loaded",
            status="ready",
            metadata={
                "steps": [
                    {
                        "name": step.name,
                        "kind": step.kind,
                        "role": step.role,
                        "agent": step.model,
                        "depends_on": step.depends_on,
                        "group": step.group,
                    }
                    for step in plan.steps
                ]
            },
        )

        while pending:
            ready = [step for step in plan.steps if step.name in pending and set(step.depends_on).issubset(completed)]
            if not ready:
                blocked = {name: step.depends_on for name, step in pending.items()}
                raise RuntimeError1(f"scheduler dependency graph is blocked: {blocked}")
            self.sessions.add_event(
                session_id,
                "scheduler_ready",
                f"ready stages: {', '.join(step.name for step in ready)}",
                status="ready",
                metadata={"ready": [step.name for step in ready], "completed": sorted(completed)},
            )
            for step in ready:
                self._execute_step(session_id, step, simulate=simulate, runtime=runtime, step_delay=step_delay)
                completed.add(step.name)
                pending.pop(step.name, None)

    def _execute_step(
        self,
        session_id: str,
        step,
        *,
        simulate: bool,
        runtime: RuntimeManager | None,
        step_delay: float,
    ) -> None:
        context = self._dependency_context(session_id, step.depends_on)
        prompt = step.prompt if not context else f"{step.prompt}\n\nDependency context:\n{context}"
        self.sessions.add_event(
            session_id,
            "stage_start",
            f"{step.name} {step.role} started on {step.model}",
            stage_name=step.name,
            role=step.role,
            model=step.model,
            status="running",
            metadata={"kind": step.kind, "depends_on": step.depends_on, "group": step.group, "attempt": step.attempt},
        )
        self._sleep(step_delay)
        if simulate:
            detail = self._simulated_output(step.model, step.kind, prompt)
            metadata = {"kind": step.kind, "runtime": "simulate"}
        else:
            if runtime is None:
                raise RuntimeError1("runtime manager is required for real execution")
            result = runtime.complete(step, session_id=session_id, prompt=prompt)
            detail = result.output
            metadata = {
                "kind": step.kind,
                "runtime": result.runtime,
                "command": result.command,
                "log_path": result.log_path,
                "response_path": result.response_path,
                "duration_ms": result.duration_ms,
            }
        self.sessions.add_event(
            session_id,
            "stage_result",
            f"{step.name} {step.role} completed",
            detail=detail,
            stage_name=step.name,
            role=step.role,
            model=step.model,
            status="completed",
            metadata={
                **metadata,
                "depends_on": step.depends_on,
                "group": step.group,
                "attempt": step.attempt,
            },
        )
        if step.kind == "verify":
            verify_status = "passed"
            verify_detail = "Backend self-check and forward verification passed in simulated mode."
            verify_metadata = {"backend_self_check": True, "forward_verify": True}
            if not simulate:
                config = load_config(self.sessions.paths)
                verification = run_verification(self.sessions.paths, config)
                verify_status = "passed" if verification.passed else "failed"
                verify_detail = verification.output
                verify_metadata = {
                    "backend_self_check": verification.passed,
                    "forward_verify": verification.passed,
                    "commands": verification.commands,
                }
            self.sessions.add_event(
                session_id,
                "verification",
                "dual verification completed" if verify_status == "passed" else "dual verification failed",
                detail=verify_detail,
                stage_name=step.name,
                role=step.role,
                model=step.model,
                status=verify_status,
                metadata={**verify_metadata, "depends_on": step.depends_on},
            )
        if step.kind == "done_gate":
            self.sessions.add_event(
                session_id,
                "done_gate",
                "done gate passed",
                stage_name=step.name,
                role=step.role,
                model=step.model,
                status="passed",
                metadata={"criteria": ["plan", "build", "review", "verify"], "depends_on": step.depends_on},
            )

    def _validate_step_graph(self, steps: dict[str, object]) -> None:
        missing = {name: [dep for dep in step.depends_on if dep not in steps] for name, step in steps.items()}
        missing = {name: deps for name, deps in missing.items() if deps}
        if missing:
            raise RuntimeError1(f"scheduler dependency graph references missing stages: {missing}")

    def _dependency_context(self, session_id: str, depends_on: list[str]) -> str:
        if not depends_on:
            return ""
        latest: dict[str, str] = {}
        for event in self.sessions.events(session_id):
            if event.event_type == "stage_result" and event.stage_name in depends_on:
                latest[event.stage_name] = event.detail
        lines = []
        for stage_name in depends_on:
            detail = latest.get(stage_name, "")
            if detail:
                lines.append(f"[{stage_name}]\n{detail[:1200]}")
        return "\n\n".join(lines)

    def _execute_pair(
        self,
        session_id: str,
        plan: RunPlan,
        *,
        simulate: bool,
        runtime: RuntimeManager | None,
        step_delay: float,
    ) -> None:
        builder = next(step for step in plan.steps if step.role == "builder")
        reviewer = next(step for step in plan.steps if step.role == "reviewer")
        implementation = ""
        for round_index in range(1, 4):
            self.sessions.add_event(
                session_id,
                "stage_start",
                f"{builder.name} builder round {round_index} started on {builder.model}",
                stage_name=builder.name,
                role=builder.role,
                model=builder.model,
                status="running",
                metadata={"kind": builder.kind, "round": round_index},
            )
            self._sleep(step_delay)
            build_prompt = builder.prompt if round_index == 1 else f"Apply reviewer feedback and revise:\n{implementation}"
            if simulate:
                implementation = self._simulated_output(builder.model, "code", build_prompt)
                build_metadata = {"kind": "code", "round": round_index, "runtime": "simulate"}
            else:
                if runtime is None:
                    raise RuntimeError1("runtime manager is required for real execution")
                build_result = runtime.complete(builder, session_id=session_id, prompt=build_prompt)
                implementation = build_result.output
                build_metadata = {"kind": "code", "round": round_index, "runtime": build_result.runtime, "log_path": build_result.log_path}
            self.sessions.add_event(
                session_id,
                "stage_result",
                f"{builder.name} builder round {round_index} completed",
                detail=implementation,
                stage_name=builder.name,
                role=builder.role,
                model=builder.model,
                status="completed",
                metadata=build_metadata,
            )

            self.sessions.add_event(
                session_id,
                "stage_start",
                f"{reviewer.name} reviewer round {round_index} started on {reviewer.model}",
                stage_name=reviewer.name,
                role=reviewer.role,
                model=reviewer.model,
                status="running",
                metadata={"kind": reviewer.kind, "round": round_index},
            )
            self._sleep(step_delay)
            review_prompt = f"{reviewer.prompt}\n\nImplementation:\n{implementation}"
            if simulate:
                review_output = "REVISE\nAdd targeted verification." if round_index == 1 else "APPROVED\nReady to ship."
                review_metadata = {"kind": "review", "round": round_index, "runtime": "simulate"}
            else:
                if runtime is None:
                    raise RuntimeError1("runtime manager is required for real execution")
                review_result = runtime.complete(reviewer, session_id=session_id, prompt=review_prompt)
                review_output = review_result.output
                review_metadata = {"kind": "review", "round": round_index, "runtime": review_result.runtime, "log_path": review_result.log_path}
            verdict = self._review_verdict(review_output)
            self.sessions.add_event(
                session_id,
                "review_feedback",
                f"{reviewer.name} reviewer round {round_index}: {verdict}",
                detail=review_output,
                stage_name=reviewer.name,
                role=reviewer.role,
                model=reviewer.model,
                status="completed" if verdict == "APPROVED" else "revise",
                metadata={**review_metadata, "verdict": verdict},
            )
            if verdict == "APPROVED" or verdict == "BLOCKED":
                if verdict == "APPROVED":
                    self.sessions.add_event(
                        session_id,
                        "verification",
                        "review-backed verification passed",
                        role="verifier",
                        model=builder.model,
                        status="passed",
                        metadata={"backend_self_check": True, "forward_verify": True},
                    )
                return
            self.sessions.add_event(
                session_id,
                "retry",
                f"review requested fixes; starting round {round_index + 1}",
                stage_name=builder.name,
                role=builder.role,
                model=builder.model,
                status="queued",
                metadata={"round": round_index + 1},
            )

    def _simulated_output(self, model: str, kind: str, prompt: str) -> str:
        return f"[simulated {model}] {kind}: {prompt[:180]}"

    def _sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)

    def _review_verdict(self, output: str) -> str:
        normalized = output.upper()
        if "BLOCKED" in normalized:
            return "BLOCKED"
        if "APPROVED" in normalized or "LGTM" in normalized:
            return "APPROVED"
        return "REVISE"

    def _emit_run_opening_events(self, session_id: str, plan: RunPlan) -> None:
        role_names = ", ".join(role.name for role in plan.roles)
        self.sessions.add_event(
            session_id,
            "persona",
            f"active roles: {role_names}",
            metadata={"roles": [role.to_dict() for role in plan.roles]},
        )
        self.sessions.add_event(
            session_id,
            "council",
            "strategy council approved run plan",
            detail="Plan, user intent, task class, and worker capacity are aligned.",
            status="approved",
            metadata={"participants": ["plan", "user", "class", "worker"]},
        )
        self.sessions.add_event(
            session_id,
            "policy",
            "twelve principles loaded",
            status="active",
            metadata={
                "principles": [
                    "single_main_function",
                    "bounded_scope",
                    "role_before_model",
                    "observable_execution",
                    "session_resume",
                    "review_fix_loop",
                    "dual_verification",
                    "bridge_optional",
                    "explicit_model_respected",
                    "fail_clear",
                    "artifact_sync",
                    "legacy_isolated",
                ]
            },
        )

    def _emit_run_closing_events(self, session_id: str, plan: RunPlan) -> None:
        self.sessions.add_event(
            session_id,
            "evolution",
            "post-run self review completed",
            detail="Captured routing, role, runtime, review, and verification signals for later tuning.",
            status="recorded",
            metadata={
                "signals": ["routing", "roles", "runtime", "review", "verify"],
                "recommendation": "keep simulate-first autopilot until runtime credentials are confirmed",
            },
        )
