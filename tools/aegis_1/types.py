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


class Strategy(str, Enum):
    SINGLE = "single"
    PAIR = "pair"
    SWARM = "swarm"
    PIPELINE = "pipeline"
    MOA = "moa"


class RunStatus(str, Enum):
    PLANNED = "planned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RECOVERED = "recovered"


@dataclass(slots=True)
class RouteDecision:
    task_type: TaskType
    strategy: Strategy
    complexity: int
    mode: str
    rationale: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["task_type"] = self.task_type.value
        payload["strategy"] = self.strategy.value
        return payload


@dataclass(slots=True)
class RoleSpec:
    name: str
    purpose: str
    default_model: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RunStep:
    name: str
    role: str
    kind: str
    model: str
    prompt: str
    status: str = "queued"
    summary: str = ""
    depends_on: list[str] = field(default_factory=list)
    group: str | None = None
    attempt: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RunPlan:
    strategy: Strategy
    steps: list[RunStep]
    roles: list[RoleSpec]
    models: list[str]
    mode: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy.value,
            "steps": [step.to_dict() for step in self.steps],
            "roles": [role.to_dict() for role in self.roles],
            "models": self.models,
            "mode": self.mode,
        }


@dataclass(slots=True)
class SessionRecord:
    session_id: str
    request: str
    task_type: str
    strategy: str
    mode: str
    status: str
    plan_json: dict[str, Any]
    metadata: dict[str, Any]
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RunEvent:
    event_id: int | None
    session_id: str
    event_type: str
    summary: str
    detail: str = ""
    stage_name: str | None = None
    role: str | None = None
    model: str | None = None
    status: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
