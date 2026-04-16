# AEGIS OS

AEGIS OS 是一个 Git-native 的多 Agent 协作工作流系统，用来把产品需求从研究、规划、开发、审查、验证一直推进到发布，并且在过程中强制执行状态机、门禁评审、需求锁定和元数据一致性。

它的目标不是被某一种功能锁死，而是作为一个灵活、可扩展的 Agent 工作流 Bot 底座，随着能力增长继续接入新的 workflow、agent、工具和业务场景。

它不是某个单一业务应用，而是一个面向企业 AI 研发流程的控制面项目。

## 解决什么问题

多 Agent 系统常见的问题不是“不会做事”，而是：

- 需求在执行过程中漂移
- Agent 之间职责边界不清
- Review 只是口头约定，不是强约束
- 元数据、配置、脚本、文档经常失真
- 自我演进无法审计，也无法安全回滚

AEGIS OS 的目标就是把这些问题收进一个可校验、可追踪、可回放的控制面里。

## 现在已经有什么功能

基于当前仓库实现，AEGIS 现在已经具备这些可用能力：

- 宿主内原生入口 skill：`/aegis ...`
- 自动 workflow bootstrap、intent lock 与 workflow type 路由
- host-native orchestrator 模式
- 自动跑 pre-run / post-run hook、状态推进与 gate loop
- 多 Agent 注册表与单一真相源
- 机器可读的 workflow 状态机
- gate reviewer 独立性校验
- `review -> fix -> re-review -> ... -> LGTM` 闭环约束
- `intent-lock.json` 目标锁定
- `requirements-lock.json` 需求冻结与哈希校验
- QA traceability 校验
- 抽象工具契约与当前运行时适配说明
- `pre-agent-run` / `post-agent-run` 治理 hook
- 派生 `agents/*/agent.json` 自动同步
- `doctor` 自检与 `workflow-dry-run` 路径检查
- 夜间保守演进与结构化演进日志

当前内置的 agent 能力覆盖：

- 研究：`market-research`
- 规划：`prd-architect`
- 开发：`frontend-squad`、`backend-squad`
- 审查：`research-qa-agent`、`code-reviewer`、`security-auditor`
- 验证：`qa-validator`
- 发布：`deploy-sre`
- 控制面与演进：`orchestrator`、`darwin-skill`

需要明确的是，AEGIS 当前已经进入“host-native 自动化流水线 MVP”阶段。主入口应是宿主内 skill，由当前 Claude/Codex 会话直接作为 AEGIS bot 执行。现阶段更适合用作：

- Codex / Claude Code 上层的多 agent 工作流底座
- 自动化执行流水线的治理内核
- 可持续扩展的新 agent / 新 workflow 的治理框架

## 核心设计

### 1. Git Is The OS

工作流状态、阶段产物、评审结果和演进记录都保存在 Git 中。

### 2. Registry Is The Source Of Truth

`.aegis/core/registry.json` 是唯一真相源。

- 所有 Agent 的身份、输入、输出、依赖、可执行状态都在这里定义
- `agents/*/agent.json` 是派生产物，由控制面同步，不是手工真相

### 3. Control Plane Enforces The Rules

`python3 -m tools.control_plane` 负责：

- 校验 registry 和 orchestrator 配置
- 校验工具契约
- 同步派生 agent 元数据
- 执行 workflow dry-run
- 执行 pre-run / post-run 治理检查
- 执行 nightly evolution

`python3 -m tools.automation_runner` 负责：

- 接收自然语言请求
- 识别 workflow type
- 创建 workflow 与 `intent-lock.json`
- 自动调用 agent runtime
- 自动推进状态机直到目标状态或人工确认节点

但这层现在定位为：

- host-native 模式的 bootstrap / fallback / debug 工具
- 不是 AEGIS 的主产品交互入口

### 4. Strict Gated Workflow

AEGIS 使用固定状态机推进：

`INIT -> L1_RESEARCH -> L1_REVIEW -> L2_PLANNING -> L2_REVIEW -> L3_DEVELOP -> L3_CODE_REVIEW -> L3_SECURITY_AUDIT -> L4_VALIDATE -> L4_REVIEW -> L5_DEPLOY -> L5_REVIEW -> DONE`

如果门禁失败超出重试限制，或者安全审计出现阻断问题，流程会进入 `BLOCKED`。

### 5. Review-Fix-LGTM Loop

