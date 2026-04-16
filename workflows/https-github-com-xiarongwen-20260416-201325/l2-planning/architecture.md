# AEGIS OS 架构文档

**Version:** 1.2.0  
**Workflow:** https-github-com-xiarongwen-20260416-201325  
**Date:** 2026-04-16

---

## 1. 架构总览

AEGIS OS 采用**四层架构**：

```
┌─────────────────────────────────────────────────────────────┐
│                    Owner Layer (用户)                      │
│         给目标 / 给约束 / 做审批 / 接受结果                  │
└─────────────────────────────────────────────────────────────┘
                            ▲
                            │
┌─────────────────────────────────────────────────────────────┐
│              Host-Native Bot Layer (宿主层)                │
│    /aegis skill → 当前 Claude/Codex 会话作为 Orchestrator   │
│    负责：目标接收、workflow 路由、阶段推进、review 闭环      │
└─────────────────────────────────────────────────────────────┘
                            ▲
                            │
┌─────────────────────────────────────────────────────────────┐
│            Repo-Native Control Plane (控制面)              │
│    负责：状态机约束、registry 管理、需求锁校验、doctor 自检  │
│    形式：Git 仓库内的 Python 模块 + YAML/JSON 配置          │
└─────────────────────────────────────────────────────────────┘
                            ▲
                            │
┌─────────────────────────────────────────────────────────────┐
│           Specialist Layer (专业 Agent 层)                 │
│    market-research / prd-architect / frontend-squad         │
│    backend-squad / code-reviewer / security-auditor         │
│    qa-validator / deploy-sre / darwin-skill                 │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 核心设计决策

### 2.1 Host-Native Orchestrator

**决策**：AEGIS 的主入口不是外部 CLI，而是当前宿主会话内的 `/aegis` skill。

**理由**：
- 保留宿主完整上下文（长上下文、文件系统、shell、web 搜索）
- 避免外部 runner 递归调用模型带来的延迟和上下文分裂
- 更容易在 review/fix 循环中保持连续性
- 更自然地使用宿主原生审批机制

### 2.2 Git-Native 状态与审计

**决策**：所有 workflow 状态、产物、review 记录、锁文件都存储在 Git 中。

**理由**：
- Git 提供免费的版本控制、分支、标签、审计历史
- `post-agent-run.sh` 自动提交，确保每个阶段都有持久化快照
- 无需引入额外的数据库或对象存储
- 与用户现有的代码工作流无缝集成

### 2.3 Registry 作为单一真相源

**决策**：`.aegis/core/registry.json` 是唯一真相源，所有 `agents/*/agent.json` 都是派生产物。

**理由**：
- 防止元数据分散和失同步
- 控制面可以自动校验和同步派生文件
- 新增 agent 只需修改一处注册表

### 2.4 固定状态机 + 可扩展 Workflow Type

**决策**：状态机是固定的（INIT → L1_RESEARCH → ... → DONE），但 workflow type 是可扩展的。

**理由**：
- 固定状态机确保所有 workflow 都经过相同的治理检查点
- 不同类型的 workflow 可以从不同的 entry state 进入，覆盖不同场景
- 未来新增 workflow type 不需要修改状态机核心逻辑

---

## 3. 数据流

### 3.1 典型 Workflow 启动数据流

```
用户输入: /aegis 帮我开发一个聊天页面
    │
    ▼
┌─────────────────┐
│ automation_runner│ ──bootstrap──▶ 创建 workflow id
│   (bootstrap)   │                生成 intent-lock.json
└─────────────────┘                初始化 state.json = INIT
    │
    ▼
Host Orchestrator 读取 state.json，识别当前状态
    │
    ▼
按状态机推进到 L1_RESEARCH
    │
    ▼
运行 pre-agent-run.sh (market-research)
    │
    ▼
market-research agent 产出 L1 intelligence
    │
    ▼
运行 post-agent-run.sh ──▶ Git commit + tag
    │
    ▼
控制面 write-state ──▶ L1_REVIEW
    │
    ▼
research-qa-agent 执行 gate review
    │
    ▼
若 LGTM，write-state ──▶ L2_PLANNING
    │
    ▼
prd-architect 产出 PRD / architecture / requirements-lock
    │
    ▼
... 继续按状态机推进直到目标状态或 BLOCKED
```

### 3.2 Review-Fix-LGTM 数据流

```
workflow 到达 gate (如 L3_CODE_REVIEW)
    │
    ▼
pre-agent-run.sh 验证 reviewer 独立性
    │
    ▼
code-reviewer agent 读取代码产物，输出 review-round-1.md
    │
    ▼
写入 review-loop-status.json (status: changes_requested)
    │
    ▼
post-agent-run.sh 校验产物完整性
    │
    ▼
workflow 退回到 fix state (L3_DEVELOP)
    │
    ▼
frontend/backend squad 修复问题，输出 fix-response-round-1.md
    │
    ▼
workflow 重新进入 L3_CODE_REVIEW
    │
    ▼
code-reviewer 输出 review-round-2.md
    │
    ▼
若 LGTM: review-loop-status.json → lgtm, 写入 review-passed.json
    │
    ▼
write-state ──▶ 下一状态
```

---

## 4. 核心组件说明

### 4.1 `agents/aegis/SKILL.md`

Host-native 入口 skill。当用户在 Claude Code 中输入 `/aegis ...` 时，当前会话加载此 skill 并进入 AEGIS orchestrator 模式。

### 4.2 `agents/orchestrator/SKILL.md`

定义 orchestrator 的行为规范：如何读取控制面配置、如何选择下一阶段、如何管理 human approval boundaries、如何处理 review loop。

### 4.3 `tools/control_plane/`

Python 控制面模块，提供以下 CLI 命令：

- `doctor`：全量自检（registry、orchestrator、contracts、derived metadata、schema）
- `sync-agent-metadata`：从 registry 同步所有 `agents/*/agent.json`
- `workflow-dry-run`：模拟合法 workflow 路径
- `write-state`：强制校验后的状态迁移
- `evolution-run`：执行 nightly agent evolution

### 4.4 `.aegis/core/orchestrator.yml`

机器可读的状态机配置，包含：
- 所有 workflow states
- 每个 state 允许的 agents
- 状态转移规则
- Gate 定义（reviewer、required outputs、rubric、min score、review loop 配置）

### 4.5 `.aegis/core/registry.json`

Agent 注册表，记录每个 agent 的：
- 名称与描述
- 输入输出契约
- 依赖 capability
- evolution 开关
- 运行时约束

### 4.6 `shared-contexts/tool-contracts.yml`

抽象工具契约定义，把 agent 设计从具体运行时解耦。例如：
- `search_web`：信息检索
- `spawn_agent`：启动子 agent
- `run_gate_review`：执行门禁评审
- `lock_requirements`：冻结需求

每个契约附带 Codex 运行时适配说明。

### 4.7 `.aegis/hooks/`

- `pre-agent-run.sh`：执行前校验（workflow id、state-agent 匹配、输入齐备、依赖契约、requirements lock hash）
- `post-agent-run.sh`：执行后校验（agent 输出完整性、gate 产物、review loop 产物、Git 提交）

---

## 5. 扩展性设计

### 5.1 新增 Agent

1. 在 `agents/` 下创建新目录，编写 `SKILL.md` 和 `agent.json`
2. 在 `.aegis/core/registry.json` 中注册该 agent
3. 运行 `python3 -m tools.control_plane sync-agent-metadata`
4. 在 `orchestrator.yml` 的 `state_agents` 中指定该 agent 可执行的状态
5. 运行 `python3 -m tools.control_plane doctor` 验证

### 5.2 新增 Workflow Type

1. 在 `orchestrator.yml` 的 `workflow_types` 中定义新类型
2. 指定其 `entry_states` 和 `required_capabilities`
3. 如有需要，新增 gate 配置（引用现有 rubric 或新增）
4. 更新 `tools/automation_runner` 的路由逻辑以识别该类型
5. 运行 `workflow-dry-run` 验证路径合法性

### 5.3 新增 Capability

1. 在 `shared-contexts/tool-contracts.yml` 中定义新的抽象契约
2. 在 registry 中声明哪些 agent 提供/依赖该 capability
3. 在 agent skill 中实现该契约在当前宿主平台的适配

---

## 6. 安全与风险设计

### 6.1 执行隔离

- 每个 agent 只能在 `orchestrator.yml` 允许的 state 下执行
- `pre-agent-run.sh` 会拒绝非法的 agent-state 组合
- 子 agent 仅在"任务边界清晰"时 spawned

### 6.2 变更控制

- `intent-lock.json` 锁定用户原始目标
- `requirements-lock.json` 冻结执行需求并带 hash
- 任何偏离 locked requirement 的 fix 都必须走 change control，而不是静默 reinterpret

### 6.3 审计追踪

- 每个阶段结束后自动 Git commit + tag
- Review loop 的每一轮都有独立的 `review-round-N.md` 和 `fix-response-round-N.md`
- `evolution.log` 记录所有 agent 指令演进尝试

### 6.4 Fallback 路径

- 若 host-native skill 不可用，可降级到 `tools.automation_runner`
- 若 workflow 阻塞，可人工接管并用 `write-state` 手动推进

---

## 7. 部署与运行环境

### 7.1 本地开发/运行

```bash
# 初始化
bash scripts/bootstrap.sh

