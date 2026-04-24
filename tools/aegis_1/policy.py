from __future__ import annotations

from dataclasses import dataclass, field

from .types import RunEvent, RunPlan


class PolicyViolation(RuntimeError):
    def __init__(self, message: str, *, violations: list[str], recovery_hint: str) -> None:
        super().__init__(message)
        self.violations = violations
        self.recovery_hint = recovery_hint


@dataclass(slots=True)
class PolicyDecision:
    passed: bool
    violations: list[str] = field(default_factory=list)
    recovery_hint: str = ""


class RunPolicy:
    def evaluate(self, plan: RunPlan, events: list[RunEvent]) -> PolicyDecision:
        violations: list[str] = []
        errors = [event for event in events if event.event_type == "error"]
        if errors:
            violations.append("run contains error events")

        required_stage_names = {step.name for step in plan.steps}
        completed_stage_names = {
            event.stage_name
            for event in events
            if event.event_type == "stage_result" and event.status == "completed" and event.stage_name
        }
        completed_stage_names.update(
            event.stage_name
            for event in events
            if event.event_type == "review_feedback"
            and event.status == "completed"
            and event.metadata.get("verdict") == "APPROVED"
            and event.stage_name
        )
        missing = sorted(required_stage_names - completed_stage_names)
        if missing:
            violations.append(f"stages not completed: {', '.join(missing)}")

        if plan.strategy.value == "pair":
            approved = any(
                event.event_type == "review_feedback" and event.metadata.get("verdict") == "APPROVED"
                for event in events
            )
            if not approved:
                violations.append("pair run has no APPROVED review")
            verified = any(event.event_type == "verification" and event.status == "passed" for event in events)
            if not verified:
                violations.append("pair run has no passed verification")

        if plan.strategy.value == "pipeline":
            verified = any(event.event_type == "verification" and event.status == "passed" for event in events)
            done_gate = any(event.event_type == "done_gate" and event.status == "passed" for event in events)
            reviewed = any(
                event.event_type == "stage_result"
                and event.status == "completed"
                and event.metadata.get("kind") == "review"
                for event in events
            )
            if not reviewed:
                violations.append("pipeline has no completed review stage")
            if not verified:
                violations.append("pipeline has no passed verification")
            if not done_gate:
                violations.append("pipeline has no passed done gate")

        if violations:
            return PolicyDecision(
                passed=False,
                violations=violations,
                recovery_hint="Inspect `aegis session show <session_id>` and rerun with `aegis session recover <session_id> --simulate` after fixing the failed stage.",
            )
        return PolicyDecision(passed=True)

    def enforce(self, plan: RunPlan, events: list[RunEvent]) -> None:
        decision = self.evaluate(plan, events)
        if not decision.passed:
            raise PolicyViolation(
                "run policy blocked completion",
                violations=decision.violations,
                recovery_hint=decision.recovery_hint,
            )
