# AEGIS OS 产品需求文档 (PRD)

**Version:** 1.2.0  
**Workflow:** https-github-com-xiarongwen-20260416-201325  
**Date:** 2026-04-16  
**Status:** Locked for L2 Review

---

## 1. Problem Statement

AI Agent 系统已经能够完成越来越多的任务，但在复杂、多步骤、长期的执行过程中，存在五个核心问题：

1. **需求漂移**：AI 在执行过程中会自行 reinterpret 用户目标，导致做着做着变成了"别的东西"。
2. **Review 流于形式**：大多数系统的 review 只是建议，不是强制约束，发现问题后没有闭环跟踪。
3. **职责边界不清**：多 Agent 协作时缺乏明确的角色分工和状态隔离。
4. **审计缺失**：执行过程不可追溯，无法回答"为什么变成这样"。
5. **扩展困难**：新增能力时需要推翻核心或硬编码进主流程。

AEGIS OS 的目标是为"个人公司"（个人开发者、一人公司、超轻团队）提供一个**Git-Native、Host-Native、治理优先**的多 Agent 专业执行操作系统，让 AI 在受控边界内持续推进工作，同时不偏离用户真实目标。

---

## 2. User Stories

### 核心用户：个人公司 Owner

- **US-1**：作为个人公司 Owner，我希望用一句话启动一个复杂任务（如"帮我开发一个聊天页面"），以便 AI 能自动推进而我不需要每一步都盯着。
- **US-2**：作为个人公司 Owner，我希望 AI 在执行过程中不会自行改变需求，以便最终结果符合我的原始意图。
- **US-3**：作为个人公司 Owner，我希望每个关键产物都经过独立 reviewer 的审查闭环，以便质量可控。
- **US-4**：作为个人公司 Owner，我希望所有决策和执行过程都被记录在 Git 中，以便我能审计和回溯。
- **US-5**：作为个人公司 Owner，我希望系统能随着我的业务扩展而增加新能力，而不是被某一个功能永久锁死。

### 次要用户：小型技术团队 Lead

- **US-6**：作为技术团队 Lead，我希望为团队引入标准化的 AI 工作流（Research → Plan → Build → Review → Deploy），以便降低 ad-hoc prompt 工程带来的不确定性。
- **US-7**：作为技术团队 Lead，我希望自定义 agent 和 review 规则，以便适配团队的特定流程和质量标准。

---

## 3. Acceptance Criteria

### 目标接收与锁定

- **AC-1**：Given 用户在 Claude Code / Codex 中输入 `/aegis 帮我开发一个聊天页面`，When AEGIS 接收该请求，Then 系统应自动生成 `intent-lock.json` 并路由到正确的 workflow type（build）。
- **AC-2**：Given 一个 workflow 已进入 L2_PLANNING 阶段，When planning 完成，Then 系统必须生成 `requirements-lock.json` 并为其计算 lock_hash。
- **AC-3**：Given 一个 workflow 已生成 requirements lock，When 任意 agent 尝试进入 L3 及以后阶段，Then `pre-agent-run.sh` 必须校验 lock 文件存在且 hash 一致，否则拒绝执行。

### 状态机与 Gate 控制

- **AC-4**：Given 一个 workflow 处于任意状态，When 控制面尝试推进状态，Then 只允许 `orchestrator.yml` 中定义的合法状态迁移。
- **AC-5**：Given 一个 workflow 到达 gated review 阶段，When reviewer 发现问题，Then 流程必须进入 review-fix-re-review 循环，直到 reviewer 给出 `LGTM` 或达到阻断条件。
- **AC-6**：Given 一个 review loop 正在进行，When 达到 max rounds（L1-L4 为 3 轮，L5 为 2 轮）仍未 LGTM，Then 系统必须将 workflow 状态置为 `BLOCKED`。

### Host-Native 执行

- **AC-7**：Given 用户在宿主环境中触发 AEGIS，When workflow 开始执行，Then 当前宿主会话应直接作为 orchestrator，而不是通过外部 CLI 递归调用新模型进程。
- **AC-8**：Given 一个 host-native workflow 正在执行，When 遇到需要人工确认的节点（如部署环境、凭据、关键方向决策），Then orchestrator 必须暂停并显式询问用户。

### 审计与追踪

