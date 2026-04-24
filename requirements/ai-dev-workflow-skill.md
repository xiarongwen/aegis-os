# AI 标准开发工作流 Skill — 需求文档

> 版本: v1.0
> 日期: 2026-04-21
> 状态: Draft

---

# 第一部分：产品需求文档 (PRD)

## 1. 产品概述

### 1.1 产品名称
**DevFlow** — AI 标准开发工作流 Skill

### 1.2 一句话描述
一个 Claude Code Skill，通过编排 Claude 与 Codex 在不同阶段的角色分工，实现标准化的软件开发生命周期管理，包含「超级开发模式」和「抛光模式」两大工作流。

### 1.3 核心价值主张

- **解决长对话遗忘问题**: AI 在多轮对话中容易偏离初始目标，标准化工作流确保每个阶段目标明确
- **角色专业化**: Claude 负责思考、规划、审查；Codex 负责执行、编码、修复，各尽其能
- **质量内建**: 通过 Guard Rubric 和 Polish Checklist 将质量检查嵌入流程，而非事后补救
- **模式自适应**: 根据任务类型和当前状态自动推荐或切换工作流模式

### 1.4 目标用户

- 使用 Claude Code 进行日常开发的软件工程师
- 需要代码审查和质量把控的技术负责人
- 希望通过 AI 提升开发效率但担心质量下降的团队

---

## 2. 用户故事与场景

### 2.1 用户故事

**US-1: 新功能开发**
> 作为开发者，我能够通过一条命令启动「超级开发模式」，让 AI 自动完成从需求分析到代码实现的完整流程，我只需在关键决策点确认。

**US-2: 代码抛光**
> 作为开发者，我能够在代码初稿完成后启动「抛光模式」，让 AI 对代码进行深度优化，包括类型完善、错误处理、架构改进等。

**US-3: 质量评分**
> 作为技术负责人，我能够查看 Guard Rubric 对代码的量化评分，了解代码在多个维度的质量表现。

**US-4: 自定义规则**
> 作为团队负责人，我能够自定义 Polish Checklist 和 Guard Rubric 的检查项，以适配团队的技术规范。

**US-5: 模式切换建议**
> 作为开发者，我能够在 Super Dev 和 Polish 模式之间灵活切换，系统会根据当前状态给出切换建议。

### 2.2 典型使用场景

| 场景 | 推荐模式 | 触发方式 | 预期输出 |
|------|---------|---------|---------|
| 从零开始实现新功能 | Super Dev | `/devflow build "实现用户认证"` | 完整功能代码 + 测试 |
| 已有代码需要优化 | Polish | `/devflow polish` | 优化后的代码 + 评分报告 |
| 代码审查 | Polish (Guard) | `/devflow review` | 审查报告 + 评分 |
| Bug 修复 | Super Dev (Fix) | `/devflow fix "修复空指针"` | 修复后的代码 |
| 技术方案设计 | Super Dev (Plan) | `/devflow plan "设计缓存方案"` | 技术方案文档 |

---

## 3. 功能需求

### 3.1 超级开发模式 (Super Dev Mode)

#### 3.1.1 概述
完整功能开发工作流，覆盖从需求分析到代码合并的全生命周期。

#### 3.1.2 角色定义

| 角色 | AI 模型 | 职责 | 输入 | 输出 |
|------|--------|------|------|------|
| **Planner** | Claude | 需求分析、方案设计、任务拆解 | 用户原始需求 | 技术方案、任务列表、接口定义 |
| **Coder** | Codex | 代码编写、核心实现、单元测试 | 技术方案、任务列表 | 可运行代码、测试用例 |
| **Reviewer** | Claude | 代码审查、质量评估、问题识别 | 代码实现、技术方案 | 审查意见、问题列表、改进建议 |
| **Fixer** | Codex | 代码修改、快速修复、重构 | 审查意见、原代码 | 修复后的代码 |

#### 3.1.3 流程定义

```
PLAN → BUILD → REVIEW → FIX → MERGE
  ↑                      │
  └──────────────────────┘ (循环最多 3 轮)
```

**阶段详述：**