所有 gated review 现在都不是一次性打分，而是受控闭环：

`review -> fix -> re-review -> ... -> LGTM`

控制面会强制执行这些规则：

- reviewer 必须写出 `review-loop-status.json`
- 每轮 review 必须落 `review-round-N.md`
- fix agent 必须落 `fix-response-round-N.md`
- 只有 `LGTM` 时才允许存在 `review-passed.json`
- 超过最大 review round 或发现严重阻断问题时，流程进入 `BLOCKED`

### 6. Requirement Locking

从 L2 开始，系统会产出 `requirements-lock.json`，把需求冻结下来。

这套机制用于严格控制 AI 想法漂移和需求偏移：

- L2 规划阶段冻结范围、验收标准、非功能需求和关键假设
- 控制面为锁文件生成 `lock_hash`
- 从 L3 到 L5，每一阶段运行前都必须校验该哈希
- QA 必须输出 `requirements-traceability.json`
- 没有锁文件、哈希不一致、或需求无法追踪到验证证据时，流程不能继续

## 项目结构

```text
.aegis/
  core/
    orchestrator.yml
    registry.json
    registry.schema.json
    evolution.log
  hooks/
    pre-agent-run.sh
    post-agent-run.sh
  schedules/
    nightly-evolution.sh

agents/
  aegis/
  orchestrator/
  market-research/
  research-qa-agent/
  prd-architect/
  frontend-squad/
  backend-squad/
  code-reviewer/
  security-auditor/
  qa-validator/
  deploy-sre/
  darwin-skill/

shared-contexts/
  tool-contracts.yml
  review-rubric-8dim.json
  prd-template.md
  test-coverage-rules.yml
  requirements-lock-schema.json
  requirements-traceability-schema.json

tools/
  control_plane/
  automation_runner/

workflows/
```

## Agent 角色

- `aegis`: 宿主内主入口 skill，触发当前会话进入 AEGIS bot 模式
- `orchestrator`: 驱动状态机和工作流推进
- `market-research`: 市场研究与可行性分析
- `research-qa-agent`: 非代码类门禁的独立 reviewer
- `prd-architect`: PRD、架构和任务拆解
- `frontend-squad`: 前端实现
- `backend-squad`: 后端实现
- `code-reviewer`: 代码质量门禁
- `security-auditor`: 安全门禁
- `qa-validator`: QA 验证和需求追踪
- `deploy-sre`: 部署与发布验证
- `darwin-skill`: Agent 指令演进引擎

## 抽象工具契约

AEGIS 不直接把运行时绑定写死在每个 Agent 说明里，而是通过 `shared-contexts/tool-contracts.yml` 定义抽象动作，比如：

- `search_web`
- `fetch_source`
- `spawn_agent`
- `run_gate_review`
- `ask_user`
- `write_plan`
- `lock_requirements`
- `run_test_driven_cycle`
- `validate_requirements_traceability`
- `run_verification`
- `write_state`
- `sync_agent_metadata`

这样做的好处是：

- Agent 设计可以保持平台无关
- 当前 Codex 环境可以有自己的适配方式
- 以后迁移到别的 Agent Runtime 时，契约层不用重写

## 快速开始

### 1. 初始化

```bash
bash scripts/bootstrap.sh
```

这个命令会：

- 运行控制面自检
- 同步 `agents/*/agent.json`
- 同步本地 skills 链接
- 安装 nightly evolution 的 cron

### 2. 运行控制面自检

```bash
python3 -m tools.control_plane doctor
```

### 3. 查看合法工作流路径

```bash
python3 -m tools.control_plane workflow-dry-run
```

### 4. 手动执行元数据同步

```bash
python3 -m tools.control_plane sync-agent-metadata
```

### 5. 在宿主内启动 AEGIS

在 Claude Code 中：

- `/aegis 帮我开发一个聊天页面`
- `/aegis 帮我调研 xx 项目并输出 PRD`

在 Codex 中：

- 触发 `aegis` skill，并把自然语言目标交给当前会话

### 6. 通过控制面推进状态

```bash
python3 -m tools.control_plane write-state --workflow <workflow> --state <STATE>
```

这个命令现在主要用于 debug、人工接管和 fallback 场景。它只允许合法状态迁移，并会拒绝绕过 `next_state_hint` 的推进。

## 如何使用

