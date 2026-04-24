# AEGIS OS 架构重构方案 v2.0

## 多模型协作架构设计

**目标**: 从 "Workflow + Team Pack" 架构重构为 "多模型协作引擎"  
**核心**: 灵活配置多模型、智能分工、编码提效  
**日期**: 2026-04-21

---

## 1. 当前架构问题分析

### 1.1 现有架构 (v1.x)

```
┌─────────────────────────────────────────────────────────────────┐
│                    AEGIS v1.x 架构                               │
│                                                                 │
│   User Request                                                  │
│       │                                                         │
│       ▼                                                         │
│   ┌─────────────┐    L1→L2→L3→L4→L5    ┌─────────────┐        │
│   │ Orchestrator│ ───────────────────→ │   Agents    │        │
│   │  (单模型)    │    强制状态机          │  (静态分配)   │        │
│   └─────────────┘                       └─────────────┘        │
│        │                                    │                   │
│        │      ┌──────────────────────────┐  │                   │
│        └─────→│  Governance (Heavy)      │←─┘                   │
│               │  - Lock files             │                      │
│               │  - Review loops           │                      │
│               │  - State machine          │                      │
│               └──────────────────────────┘                      │
└─────────────────────────────────────────────────────────────────┘

问题:
1. 单模型 orchestrator，无法利用多模型优势
2. 强制 L1-L5 流程，不适合快速编码场景
3. Agents 静态绑定，无法动态路由到最优模型
4. Governance 过重，影响开发效率
```

### 1.2 业界最佳实践

| 框架 | 多模型策略 | 分工模式 | 路由机制 |
|------|-----------|----------|----------|
| **AutoGen** | SelectorGroupChat / Swarm | 角色专业化 | LLM-based 动态选择 / Handoff |
| **CrewAI** | Model 参数配置 | Role-Goal-Backstory | 静态配置 |
| **LangGraph** | Callable model factory | 图节点分发 | State-based 条件路由 |
| **LangChain** | Middleware 动态切换 | 任务类型匹配 | 规则 + LLM 混合 |
| **PydanticAI** | Agent delegation | 父子 Agent | 程序化路由 |

### 1.3 关键洞察

1. **模型专业化**: Claude (深度推理) / Codex (代码生成) / GPT-4 (通用任务)
2. **动态路由**: 根据任务类型、上下文长度、成本约束选择模型
3. **协作模式**: Coder → Reviewer → Fix 的迭代循环
4. **并行化**: 多个子任务分发到不同模型并行执行

---

## 2. 新架构设计

### 2.1 核心概念

