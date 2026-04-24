from __future__ import annotations

from typing import Any, Callable

from .registry import ModelRegistry
from .types import RoutingDecision, RoutingStrategy, TaskType


class TaskRouter:
    def __init__(
        self,
        registry: ModelRegistry,
        *,
        classifier: Callable[[str, dict[str, Any]], dict[str, Any] | None] | None = None,
    ) -> None:
        self.registry = registry
        self.classifier = classifier

    def validate_request(self, request: str) -> str:
        normalized = request.strip()
        if not normalized:
            raise ValueError("request cannot be empty; describe the coding task you want AEGIS to handle")
        ambiguous_requests = {
            "优化代码",
            "优化一下",
            "改一下",
            "处理一下",
            "做一下",
            "看看代码",
            "帮我看看",
            "完善一下",
        }
        if normalized in ambiguous_requests:
            raise ValueError(
                "request is too ambiguous; specify the code area, target file, or concrete outcome you want"
            )
        return normalized

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
        request_text = str(ctx.get("request_text", "")).lower()
        if task_type == TaskType.CODE_REVIEW and (
            complexity >= 5
            or any(keyword in request_text for keyword in ("安全", "security", "性能", "performance", "可维护性", "tradeoff", "取舍", "多个角度"))
        ):
            return RoutingStrategy.MOA
        if task_type == TaskType.ARCHITECTURE:
            return RoutingStrategy.MOA
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
            if isinstance(explicit_models, list):
                names = [str(item).strip() for item in explicit_models if str(item).strip()]
            else:
                names = [item.strip() for item in str(explicit_models).split(",") if item.strip()]
            available = [name for name in names if name in self.registry.names()]
            if available:
                return available

        if strategy == RoutingStrategy.MOA:
            preferred_order = ["codex", "claude-sonnet-4-6", "claude-opus-4-7", "o3-mini", "local-llm"]
            enabled = set(self.registry.bundle.enabled_model_names())
            selected = [name for name in preferred_order if name in enabled and name in self.registry.names()]
            if selected:
                return selected[:3]

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
        ctx = dict(context or {})
        request = self.validate_request(request)
        ctx = dict(ctx)
        ctx.setdefault("request_text", request)
        advisor_payload: dict[str, Any] | None = None
        if self.classifier is not None and not any(key in ctx for key in ("task_type", "strategy", "models")):
            suggestion = self.classifier(request, ctx)
            if isinstance(suggestion, dict):
                advisor_payload = dict(suggestion)
                for key in ("task_type", "strategy", "models", "mode"):
                    if suggestion.get(key) not in (None, "", []):
                        ctx[key] = suggestion[key]
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
        advisor_rationale = advisor_payload.get("rationale") if isinstance(advisor_payload, dict) else None
        if isinstance(advisor_rationale, list):
            rationale.extend(f"advisor: {str(item)}" for item in advisor_rationale if str(item).strip())
        return RoutingDecision(
            task_type=task_type,
            strategy=strategy,
            models=models,
            mode=mode,
            complexity=complexity,
            estimated_cost=self.calculate_cost(task_type, models, complexity),
            estimated_time_seconds=self.calculate_time(strategy, complexity, models),
            rationale=rationale,
            advisor=advisor_payload,
        )