1. **PLAN (规划)**
   - Planner 分析用户需求
   - 输出技术方案文档（架构决策、数据流、接口契约）
   - 输出任务拆解清单（可执行的子任务）
   - 用户确认或调整方案

2. **BUILD (构建)**
   - Coder 按任务清单逐一实现
   - 每完成一个子任务提交 checkpoint
   - 自动生成单元测试
   - 输出可编译/运行的代码

3. **REVIEW (审查)**
   - Reviewer 对代码进行全面审查
   - 检查项包括：功能正确性、代码风格、安全漏洞、性能问题
   - 输出审查报告，标注严重级别（Blocker / Critical / Minor）

4. **FIX (修复)**
   - Fixer 根据审查意见修复代码
   - 若审查意见中包含架构级问题，返回 PLAN 阶段
   - 每轮修复后更新审查状态

5. **MERGE (合并)**
   - 审查通过后，生成最终代码
   - 输出变更摘要（CHANGELOG）
   - 提供 git diff 预览

#### 3.1.4 循环机制

- REVIEW → FIX 最多循环 3 轮
- 若 3 轮后仍有未解决的 Blocker 级问题，暂停并交由用户决策
- 每轮循环需记录 diff 和审查意见变化

#### 3.1.5 验收标准

- [ ] 用户输入自然语言需求后，系统在 2 分钟内输出技术方案
- [ ] 代码实现能够通过基本编译/语法检查
- [ ] 审查阶段能够识别至少 80% 的明显代码问题
- [ ] 3 轮修复循环内，Blocker 级问题清零率 > 90%
- [ ] 最终输出包含完整的 git diff 和 CHANGELOG

---

### 3.2 抛光模式 (Polish Mode)

#### 3.2.1 概述
针对已有代码的深度优化工作流，专注于代码质量提升而非功能开发。

#### 3.2.2 角色定义

| 角色 | AI 模型 | 职责 | 输入 | 输出 |
|------|--------|------|------|------|
| **Architect** | Claude | 架构设计、技术选型、核心决策 | 现有代码、优化目标 | 架构改进方案、重构建议 |
| **Polisher** | Codex | 代码优化、类型完善、错误处理 | 代码、改进方案 | 优化后的代码 |
| **Guard** | Claude | 检查、评估、最终把关 | 优化后的代码 | 质量评分、通过/不通过 verdict |

#### 3.2.3 流程定义

```
ARCHITECT → POLISH → GUARD
              ↑
              └──── (不通过则返回 POLISH，最多 2 轮)
```

**阶段详述：**

1. **ARCHITECT (架构审视)**
   - Architect 审视代码整体架构
   - 识别架构异味（Architecture Smells）
   - 输出改进方案（可执行的重构步骤）

2. **POLISH (抛光)**
   - Polisher 按照 Polish Checklist 逐项优化
   - 按照 Architect 的改进方案执行重构
   - 输出优化后的代码

3. **GUARD (把关)**
   - Guard 使用 Guard Rubric 进行量化评分
   - 每个评分维度给出具体分数和改进建议
   - 输出 verdict: PASS / NEEDS_IMPROVEMENT / FAIL

#### 3.2.4 验收标准

- [ ] 能够识别代码中的架构异味并给出改进方案
- [ ] Polish Checklist 检查覆盖率达到 100%
- [ ] Guard Rubric 评分结果可解释（每项分数都有具体依据）
- [ ] 评分结果与人工评估的一致性 > 75%

---

### 3.3 Polish Checklist

#### 3.3.1 内置检查项

| 检查项 | 说明 | 严重程度 | 自动修复 |
|--------|------|---------|---------|
| **DRY** | 消除重复代码，抽象公共逻辑 | Critical | 部分支持 |
| **类型安全** | 完善类型注解，消除 any/unknown 滥用 | Critical | 支持 |
| **跨平台兼容** | 避免平台特定 API，确保可移植性 | Major | 不支持 |
| **异常处理** | 完善的错误处理，不吞异常 | Critical | 部分支持 |
| **Edge Case** | 边界条件处理（空值、极限值、并发） | Critical | 部分支持 |
| **Magic String/Number** | 提取魔法字符串和数字为常量/枚举 | Major | 支持 |
| **SAM 规范** | 遵循团队/项目的 SAM (Standard Architecture Model) 规范 | Major | 不支持 |
| **注释质量** | 必要处添加注释，去除无效注释 | Minor | 部分支持 |
| **命名规范** | 变量/函数/类命名符合语义和团队规范 | Major | 部分支持 |