```
AEGIS v2.0 核心概念:

┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│  Model Registry (模型注册表)                                         │
│  ─────────────────────────────                                      │
│  • claude-opus-4-7:   深度推理, 复杂架构                             │
│  • claude-sonnet-4-6: 平衡性能, 日常编码                             │
│  • codex:             代码生成, 快速实现                             │
│  • o3-mini:           快速响应, 简单任务                             │
│                                                                     │
│  Task Router (任务路由)                                             │
│  ─────────────────────────────                                      │
│  • Intent Classifier: 识别任务类型 (arch/design/code/review/test)    │
│  • Model Selector:    基于策略选择最优模型                            │
│  • Load Balancer:     并发控制和队列管理                              │
│                                                                     │
│  Collaboration Pattern (协作模式)                                    │
│  ─────────────────────────────────                                  │
│  • Pair Programming:  Coder + Reviewer                              │
│  • Swarm:             多模型并行处理子任务                            │
│  • Pipeline:          顺序依赖的任务链                               │
│  • MoA:               分层聚合多个模型结果                            │
│                                                                     │
│  Session Manager (会话管理)                                          │
│  ─────────────────────────────                                      │
│  • Context sharing:   模型间上下文共享                                │
│  • State persistence: 检查点和恢复                                   │
│  • Message routing:   模型间消息传递                                  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 架构图

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                           AEGIS v2.0 多模型协作架构                            │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                         User Interface                               │    │
│  │                                                                      │    │
│  │   /aegis "实现登录功能"  ──→  Intent Parser                          │    │
│  │   /aegis-config --model claude,codex                                │    │
│  │   /aegis-swarm "生成测试用例"                                        │    │
│  └─────────────────────────────────┬────────────────────────────────────┘    │
│                                    │                                         │
│                                    ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                      Task Router (路由核心)                          │    │
│  │                                                                      │    │
│  │   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐           │    │
│  │   │Task          │   │Model         │   │Strategy      │           │    │
│  │   │Classifier    │──→│Selector      │──→│Executor      │           │    │
│  │   │              │   │              │   │              │           │    │
│  │   │arch/code/test│   │cost/speed/  │   │pair/swarm/   │           │    │
│  │   │              │   │quality      │   │pipeline      │           │    │
│  │   └──────────────┘   └──────────────┘   └──────────────┘           │    │
│  └─────────────────────────────────┬────────────────────────────────────┘    │
│                                    │                                         │
│              ┌─────────────────────┼─────────────────────┐                   │
│              │                     │                     │                   │
│              ▼                     ▼                     ▼                   │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐              │
│  │  Claude Session │  │  Codex Session  │  │  Other Models   │              │
│  │                 │  │                 │  │                 │              │
│  │  • Architecture │  │  • Code Gen     │  │  • o3-mini      │              │
│  │  • Design       │  │  • Quick Fix    │  │  • GPT-4        │              │
│  │  • Complex Logic│  │  • Refactoring  │  │  • Local LLM    │              │
│  │                 │  │                 │  │                 │              │
│  │  Runtime: Claude│  │  Runtime: Codex │  │  Runtime: API   │              │
│  │  Code CLI       │  │  CLI            │  │  / CLI          │              │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘              │
│           │                    │                    │                        │
│           └────────────────────┼────────────────────┘                        │
│                                │                                            │
│                                ▼                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Collaboration Engine (协作引擎)                   │   │
│  │                                                                      │   │
│  │   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐             │   │
│  │   │ Message Bus  │  │ Context Sync │  │ Result Merge │             │   │
│  │   │ (消息总线)    │  │ (上下文同步)  │  │ (结果聚合)   │             │   │
│  │   └──────────────┘  └──────────────┘  └──────────────┘             │   │
│  │                                                                      │   │
│  │   Collaboration Patterns:                                            │   │
│  │   • Pair: Coder(Claude) ⟷ Reviewer(Codex)                           │   │
│  │   • Swarm: [Codex,Codex,Codex] for test cases                       │   │
│  │   • Pipeline: Design → Code → Test → Review                         │   │
│  │   • MoA: [Claude,Codex] → Aggregator(Claude)                        │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                │                                            │
│                                ▼                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Output Consolidator (输出整合)                    │   │
│  │                                                                      │   │
│  │   • Code merge: git-style merge / conflict resolution                │   │
│  │   • Review aggregation: combine multiple reviews                     │   │
│  │   • Quality scoring: coverage, complexity, style                     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 功能模块设计

### 3.1 模型注册表 (Model Registry)

```yaml
# .aegis/models/registry.yml
version: "2.0"

models:
  # Claude 系列
  claude-opus-4-7:
    provider: anthropic
    runtime: claude-code-cli
    capabilities:
      - architecture_design
      - complex_reasoning
      - security_audit
      - long_context
    context_window: 200000
    cost_per_1k_tokens: 0.015
    specialties:
      - system_architecture
      - algorithm_design
      - security_review
    config:
      max_thinking_tokens: 32000
      temperature: 0.7

  claude-sonnet-4-6:
    provider: anthropic
    runtime: claude-code-cli
    capabilities:
      - code_generation
      - refactoring
      - debugging
      - code_review
    context_window: 200000
    cost_per_1k_tokens: 0.003
    specialties:
      - full_stack_development
      - api_design
      - testing
    config:
      temperature: 0.5

  # Codex 系列
  codex:
    provider: openai
    runtime: codex-cli
    capabilities:
      - fast_code_generation
      - quick_fixes
      - boilerplate
      - autocomplete
    context_window: 128000
    cost_per_1k_tokens: 0.001
    specialties:
      - rapid_prototyping
      - syntax_correction
      - simple_tasks
    config:
      temperature: 0.3

  # 其他模型
  o3-mini:
    provider: openai
    runtime: api
    capabilities:
      - fast_response
      - simple_reasoning
    context_window: 64000
    cost_per_1k_tokens: 0.0005
    specialties:
      - quick_questions
      - simple_explanations

  local-llm:
    provider: ollama
    runtime: local
    capabilities:
      - offline_work
      - privacy_sensitive
    context_window: 32000
    cost_per_1k_tokens: 0
    specialties:
      - private_code_review
