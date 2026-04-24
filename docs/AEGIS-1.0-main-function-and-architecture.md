# AEGIS 1.0 主功能与主架构基线

**版本:** 1.0 baseline  
**日期:** 2026-04-21  
**状态:** 主线收口文档  
**结论:** AEGIS 1.0 只做一个主功能：多 Agent CLI 协作完成一个编程任务。

---

## 1. 治理结论

AEGIS 1.0 不再延续 v1 的治理型 workflow 产品线。

v1 中的 L1-L5 workflow、requirements lock、gate review、team pack、nightly evolution、复杂 artifact 审批链，不进入 1.0 主产品。

AEGIS 1.0 的主产品定义是：

> AEGIS 是一个面向 Claude Code、Codex CLI 和本地 runtime 的多 Agent CLI 协作编程 harness。用户输入一个编程任务，AEGIS 自动选择协作模式、角色和 agent runtime，并保存可恢复的 session。

一句话：

> AEGIS 1.0 = 一个命令，让多个本地 agent CLI 协作完成一个编程任务。

---

## 2. 1.0 主功能

### 主功能名称

**Multi-Agent CLI Coding Run**

### 用户入口

1. 默认入口：

```bash
aegis "修复登录接口的 SQL 注入问题"
```

2. 显式入口：

```bash
aegis run "修复登录接口的 SQL 注入问题"
```

3. 高执行力入口：

```bash
aegis ulw "把认证模块重构成清晰的 service/repository 结构"
aegis ultrawork "补齐支付模块测试并修复失败用例"
```

### 主功能承诺

用户给出一个编程任务后，AEGIS 1.0 必须完成：

1. 判断任务类型。
2. 选择协作模式。
3. 选择合适 agent runtime。
4. 生成执行计划。
5. 可选择真实执行或模拟执行。
6. 保存 session、日志、agent 输出和成本信息。
7. 支持查看、恢复和复盘。

### 1.0 的默认行为

`aegis "<task>"` 等价于：

```bash
aegis run "<task>"
```

默认只做规划，不强制执行真实 agent runtime 调用。

`aegis ulw "<task>"` 等价于高执行力模式：

```bash
aegis run "<task>" --execute --bridge --mode balanced
```

如果 bridge 不可用，应降级到普通 execute，并给出清晰提示。

---

## 3. 1.0 主架构

### 总体链路

```text
User Request
  -> CLI
  -> TaskRouter
  -> AgentRuntimeRegistry
  -> MultiAgentExecutor
  -> ExecutionPlan
  -> CollaborationPattern
  -> RuntimeManager
  -> RuntimeAdapter
  -> SessionStore
  -> Result / Logs / Recovery
```

### 目录归属

1.0 主线代码只认以下目录：

```text
tools/aegis_v2/
tools/runtime_bridge/
tests/test_aegis_v2.py
tests/test_runtime_bridge.py
.aegis/config.yml
.aegis/models/registry.yml
.aegis/state/
```

以下目录和能力在 1.0 中标记为 legacy/internal：

```text
tools/control_plane/
tools/automation_runner/
.aegis/core/
.aegis/runs/
shared-contexts/
agents/*/agent.json
```

legacy 代码暂时不删除，但不再作为 1.0 产品入口、文档主线或新功能扩展点。

---

## 4. 核心模块职责

### CLI

文件：

```text
tools/aegis_v2/cli.py
aegis
```

职责：

- 解析用户命令。
- 支持裸请求自动转成 `run`。
- 暴露 1.0 主命令。
- 输出 text/json 两种格式。
- 不暴露 v1 workflow 命令。

1.0 必须支持：

