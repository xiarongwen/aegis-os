# AEGIS Cross-Project Architecture v1

## Summary

本方案用于把当前 `aegis-os` 从“只能在本仓库目录下运行的 repo-bound 系统”重构为“可在任意业务项目中附着执行的宿主内 AEGIS Bot 系统”。

这次重构的目标不是把 AEGIS 变成一个外部 CLI 工具，也不是把它变成需要复制到每个项目里的产物框架。

正确目标是：

- AEGIS 仍然是运行在 Claude Code / Codex 宿主里的 bot
- AEGIS 仍然以治理和防漂移为核心，而不是以脚手架生成为核心
- AEGIS Core 全局维护
- 任意业务项目只保留最小项目配置
- 每次 workflow 启动时编译出唯一可执行的 runtime snapshot

一句话定义：

**AEGIS 应该从一个 repo-bound control-plane 项目，升级成一个 host-native、workspace-aware、cross-project attachable 的 Agent Operating Core。**

---

## Problem

当前仓库已经具备：

- host-native `/aegis ...` 产品形态
- 单一真相 registry
- control-plane 执法能力
- requirement lock
- review-fix-LGTM loop
- L3 的 DRY-first / 并行任务 / 宿主增强约束

但它仍有一个结构性问题：

- 它默认假设当前项目根目录就是 `aegis-os`
- workflow 产物默认写在本仓库的 `workflows/`
- control plane、hooks、automation runner 都把当前 repo 当成唯一执行空间

这会导致：

- AEGIS 不能自然附着到别的业务项目
- 用户必须进入 `aegis-os` 仓库才能使用系统
- AEGIS 更像一个特殊项目，而不是一个通用 bot 底座
- 产品形态和“在任意 Claude/Codex 工作区里说 `/aegis ...` 就开始工作”的目标不一致

---

## Non-Goals

这次重构明确不做以下事情：

- 不把 AEGIS 改造成以 `./aegis run "..."` 为主入口的 CLI 产品
- 不把整个 `aegis-os` 仓库复制到每个业务项目中
- 不允许每个业务项目维护一整套独立 registry / orchestrator / schemas
- 不放松现有治理能力
- 不为了跨项目而牺牲 requirement lock、review loop、DRY、并行开发治理

如果重构过程中出现下面这些倾向，就说明需求已经偏移：

- “先把 CLI 做起来，bot 以后再说”
- “让每个项目自己维护完整 agent 系统”
- “把产物目录设计放在治理能力之前”
- “为了兼容不同项目，降低控制面的约束强度”

---

## Product Invariants

跨项目化之后，以下原则必须保持不变：

### 1. Host-native Entry 不变

主入口仍然是：

- `/aegis 帮我开发一个聊天页面`
- `/aegis 帮我调研 xx 项目并输出 PRD`

当前 Claude/Codex 宿主会话仍然是 orchestrator。

### 2. AEGIS 仍是治理系统

AEGIS 的核心仍然是：

- 锁定目标
- 约束执行
- 控制漂移
- 做 review / fix 闭环
- 沉淀审计链路

而不是单纯的代码生成工具。

### 3. 单一执行真相必须存在

即使引入全局 core 和项目本地配置，也不能重新回到双源真相。

真正执行时必须始终存在：

- 一个唯一的 runtime snapshot

### 4. L3 治理能力必须保留

跨项目化后依然必须保留：

- `requirements-lock.json`
- `task_breakdown.json`
- `implementation-contracts.json`
- `reuse-audit.json`
- `review -> fix -> re-review -> ... -> LGTM`
- `DRY-first`
- `parallel_by_default`
- `host_capability_enhancement`

---

## Target Architecture

目标架构应拆成三层：

### 1. Global AEGIS Core

这是当前 `aegis-os` 仓库未来的正确身份。

职责：

- control plane
- orchestrator state machine
- base registry
- abstract tool contracts
- host capability map
- global agent skills
- schema definitions
- doctor / validate / dry-run / evolution
- 通用治理规则

这一层提供的是：

- 通用能力
- 通用规则
- 通用 agent 行为模型

这一层不应该假设：