```

### 3.2 任务路由 (Task Router)

```python
# aegis/router/task_router.py
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel

class TaskType(Enum):
    ARCHITECTURE = "architecture"      # 系统设计
    CODE_GENERATION = "code_gen"       # 代码生成
    CODE_REVIEW = "code_review"        # 代码审查
    DEBUGGING = "debugging"            # 调试
    TESTING = "testing"                # 测试
    REFACTORING = "refactoring"        # 重构
    DOCUMENTATION = "documentation"    # 文档
    RESEARCH = "research"              # 研究

class RoutingStrategy(Enum):
    PAIR_PROGRAMMING = "pair"          # 结对编程
    SWARM = "swarm"                    # 群体协作
    PIPELINE = "pipeline"              # 流水线
    SINGLE = "single"                  # 单一模型
    MOA = "moa"                        # Mixture of Agents

class TaskRouter:
    """智能任务路由器"""

    def __init__(self, model_registry, config):
        self.models = model_registry
        self.config = config

    async def classify_task(self, request: str, context: dict) -> TaskType:
        """使用轻量级分类器识别任务类型"""
        # 可以使用 o3-mini 或本地规则引擎
        classifier_prompt = f"""
        Classify the following coding request into one of:
        - architecture: System design, module structure, data flow
        - code_gen: Implement features, write functions
        - code_review: Review existing code for issues
        - debugging: Find and fix bugs
        - testing: Write tests, test coverage
        - refactoring: Restructure code without changing behavior
        - documentation: Write docs, comments
        - research: Explore solutions, compare approaches

        Request: {request}
        Context: {context}

        Response format: <task_type>
        """
        # 使用 o3-mini 进行快速分类
        result = await self.models["o3-mini"].complete(classifier_prompt)
        return TaskType(result.strip())

    def select_model(self, task_type: TaskType, constraints: dict) -> List[str]:
        """基于任务类型和约束选择模型"""
        strategy = constraints.get("strategy", "cost_optimized")

        selection_rules = {
            "quality_optimized": {
                TaskType.ARCHITECTURE: ["claude-opus-4-7"],
                TaskType.CODE_GENERATION: ["claude-sonnet-4-6"],
                TaskType.CODE_REVIEW: ["claude-opus-4-7", "claude-sonnet-4-6"],
                TaskType.DEBUGGING: ["claude-sonnet-4-6"],
                TaskType.TESTING: ["codex", "claude-sonnet-4-6"],
            },
            "cost_optimized": {
                TaskType.ARCHITECTURE: ["claude-sonnet-4-6"],
                TaskType.CODE_GENERATION: ["codex"],
                TaskType.CODE_REVIEW: ["codex"],
                TaskType.DEBUGGING: ["codex"],
                TaskType.TESTING: ["codex"],
            },
            "speed_optimized": {
                TaskType.CODE_GENERATION: ["codex"],
                TaskType.TESTING: ["codex", "codex", "codex"],  # Swarm
            }
        }

        return selection_rules.get(strategy, {}).get(task_type, ["claude-sonnet-4-6"])

    def determine_strategy(self, task_type: TaskType, complexity: int) -> RoutingStrategy:
        """确定协作策略"""
        strategy_matrix = {
            TaskType.ARCHITECTURE: RoutingStrategy.SINGLE,
            TaskType.CODE_GENERATION: RoutingStrategy.PAIR_PROGRAMMING if complexity > 7 else RoutingStrategy.SINGLE,
            TaskType.CODE_REVIEW: RoutingStrategy.SWARM,  # 多个模型同时审查
            TaskType.TESTING: RoutingStrategy.SWARM,
            TaskType.DEBUGGING: RoutingStrategy.PIPELINE,  # Analyze → Fix → Verify
        }
        return strategy_matrix.get(task_type, RoutingStrategy.SINGLE)

    async def route(self, request: str, context: dict) -> RoutingDecision:
        """主路由函数"""
        task_type = await self.classify_task(request, context)
        complexity = self.estimate_complexity(request)
        strategy = self.determine_strategy(task_type, complexity)
        models = self.select_model(task_type, context.get("constraints", {}))

        return RoutingDecision(
            task_type=task_type,
            strategy=strategy,
            models=models,
            estimated_cost=self.calculate_cost(models, task_type),
            estimated_time=self.calculate_time(models, strategy)
        )