# 运行控制面自检
python3 -m tools.control_plane doctor

# Host-native 启动
/aegis 帮我开发一个聊天页面
```

### 7.2 依赖

- Python 3.10+
- Git
- Claude Code CLI 或 Codex CLI（Host-native 模式）
- Bash/Zsh（用于 hooks）

### 7.3 无外部数据库

AEGIS 的设计假设是：Git 即数据库。所有状态、配置、产物、审计记录都存在于 Git 仓库中。这大大降低了运维复杂度和部署门槛。

---

## 8. 未来架构演进方向

### 8.1 短期（v1.2 - v1.3）

- 完善 Owner Profile 和 Company Profile 的结构化存储
- 增强 `resume` 机制的健壮性
- 优化 review loop 的自动化体验

### 8.2 中期（v1.4 - v1.5）

- 引入跨 workflow 的 Knowledge Base
- 支持更灵活的 branch-per-workflow 策略
- 扩展 operate workflow 类型（日常运营、反馈收集）

### 8.3 长期（v2.0+）

- 考虑支持非 Codex/Claude 的宿主平台适配层
- 引入 dashboard 用于可视化 workflow 状态和审计历史
- 探索分布式 agent 执行（在保持治理约束的前提下）

---

*文档锁定于 L2_PLANNING 阶段。*