#### 3.3.2 自定义检查项

- 用户可通过配置文件添加自定义检查项
- 每个检查项包含：名称、描述、严重程度、判断规则（正则/AST 规则）
- 支持团队级共享配置（`.devflow/checklist.yml`）

---

### 3.4 Guard Rubric 评分体系

#### 3.4.1 内置评分维度

| 维度 | 权重 | 说明 | 评分标准 |
|------|------|------|---------|
| **Helper Misuse** | 15% | 不该用 helper 的地方用了 helper，或 helper 职责不单一 | 0-10 分 |
| **Premature Abstraction** | 15% | 过早抽象，当前场景下抽象带来的复杂度大于收益 | 0-10 分 |
| **Defensive Validation** | 10% | 过度防御性验证，对不可能发生的场景做多余校验 | 0-10 分 |
| **Comment Inflation** | 10% | 注释膨胀，用注释弥补命名不当或代码不清晰 | 0-10 分 |
| **Scope Creep** | 15% | 范围蔓延，代码做了超出当前需求的事 | 0-10 分 |
| **File Bloat** | 15% | 文件膨胀，单个文件职责过多或行数过多 | 0-10 分 |
| **Backward-Compatibility Sham** | 10% | 向后兼容的假象，虚假的兼容层或无用的兼容代码 | 0-10 分 |
| **Naming Quality** | 10% | 命名质量，是否准确表达意图 | 0-10 分 |

#### 3.4.2 评分规则

- 总分 = Σ(维度分数 × 权重)
- 等级划分:
  - **A (90-100)**: 优秀，可直接合并
  - **B (75-89)**: 良好， minor 问题可后续修复
  - **C (60-74)**: 合格，需要修复后重新评分
  - **D (<60)**: 不合格，需要重大改进

#### 3.4.3 Verdict 规则

- **PASS**: 总分 ≥ 75 且无单项低于 5 分
- **NEEDS_IMPROVEMENT**: 总分 60-74 或有单项低于 5 分
- **FAIL**: 总分 < 60

#### 3.4.4 自定义维度

- 用户可添加自定义评分维度
- 可调整内置维度的权重
- 支持导入/导出评分配置

---

### 3.5 模式切换策略

#### 3.5.1 自动推荐

系统根据以下因素自动推荐工作流模式：

| 因素 | Super Dev | Polish |
|------|-----------|--------|
| 输入类型 | 自然语言需求 | 代码文件/目录 |
| 代码状态 | 无/少量代码 | 已有完整代码 |
| 用户意图 | "实现..." / "创建..." | "优化..." / "审查..." |
| 代码质量 | 未知 | 需要评估 |

#### 3.5.2 手动切换

- 在 Super Dev 的任意阶段可通过 `/devflow polish` 切换到 Polish 模式
- 在 Polish 模式完成后可通过 `/devflow continue` 返回 Super Dev 的 MERGE 阶段
- 切换时保留上下文（shared context）

#### 3.5.3 模式对比矩阵

| 维度 | Super Dev | Polish |
|------|-----------|--------|
| 目标 | 完成功能开发 | 提升代码质量 |
| 起点 | 需求描述 | 现有代码 |
| 终点 | 可合并的代码 | 高质量代码 + 评分 |
| 循环 | REVIEW-FIX (最多3轮) | POLISH-GUARD (最多2轮) |
| 失败处理 | 暂停，交由用户决策 | 返回 POLISH 或终止 |
| 适用场景 | 新功能、Bug修复、技术方案 | 代码优化、重构、审查 |

---

### 3.6 会话管理与上下文传递

#### 3.6.1 会话持久化

- 每个工作流实例对应一个 session
- Session 包含：任务描述、阶段历史、角色输出、评分结果
- 支持会话列表、查看、恢复

#### 3.6.2 上下文传递