```

### 3.3 协作模式 (Collaboration Patterns)

```python
# aegis/collaboration/patterns.py

class PairProgrammingPattern:
    """
    结对编程模式: Coder + Reviewer 交替工作

    ┌─────────────────────────────────────────┐
    │  User Request                           │
    │       │                                 │
    │       ▼                                 │
    │  ┌─────────┐   Code    ┌─────────┐    │
    │  │  Coder  │ ─────────→│ Reviewer│    │
    │  │ (Codex) │           │(Claude) │    │
    │  └────┬────│           └────┬────│    │
    │       │      Feedback        │        │
    │       └──────────────────────┘        │
    │              Loop (max 3)              │
    └─────────────────────────────────────────┘
    """

    async def execute(self, task: Task, coder_model: str, reviewer_model: str) -> Result:
        coder = self.models[coder_model]
        reviewer = self.models[reviewer_model]

        # 初始代码生成
        code = await coder.complete(f"Generate code for: {task.description}")

        for iteration in range(self.max_iterations):
            # 审查
            review = await reviewer.complete(
                f"Review this code for bugs, style, and best practices:\n{code}"
            )

            if "LGTM" in review or "APPROVE" in review:
                break

            # 修复
            code = await coder.complete(
                f"Fix these issues in the code:\nReview: {review}\n\nCode:\n{code}"
            )

        return Result(code=code, review=review, iterations=iteration + 1)


class SwarmPattern:
    """
    群体模式: 多个模型并行处理子任务

    ┌──────────────────────────────────────────┐
    │  User: "Generate test cases"             │
    │       │                                  │
    │       ▼                                  │
    │  ┌──────────────┐                        │
    │  │ Task Splitter│                        │
    │  │ (Claude)     │                        │
    │  └──────┬───────┘                        │
    │         │                                │
    │    ┌────┼────┬────────┐                 │
    │    ▼    ▼    ▼        ▼                 │
    │ ┌───┐┌───┐┌───┐   ┌───┐                │
    │ │W1 ││W2 ││W3 │...│Wn │  Parallel       │
    │ │(C)││(C)││(C)│   │(C)│  (Codex)        │
    │ └───┘└───┘└───┘   └───┘                │
    │    │    │    │       │                 │
    │    └────┴────┴───────┘                 │
    │         │                                │
    │         ▼                                │
    │  ┌──────────────┐                        │
    │  │ Aggregator   │                        │
    │  │ (Claude)     │                        │
    │  └──────────────┘                        │
    └──────────────────────────────────────────┘
    """

    async def execute(self, task: Task, worker_model: str, count: int) -> Result:
        # 使用 Claude 分割任务
        splitter = self.models["claude-sonnet-4-6"]
        subtasks = await splitter.complete(
            f"Split this task into {count} independent subtasks:\n{task.description}"
        )

        # 并行执行
        workers = [self.models[worker_model] for _ in range(count)]
        results = await asyncio.gather(*[
            worker.complete(subtask) for worker, subtask in zip(workers, subtasks)
        ])

        # 聚合结果
        aggregator = self.models["claude-sonnet-4-6"]
        final = await aggregator.complete(
            f"Combine these results into a cohesive output:\n{chr(10).join(results)}"
        )

        return Result(output=final, subresults=results)


class PipelinePattern:
    """
    流水线模式: 顺序依赖的任务链

    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
    │  Design  │───→│  Code    │───→│  Test    │───→│  Review  │
    │ (Claude) │    │ (Codex)  │    │ (Codex)  │    │ (Claude) │
    └──────────┘    └──────────┘    └──────────┘    └──────────┘
    """

    async def execute(self, task: Task, stages: List[Stage]) -> Result:
        context = task.description
        stage_results = []

        for stage in stages:
            model = self.models[stage.model]
            result = await model.complete(
                f"{stage.prompt}\n\nPrevious context:\n{context}"
            )
            stage_results.append(StageResult(stage=stage.name, output=result))
            context = result  # 传递给下一阶段

        return Result(stages=stage_results, final=stage_results[-1].output)