- 当前工作区一定是 `aegis-os`
- workflow 产物一定写在 core 仓库中
- 被开发的业务代码一定和 core 在同一 repo

### 2. Project Local AEGIS Config

每个业务项目只放最小项目配置。

建议结构：

```text
<workspace-root>/
  .aegis/
    project.yml
    overrides/
    policies/
    runs/
    cache/
```

职责：

- 声明当前项目的技术栈
- 声明当前项目启用的 workflow / policy
- 对全局 agent 做最小覆盖
- 定义项目级测试、构建、部署规则
- 保存当前项目的 workflow 运行产物

这一层是“项目适配层”，不是“项目内复制一整套 AEGIS Core”。

### 3. Runtime Snapshot Layer

每次 workflow 启动时，必须从：

- Global AEGIS Core
- Project Local Config
- 当前用户请求

编译出一份运行时锁定快照。

建议结构：

```text
<workspace-root>/.aegis/runs/<workflow-id>/
  intent-lock.json
  project-lock.json
  registry.lock.json
  orchestrator.lock.json
  requirements-lock.json
  state.json
```

真正执行时，只允许信任：

- `project-lock.json`
- `registry.lock.json`
- `orchestrator.lock.json`
- `state.json`

也就是说：

**运行时真相高于全局真相和项目配置真相。**

这样才能避免 workflow 跑到一半时，底层配置被改掉导致执行漂移。

---

## Root Resolution Model

当前 repo 最大的技术问题之一，是很多逻辑默认只有一个 `ROOT`。

跨项目化后必须改成三种 root：

- `core_root`
- `workspace_root`
- `run_root`

### core_root

AEGIS Core 安装目录。

包含：

- `tools/control_plane/`
- `agents/`
- `shared-contexts/`
- `docs/`
- `tests/`

### workspace_root

当前被 AEGIS 接管的业务项目根目录。

解析优先级建议固定为：

1. 用户显式指定的 workspace
2. 当前 Claude/Codex 会话 cwd
3. 当前 cwd 向上查找 git root
4. 若找不到 git root，则使用 cwd

### run_root

当前 workflow 的运行目录。

建议固定为：

```text
<workspace-root>/.aegis/runs/<workflow-id>/
```

所有 workflow 产物、锁文件、状态文件都应该写到这里，而不是写回 core 仓库。

---

## Recommended Repository Roles

重构后建议把当前仓库视为：

```text
aegis-os/
  core/
  agents/
  shared-contexts/
  host/
  docs/
  tests/
  installers/
```

即使短期内不真的把目录全部挪动，也要先在逻辑上完成这种分层：

- 当前仓库是 AEGIS Core 仓库
- 业务项目是 workspace
- workflow 产物属于 workspace

不要继续把当前仓库理解成某个业务 workflow 的默认承载仓库。

---

## Project Local Minimal Config

每个业务项目建议最少只包含一份：

### `.aegis/project.yml`

建议字段：

- `project_id`
- `project_type`
- `stack`
- `enabled_workflows`
- `default_output_policy`
- `artifact_retention`
- `review_policy`
- `test_commands`
- `build_commands`
- `deploy_policy`
- `agent_overrides`

### `.aegis/overrides/`

只允许放补充性 override，不允许放完整复制版的 core 配置。

允许覆盖：

- 某些 agent 的项目特有提示
- 项目专属 workflow policy
- 特定测试 / 构建 / 部署命令
- 项目级 reviewer 增强规则

不允许覆盖：

- 核心状态机语义
- requirement lock 基本规则
- review-fix-LGTM 闭环语义
- registry 的核心 identity model

---

## Single Source Of Truth Model

跨项目后，真相来源要重新定义。

建议分成三层：

### Layer 1: Global Truth

由 AEGIS Core 提供：

- base registry
- base orchestrator
- base contracts
- base host capability map

### Layer 2: Project Truth

由当前 workspace 提供：

- `.aegis/project.yml`
- 项目 override
- 项目 policy

### Layer 3: Runtime Truth

由 workflow 启动时生成：

- `project-lock.json`
- `registry.lock.json`
- `orchestrator.lock.json`
- `requirements-lock.json`
- `state.json`