当前项目的主使用方式已经是“在宿主会话里运行 AEGIS bot”，手动模式和外部 runner 都退到 debug / fallback。

### 使用方式 1：在 Claude / Codex 当前会话里触发 AEGIS

1. 初始化环境

```bash
bash scripts/bootstrap.sh
```

2. 在宿主里直接输入请求

Claude Code:

- `/aegis 帮我开发一个聊天页面`
- `/aegis 帮我调研 xx 项目并输出 PRD`

Codex:

- 触发 `aegis` skill，并把自然语言目标交给当前会话

host-native AEGIS 会自动完成：

- 创建 workflow id
- 路由 workflow type
- 写入 `intent-lock.json`
- 初始化 `state.json`
- 让当前宿主会话进入 orchestrator 模式
- 自动运行 hook 与 gate 校验
- 自动进入 `review -> fix -> re-review -> ... -> LGTM`
- 在到达目标状态或人工确认节点时停下

### 使用方式 2：bootstrap / fallback 模式

如果你要 debug，或者宿主内 skill 还没接好，可以用 fallback：

```bash
python3 -m tools.automation_runner bootstrap "帮我开发一个聊天页面"
python3 -m tools.automation_runner run "帮我调研 xx 项目并输出 PRD" --runtime codex
```

说明：

- `bootstrap` 只负责创建 workflow 与 intent lock，适合 host-native skill 内部调用
- `run` 会递归调用外部 runtime，保留为 fallback/debug
- `codex` 适配器是 fallback 层优先路径
- `claude` 适配器已接入，但仍偏实验性

### 使用方式 3：恢复一个暂停中的 workflow

```bash
python3 -m tools.automation_runner resume --workflow <workflow-id>
```

这适用于：

- runner 到达人工确认节点后继续执行
- 上一次 runtime 中断后继续推进
- 你修复了一轮 review loop 产物后继续自动跑后续阶段

### 使用方式 4：查看请求会被路由成什么 workflow

```bash
python3 -m tools.automation_runner route "帮我调研 xx 项目并输出 PRD"
```

这会返回：

- `workflow_type`
- `target_state`
- `normalized_goal`
- `routing_rationale`

### 使用方式 5：需要时手动接管

如果你要 debug、人工修复、或在 runner 停下后接管，也可以退回控制面命令：

```bash
python3 -m tools.control_plane write-state --workflow <workflow> --state <STATE>
bash .aegis/hooks/pre-agent-run.sh <agent> <workflow>
bash .aegis/hooks/post-agent-run.sh <agent> <workflow>
```

## 一个典型场景怎么跑

### 场景 1：调研一个产品方向并产出 PRD

一句话：

`/aegis 帮我调研 xx 项目并输出 PRD`

runner 的自动目标是：

1. 进入 `L1_RESEARCH`
2. 产出研究结果
3. 通过 `L1_REVIEW`
4. 进入 `L2_PLANNING`
5. 产出：
   - `PRD.md`
   - `architecture.md`
   - `task_breakdown.json`
   - `requirements-lock.json`
6. 通过 `L2_REVIEW`
7. 在准备进入 `L3_DEVELOP` 前停下

这意味着这个请求的目标不是“继续开发”，而是“得到 review 通过的 PRD 与锁定需求”。

### 场景 2：在锁定需求下开发一个项目

一句话：

`/aegis 帮我开发一个聊天页面`

runner 的自动目标是：

1. 自动完成 research
2. 自动完成 planning 与 `requirements-lock.json`
3. 自动进入 `L3_DEVELOP`
4. 自动完成 `L3_CODE_REVIEW`
5. 自动完成 `L3_SECURITY_AUDIT`
6. 自动完成 `L4_VALIDATE`
7. 自动完成 `L4_REVIEW`
8. 在准备进入 `L5_DEPLOY` 前停下，等待人工提供部署环境或批准

## 当前项目边界

为了避免 README 造成误解，这里明确当前边界：

- 已实现 host-native 入口 skill、intent routing、bootstrap helper 和 fallback runner
- `/aegis ...` 的主产品语义已经在仓库里落成 skill 与架构规范
- Claude/Codex 对 repo-local skill 的具体触发方式仍受宿主能力影响
- fallback runner 仍然存在，但已经降级为 debug / 兼容路径
- 项目已经支持扩展新的 agent / workflow type，但新增能力仍需要补 registry、contracts、skills 和控制面校验
- deploy 阶段默认仍会在需要人工信息时停下，不会伪造环境参数继续推进