class MoAPattern:
    """
    Mixture of Agents 模式: 分层聚合

    Layer 1: [Claude, Codex, GPT-4] → 各自生成结果
    Layer 2: [Aggregator] → 综合所有结果
    """

    async def execute(self, task: Task, layer1_models: List[str]) -> Result:
        # Layer 1: 多个模型并行
        layer1_results = await asyncio.gather(*[
            self.models[m].complete(task.description) for m in layer1_models
        ])

        # Layer 2: 聚合
        aggregator_prompt = f"""
        Given these solutions from different experts:
        {chr(10).join(f"Expert {i+1}: {r}" for i, r in enumerate(layer1_results))}

        Synthesize the best approach, combining strengths and addressing weaknesses.
        """
        final = await self.models["claude-opus-4-7"].complete(aggregator_prompt)

        return Result(
            layer1_results=layer1_results,
            final=final,
            confidence=self.calculate_confidence(layer1_results)
        )
```

### 3.4 会话管理 (Session Manager)

```python
# aegis/session/manager.py

class MultiModelSession:
    """
    多模型会话管理器
    管理多个模型的上下文共享和消息传递
    """

    def __init__(self, session_id: str, models: List[str]):
        self.session_id = session_id
        self.models = {m: self.create_runtime(m) for m in models}
        self.shared_context = SharedContext()
        self.message_bus = MessageBus()
        self.checkpointer = Checkpointer()

    async def run(self, task: str, pattern: CollaborationPattern):
        """执行协作任务"""

        # 1. 创建检查点
        await self.checkpointer.save(self.session_id, "init", {
            "task": task,
            "models": list(self.models.keys()),
            "pattern": pattern.name
        })

        # 2. 设置消息监听
        for model_name, runtime in self.models.items():
            self.message_bus.subscribe(f"{self.session_id}/{model_name}",
                                        lambda msg, m=model_name: self.handle_message(m, msg))

        # 3. 执行协作模式
        result = await pattern.execute(task, self.models)

        # 4. 保存最终检查点
        await self.checkpointer.save(self.session_id, "complete", {
            "result": result,
            "context": self.shared_context.export()
        })

        return result

    def handle_message(self, model_name: str, message: Message):
        """处理模型间消息"""
        if message.type == MessageType.CODE_SHARE:
            # 共享代码给所有模型
            self.shared_context.update("shared_code", message.content)
            for other_model in self.models:
                if other_model != model_name:
                    self.message_bus.publish(
                        f"{self.session_id}/{other_model}",
                        Message(type=MessageType.CODE_UPDATE, content=message.content)
                    )

        elif message.type == MessageType.REQUEST_REVIEW:
            # 请求代码审查
            self.message_bus.publish(
                f"{self.session_id}/claude-sonnet-4-6",
                Message(type=MessageType.REVIEW_TASK, content=message.content)
            )

        elif message.type == MessageType.REVIEW_FEEDBACK:
            # 反馈给原模型
            original_model = message.metadata.get("requester")
            self.message_bus.publish(
                f"{self.session_id}/{original_model}",
                Message(type=MessageType.FEEDBACK, content=message.content)
            )
```

---

## 4. 配置系统

### 4.1 用户配置

```yaml
# .aegis/config.yml (v2.0)
version: "2.0"

# 模型配置
models:
  enabled:
    - claude-opus-4-7
    - claude-sonnet-4-6
    - codex

  default_strategy: "balanced"  # quality | speed | cost | balanced

  # 模型特定配置
  overrides:
    claude-opus-4-7:
      max_budget_per_task: 5.00  # USD
      temperature: 0.7

    codex:
      max_budget_per_task: 1.00
      temperature: 0.3

# 协作模式默认配置
collaboration:
  pair_programming:
    max_iterations: 3
    coder_model: "codex"
    reviewer_model: "claude-sonnet-4-6"

  swarm:
    default_workers: 3
    worker_model: "codex"
    aggregator_model: "claude-sonnet-4-6"

  pipeline:
    stages:
      - name: "design"
        model: "claude-opus-4-7"
        condition: "complexity > 7"
      - name: "code"
        model: "codex"
      - name: "test"
        model: "codex"
      - name: "review"
        model: "claude-sonnet-4-6"

# 路由规则
routing:
  # 任务类型到协作策略的映射
  task_patterns:
    architecture: { strategy: "single", model: "claude-opus-4-7" }
    feature_impl: { strategy: "pair", priority: "speed" }
    bug_fix: { strategy: "pipeline", stages: ["analyze", "fix", "verify"] }
    code_review: { strategy: "swarm", workers: 2 }
    test_gen: { strategy: "swarm", workers: 3 }
    refactoring: { strategy: "pair" }

  # 上下文长度阈值
  context_thresholds:
    use_long_context_model: 100000  # tokens
    truncate_context: 150000

