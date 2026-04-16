# AEGIS OS

AEGIS OS 是一个 Git-native 的多 Agent 协作工作流系统，用来把产品需求从研究、规划、开发、审查、验证一直推进到发布，并且在过程中强制执行状态机、门禁评审、需求锁定和元数据一致性。

它不是某个单一业务应用，而是一个面向企业 AI 研发流程的控制面项目。

## 解决什么问题

多 Agent 系统常见的问题不是“不会做事”，而是：

- 需求在执行过程中漂移
- Agent 之间职责边界不清
- Review 只是口头约定，不是强约束
- 元数据、配置、脚本、文档经常失真
- 自我演进无法审计，也无法安全回滚

AEGIS OS 的目标就是把这些问题收进一个可校验、可追踪、可回放的控制面里。

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

### 4. Strict Gated Workflow

AEGIS 使用固定状态机推进：

`INIT -> L1_RESEARCH -> L1_REVIEW -> L2_PLANNING -> L2_REVIEW -> L3_DEVELOP -> L3_CODE_REVIEW -> L3_SECURITY_AUDIT -> L4_VALIDATE -> L4_REVIEW -> L5_DEPLOY -> L5_REVIEW -> DONE`

如果门禁失败超出重试限制，或者安全审计出现阻断问题，流程会进入 `BLOCKED`。

### 5. Requirement Locking

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

workflows/
```

## Agent 角色

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
- 校验 `review-passed.json`
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

## 当前保证

目前这个项目已经具备这些控制能力：

- 机器可读的状态机配置
- 单一真相的 Agent 注册表
- 派生元数据一致性检查
- 工具契约可解析性检查
- 独立 reviewer 门禁约束
- Review artifact schema 校验
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
# 全量自检
python3 -m tools.control_plane doctor

# 同步派生 agent 元数据
python3 -m tools.control_plane sync-agent-metadata

# 同步本地 skills
python3 -m tools.control_plane sync-agents

# 查看状态机路径
python3 -m tools.control_plane workflow-dry-run

# 手动运行 nightly evolution
python3 -m tools.control_plane evolution-run
```