- **AC-9**：Given 任意 agent 完成一个阶段，When `post-agent-run.sh` 执行，Then 该阶段的所有产物和状态变更必须被提交到 Git 并打上版本标签。
- **AC-10**：Given 一个 workflow 已结束或阻塞，When 用户查看 Git 历史，Then 应能清晰追踪每个阶段的决策、review 结论和变更原因。

### 扩展性

- **AC-11**：Given 开发者希望新增一个 specialist agent，When 其在 `registry.json` 中声明该 agent 的元数据并运行 `sync-agent-metadata`，Then 系统应自动同步所有派生 `agent.json` 且 doctor 通过。
- **AC-12**：Given 开发者希望新增一个 workflow type，When 其在 `orchestrator.yml` 中定义该类型所需的状态和 capability，Then 现有控制面应能在不修改核心代码的情况下支持该类型。

---

## 4. Non-Functional Requirements

### 性能
- **NFR-1**：Workflow bootstrap（从用户输入到生成 `intent-lock.json` 和 `state.json`）应在 5 秒内完成。
- **NFR-2**：`pre-agent-run.sh` 和 `post-agent-run.sh` 的执行时间应在 10 秒内完成（不含 Git 提交的网络延迟）。
- **NFR-3**：控制面 `doctor` 命令应在 30 秒内完成全量自检。

### 安全
- **NFR-4**：所有 shell hook 必须拒绝非法 agent-state 组合的执行。
- **NFR-5**：Requirements lock 的 hash 必须使用抗碰撞算法（SHA-256）。
- **NFR-6**：Deploy 阶段（L5）默认必须在需要环境参数或凭据时停下，不得自动推断或伪造敏感信息。

### 可扩展性
- **NFR-7**：Agent 注册表应支持声明式增删改，新增 agent 不应触发核心控制面代码重构。
- **NFR-8**：工具契约层应保持平台无关，新增宿主平台适配不应要求重写 agent skill。

### 可靠性
- **NFR-9**：每个阶段结束后，workflow 状态必须持久化到 Git，支持从中断点 `resume`。
- **NFR-10**：Review loop 必须设置明确的最大轮次，防止无限循环消耗资源。

### 兼容性
- **NFR-11**：AEGIS 应优先兼容 Claude Code 和 Codex 的 skill/agent 机制。
- **NFR-12**：External runner（`tools/automation_runner`）应保留为 fallback/debug 路径，确保 host-native 不可用时系统仍可降级运行。

---

## 5. Out of Scope

以下功能在当前 PRD 范围内明确不做：

1. **多用户实时协作**：AEGIS v1 面向个人公司 Owner，不支持多人同时编辑同一 workflow。
2. **可视化 Workflow Builder**：暂不提供拖拽式 workflow 设计器，所有配置通过 YAML/JSON 声明。
3. **企业级 RBAC**：v1 不涉及细粒度角色权限控制。
4. **跨仓库 workflow 依赖**：一个 workflow 不直接触发或阻塞另一个仓库的 workflow。
5. **自动商业化 / 计费系统**：AEGIS 本身是开源控制面，不包含 SaaS 计费逻辑。
6. **非 Git 的版本控制后端**：状态与审计默认依赖 Git，v1 不抽象出 SVN/Mercurial 等适配层。
7. **通用 AI 模型训练 / 微调**：AEGIS 不训练模型，只编排和治理已有的模型能力。

---

## 6. Open Questions

1. **宿主平台 API 演进**：Claude Code / Codex 的 skill 触发和 sub-agent 机制仍在变化，是否需要预留更厚的运行时适配层？
2. **Owner Profile 的存储位置**：长期用户偏好和公司上下文应存储在仓库内还是独立的用户级配置目录？
3. **多 workflow 并发冲突**：未来是否需要引入 branch-per-workflow 策略来避免 Git 冲突？
4. **Review 评分模型**：当前评分依赖 reviewer agent 的 LLM 判断，是否需要引入更结构化的 rubric 打分工具？
5. **第三方集成扩展**：当需要接入 Slack、Notion、Linear 等外部系统时，应通过新增 agent 还是新增 capability 来实现？

---

*PRD 版本锁定于 L2_PLANNING 阶段。任何偏离本 PRD 的变更必须通过 change control 流程。*