- PLAN 阶段的技术方案传递给 BUILD 阶段
- BUILD 阶段的代码传递给 REVIEW 阶段
- REVIEW 阶段的意见传递给 FIX 阶段
- 阶段间上下文自动传递，无需用户重复输入

#### 3.6.3 人工介入点

| 阶段 | 介入时机 | 用户可做的操作 |
|------|---------|--------------|
| PLAN 完成后 | 用户确认技术方案 | 修改、补充、批准、取消 |
| REVIEW 完成后 | 审查报告呈现 | 批准、要求修改、跳过某些意见 |
| GUARD 评分后 | 评分结果呈现 | 接受、要求重新抛光、查看详情 |
| 循环上限到达 | 3轮修复/2轮抛光后 | 强制继续、终止、人工处理 |

---

## 4. 非功能需求

### 4.1 性能

- 单阶段响应时间 < 30 秒（不含模型生成时间）
- 完整 Super Dev 流程 < 10 分钟（标准复杂度任务）
- 完整 Polish 流程 < 5 分钟（标准文件数）

### 4.2 可靠性

- 工作流中断后可从断点恢复
- 每个阶段完成后自动保存 checkpoint
- 模型调用失败时自动重试（最多 3 次）

### 4.3 可扩展性

- 支持新增自定义角色
- 支持新增自定义阶段
- 支持自定义检查项和评分维度

### 4.4 用户体验

- 命令简洁，符合 Claude Code 用户习惯
- 输出结构化，关键信息高亮
- 支持 `--dry-run` 预览完整流程而不实际执行

---

# 第二部分：技术规格文档

## 1. 架构设计

### 1.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                     Claude Code Skill                        │
│                    (SKILL.md + COMMAND.md)                   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      DevFlow Engine                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │  Workflow    │  │   Session    │  │  Context Manager │  │
│  │  Orchestrator│  │   Manager    │  │                  │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │  Role Router │  │   Guard      │  │  Checklist       │  │
│  │              │  │   Rubric     │  │  Engine          │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        ┌─────────┐    ┌─────────┐    ┌─────────┐
        │ Claude  │    │  Codex  │    │  Local  │
        │  API    │    │  API    │    │  Tools  │
        └─────────┘    └─────────┘    └─────────┘
```

### 1.2 模块职责

| 模块 | 职责 |
|------|------|
| **Workflow Orchestrator** | 管理 Super Dev / Polish 流程状态机，驱动阶段流转 |
| **Session Manager** | 会话 CRUD、状态持久化、历史查询 |
| **Context Manager** | 阶段间上下文传递、共享状态管理 |
| **Role Router** | 根据角色定义将任务路由到对应模型 |
| **Guard Rubric** | 评分计算、规则引擎、报告生成 |
| **Checklist Engine** | 检查项执行、AST 分析、正则匹配 |

---

## 2. 核心数据模型

### 2.1 Workflow Session

```typescript
interface WorkflowSession {
  sessionId: string;
  mode: "super_dev" | "polish";
  status: "planning" | "building" | "reviewing" | "fixing" | "merging" 
        | "architecting" | "polishing" | "guarding" | "completed" | "failed";
  request: string;           // 用户原始需求
  currentRound: number;      // 当前循环轮次
  maxRounds: number;         // 最大循环轮次
  context: SharedContext;
  stages: Stage[];
  metadata: SessionMetadata;
  createdAt: string;
  updatedAt: string;
}
```

### 2.2 Stage

```typescript
interface Stage {
  name: string;              // e.g., "plan", "build", "review"
  role: Role;
  status: "pending" | "running" | "completed" | "failed";
  input: StageInput;
  output: StageOutput;
  checkpoint: Checkpoint;
  startedAt: string;
  completedAt: string;
}
```

### 2.3 Role

```typescript
interface Role {
  name: string;              // e.g., "planner", "coder", "reviewer"
  model: "claude" | "codex" | string;
  systemPrompt: string;      // 角色系统提示词
  capabilities: string[];    // 能力列表
}
```

### 2.4 Guard Rubric

```typescript
interface GuardRubric {
  dimensions: RubricDimension[];
  weights: Record<string, number>;
  passThreshold: number;     // 默认 75
}

