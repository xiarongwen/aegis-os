# AEGIS 1.0 PRD

**版本:** 1.0  
**日期:** 2026-04-21  
**状态:** 1.0 新主线产品基线  
**产品方向:** 多 Agent CLI 协作编程 harness  
**主功能:** Multi-Agent CLI Coding Run with Autopilot Cockpit  

---

## 1. 产品结论

AEGIS 1.0 是一次新主线开发，不是在旧 v1/v2 实现上继续打补丁。

旧版本中已经走偏的 governance workflow、重型控制面、散落文档和不一致 CLI 契约，全部进入 legacy。1.0 只迁移其中经过确认的可复用零件，例如 runtime bridge、session store 思路、现有 collaboration pattern 经验和测试样例。

AEGIS 1.0 不做 v1 的治理型 workflow 系统。

AEGIS 1.0 只聚焦一个主功能：

> 用户输入一个编程任务，AEGIS 自动选择协作模式、角色和本地 agent CLI/runtime，让 Claude Code 与 Codex CLI 协作完成任务，并用一个实时终端驾驶舱展示进度、任务状态和动态日志。

一句话：

> AEGIS 1.0 = `aegis ulw "<task>"` 启动的多 Agent CLI 编程 autopilot。

---

## 2. 背景与问题

当前开发者已经可以单独使用 Claude Code 或 Codex CLI 写代码，但真实工作中会遇到几个问题：

1. 单个 agent CLI 容易卡在自己的盲区。
2. 用户需要手动判断该让哪个 agent/runtime 做规划、写代码、审查、测试。
3. 多 Agent 协作没有统一状态，结果散落在终端、文件和聊天记录里。
4. 执行过程不可见，用户不知道任务卡在哪里。
5. 失败后缺少可恢复的 session、日志和复盘信息。

AEGIS 1.0 要解决的不是“再做一个 AI 问答 CLI”，而是把一次编程任务变成一个可观察、可恢复、可复盘的多 Agent CLI 协作运行。

---

## 3. 目标用户

### 主要用户

- 日常使用 Claude Code / Codex 的开发者。
- 想让多个 agent CLI 分工完成开发任务的个人开发者。
- 需要快速实现、审查、修复、补测试的小团队。
- 想要类似 `ultrawork` 体验，但希望运行在 AEGIS/Codex/Claude 组合上的用户。

### 用户心智

用户不想先学习 workflow、gate、team pack、lock file。

用户真正想要的是：

```bash
aegis ulw "修复登录 bug 并补测试"
```

然后看到一个终端驾驶舱持续更新：

- 总体完成到哪里。
- 哪些子任务在跑。
- 哪些 agent/runtime 正在工作。
- 哪些审查失败需要返修。
- 最终产出和日志在哪里。

---

## 4. 产品定位

### AEGIS 是什么

AEGIS 是一个多 Agent CLI 协作编程 harness。

它负责：

- 理解编程任务。
- 判断任务类型。
- 选择协作模式。
- 选择角色和 agent runtime。
- 执行或模拟执行。
- 展示实时进度。
- 保存 session、日志、输出和成本。
- 支持恢复和复盘。

### AEGIS 不是什么

AEGIS 1.0 不是：

- 企业治理 workflow 系统。
- L1-L5 状态机平台。
- requirements lock / gate review 系统。
- Team Pack 产品。
- Web IDE。
- 聊天机器人。
- 单纯的脚手架生成器。

v1/v2 旧代码可以暂时保留为 legacy/internal，但不进入 1.0 产品主线。1.0 新代码应有清晰边界，避免继续耦合旧 control plane、automation runner、workflow artifacts 和历史命令形态。

---

## 5. 1.0 主功能

### 功能名称

**Multi-Agent CLI Coding Run**

### 主命令

```bash
aegis ulw "<task>"
aegis ultrawork "<task>"
```

### 辅助命令

```bash
aegis "<task>"
aegis run "<task>"
aegis pair "<task>"
aegis swarm "<task>"
aegis pipeline "<task>"
aegis moa "<task>"
```

### 主功能流程

```text
User Task
  -> Intent / Task Router
  -> Collaboration Strategy
  -> Role / Agent Runtime Resolution
  -> Execution Plan
  -> Runtime Execution
  -> Autopilot Cockpit
  -> Session / Logs / Outputs
  -> Final Result
```

### `aegis ulw` 默认语义

`aegis ulw "<task>"` 是高执行力入口，默认：

```text
execute = true
mode = balanced
watch = true
bridge = auto
```

如果 tmux bridge 可用，优先用 bridge 展示 agent CLI 运行。

