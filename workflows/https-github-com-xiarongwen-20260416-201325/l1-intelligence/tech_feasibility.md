# AEGIS OS 技术可行性评估

## 评估目标

基于 AEGIS OS 现有代码库和架构设计，评估其核心技术方案的可行性、成熟度与主要技术风险。

---

## 1. 技术架构概览

AEGIS 采用三层架构：

1. **Host-Native Bot Layer**：当前 Claude/Codex 会话作为 orchestrator
2. **Repo-Native Control Plane**：Git 仓库内的配置、状态机、校验逻辑
3. **External Runner（Fallback）**：`tools/automation_runner/` 用于 bootstrap 和 debug

核心组件：
- `.aegis/core/orchestrator.yml` — 状态机和 gate 定义
- `.aegis/core/registry.json` — Agent 注册表（单一真相源）
- `tools/control_plane/` — Python 控制面，负责校验、同步、doctor、状态推进
- `agents/` — 各 specialist agent 的 skill 定义和元数据
- `workflows/` — 每个工作流的产物和状态目录

---

## 2. 核心技术方案评估

### 2.1 Git-Native 状态与审计

**方案**：所有 workflow 状态、review 产物、锁文件都存储在 Git 中，通过 `state.json` 和 Git 历史实现审计追踪。

**可行性**：高
- Git 是成熟、稳定、广泛使用的版本控制系统
- 状态文件（JSON/YAML）体积小，适合 Git 管理
- `post-agent-run.sh` 已自动将产物提交到 Git

**风险**：低
- 高频状态更新可能导致 Git 历史膨胀（可通过 `.gitignore` 控制大文件/日志）
- 多并发 workflow 可能产生 Git 冲突（当前单宿主模式可缓解）

### 2.2 Host-Native Orchestrator

**方案**：AEGIS 主入口通过 `/aegis` skill 直接在当前 Claude/Codex 会话中运行，当前会话即 orchestrator。

**可行性**：高
- 充分利用宿主平台的长上下文、文件读写、shell 执行、web 搜索能力
- 避免外部 runner 递归调用模型带来的上下文分裂和延迟
- 已在 `agents/aegis/SKILL.md` 和 `CLAUDE.md` 中完整定义

**风险**：中
- 宿主平台（Claude Code / Codex）的 skill 机制仍在演进，API/触发方式可能变化
- 长时间运行的 orchestrator 会话可能受宿主平台超时或上下文限制
- 子 agent 的调度深度依赖宿主平台的 sub-agent / Agent tool 能力

### 2.3 状态机与 Gate 控制

**方案**：固定状态机 `INIT -> L1_RESEARCH -> L1_REVIEW -> L2_PLANNING -> L2_REVIEW -> L3_DEVELOP -> L3_CODE_REVIEW -> L3_SECURITY_AUDIT -> L4_VALIDATE -> L4_REVIEW -> L5_DEPLOY -> L5_REVIEW -> DONE`，每个 gate 有独立的 reviewer、评分标准和 review loop。

**可行性**：高
- 状态机已在 `.aegis/core/orchestrator.yml` 中明确定义
- `tools.control_plane write-state` 已实现对合法状态迁移的强制校验
- `pre-agent-run.sh` 已实现对 agent-state 匹配性的校验

**风险**：低
- 状态机是固定的，新增 workflow type 需要扩展配置，但架构已支持
- review loop 的自动化闭环需要各 agent 严格遵守输出契约

### 2.4 Intent Lock / Requirement Lock

**方案**：
- `intent-lock.json`：锁定用户本次请求的原始目标
- `requirements-lock.json`：从 L2 开始冻结可执行需求，并生成哈希校验

**可行性**：高
- schema 已定义：`shared-contexts/intent-lock-schema.json`、`shared-contexts/requirements-lock-schema.json`
- bootstrap 流程已自动创建 `intent-lock.json`
- `pre-agent-run.sh` 从 L3 起校验 requirement lock 的存在性和哈希

**风险**：低
- 锁文件的内容质量取决于 planning agent（prd-architect）的输出
- 需求变更必须通过显式 change control，当前机制已设计但自动化程度待验证

### 2.5 Review-Fix-LGTM Loop

**方案**：每个 gated review 不是一次性判定，而是多轮循环，直到 reviewer 给出 `LGTM` 或达到阻断条件。

**可行性**：中高
- 产物规范已明确：`review-round-N.md`、`fix-response-round-N.md`、`review-loop-status.json`
- `orchestrator.yml` 已定义各 gate 的 reviewer、fixer 和 max rounds
- 控制面已具备对 review artifact 的 schema 校验能力

**风险**：中
- 循环的自动化执行需要 reviewer agent 和 fixer agent 的高质量配合
- 如果 reviewer 过于严苛或 fixer 能力不足，可能导致循环耗尽进入 `BLOCKED`
- 当前主要依赖 host-native 执行，无外部 persistent queue 支撑长时间 review loop