# 成本控制
cost_control:
  daily_budget: 50.00  # USD
  per_task_budget: 10.00
  alerts:
    - at: 80%  # 预算使用 80% 时警告
    - at: 100%  # 预算用完时停止

# 性能优化
performance:
  parallel_execution: true
  max_concurrent_models: 3
  cache_responses: true
  cache_ttl: 3600  # seconds
```

### 4.2 动态配置切换

```bash
# 快速切换配置模式
/aegis-mode quality    # 质量优先：使用 Claude Opus
/aegis-mode speed      # 速度优先：使用 Codex
/aegis-mode cost       # 成本优先：使用 cheapest models
/aegis-mode custom --models claude,codex --strategy pair

# 查看当前配置
/aegis-config show

# 查看成本统计
/aegis-cost today
/aegis-cost this-week
```

---

## 5. CLI 设计

### 5.1 新命令结构

```bash
# 主要入口
aegis <request>                    # 使用默认配置
aegis --mode quality "实现登录功能"  # 指定质量模式
aegis --models claude,codex        # 指定模型组合

# 子命令
aegis run <request>                # 运行任务
aegis router dry-run <request>     # 预览路由决策
aegis session list                 # 列出活跃会话
aegis session attach <id>          # 附加到会话
aegis models list                  # 列出可用模型
aegis models test <name>           # 测试模型连接
aegis config set <key> <value>     # 设置配置
aegis cost report                  # 成本报告
aegis collaboration pair <task>    # 强制使用结对模式
aegis collaboration swarm <task>   # 强制使用群体模式
```

### 5.2 交互式 TUI

```
┌─────────────────────────────────────────────────────────────────────┐
│ AEGIS v2.0 - Multi-Model Coding Assistant                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│ Active Session: sess-20260421-001                                   │
│ Mode: Balanced | Budget: $12.50 / $50.00                            │
│                                                                     │
│ ┌─ Active Models ─────────────────────────────────────────────────┐ │
│ │ ⬤ Claude Opus (Architecture)  [████████████████░░░░] 80%       │ │
│ │ ⬤ Codex (Code Generation)     [████████████░░░░░░░░] 60%       │ │
│ │ ○ o3-mini (Classifier)        [░░░░░░░░░░░░░░░░░░░░] Idle      │ │
│ └──────────────────────────────────────────────────────────────────┘ │
│                                                                     │
│ ┌─ Current Task ──────────────────────────────────────────────────┐ │
│ │ Task: Implement user authentication                               │ │
│ │ Stage: Code Review (2/4)                                          │ │
│ │ Models: [Claude reviewing Codex output]                           │ │
│ │ Progress: [████████████████░░░░░░░░░░░░░░░░░░░░░░░░] 40%        │ │
│ └──────────────────────────────────────────────────────────────────┘ │
│                                                                     │
│ ┌─ Live Output ───────────────────────────────────────────────────┐ │
│ │ [Claude] Reviewing auth_service.py...                             │ │
│ │ [Claude] Found 2 issues:                                          │ │
│ │          - Line 15: SQL injection risk                            │ │
│ │          - Line 42: Missing input validation                      │ │
│ │ [Codex]  Fixing issues...                                         │ │
│ └──────────────────────────────────────────────────────────────────┘ │
│                                                                     │
│ [q]uit [p]ause [c]ancel [d]etails [r]eplay [s]witch-model          │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 6. 典型使用场景

### 6.1 场景 1: 快速 Bug 修复

```bash
$ aegis "修复登录功能的 SQL 注入漏洞"

# 路由决策:
# - Task Type: DEBUGGING
# - Strategy: PIPELINE
# - Models: [claude-sonnet-4-6 → codex → claude-sonnet-4-6]
# - Pipeline: Analyze → Fix → Verify

# 执行流程:
# 1. Claude 分析代码，定位漏洞
# 2. Codex 生成修复代码
# 3. Claude 验证修复，检查边界情况

# 输出:
# ✅ 已修复 auth_service.py:15
# ✅ 已添加参数化查询
# ✅ 已通过安全审查
# 💰 成本: $0.45 | ⏱ 时间: 45s
```

### 6.2 场景 2: 新功能实现