```bash
aegis "<task>"
aegis run "<task>"
aegis ulw "<task>"
aegis ultrawork "<task>"
aegis pair "<task>"
aegis swarm "<task>"
aegis pipeline "<task>"
aegis moa "<task>"
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

### TaskRouter

文件：

```text
tools/aegis_v2/router.py
```

职责：

- 校验请求。
- 分类任务。
- 估算复杂度。
- 选择协作策略。
- 选择候选 agent runtime。
- 生成 routing rationale。

1.0 的任务类型：

```text
architecture
code_gen
code_review
debugging
testing
refactoring
documentation
research
```

1.0 的协作策略：

```text
single
pair
swarm
pipeline
moa
```

### AgentRuntimeRegistry

文件：

```text
tools/aegis_1/models.py
.aegis/aegis-1.json
```

职责：

- 加载 agent runtime 定义。
- 加载启用 runtime。
- 检查 Codex CLI / Claude Code 等本机 runtime 可用性。
- 为 runtime fallback 提供候选 agent。

1.0 内置 agent runtime：

```text
codex
claude
```

底层具体模型名只能作为 runtime 配置参数存在，不作为 1.0 产品层主对象。

### MultiAgentExecutor

文件：

```text
tools/aegis_1/engine.py
tools/aegis_1/runtime.py
```

职责：

- 将 routing decision 转成 execution plan。
- 创建 session。
- 写 checkpoint。
- 根据 `--execute` 决定规划或真实执行。
- 调用 collaboration pattern。
- 处理执行成功、失败和恢复。

1.0 约束：

- `RunPlan.models` 当前是兼容字段，语义是 agent runtime identity。
- 用户通过 `--agents` 显式指定 runtime 时，不得被静默覆盖。
- 兼容参数 `--models` 等价于 `--agents`，但不再作为产品主叙事。
- `plan.steps[*].model` 当前是兼容字段，必须和实际 runtime 使用的 agent identity 一致。

### CollaborationPattern

文件：

```text
tools/aegis_v2/collaboration.py
```

职责：

- 执行 single、pair、swarm、pipeline、moa。
- 管理阶段间 shared context。
- 记录 stage result。
- 支持 pair review loop。
- 支持 swarm/moa 并行。

1.0 验收重点：

- pair 可以 coder/reviewer 迭代。
- swarm 可以 splitter/workers/aggregator。
- pipeline 可以串行传递上下文。
- moa 可以并行候选并聚合。
- 每个 stage 都能在 session 中复盘。

### RuntimeManager

文件：

```text
tools/aegis_v2/runtime.py
tools/runtime_bridge/cli.py
```

职责：

- 将 agent stage 调用映射到实际 runtime。
- 支持 simulate。
- 支持 codex CLI。
- 支持 claude CLI。
- 支持 tmux bridge。
- 写 log 和 response。
- 提供失败提示和 fallback。

1.0 runtime 优先级：

```text
simulate
codex-cli
claude-code-cli
tmux bridge
```

bridge 是增强体验，不是唯一执行路径。

### SessionStore

文件：

```text
tools/aegis_v2/session.py
.aegis/state/sessions.db
```

职责：

- 保存 session。
- 保存 checkpoints。
- 保存 messages。
- 保存 stage outputs。
- 保存 estimated/actual cost。
- 支持 list/show/resume/recover。

1.0 session 状态：

```text
planned
running
completed
failed
recovered
```

---

## 5. 1.0 明确不做

1.0 不做以下主功能：

- 企业治理 workflow。
- L1-L5 状态机。
- requirements lock。
- gate review。
- Team Pack 产品化。
- nightly evolution。
- 自动写复杂项目 artifact。
- IDE 插件。
- Web UI。
- 长期记忆学习系统。
- 真实多 provider 订阅安装器。

这些可以后续作为插件或 1.1+ 能力讨论。

---

## 6. 1.0 可用版本验收标准

### CLI 验收

- `aegis "<task>"` 可运行。
- `aegis run "<task>"` 可运行。
- `aegis ulw "<task>"` 可运行。
- `aegis pair/swarm/pipeline/moa "<task>"` 可运行。
- `aegis --help` 不展示 v1 workflow 作为主能力。
- 文档命令和真实 CLI 完全一致。

### 路由验收

- 空请求被拒绝。
- 模糊请求被拒绝并要求用户补充目标。
- debugging 任务默认 pipeline。
- refactoring 任务默认 pair。
- testing/code_review 任务默认 swarm。
- architecture 任务默认 single 或 moa。

### 执行验收

- `--simulate --execute` 可以完整跑完所有协作模式。
- `--execute` 在 runtime 缺失时给出可理解错误。
- runtime fallback 不静默改变用户显式 agent runtime。
- stage 失败会写入 session。

### session 验收

- 每次 run 都有 session id。
- `session list` 能看到历史任务。
- `session show` 能看到 routing、plan、messages、checkpoints。
- `session resume/recover` 至少可以基于原始 request 重新创建恢复 session，并标记来源。

### bridge 验收

- `aegis bridge up/status/stop` 或等价 v2 命令可用。
- `--bridge` 可将 codex/claude 调用投递到 tmux pane。
- bridge 不可用时能清楚降级或报错。

### 测试验收

1.0 最低测试命令：

```bash
python3 -m unittest tests.test_aegis_v2 tests.test_runtime_bridge
```

可选全量：

```bash
python3 -m unittest
```

---

## 7. 1.0 P0 工作清单

### P0-1 统一 CLI 契约

- 新增 `ulw` / `ultrawork`。
- 将裸请求稳定映射到 `run`。
- 清理文档中不存在的命令形态。
- 增加 `aegis bridge` 命令组，或明确继续使用 `aegis ctl bridge-*` 作为 1.0 临时入口。

### P0-2 修复 Agent Runtime 一致性

- `routing.models`、`execution_plan.steps[*].model`、runtime 实际 agent identity 必须一致。这里的 `model` 是兼容字段名，1.0 语义为 agent runtime。
- 显式 `--agents` 不得被覆盖；`--models` 仅作为兼容别名。
- pipeline 应尊重 stage role 或明确只按 routing runtime 分配。

### P0-3 固化 ultrawork

- `ulw/ultrawork` 默认 `execute=True`。
- 默认尝试 bridge。
- 默认 balanced mode。
- 输出最终结果、session id、日志路径。

### P0-4 精简 README/Quickstart

- 删除 v1 governance 主叙述。
- 删除 L1-L5、Team Pack、gate 作为主功能的描述。
- README 首屏只讲 1.0 主功能。

### P0-5 测试 1.0 主链路

- 覆盖裸请求。
- 覆盖 `ulw`。
- 覆盖显式 agent runtime。
- 覆盖 simulate execute。
- 覆盖 session show/recover。

---

## 8. 1.0 成功标准

AEGIS 1.0 成功不是功能多，而是主链路稳：

```text
安装后，用户输入一个编程任务，AEGIS 能自动决定怎么让多个 agent/runtime 协作，能执行，能记录，能恢复，能解释为什么这么做。
```

只要这条链路稳定，1.0 就成立。