如果 bridge 不可用，降级到普通 runtime 执行，并在 cockpit 中提示：

```text
bridge unavailable -> running without tmux bridge
```

---

## 6. 核心用户场景

### 场景一：自动完成一个 bug 修复

```bash
aegis ulw "修复登录接口 SQL 注入问题，并补对应测试"
```

期望行为：

- 识别为 debugging/testing。
- 选择 pipeline 或 pair。
- Codex 负责修复和测试。
- Claude 负责审查或复杂推理。
- 运行过程显示在 cockpit。
- 最终输出 session id、关键结果、日志路径。

### 场景二：重构一个模块

```bash
aegis ulw "重构认证模块，保持外部行为不变"
```

期望行为：

- 识别为 refactoring。
- 选择 pair。
- builder 生成方案或补丁。
- reviewer 审查行为兼容性。
- 如果审查不通过，进入返修。

### 场景三：并行补测试

```bash
aegis swarm "为支付模块补齐单元测试和边界测试" --execute
```

期望行为：

- splitter 拆分测试区域。
- 多个 worker 并行。
- aggregator 汇总测试策略和结果。
- cockpit 显示并行 worker 状态。

### 场景四：架构方案评审

```bash
aegis moa "评审当前插件架构是否适合支持多模型 fallback"
```

期望行为：

- 多个模型或角色给出独立意见。
- aggregator 汇总。
- 输出优先级明确的建议。

---

## 7. Autopilot Cockpit 终端页面

### 产品目标

AEGIS 1.0 的终端页面不是普通日志输出，而是一个实时任务驾驶舱。

它要回答三个问题：

1. 整体任务完成到哪里了。
2. 每个阶段、子任务、模型现在是什么状态。
3. 最近发生了什么，是否有审查、返修、失败或人工介入。

### 入口

```bash
aegis ulw "<task>"
aegis ulw "<task>" --watch
aegis watch <session_id>
```

`ulw` 默认进入 watch。

### 页面结构

```text
┌─ AEGIS AUTOPILOT  <workspace> / <session_id> ───────────────────────────┐
│ ███████████░░░░░  72%   running                                         │
│ 4/7 stages   08m41s   dispatch x12   parallel x3   review x2   fix x1   │
└─────────────────────────────────────────────────────────────────────────┘

┌─ 任务进展 ───────────────────────────────────────────────────────────────┐
│ S1  done     plan       planner          claude      01m12s              │
│ S2  running  build      builder-a        codex       editing auth.py     │
│ S3  running  tests      builder-b        codex       generating tests    │
│ S4  queued   review     reviewer         claude      waiting             │
│ S5  queued   verify     verifier         codex       waiting             │
└─────────────────────────────────────────────────────────────────────────┘

┌─ 动态 ───────────────────────────────────────────────────────────────────┐
│ 17:35 start       routed as debugging -> pipeline                        │
│ 17:36 dispatch    S2 builder-a -> codex                                  │
│ 17:36 dispatch    S3 builder-b -> codex                                  │
│ 17:39 result      S3 generated 12 tests                                  │
│ 17:40 review      reviewer requested fix for auth edge case              │
│ 17:41 fix         S2 applying reviewer feedback                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Cockpit 数据来源

第一版数据来自：

```text
.aegis/state/sessions.db
.aegis/state/logs/
.aegis/state/responses/
```

后续可抽象成统一 event stream。

### Cockpit 必须展示的状态

顶部总览：

- workspace。
- session id。
- 总进度。
- session 状态。
- 已完成 stage 数。
- 耗时。
- dispatch 数。
- 并行 worker 数。
- review/fix 次数。

任务进展：

- stage name。
- stage status。
- role。
- model。
- runtime。
- duration。
- 简短摘要。

动态事件：

- route。
- dispatch。
- stage_start。
- stage_result。
- review_feedback。
- retry。
- fallback。
- bridge_unavailable。
- error。
- complete。

### 技术建议

1.0 推荐使用：

```text
Textual + Rich
```

第一版可以轮询 sqlite/log 文件，不强求实时事件总线。

---

## 8. 协作模式

### Single

一个 agent runtime 完成任务。

适合：

- 简单代码生成。
- 文档。
- 小修复。

### Pair

一个 agent runtime 写，一个 agent runtime 审。

适合：

- 重构。
- 风险较高的代码修改。
- 需要 review/fix loop 的任务。

### Swarm

拆分任务，多 worker 并行，再聚合。

适合：

- 测试生成。
- 多文件分析。
- 大范围重复性任务。

### Pipeline

按阶段串行执行。

适合：

- 分析 -> 修复 -> 验证。
- 设计 -> 编码 -> 审查。

### MoA

多个候选 agent runtime 或角色独立输出，再综合。

适合：

- 架构评审。
- 不确定性高的问题。
- 多方案比较。

---

## 9. 角色与 Agent Runtime

### 1.0 最小角色

AEGIS 1.0 在内部引入角色层，但不必暴露给普通用户。

```text
orchestrator
planner
builder
reviewer
researcher
verifier
aggregator
```

### 角色职责

orchestrator：

- 负责运行总控。
- 决定协作模式。
- 控制 session 状态。

planner：

- 负责复杂任务拆解和阶段设计。

builder：

- 负责代码生成、修改、修复。

reviewer：

- 负责审查实现质量、风险和遗漏。

researcher：

- 负责代码库探索、文档或上下文检索。

verifier：

- 负责测试、验证、诊断。

aggregator：

- 负责汇总多个 worker 或多个候选输出。

### 1.0 默认 Agent Runtime 策略

默认 agent runtime 由 `.aegis/aegis-1.json` 和内置 runtime registry 控制。

1.0 内置 agent runtime：

```text
codex
claude
```

默认倾向：

```text
builder    -> codex
reviewer   -> claude
planner    -> claude
verifier   -> codex
aggregator -> claude
```

显式 `--agents` 优先级最高，不得被静默覆盖。

兼容旧参数 `--models`，语义等价于 `--agents`，但 1.0 文档和产品叙事应使用 agent/runtime。

---

## 10. 系统架构

### 1.0 主链路

```text
CLI
  -> TaskRouter
  -> RolePlanner / AgentRuntimeResolver
  -> MultiAgentExecutor
  -> ExecutionPlan
  -> CollaborationPattern
  -> RuntimeManager
  -> RuntimeAdapter
  -> SessionStore
  -> Cockpit