```bash
$ aegis --mode quality "设计并实现用户权限系统"

# 路由决策:
# - Task Type: ARCHITECTURE + CODE_GENERATION
# - Strategy: PIPELINE with MULTI_MODEL
# - Models: [claude-opus-4-7 → codex → codex(swarm) → claude-sonnet-4-6]

# 执行流程:
# 1. Claude Opus: 设计权限模型架构
# 2. Claude Sonnet: 生成核心接口
# 3. Codex (swarm): 并行实现各模块
#    - Worker 1: 用户管理
#    - Worker 2: 角色管理
#    - Worker 3: 权限验证
# 4. Codex: 生成测试用例
# 5. Claude Sonnet: 代码审查

# 输出:
# 📁 已生成文件:
#    - src/auth/permission_model.py
#    - src/auth/user_manager.py
#    - src/auth/role_manager.py
#    - src/auth/permission_checker.py
#    - tests/test_permission_system.py
# ✅ 所有测试通过
# ✅ 代码审查通过
# 💰 成本: $8.50 | ⏱ 时间: 3m 20s
```

### 6.3 场景 3: 代码审查

```bash
$ aegis collaboration swarm "审查 src/payment/ 目录"

# 路由决策:
# - Task Type: CODE_REVIEW
# - Strategy: SWARM
# - Models: [claude-opus-4-7, claude-sonnet-4-6, codex]

# 执行流程:
# 1. 三个模型并行审查不同方面:
#    - Claude Opus: 安全审查
#    - Claude Sonnet: 架构审查
#    - Codex: 风格和最佳实践
# 2. 聚合结果，去除重复
# 3. 按严重程度排序

# 输出:
# 🔍 代码审查报告 (3 个模型聚合)
# ─────────────────────────────────
# 🔴 严重: 2 个安全漏洞
#    - payment_gateway.py:78 (Claude Opus)
#    - transaction.py:134 (Claude Opus)
#
# 🟡 警告: 5 个架构问题
#    - 缺少异常处理 (Claude Sonnet)
#    - 建议提取公共逻辑 (Claude Sonnet)
#
# 🟢 建议: 8 个风格优化
#    - 变量命名 (Codex)
#    - 注释完善 (Codex)
#
# 💰 成本: $2.30 | ⏱ 时间: 1m 15s
```

### 6.4 场景 4: 强制结对编程

```bash
$ aegis collaboration pair "实现 JWT 认证中间件"

# 强制使用 Pair Programming 模式

# 执行流程:
# Round 1:
#   Coder (Codex): 生成初始实现
#   Reviewer (Claude): 发现 3 个问题
# Round 2:
#   Coder (Codex): 修复问题
#   Reviewer (Claude): 发现 1 个新问题
# Round 3:
#   Coder (Codex): 最终修复
#   Reviewer (Claude): LGTM ✅

# 输出:
# ✅ 结对编程完成 (3 轮迭代)
# 📁 src/middleware/jwt_auth.py
# 📝 Review History: .aegis/reviews/jwt_auth.md
# 💰 成本: $1.80 | ⏱ 时间: 2m 10s
```

---

## 7. 实施路线图

### Phase 1: 核心重构 (Week 1-2)
- [ ] 创建 Model Registry 模块
- [ ] 实现 Task Router (分类器 + 选择器)
- [ ] 重构 Runtime Bridge 支持多模型并发
- [ ] 基础 CLI 命令重构

### Phase 2: 协作模式 (Week 3-4)
- [ ] 实现 Pair Programming Pattern
- [ ] 实现 Swarm Pattern
- [ ] 实现 Pipeline Pattern
- [ ] 实现 MoA Pattern
- [ ] Session Manager 和消息总线

### Phase 3: 配置与优化 (Week 5-6)
- [ ] 新配置系统 (.aegis/config.yml v2)
- [ ] 成本追踪和控制
- [ ] 性能优化 (缓存、并行)
- [ ] 动态模型切换

### Phase 4: 用户体验 (Week 7-8)
- [ ] 交互式 TUI
- [ ] 实时协作可视化
- [ ] 成本报告和分析
- [ ] 文档和示例

### Phase 5: 高级功能 (Week 9-10)
- [ ] 自定义模型接入 (Local LLM)
- [ ] 团队协作模式
- [ ] 学习优化 (根据历史优化路由)
- [ ] IDE 插件

---

## 8. 与现有功能的取舍

### 8.1 保留并增强