## Hook 与治理入口

### Pre-run Hook

```bash
bash .aegis/hooks/pre-agent-run.sh <agent> <workflow>
```

用途：

- 校验 workflow id
- 校验当前状态是否允许该 agent 执行
- 校验输入是否齐备
- 校验依赖契约是否存在
- 从 L3 起校验 requirements lock 是否存在且 hash 正确

### Post-run Hook

```bash
bash .aegis/hooks/post-agent-run.sh <agent> <workflow>
```

用途：

- 校验 agent 输出是否符合 registry 声明
- 校验 gate 所需产物是否存在
- 校验 review loop 产物
- 在 L2 写入需求锁哈希
- 在 L4 校验需求追踪结果
- 将 workflow 变更提交进 Git

## Evolution

nightly evolution 入口：

```bash
bash .aegis/schedules/nightly-evolution.sh
```

内部实际调用：

```bash
python3 -m tools.control_plane evolution-run
```

演进规则：

- 在隔离 worktree 中进行
- 逐个评估开启 `evolution=true` 的 Agent
- 仅允许低风险、确定性的优化
- 候选变更必须提升评分
- 候选变更必须重新通过 `doctor`
- 所有结果都进入 `.aegis/core/evolution.log`

## Review Loop 产物

每个 gated review 目录会按轮次沉淀这些产物：

- `review-round-N.md`
- `fix-response-round-N.md`
- `review-loop-status.json`
- `review-passed.json` 仅在 `LGTM` 时存在

该机制来自 [docs/requirements/review-fix-loop.md](/Users/it/aegis-os/docs/requirements/review-fix-loop.md)。

## 关键文件

- `.aegis/core/registry.json`
  Agent 注册表，系统唯一真相源

- `.aegis/core/registry.schema.json`
  Registry 结构校验

- `.aegis/core/orchestrator.yml`
  状态机、门禁、目录规则、演进配置

- `shared-contexts/tool-contracts.yml`
  抽象工具契约定义与运行时适配说明

- `shared-contexts/requirements-lock-schema.json`
  需求冻结文件 schema

- `shared-contexts/requirements-traceability-schema.json`
  QA 需求追踪文件 schema

- `shared-contexts/intent-lock-schema.json`
  自动流水线入口的 intent lock schema

- `agents/aegis/SKILL.md`
  宿主内 `/aegis` 入口 skill

- `docs/AEGIS-host-native-architecture-v1.md`
  host-native AEGIS 架构说明

- `tools/automation_runner/`
  bootstrap helper、fallback runner 与 runtime adapter

## 当前保证

目前这个项目已经具备这些控制能力：

- 自然语言请求自动拉起 workflow
- 自动 workflow type 路由
- 自动状态推进与自动 runner 停点控制
- 机器可读的状态机配置
- 单一真相的 Agent 注册表
- 派生元数据一致性检查
- 工具契约可解析性检查
- 独立 reviewer 门禁约束
- Review-fix-LGTM 闭环约束
- intent lock 与 requirement lock 双层锁定
- 合法状态迁移约束
- 需求锁定与需求漂移防护
- QA 需求追踪要求
- 可审计的演进日志

## 适合谁

这个项目适合：

- 想搭建企业级多 Agent 研发流程的人
- 想严格控制 AI 执行边界、需求准确性和审计链路的团队
- 想把“Agent 规范”升级成“Agent 控制面”的工程团队

## 常用命令

```bash
# host-native fallback bootstrap
python3 -m tools.automation_runner bootstrap "帮我开发一个聊天页面"

# 自动路由但不执行，只看识别结果
python3 -m tools.automation_runner route "帮我调研 xx 项目并输出 PRD"

# 恢复一个已暂停的 workflow
python3 -m tools.automation_runner resume --workflow <workflow-id>

# 全量自检
python3 -m tools.control_plane doctor

# 同步派生 agent 元数据
python3 -m tools.control_plane sync-agent-metadata

# 同步本地 skills
python3 -m tools.control_plane sync-agents

# 查看状态机路径
python3 -m tools.control_plane workflow-dry-run

# 合法推进状态
python3 -m tools.control_plane write-state --workflow demo --state L1_RESEARCH

# 手动运行 nightly evolution
python3 -m tools.control_plane evolution-run
```
