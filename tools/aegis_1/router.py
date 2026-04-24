from __future__ import annotations

from typing import Any

from .types import RouteDecision, Strategy, TaskType


AMBIGUOUS_REQUESTS = {
    "优化代码",
    "优化一下",
    "改一下",
    "处理一下",
    "做一下",
    "看看代码",
    "帮我看看",
    "完善一下",
}


class IntentRouter:
    def validate(self, request: str) -> str:
        normalized = request.strip()
        if not normalized:
            raise ValueError("request cannot be empty; describe the coding task for AEGIS 1.0")
        if normalized in AMBIGUOUS_REQUESTS:
            raise ValueError("request is too ambiguous; name the target module, file, bug, or desired outcome")
        if len(normalized) > 8000:
            raise ValueError("request is too long; summarize the task and reference files instead")
        return normalized

    def classify(self, request: str, context: dict[str, Any] | None = None) -> TaskType:
        forced = (context or {}).get("task_type")
        if forced:
            return TaskType(str(forced))
        text = request.lower()
        groups: list[tuple[TaskType, tuple[str, ...]]] = [
            (TaskType.CODE_REVIEW, ("review", "code review", "审查", "评审", "检查代码", "lgtm")),
            (TaskType.DEBUGGING, ("bug", "debug", "fix", "修复", "报错", "漏洞", "异常", "crash")),
            (TaskType.TESTING, ("test", "测试", "单测", "集成测试", "coverage", "覆盖率")),
            (TaskType.ARCHITECTURE, ("architecture", "架构", "模块设计", "系统设计", "重构方案")),
            (TaskType.REFACTORING, ("refactor", "重构", "cleanup", "整理代码")),
            (TaskType.DOCUMENTATION, ("docs", "documentation", "readme", "文档", "注释")),
            (TaskType.RESEARCH, ("research", "调研", "compare", "方案对比", "可行性")),
        ]
        for task_type, keywords in groups:
            if any(keyword in text for keyword in keywords):
                return task_type
        return TaskType.CODE_GENERATION

    def complexity(self, request: str) -> int:
        text = request.lower()
        score = 3
        if len(request) > 80:
            score += 1
        if len(request) > 180:
            score += 1
        hard = ("多 agent", "多agent", "multi-agent", "多模型", "multi-model", "architecture", "架构", "迁移", "复杂", "并发", "pipeline", "security")
        score += sum(1 for keyword in hard if keyword in text)
        return max(1, min(score, 10))

    def strategy_for(self, task_type: TaskType, complexity: int, context: dict[str, Any] | None = None) -> Strategy:
        forced = (context or {}).get("strategy")
        if forced:
            return Strategy(str(forced))
        if task_type == TaskType.DEBUGGING:
            return Strategy.PIPELINE
        if task_type == TaskType.REFACTORING:
            return Strategy.PAIR
        if task_type in {TaskType.TESTING, TaskType.CODE_REVIEW}:
            return Strategy.SWARM
        if task_type == TaskType.ARCHITECTURE and complexity >= 6:
            return Strategy.MOA
        if task_type == TaskType.CODE_GENERATION and complexity >= 7:
            return Strategy.PAIR
        return Strategy.SINGLE

    def route(self, request: str, context: dict[str, Any] | None = None) -> RouteDecision:
        ctx = context or {}
        normalized = self.validate(request)
        task_type = self.classify(normalized, ctx)
        complexity = self.complexity(normalized)
        strategy = self.strategy_for(task_type, complexity, ctx)
        mode = str(ctx.get("mode") or "balanced")
        return RouteDecision(
            task_type=task_type,
            strategy=strategy,
            complexity=complexity,
            mode=mode,
            rationale=[
                f"classified as {task_type.value}",
                f"selected {strategy.value} at complexity {complexity}/10",
                f"using {mode} mode",
            ],
        )
