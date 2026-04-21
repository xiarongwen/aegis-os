from __future__ import annotations

from typing import Any

from .registry import ModelRegistry
from .types import RoutingDecision, RoutingStrategy, TaskType


class TaskRouter:
    def __init__(self, registry: ModelRegistry) -> None:
        self.registry = registry

    def classify_task(self, request: str, context: dict[str, Any] | None = None) -> TaskType:
        ctx = context or {}
        forced = ctx.get("task_type")
        if forced:
            return TaskType(str(forced))
        text = request.lower()
        keyword_groups: list[tuple[TaskType, tuple[str, ...]]] = [
            (TaskType.CODE_REVIEW, ("review", "code review", "审查", "评审", "检查代码", "lgtm")),
            (TaskType.DEBUGGING, ("bug", "debug", "fix", "修复", "报错", "漏洞", "异常", "crash")),
            (TaskType.TESTING, ("test", "测试", "单测", "集成测试", "coverage", "覆盖率")),
            (TaskType.ARCHITECTURE, ("architecture", "设计系统", "架构", "模块设计", "系统设计", "重构方案")),
            (TaskType.REFACTORING, ("refactor", "重构", "cleanup", "整理代码")),
            (TaskType.DOCUMENTATION, ("docs", "documentation", "readme", "文档", "注释")),
            (TaskType.RESEARCH, ("research", "调研", "compare", "方案对比", "可行性")),
        ]
        for task_type, keywords in keyword_groups:
            if any(keyword in text for keyword in keywords):
                return task_type
        return TaskType.CODE_GENERATION

    def estimate_complexity(self, request: str, context: dict[str, Any] | None = None) -> int:
        text = request.lower()
        score = 3
        if len(request) > 60:
            score += 1
        if len(request) > 140:
            score += 1
        hard_keywords = (
            "全量重构",
            "multi-model",
            "多模型",
            "architecture",
            "distributed",
            "迁移",
            "复杂",
            "platform",
            "framework",
            "security",
            "并发",
            "pipeline",
        )
        score += sum(1 for keyword in hard_keywords if keyword in text)
        return max(1, min(score, 10))

    def determine_strategy(
        self,
        task_type: TaskType,
        complexity: int,
        context: dict[str, Any] | None = None,
    ) -> RoutingStrategy:
        ctx = context or {}
        forced = ctx.get("strategy")
        if forced:
            return RoutingStrategy(str(forced))
        if task_type == TaskType.ARCHITECTURE:
            return RoutingStrategy.SINGLE
        if task_type == TaskType.CODE_REVIEW:
            return RoutingStrategy.SWARM
        if task_type == TaskType.TESTING:
            return RoutingStrategy.SWARM
        if task_type == TaskType.DEBUGGING:
            return RoutingStrategy.PIPELINE
        if task_type == TaskType.REFACTORING:
            return RoutingStrategy.PAIR_PROGRAMMING
        if task_type == TaskType.CODE_GENERATION and complexity > 7:
            return RoutingStrategy.PAIR_PROGRAMMING
        return RoutingStrategy.SINGLE

    def select_models(
        self,
        task_type: TaskType,
        strategy: RoutingStrategy,
        context: dict[str, Any] | None = None,
    ) -> list[str]:
        ctx = context or {}
        explicit_models = ctx.get("models")
        if explicit_models:
            names = [item.strip() for item in str(explicit_models).split(",") if item.strip()]
            available = [name for name in names if name in self.registry.names()]
            if available:
                return available

        mode = str(
            ctx.get("mode")
            or self.registry.config.get("models", {}).get("default_strategy")
            or "balanced"
        ).lower()
        selection_rules = {
            "quality": {
                TaskType.ARCHITECTURE: ["claude-opus-4-7"],
                TaskType.CODE_GENERATION: ["claude-sonnet-4-6"],
                TaskType.CODE_REVIEW: ["claude-opus-4-7", "claude-sonnet-4-6", "codex"],
                TaskType.DEBUGGING: ["claude-sonnet-4-6", "codex"],
                TaskType.TESTING: ["claude-sonnet-4-6", "codex"],
                TaskType.REFACTORING: ["claude-sonnet-4-6", "codex"],
            },
            "speed": {
                TaskType.CODE_GENERATION: ["codex"],
                TaskType.TESTING: ["codex", "codex", "codex"],
                TaskType.DEBUGGING: ["codex", "claude-sonnet-4-6"],
                TaskType.CODE_REVIEW: ["codex", "claude-sonnet-4-6"],
            },
            "cost": {
                TaskType.ARCHITECTURE: ["claude-sonnet-4-6"],
                TaskType.CODE_GENERATION: ["codex"],
                TaskType.CODE_REVIEW: ["codex"],
                TaskType.DEBUGGING: ["codex"],
                TaskType.TESTING: ["codex"],
                TaskType.REFACTORING: ["codex"],
            },
            "balanced": {
                TaskType.ARCHITECTURE: ["claude-opus-4-7"],
                TaskType.CODE_GENERATION: ["codex", "claude-sonnet-4-6"]
                if strategy == RoutingStrategy.PAIR_PROGRAMMING
                else ["codex"],
                TaskType.CODE_REVIEW: ["claude-sonnet-4-6", "codex"],
                TaskType.DEBUGGING: ["claude-sonnet-4-6", "codex"],
                TaskType.TESTING: ["codex", "claude-sonnet-4-6"],
                TaskType.REFACTORING: ["codex", "claude-sonnet-4-6"],
                TaskType.DOCUMENTATION: ["claude-sonnet-4-6"],
                TaskType.RESEARCH: ["o3-mini", "claude-sonnet-4-6"],
            },
        }
        choices = selection_rules.get(mode, selection_rules["balanced"]).get(task_type, ["claude-sonnet-4-6"])
        enabled = set(self.registry.bundle.enabled_model_names())
        filtered = [name for name in choices if name in enabled and name in self.registry.names()]
        if filtered:
            return filtered
        fallback = self.registry.available_model_names(names=self.registry.bundle.enabled_model_names())
        if fallback:
            return fallback[:1]
        return self.registry.bundle.enabled_model_names()[:1]

    def calculate_cost(self, task_type: TaskType, models: list[str], complexity: int) -> float:
        base_tokens = {
            TaskType.ARCHITECTURE: 18,
            TaskType.CODE_GENERATION: 10,
            TaskType.CODE_REVIEW: 12,
            TaskType.DEBUGGING: 12,
            TaskType.TESTING: 8,
            TaskType.REFACTORING: 10,
            TaskType.DOCUMENTATION: 6,
            TaskType.RESEARCH: 7,
        }.get(task_type, 8)
        total = 0.0
        for name in models:
            if name not in self.registry.names():
                continue
            spec = self.registry.get(name)
            total += spec.cost_per_1k_tokens * (base_tokens + complexity)
        return round(total, 2)

    def calculate_time(self, strategy: RoutingStrategy, complexity: int, models: list[str]) -> int:
        base = {
            RoutingStrategy.SINGLE: 45,
            RoutingStrategy.PAIR_PROGRAMMING: 120,
            RoutingStrategy.SWARM: 90,
            RoutingStrategy.PIPELINE: 150,
            RoutingStrategy.MOA: 135,
        }.get(strategy, 60)
        modifier = max(0, complexity - 5) * 10
        parallel_discount = 20 if strategy in {RoutingStrategy.SWARM, RoutingStrategy.MOA} and len(models) > 1 else 0
        return max(20, base + modifier - parallel_discount)

    def route(self, request: str, context: dict[str, Any] | None = None) -> RoutingDecision:
        ctx = context or {}
        task_type = self.classify_task(request, ctx)
        complexity = self.estimate_complexity(request, ctx)
        strategy = self.determine_strategy(task_type, complexity, ctx)
        models = self.select_models(task_type, strategy, ctx)
        mode = str(ctx.get("mode") or self.registry.config.get("models", {}).get("default_strategy") or "balanced")
        rationale = [
            f"classified as {task_type.value}",
            f"selected {strategy.value} strategy at complexity {complexity}/10",
            f"picked models {', '.join(models)} for {mode} mode",
        ]
        return RoutingDecision(
            task_type=task_type,
            strategy=strategy,
            models=models,
            mode=mode,
            complexity=complexity,
            estimated_cost=self.calculate_cost(task_type, models, complexity),
            estimated_time_seconds=self.calculate_time(strategy, complexity, models),
            rationale=rationale,
        )