运行时只允许信任第三层。

这条必须成为核心规则，否则跨项目后会重新出现：

- 到底该信全局配置还是项目配置
- workflow 过程中配置被修改后如何处理
- agent 到底该按哪个版本执行

---

## Workflow Artifact Relocation

当前顶层 `workflows/` 目录不适合作为跨项目模式的默认产物目录。

建议迁移为：

```text
<workspace-root>/.aegis/runs/<workflow-id>/
```

好处：

- 不污染业务项目顶层目录
- 产物天然归属于当前项目
- 更符合“AEGIS 是附着在项目上的治理层”
- 更容易做 `.gitignore`、归档、清理和 retention policy

迁移后的核心产物仍然保留，但路径变为：

- `.aegis/runs/<workflow-id>/intent-lock.json`
- `.aegis/runs/<workflow-id>/state.json`
- `.aegis/runs/<workflow-id>/l2-planning/task_breakdown.json`
- `.aegis/runs/<workflow-id>/l2-planning/implementation-contracts.json`
- `.aegis/runs/<workflow-id>/l3-dev/frontend/reuse-audit.json`
- `.aegis/runs/<workflow-id>/l3-dev/backend/reuse-audit.json`

---

## Host-Native Cross-Project UX

未来正确的用户体验应该是：

在任意业务项目目录中打开 Claude/Codex，然后直接说：

- `/aegis 接管当前项目`
- `/aegis 帮我调研当前项目要做的方向并输出 PRD`
- `/aegis 帮我为当前项目开发一个聊天页面`
- `/aegis 审查当前项目的安全问题并给出修复闭环`

AEGIS 自动执行：

1. 识别当前 `workspace_root`
2. 查找 `.aegis/project.yml`
3. 若不存在，则初始化最小项目配置
4. 加载全局 core
5. 编译 runtime snapshot
6. 在当前项目的 `.aegis/runs/<workflow-id>/` 内推进 workflow

这一步必须保持：

- 宿主会话即 orchestrator
- control plane 负责治理
- CLI 只保留为 bootstrap / debug / fallback

---

## Runtime Resolution Flow

建议运行时解析流程固定为：

1. 接收用户自然语言目标
2. 解析 `workspace_root`
3. 加载 `.aegis/project.yml`
4. 合并 base registry 与项目 override
5. 合并 base orchestrator 与项目 policy
6. 生成：
   - `project-lock.json`
   - `registry.lock.json`
   - `orchestrator.lock.json`
7. 创建 `intent-lock.json`
8. 初始化 `state.json`
9. 使用 runtime snapshot 驱动后续所有执行

注意：

- 一旦 workflow 启动，不应继续直接读取“未锁定”的项目 override 作为执行真相
- 任何 change control 必须通过重新生成锁定文件来完成

---

## Override Rules

为了避免跨项目之后再次产生配置漂移，override 需要强约束。

### Allowed Overrides

- 项目技术栈说明
- 测试命令
- lint / build / deploy 命令
- 项目专属 reviewer policy
- agent 的项目补充提示
- artifact 保留和忽略策略

### Forbidden Overrides

- 删除 review-fix-LGTM 机制
- 删除 requirement lock 校验
- 删除 reviewer independence
- 取消 L3 的 DRY-first / parallel / implementation contracts / reuse audit 约束
- 修改核心状态含义
- 让项目本地直接成为新的完整 registry 真相

原则很简单：

**项目可以调整执行细节，但不能破坏全局治理底线。**

---

## Control Plane Refactor Requirements

当前控制面需要做的第一优先级改造不是“加更多命令”，而是“去掉 repo-root 假设”。

必须完成：

### 1. Path Context Injection

control plane 不能再只有：

- `ROOT`

而必须显式引入：

- `core_root`
- `workspace_root`
- `run_root`

### 2. Workspace-Aware Hooks

`pre-agent-run` 与 `post-agent-run` 应支持：

- 传入 workspace context
- 读取当前 run snapshot
- 在 workspace 中验证输入输出，而不是只在 core 仓库中验证

### 3. Snapshot-Based Validation