| 功能 | v1.x 状态 | v2.0 规划 |
|------|-----------|-----------|
| Model Registry | 简单配置 | ✅ 增强为能力注册表 |
| Bridge Mode | tmux | ✅ 重构为多模型 Runtime Bridge |
| Session 管理 | 基础 | ✅ 增强为多模型会话 |
| Cost 追踪 | 无 | ✅ 新增完整成本控制 |

### 8.2 简化或移除

| 功能 | v1.x 状态 | v2.0 规划 |
|------|-----------|-----------|
| L1-L5 强制流程 | 核心 | ⚠️ 变为可选模式 (pipeline) |
| Lock Files | 核心 | ⚠️ 简化为轻量 checkpoint |
| Team Pack | 核心 | ⚠️ 迁移为协作模式配置 |
| Governance | 重量级 | ⚠️ 可配置级别 |
| Evolution | 存在 | ❌ 移除 (v2.1 考虑) |
| Nightly Schedule | 存在 | ❌ 移除 |

### 8.3 新增核心功能

- 多模型动态路由
- 协作模式引擎
- 智能任务分类
- 实时成本追踪
- 模型性能分析

---

## 9. 技术架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         AEGIS v2.0 Stack                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Presentation Layer                                                 │
│  ──────────────────                                                 │
│  • CLI (Rich/Click)                                                 │
│  • TUI (Textual)                                                    │
│  • API (FastAPI - future)                                           │
│                                                                     │
│  Orchestration Layer                                                │
│  ────────────────────                                               │
│  • Task Router                                                      │
│  • Collaboration Engine                                             │
│  • Session Manager                                                  │
│  • Cost Controller                                                  │
│                                                                     │
│  Model Runtime Layer                                                │
│  ─────────────────────                                              │
│  • Claude Code Adapter                                              │
│  • Codex CLI Adapter                                                │
│  • OpenAI API Adapter                                               │
│  • Local LLM Adapter (Ollama)                                       │
│                                                                     │
│  Infrastructure Layer                                               │
│  ─────────────────────                                              │
│  • Message Bus (Redis/内置)                                          │
│  • Checkpointer (SQLite)                                            │
│  • Cache (Redis/Disk)                                               │
│  • Config Store (YAML)                                              │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 10. 预期效果

### 10.1 编码效率提升

| 指标 | v1.x | v2.0 目标 | 提升 |
|------|------|-----------|------|
| 简单功能实现 | 5 min | 2 min | **2.5x** |
| 复杂功能实现 | 30 min | 10 min | **3x** |
| Bug 修复 | 10 min | 3 min | **3.3x** |
| 代码审查 | 15 min | 2 min | **7.5x** |
| 测试生成 | 20 min | 3 min | **6.7x** |

### 10.2 成本优化

- **智能路由**: 简单任务使用低成本模型 (Codex)，复杂任务使用高质量模型 (Claude)
- **预算控制**: 实时监控和告警
- **并行优化**: 减少总体执行时间

### 10.3 灵活性

- 支持 5+ 种协作模式
- 支持自定义模型接入
- 支持动态配置切换

---

## 附录

### A. 模型对比参考

| 模型 | 强项 | 弱项 | 适用场景 | 成本 |
|------|------|------|----------|------|
| Claude Opus 4.7 | 深度推理、架构 | 速度、成本 | 架构设计、安全审查 | $$$$ |
| Claude Sonnet 4.6 | 平衡 | 极端复杂任务 | 日常开发、代码审查 | $$ |
| Codex | 速度、代码生成 | 复杂推理 | 快速实现、原型 | $ |
| o3-mini | 响应快、便宜 | 能力有限 | 分类、简单任务 | $ |
| GPT-4 | 通用能力 | 代码不如 Claude | 一般性任务 | $$ |

### B. 协作模式选择指南

| 场景 | 推荐模式 | 理由 |
|------|----------|------|
| 新功能实现 | Pipeline | 结构化流程确保质量 |
| Bug 修复 | Pair | 快速迭代验证 |
| 代码审查 | Swarm | 多视角全面检查 |
| 架构设计 | Single (Claude Opus) | 需要深度思考 |
| 测试生成 | Swarm | 并行覆盖更多场景 |
| 重构 | Pair | 保持行为不变 |

---

*重构方案设计: 2026-04-21*  
*基于 AutoGen, CrewAI, LangGraph, PydanticAI 研究*