```

### 当前代码映射

```text
tools/aegis_v2/cli.py
  CLI 命令、参数、输出

tools/aegis_v2/router.py
  任务分类、复杂度、协作策略、模型选择

tools/aegis_v2/executor.py
  plan 构建、session 创建、执行调度

tools/aegis_v2/collaboration.py
  single/pair/swarm/pipeline/moa

tools/aegis_v2/runtime.py
  codex/claude/simulate/bridge runtime

tools/aegis_v2/session.py
  sqlite session、checkpoint、message

tools/runtime_bridge/cli.py
  tmux bridge
```

### 1.0 新增建议模块

```text
tools/aegis_v2/tui.py
  cockpit 终端 UI

tools/aegis_v2/events.py
  session event projection

tools/aegis_v2/roles.py
  role definitions and role-to-model defaults

tools/aegis_v2/watch.py
  watch session and stream status
```

---

## 11. 数据模型

### Session

必须记录：

- session_id。
- request。
- task_type。
- strategy。
- models。
- mode。
- status。
- metadata。
- created_at。
- updated_at。

### Execution Plan

必须记录：

- strategy。
- steps。
- max_iterations。
- worker_count。
- aggregator_model。

### Step

必须记录：

- name。
- role。
- kind。
- model。
- prompt。
- status。
- start/end time。
- summary。

### Event

1.0 cockpit 需要投影出统一事件：

```text
event_id
session_id
timestamp
event_type
stage_name
role
model
status
summary
detail
metadata
```

事件类型：

```text
route
plan_created
execution_start
stage_start
stage_result
review_feedback
retry
fallback
bridge_unavailable
error
complete
```

---

## 12. 命令范围

### 1.0 必须支持

```bash
aegis "<task>"
aegis run "<task>"
aegis ulw "<task>"
aegis ultrawork "<task>"
aegis pair "<task>"
aegis swarm "<task>"
aegis pipeline "<task>"
aegis moa "<task>"
aegis watch <session_id>
aegis router dry-run "<task>"
aegis models list
aegis models test
aegis session list
aegis session show <session_id>
aegis session resume <session_id>
aegis session recover <session_id>
aegis cost report
aegis config show
aegis config init
```

### 1.0 应迁移或包装

```bash
aegis bridge up
aegis bridge status
aegis bridge stop
aegis doctor
aegis install
```

如果 1.0 时间不足，可以临时保留：

```bash
aegis ctl bridge-up
aegis ctl doctor
```

但 README 不应把它们作为主入口。

### 1.0 不展示为主命令

```text
workflow-dry-run
pre-agent-run
post-agent-run
write-gate-review
write-state
compose-team-pack
create-team-pack
invoke-team-pack
evolution-run
```

---

## 13. 非功能需求

### 可见性

- 长任务必须有 cockpit 或 watch。
- 每个 stage 必须有状态。
- runtime 失败必须显示原因和下一步建议。

### 可恢复性

- 每次 run 必须创建 session。
- session show 必须能复盘 routing、plan、messages、checkpoints。
- recover 必须能基于原 request 和 context 重新启动，并记录来源 session。

### 一致性

- `routing.models`、`execution_plan.steps[*].model`、runtime 实际 agent identity 必须一致。这里的 `model` 是兼容字段名，1.0 语义为 agent runtime。
- 显式 `--agents` 不允许被静默覆盖；`--models` 只作为兼容别名。

### 降级

- bridge 不可用时可降级普通执行。
- 指定 agent runtime 不可用时，如果是系统默认选择，可以 fallback。
- 指定 agent runtime 不可用时，如果是用户显式指定，必须报清晰错误，不静默替换。

### 简洁性

- 默认用户不需要理解 v1 workflow。
- 默认用户不需要手动选择 pair/swarm/pipeline/moa。
- 默认用户只需要知道 `aegis ulw`。

---

## 14. 1.0 范围

### In Scope

- `ulw/ultrawork` 主入口。
- 裸请求自动映射到 `run`。
- TaskRouter。
- AgentRuntimeRegistry。
- single/pair/swarm/pipeline/moa。
- RuntimeManager。
- Codex CLI adapter。
- Claude CLI adapter。
- simulate mode。
- tmux bridge。
- sqlite session store。
- session list/show/resume/recover。
- cost report。
- cockpit/watch 终端页面第一版。
- README/Quickstart 1.0 收口。

### Out of Scope

- Web UI。
- IDE 插件。
- 企业治理。
- Team Pack 产品化。
- L1-L5 workflow。
- requirements lock。
- gate review。
- nightly evolution。
- 长期记忆学习。
- 完整 OpenAI/Anthropic API SDK 接入。
- LSP/AST-Grep 完整工具层。

---

## 15. 里程碑

### M0: PRD 与架构冻结

交付：

- `docs/AEGIS-1.0-PRD.md`
- `docs/AEGIS-1.0-main-function-and-architecture.md`

验收：

- 主功能唯一。
- v1 legacy 边界明确。
- 1.0 命令范围明确。

### M1: CLI 收口

交付：

- `aegis ulw`
- `aegis ultrawork`
- `aegis watch`
- 裸请求稳定映射。
- README/Quickstart 同步。

验收：

```bash
aegis "修复 bug"
aegis ulw "修复 bug" --simulate
aegis router dry-run "修复 bug" --format json
```

### M2: Agent Runtime 一致性与角色层

交付：

- role definitions。
- role-to-runtime defaults。
- `--agents` 一致性。
- plan/runtime agent identity 一致。

验收：

- 显式 agent runtime 不被覆盖。
- pair/swarm/pipeline/moa plan 和 runtime 一致。

### M3: Cockpit 第一版

交付：

- Textual/Rich cockpit。
- session watch。
- 顶部总览。
- 任务进展。
- 动态事件。

验收：

```bash
aegis ulw "生成测试" --simulate
aegis watch <session_id>
```

### M4: 1.0 稳定化

交付：

- runtime error 改善。
- bridge fallback。
- session recover。
- cost report。
- 测试补齐。

验收：

```bash
python3 -m unittest tests.test_aegis_v2 tests.test_runtime_bridge
```

---

## 16. 验收标准

### 产品验收

- 用户能通过 `aegis ulw "<task>"` 启动一次完整多 Agent CLI 编程运行。
- 用户能看到终端 cockpit。
- 用户能知道当前进度、运行中的 agent/runtime、失败原因和最终结果。
- 用户不需要理解 v1 workflow。

### 技术验收

- 所有主命令可运行。
- 所有协作模式支持 simulate execute。
- session 可 list/show/recover。
- runtime 缺失时错误可理解。
- bridge 可用时能投递到 tmux。
- bridge 不可用时可降级或清晰报错。

### 文档验收

- README 首屏只讲 1.0。
- Quickstart 只展示 1.0 主命令。
- v1 相关内容标为 legacy/internal。
- 命令示例和真实 CLI 一致。

---

## 17. 成功标准

AEGIS 1.0 的成功标准不是功能数量，而是主链路是否清楚、稳定、有产品感。

成功状态：

```text
用户安装后输入 aegis ulw "<task>"，
AEGIS 能自动组织多个 agent/runtime 协作，
在终端 cockpit 里实时展示进度，
最终给出可复盘、可恢复的 session 和结果。
```

这就是 1.0。