interface RubricDimension {
  id: string;
  name: string;
  description: string;
  weight: number;            // 0-1
  score: number;             // 0-10
  evidence: string[];        // 评分依据
  suggestions: string[];     // 改进建议
}

interface GuardReport {
  totalScore: number;        // 加权总分
  grade: "A" | "B" | "C" | "D";
  verdict: "PASS" | "NEEDS_IMPROVEMENT" | "FAIL";
  dimensions: RubricDimension[];
  summary: string;
}
```

### 2.5 Polish Checklist

```typescript
interface ChecklistItem {
  id: string;
  name: string;
  description: string;
  severity: "critical" | "major" | "minor";
  category: string;
  rule: CheckRule;           // 检查规则
  autoFixable: boolean;
  fixRule?: FixRule;         // 自动修复规则
}

interface CheckRule {
  type: "regex" | "ast" | "llm";
  pattern?: string;          // regex 模式
  astQuery?: string;         // AST 查询
  prompt?: string;           // LLM 判断提示词
}

interface ChecklistReport {
  items: ChecklistResult[];
  passed: number;
  failed: number;
  criticalIssues: number;
}
```

---

## 3. 接口定义

### 3.1 Skill 命令接口

```bash
# 超级开发模式
/devflow build "<需求描述>" [--mode <strategy>] [--dry-run]

# 抛光模式
/devflow polish [<文件路径>] [--target <dimension>] [--strict]

# 代码审查
/devflow review [<文件路径>] [--focus <area>]

# 查看会话
/devflow session list
/devflow session show <session_id>
/devflow session resume <session_id>

# 查看评分报告
/devflow report <session_id>

# 配置管理
/devflow config show
/devflow config set <key> <value>

# 帮助
/devflow help
/devflow help <command>
```

### 3.2 内部模块接口

```typescript
// Workflow Orchestrator
interface IWorkflowOrchestrator {
  start(mode: WorkflowMode, request: string): Promise<WorkflowSession>;
  advance(sessionId: string, userDecision?: UserDecision): Promise<Stage>;
  getStatus(sessionId: string): Promise<WorkflowStatus>;
  switchMode(sessionId: string, targetMode: WorkflowMode): Promise<WorkflowSession>;
}

// Role Router
interface IRoleRouter {
  execute(role: Role, task: Task, context: SharedContext): Promise<RoleOutput>;
}

// Guard Rubric
interface IGuardRubric {
  evaluate(code: string, rubricConfig?: RubricConfig): Promise<GuardReport>;
  explain(dimensionId: string, code: string): Promise<string>;
}

// Checklist Engine
interface IChecklistEngine {
  run(code: string, checklist: ChecklistItem[]): Promise<ChecklistReport>;
  fix(code: string, issues: ChecklistResult[]): Promise<string>;
}
```

---

## 4. 状态机设计

### 4.1 Super Dev 状态机

```
                    ┌─────────────┐
         ┌─────────│   PLANNING  │◄────────┐
         │         └──────┬──────┘         │
         │                │ approve         │
         │                ▼                 │
         │         ┌─────────────┐         │
         │         │   BUILDING  │         │
         │         └──────┬──────┘         │
         │                │ complete        │
         │                ▼                 │
         │         ┌─────────────┐         │
         └────────►│  REVIEWING  │─────────┘ (approve)
                   └──────┬──────┘
                          │ has issues
                          ▼
                   ┌─────────────┐
         ┌────────►│   FIXING    │─────────┐
         │         └──────┬──────┘         │
         │                │ complete        │
         │                ▼                 │
         │         ┌─────────────┐         │
         └─────────│  REVIEWING  │◄────────┘
                   └──────┬──────┘
                          │ approve (round < 3)
                          ▼
                   ┌─────────────┐
                   │   MERGING   │
                   └──────┬──────┘
                          ▼
                   ┌─────────────┐
                   │  COMPLETED  │
                   └─────────────┘
