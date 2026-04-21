from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class TaskType(str, Enum):
    ARCHITECTURE = "architecture"
    CODE_GENERATION = "code_gen"
    CODE_REVIEW = "code_review"
    DEBUGGING = "debugging"
    TESTING = "testing"
    REFACTORING = "refactoring"
    DOCUMENTATION = "documentation"
    RESEARCH = "research"


class RoutingStrategy(str, Enum):
    PAIR_PROGRAMMING = "pair"
    SWARM = "swarm"
    PIPELINE = "pipeline"
    SINGLE = "single"
    MOA = "moa"


class MessageType(str, Enum):
    INFO = "info"
    STAGE_START = "stage_start"
    STAGE_RESULT = "stage_result"
    CODE_SHARE = "code_share"
    REQUEST_REVIEW = "request_review"
    REVIEW_FEEDBACK = "review_feedback"
    ERROR = "error"


@dataclass(slots=True)
class ModelSpec:
    name: str
    provider: str
    runtime: str
    capabilities: list[str] = field(default_factory=list)
    context_window: int = 0
    cost_per_1k_tokens: float = 0.0
    specialties: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RoutingDecision:
    task_type: TaskType
    strategy: RoutingStrategy
    models: list[str]
    mode: str
    complexity: int
    estimated_cost: float
    estimated_time_seconds: int
    rationale: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["task_type"] = self.task_type.value
        payload["strategy"] = self.strategy.value
        return payload


@dataclass(slots=True)
class ExecutionStep:
    name: str
    model: str
    kind: str
    prompt: str
    condition: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ExecutionPlan:
    strategy: RoutingStrategy
    steps: list[ExecutionStep] = field(default_factory=list)
    max_iterations: int | None = None
    worker_count: int | None = None
    aggregator_model: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "strategy": self.strategy.value,
            "steps": [step.to_dict() for step in self.steps],
        }
        if self.max_iterations is not None:
            payload["max_iterations"] = self.max_iterations
        if self.worker_count is not None:
            payload["worker_count"] = self.worker_count
        if self.aggregator_model is not None:
            payload["aggregator_model"] = self.aggregator_model
        return payload


@dataclass(slots=True)
class RuntimeInvocation:
    model: str
    runtime: str
    command: list[str]
    cwd: str
    log_path: str
    response_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RuntimeResult:
    model: str
    runtime: str
    output: str
    exit_code: int
    duration_ms: int
    command: list[str]
    log_path: str
    response_path: str | None = None
    approximate_cost: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class StageResult:
    stage_name: str
    model: str
    kind: str
    output: str
    exit_code: int
    duration_ms: int
    approximate_cost: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PatternExecutionResult:
    strategy: RoutingStrategy
    final_output: str
    stage_results: list[StageResult] = field(default_factory=list)
    iterations: int | None = None
    approximate_cost: float = 0.0
    shared_context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["strategy"] = self.strategy.value
        return payload


@dataclass(slots=True)
class ModelHealth:
    name: str
    available: bool
    runtime: str
    provider: str
    details: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SessionRecord:
    session_id: str
    request: str
    task_type: str
    strategy: str
    models: list[str]
    mode: str
    status: str
    metadata: dict[str, Any]
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SessionMessage:
    session_id: str
    channel: str
    sender: str
    recipient: str | None
    message_type: str
    content: str
    metadata: dict[str, Any]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RunResult:
    session: SessionRecord
    routing: RoutingDecision
    plan: ExecutionPlan
    executed: bool
    message: str
    execution: PatternExecutionResult | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "session": self.session.to_dict(),
            "routing": self.routing.to_dict(),
            "plan": self.plan.to_dict(),
            "executed": self.executed,
            "message": self.message,
        }
        if self.execution is not None:
            payload["execution"] = self.execution.to_dict()
        return payload