`doctor` 需要分层：

- `doctor core`
- `doctor workspace`
- `doctor run --workflow <id>`

这样才能分别验证：

- Core 本身是否完整
- 当前项目配置是否可附着
- 当前 workflow snapshot 是否一致

---

## Migration Phases

建议按四阶段渐进重构，避免一次性推倒。

### Phase 1: 路径解耦

目标：

- 去掉所有基于单一 `ROOT` 的 repo 绑定
- 为 control plane 引入 `core_root` / `workspace_root` / `run_root`

交付：

- path resolver
- workspace detection
- run-root abstraction

### Phase 2: 项目清单化

目标：

- 引入 `.aegis/project.yml`
- 引入项目级 override / policy 结构

交付：

- project manifest schema
- project-level config loader
- 项目 attach 流程

### Phase 3: 运行产物迁移

目标：

- 把当前 `workflows/` 迁移到 `.aegis/runs/`
- 所有 hook / state / artifact 路径改为 workspace-local

交付：

- run snapshot layout
- artifact migration rules
- workspace-local retention policy

### Phase 4: 全局安装与宿主绑定

目标：

- 把 AEGIS Core 变成宿主全局可用能力
- 在任意工作区中都能 `/aegis ...`

交付：

- global install mode
- host-native attach current workspace mode
- fallback/debug compatibility path

---

## Testing Requirements

跨项目化之后，至少要补这些测试：

### Core

- base registry / orchestrator / contracts 可被独立加载
- host capability map 可解析

### Workspace Attach

- 在一个没有 `.aegis/project.yml` 的项目中，AEGIS 能创建最小 attach 配置
- 在一个已有 `.aegis/project.yml` 的项目中，AEGIS 能正确读取项目配置

### Runtime Snapshot

- workflow 启动时能正确生成 `project-lock.json` / `registry.lock.json` / `orchestrator.lock.json`
- workflow 运行过程中修改项目配置不会影响当前 snapshot

### Governance

- requirement lock 仍然从 L3 起强制校验
- review-fix-LGTM 仍然按原语义工作
- L3 的 `task_breakdown.json` / `implementation-contracts.json` / `reuse-audit.json` 仍然必须存在

### Cross-Project

- 在不同技术栈项目中，AEGIS 可以读取项目 override
- 同一个全局 Core 可以附着多个不同 workspace

---

## Risks

### 1. 再次出现双源真相

如果运行时不生成锁定 snapshot，就会重新出现：

- 全局 core 一份
- 项目 override 一份
- workflow 临时状态又一份

这是最需要避免的风险。

### 2. 过度项目化导致核心分叉

如果允许项目本地维护完整 registry / orchestrator，就会导致每个项目都长成一套不同的 AEGIS。

这样系统很快会失去统一治理能力。

### 3. 重构时误把 CLI 做成主产品

跨项目化很容易诱导系统退回到：

- “做个全局 CLI 安装器”

但这不符合产品定位。

CLI 只能是：

- bootstrap
- debug
- fallback

不能重新成为主入口。

---

## Recommended Next Document

在本方案之后，建议继续补一份：

- `AEGIS-project-manifest-spec-v1.md`

用于定义：

- `.aegis/project.yml` schema
- override 允许覆盖哪些字段
- runtime snapshot 如何生成

---

## Final Decision

当前 repo 的正确重构方向是：

**把 `aegis-os` 升级为全局 AEGIS Core 仓库，使其作为宿主内 `/aegis ...` bot 的治理后端，在任意业务项目中通过 workspace attach 模式运行，并把项目级配置与运行产物收敛到当前项目的 `.aegis/` 下，同时在每次 workflow 启动时生成唯一可信的 runtime snapshot。**

这次重构中，以下内容必须保留不变：

- host-native bot 入口
- control-plane 治理中心地位
- requirement lock
- review-fix-LGTM loop
- L3 的 DRY-first / parallel-by-default / implementation contracts / reuse audit
- 宿主增强能力必须走抽象契约和映射层

只要这几条不被破坏，AEGIS 就能从“当前 repo 里的系统”升级成“任意项目里可用的专业多 Agent bot 底座”。