```

### 4.2 Polish 状态机

```
              ┌───────────────┐
              │  ARCHITECTING │
              └───────┬───────┘
                      │
                      ▼
              ┌───────────────┐
              │   POLISHING   │
              └───────┬───────┘
                      │
                      ▼
              ┌───────────────┐
              │   GUARDING    │
              └───────┬───────┘
                      │
           ┌──────────┼──────────┐
           │          │          │
           ▼          ▼          ▼
        ┌────┐    ┌────┐    ┌────┐
        │PASS│    │NEED│    │FAIL│
        │    │    │IMP │    │    │
        └──┬─┘    └──┬─┘    └──┬─┘
           │         │         │
           ▼         ▼         ▼
        ┌────┐   ┌────┐   ┌────┐
        │DONE│   │POLI│   │STOP│
        │    │   │SH  │   │    │
        └────┘   └────┘   └────┘
```

---

## 5. 配置系统

### 5.1 配置文件位置

```
.aegis/
├── devflow/
│   ├── config.yml          # 主配置
│   ├── roles/              # 角色定义
│   │   ├── planner.yml
│   │   ├── coder.yml
│   │   ├── reviewer.yml
│   │   └── fixer.yml
│   ├── rubric/             # 评分配置
│   │   ├── default.yml     # 默认 Guard Rubric
│   │   └── custom.yml      # 自定义扩展
│   └── checklist/          # 检查项配置
│       ├── default.yml     # 默认 Polish Checklist
│       └── custom.yml      # 自定义扩展
```

### 5.2 配置示例

```yaml
# config.yml
devflow:
  version: "1.0"
  
  super_dev:
    max_review_rounds: 3
    auto_merge_threshold: 0.9  # 自动化合并阈值
    
  polish:
    max_polish_rounds: 2
    pass_threshold: 75
    
  models:
    planner: "claude-opus-4-7"
    coder: "codex"
    reviewer: "claude-sonnet-4-6"
    fixer: "codex"
    architect: "claude-opus-4-7"
    polisher: "codex"
    guard: "claude-sonnet-4-6"
    
  checkpoints:
    auto_save: true
    retention_days: 30
```

---

## 6. 实现计划

### 6.1 里程碑

| 阶段 | 目标 | 工期 | 交付物 |
|------|------|------|--------|
| **M1** | 核心框架 | 1 周 | Workflow Orchestrator、Session Manager、基础 CLI |
| **M2** | Super Dev | 1 周 | 4 角色实现、PLAN-BUILD-REVIEW-FIX-MERGE 流程 |
| **M3** | Polish | 1 周 | 3 角色实现、ARCHITECT-POLISH-GUARD 流程 |
| **M4** | 质量体系 | 1 周 | Polish Checklist、Guard Rubric、评分系统 |
| **M5** | 配置与扩展 | 3 天 | 配置系统、自定义规则、导入导出 |
| **M6** | 集成与测试 | 3 天 | Skill 集成、测试用例、文档 |

### 6.2 依赖关系

```
M1 (核心框架)
  ├── M2 (Super Dev)
  │     └── M4 (质量体系)
  └── M3 (Polish)
        └── M4 (质量体系)
              └── M5 (配置与扩展)
                    └── M6 (集成与测试)
```

### 6.3 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 模型 API 延迟/不稳定 | 用户体验差 | 实现重试机制、缓存中间结果 |
| 评分主观性强 | 用户不信任 | 提供评分依据、支持人工校准 |
| 上下文过长 | 超出模型限制 | 实现上下文压缩、分块处理 |
| 循环无法收敛 | 流程卡住 | 设置轮次上限、支持人工介入 |

---

## 7. 附录

### 7.1 术语表

| 术语 | 说明 |
|------|------|
| **Super Dev** | 超级开发模式，完整功能开发工作流 |
| **Polish** | 抛光模式，代码质量优化工作流 |
| **Guard Rubric** | 代码质量评分体系 |
| **Polish Checklist** | 代码优化检查清单 |
| **Session** | 一次工作流执行的会话实例 |
| **Checkpoint** | 阶段完成的快照，用于恢复 |

### 7.2 参考文档

- [Claude Code Skill 开发指南](https://docs.claude.ai/code/skills)
- [AEGIS v2.0 多模型协作框架](./AEGIS-重构方案-多模型协作-v2.0.md)

---

*文档结束*
