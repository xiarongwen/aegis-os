# AEGIS OS

AEGIS OS 1.0 是一个面向 Codex CLI、Claude Code 等本地 agent CLI 的协作编程 autopilot。

主入口只有一个：

```bash
aegis ulw "修复登录 bug 并补测试"
```

AEGIS 会把一次编程任务转成可观察、可恢复、可复盘的运行：

```text
User Task
  -> Intent Router
  -> Role / Agent Runtime Plan
  -> Collaboration Engine
  -> Runtime / Verification
  -> RunPolicy Gate
  -> Live Cockpit
  -> Session / Events / Artifacts
```

旧 v1/v2 的 workflow、gate、team pack、control plane 代码仍保留在仓库中作为 legacy/internal，不再是 1.0 产品主线。

## 当前状态

AEGIS 1.0 当前已具备：

- `ulw / ultrawork` 主入口
- 裸请求自动映射到 `run`
- `single / pair / swarm / pipeline / moa` 协作模式
- 八段 autopilot pipeline
- pair review/fix loop
- Rich Live 动态终端 cockpit
- sqlite session/event store
- run artifacts
- RunPolicy gate，防止假 completed
- Codex CLI / Claude Code runtime adapter 基础版
- tmux bridge 包装
- doctor / config / cost 基础命令
- verification runner 基础版

## 安装

### 依赖

必需：

```text
python3
git
rich
textual
```

可选：

```text
codex
claude
tmux
```

### 本地使用

```bash
git clone <your-aegis-repo-url> aegis-os
cd aegis-os
export PATH="$HOME/.local/bin:$PATH"
```

如果 `~/.local/bin/aegis` 已经指向本仓库，可以直接运行：

```bash
aegis doctor
```

如果没有 shim，可以先直接用仓库脚本：

```bash
./aegis doctor
```

## 快速开始

### 1. 检查环境

```bash
aegis doctor
```

JSON 输出：

```bash
aegis doctor --format json
```

### 2. 初始化 1.0 配置

```bash
aegis config init
aegis config show
```

配置文件位置：

```text
.aegis/aegis-1.json
```

### 3. 启动 autopilot

安全模拟运行：

```bash
aegis ulw "修复登录 bug"
```

动态 TUI：

```bash
aegis ulw "修复登录 bug" --live
```

看得更慢一点：

```bash
aegis ulw "修复登录 bug" --live --interval 0.1 --step-delay 0.6
```

真实 runtime 执行：

```bash
aegis ulw "修复登录 bug" --execute
```

通过 tmux bridge 执行：

```bash
aegis bridge up
aegis ulw "修复登录 bug" --execute --bridge --live
```

## Cockpit

`aegis ulw --live` 会进入 `AEGIS AUTOPILOT` 终端驾驶舱。

当前 cockpit 展示：

- 顶部进度和 session 状态
- 任务进展表格
- 八大底层能力
- 双向共验证
- 方圆会议
- 自动复盘
- 七业大师协同在场
- 三层一致的共识层
- 十二铁律
- 动态事件流

非 TTY 或管道输出时，AEGIS 会自动退回稳定文本版 cockpit。

## 命令

### 主命令

```bash
aegis ulw "<task>"
aegis ultrawork "<task>"
```

### 运行任务

```bash
aegis "<task>"
aegis run "<task>"
aegis pair "<task>"
aegis swarm "<task>"
aegis pipeline "<task>"
aegis moa "<task>"
```

常用参数：

```bash
--simulate                 # 强制模拟执行
--execute                  # 调用真实 runtime
--live                     # 动态 cockpit
--bridge                   # 真实执行时使用 tmux bridge
--agents codex             # 显式指定本地 agent CLI/runtime
--models codex             # 兼容旧参数，等价于 --agents
--mode balanced            # speed / balanced / quality / cost
--workers 3                # swarm worker 数
```

### Session

```bash
aegis session list
aegis session show <session_id>
aegis session resume <session_id> --simulate
aegis session recover <session_id> --simulate
aegis watch <session_id>
aegis watch <session_id> --live
```

### Agent Runtime

推荐命令：

```bash
aegis agents list
aegis agents test
aegis agents test codex
```

兼容命令：

```bash
aegis models list
aegis models test
aegis models test codex
```

### Config / Cost / Doctor

```bash
aegis config init
aegis config show
aegis cost report
aegis doctor
```

### Bridge

```bash
aegis bridge up
aegis bridge status
aegis bridge stop
```

旧 v2 CLI 仍可通过下面的逃生口访问：

```bash
aegis v2 <command>
```

旧 control plane 仍可通过下面的逃生口访问：

```bash
aegis ctl <command>
```

## 八段流水线

`pipeline` 和多数 debugging 类型的 `ulw` 任务会使用八段流水线：

```text
S1 plan_check
S2 story_split
S3 spec
S4 build
S5 review
S6 verify
S7 done_gate
S8 delivery
```

完成前必须通过 RunPolicy：

- 没有 error event
- 所有 stage 完成
- pipeline 必须有 review、passed verification、passed done gate
- pair 必须有 APPROVED review 和 passed verification

不满足时 session 会变成 `failed`，并写入 `policy_violation` 和 recovery hint，不会假 completed。

## Verification

1.0 支持基础真实验证。

可以在 `.aegis/aegis-1.json` 中配置：

```json
{
  "verification": {
    "commands": [["python3", "-m", "pytest"]],
    "auto_detect": true
  }
}
```

如果没有配置，AEGIS 会尝试自动检测：

```text
package.json -> npm test
pyproject.toml / pytest.ini / tests -> python3 -m pytest
go.mod -> go test ./...
```

验证失败会阻止 `completed`。

## Artifacts

每次运行会写入：

```text
.aegis/state/aegis1_sessions.db
.aegis/runs/aegis-1/<session_id>/run_manifest.json
.aegis/runs/aegis-1/<session_id>/events.jsonl
.aegis/runs/aegis-1/<session_id>/summary.md
```

## 1.0 文档

- [Quickstart](AEGIS-1.0-QUICKSTART.md)
- [PRD](docs/AEGIS-1.0-PRD.md)
- [主功能与架构](docs/AEGIS-1.0-main-function-and-architecture.md)
- [多 Agent Runtime 架构](docs/AEGIS-1.0-multi-agent-runtime-architecture.md)
- [重构计划](docs/AEGIS-1.0-rebuild-plan.md)
- [当前问题状态](docs/AEGIS-1.0-ISSUE-STATUS.md)

## 开发验证

运行 1.0 测试：

```bash
python3 -m unittest discover -s tests -p 'test_aegis_1.py'
```

运行 bridge 测试：

```bash
python3 -m unittest discover -s tests -p 'test_runtime_bridge.py'
```

编译检查：

```bash
python3 -m compileall -q tools/aegis_1
```

## 还未完成

当前 1.0 仍在开发中，主要缺口：

- P0-1：显式 agent/runtime 选择需要角色级校验和更完整一致性测试
- P0-5：runtime 需要结构化错误、fallback/retry 和更好的失败指引
- P0-4：swarm/MoA 需要更强拆分、聚合与真实并行语义
- P1-2：cost controller 需要 `--budget`、阈值事件、超预算终止/降级
- P1-1：session resume 需要支持从失败 stage/checkpoint 恢复
- TUI 后续增强：runtime stdout/stderr 流式进入 cockpit、键盘交互