### 2.6 Agent 注册表与元数据同步

**方案**：`.aegis/core/registry.json` 是单一真相源，所有 `agents/*/agent.json` 都是派生产物，由控制面自动同步。

**可行性**：高
- `python3 -m tools.control_plane sync-agent-metadata` 已实现同步逻辑
- `registry.schema.json` 保证结构一致性
- doctor 命令会检查 derived metadata parity

**风险**：低
- 注册表 schema 变更时需要同步更新所有派生文件，当前已有工具支撑

### 2.7 工具契约抽象层

**方案**：通过 `shared-contexts/tool-contracts.yml` 定义抽象动作（如 `search_web`、`spawn_agent`、`run_gate_review`），Agent 设计保持平台无关。

**可行性**：中高
- 契约定义文件已存在，包含动作语义和 Codex 运行时适配说明
- 这种抽象层设计有利于未来迁移到其他 Agent 运行时

**风险**：中
- 契约的落地执行仍依赖各 agent skill 的具体实现
- 不同宿主平台的工具名称和能力差异可能导致契约适配复杂化

### 2.8 Nightly Evolution（夜间演进）

**方案**：每晚自动在隔离 worktree 中评估和尝试改进 agent 指令，仅保留通过 doctor 且评分提升的变更。

**可行性**：中
- `.aegis/schedules/nightly-evolution.sh` 和 `tools.control_plane evolution-run` 已实现
- 演进在隔离 worktree 中进行，主分支安全
- 保守策略（ratchet + require_doctor）降低了风险

**风险**：中
- Agent 指令的自动改进效果取决于评分模型的准确性
- 演进可能产生意料之外的 side effects，需要人工定期审查 evolution.log

---

## 3. 技术栈与依赖评估

| 组件 | 技术栈 | 成熟度 | 备注 |
|------|--------|--------|------|
| 控制面 | Python 3 | 高 | 标准库为主，无需额外重型依赖 |
| 配置/状态 | YAML, JSON | 高 | 完全标准化 |
| 版本控制 | Git | 高 | 核心假设 |
| 宿主平台 | Claude Code / Codex | 中高 | 仍在快速迭代 |
| 调度 | Cron (local) | 高 | nightly evolution 用 |
| 子 Agent | 宿主原生 Agent tool | 中 | 依赖平台能力 |

---

## 4. 主要技术风险与缓解

### 4.1 宿主平台能力变化

**风险**：Claude Code / Codex 的 skill 触发方式、sub-agent 机制、上下文限制可能变化。

**缓解**：
- 工具契约抽象层降低直接绑定
- external runner 保留为 fallback 路径
- 紧密跟踪宿主平台更新

### 4.2 长 workflow 的会话稳定性

**风险**：复杂 workflow（如完整 build + review + deploy）可能需要长时间运行，宿主会话可能中断。

**缓解**：
- 每个阶段结束后状态持久化到 Git
- `resume` 机制支持从中断点恢复
- 将长 workflow 拆分为多个独立阶段

### 4.3 Agent 输出质量不稳定

**风险**：reviewer agent 可能误判，fixer agent 可能修复不到位，导致 review loop 耗尽。

**缓解**：
- 设置合理的 max rounds（通常 3 轮）
- BLOCKED 状态允许人工接管
- 通过 evolution 持续优化 agent 指令
- 评分门槛（8.0-9.0）可根据实际运行数据微调

### 4.4 并发与冲突

**风险**：多 workflow 同时运行时可能修改同一文件（如 registry、shared-contexts）。

**缓解**：
- 当前 host-native 模式下通常串行执行
- 未来可考虑 workflow 隔离目录或 branch-per-workflow 策略

---

## 5. 总体评估结论

| 维度 | 评分 | 说明 |
|------|------|------|
| 架构可行性 | 高 | Host-Native + Git-Native + Control Plane 三层架构清晰合理 |
| 技术成熟度 | 中高 | 核心控制面已实现并可用，部分机制（evolution、跨宿主迁移）待验证 |
| 实现风险 | 中 | 主要风险来自宿主平台变化和 agent 输出质量的稳定性 |
| 扩展性 | 高 | 声明式 registry、工具契约、workflow type 系统都支持未来扩展 |

**综合结论**：AEGIS OS 的技术方案是**可行且具备工程落地条件**的。核心优势在于把"治理"做进了可校验、可审计的基础设施中，而不是停留在 prompt 层面。当前阶段应优先验证 host-native 端到端 workflow 的稳定性和用户体验，再逐步扩展 specialist agent 生态。

---

*报告生成时间：2026-04-16*  
*来源：代码库分析 + 架构文档评审*  
*workflow: https-github-com-xiarongwen-20260416-201325*
