# AEGIS OS

AEGIS OS 是一个运行在 Claude Code / Codex 上层的 host-native 多 Agent 工作流 Bot。

它不是一个“生成某个固定项目模板”的框架，也不是把自然语言请求再包一层外部 CLI 的壳。它的核心目标是：

- 让当前 Claude Code / Codex 会话直接成为 orchestrator
- 用一套可执行的控制面来约束多 Agent 协作
- 支持两类形态：
  - `Workflow`：研究 -> 规划 -> 开发 -> review -> 验证 -> 发布
  - `Team Pack`：长期可复用的专业团队，例如 `/aegis-video`、`/aegis-nx`

一句话理解：

AEGIS OS = 宿主内运行的多 Agent Bot + repo 里的控制面 + 可长期复用的专业团队系统。

## 这个项目是什么

这个仓库是 **AEGIS Core**，也就是 AEGIS 的控制面与能力底座。

它负责：

- 定义多 Agent 注册表和状态机
- 提供 `pre-run` / `post-run` 治理 hook
- 管理 workflow 运行目录和运行时锁文件
- 创建、安装、运行、校验 Team Pack
- 为长期团队提供 Team Memory
- 通过 `doctor` / `workspace-doctor` / `team-doctor` 做自检

它不负责：

- 替代 Claude Code / Codex 的原生能力
- 变成一个外部常驻调度服务
- 只服务某一种业务场景

## 你可以用它做什么

### 1. 作为宿主内自动化工作流 Bot

例如在 Claude Code 里直接说：

- `/aegis 帮我开发一个聊天页面`
- `/aegis 帮我处理一个登录 bug`
- `/aegis 帮我调研某个项目并输出 PRD`

当前宿主会话会成为 orchestrator，AEGIS 控制面负责状态推进、review/fix loop、需求锁定、门禁检查和产物落盘。

### 2. 作为长期专业团队系统

例如先生成一个长期团队：

- `/aegis 帮我创建一个专业的视频剪辑团队，名字叫 AEGIS-video`
- `/aegis 帮我创建一个逆向工程团队，名字叫 AEGIS-nx`

之后就可以长期复用：

- `/aegis-video 帮我剪一条 30 秒科技短视频`
- `/aegis-nx 帮我逆向一下 xx app 的登录流程`

这些团队有自己的：

- `team.json`
- `SKILL.md`
- `COMMAND.md`
- Team Memory
- run summaries
- learnings
- preference memory
- project memory

## 核心能力

当前仓库已经落地的核心能力包括：

- host-native 入口：`/aegis`
- Team Pack 创建、安装、列出、查看、校验
- 跨项目 attach 当前 workspace
- 单一真相源：`.aegis/core/registry.json`
- 机器可读状态机：`.aegis/core/orchestrator.yml`
- workflow runtime locks
- gate reviewer 独立性约束
- `review -> fix -> re-review -> ... -> LGTM` 闭环
- `requirements-lock.json` 需求冻结
- `task_breakdown.json` 并行任务拆解
- `implementation-contracts.json` 实现边界冻结
- `reuse-audit.json` 复用与 DRY 审计
- Team Memory v2
- 自动偏好学习
- 夜间保守演进

## 架构怎么工作

AEGIS 的工作方式可以简化成下面这条链：

```text
User in Claude Code / Codex
  -> /aegis or /aegis-video
  -> current host session becomes orchestrator
  -> AEGIS control plane validates and prepares execution
  -> workspace .aegis/ receives workflow state and artifacts
  -> specialists execute
  -> review / fix / LGTM loop
  -> results + memory are persisted
```

几个关键角色：

- `agents/aegis/`
  宿主内主入口 skill
- `tools/control_plane/`
  控制面 CLI，负责校验、同步、doctor、Team Pack、hooks、状态机
- `tools/automation_runner/`
  fallback runner，适合 bootstrap / debug / 非宿主路径
- `.aegis/core/registry.json`
  Agent 唯一真相源
- `.aegis/core/orchestrator.yml`
  workflow 状态机与治理规则

## Bridge Mode

参考 `ccb` 的模式，AEGIS 现在支持一个 `tmux`-first 的 runtime bridge。

这个模式的目标不是让 TUI 静默 `Popen` 多个 CLI，而是把 runtime 放进可见 pane，并为后续投递保留会话注册信息。

### 能力

- `codex` / `claude` / `aegis` 可放进同一个 `tmux` bridge session
- 每个 workspace 有稳定的 bridge session 名称
- session / pane 信息会写入 `.aegis/runtime-bridge/sessions/...`
- `automation_runner` 在设置 `AEGIS_RUNTIME_BRIDGE=tmux` 时，会优先通过 bridge 把 `codex` / `claude` 任务投递到可见 pane 中执行
- 没有 bridge 或没有 `tmux` 时，仍会退回原来的直接执行模式

### 命令

```bash
aegisctl bridge-up
aegisctl bridge-up --model codex --model claude
aegisctl bridge-status
aegisctl bridge-stop
```

### 配合 automation runner 使用

```bash
export AEGIS_RUNTIME_BRIDGE=tmux
aegisctl bridge-up
aegis ui
```

这时 runner 对 `codex` / `claude` 的单次执行会优先走 bridge pane，而不是完全隐藏在后台进程里。

## 安装

### 环境要求

- macOS / Linux
- `git`
- `python3`
- `bash`
- Claude Code CLI or Codex CLI

当前 `scripts/bootstrap.sh` 会检查 `claude` 或 `codex` 命令至少有一个存在。bootstrap 仍会把 AEGIS skill 和 Claude slash commands 同步到 `~/.claude/skills` 和 `~/.claude/commands`，这样 Claude Code 可以直接使用；Codex 场景则主要通过已安装 skill 或 CLI fallback 运行。

如果你主要用 Codex，不再强制要求先装 Claude Code CLI；如果你也想用 `/aegis` 这类 Claude slash command，再额外安装 Claude Code CLI 即可。

### 官方安装方式

1. 克隆仓库

```bash
git clone <your-aegis-repo-url> aegis-os
cd aegis-os
```

2. 运行 bootstrap

```bash
bash scripts/bootstrap.sh
```

这一步会做这些事：

- 运行 `doctor`
- 运行 `workspace-doctor`
- 同步派生 `agent.json`
- 同步 AEGIS skills / commands
- 安装 `aegis` / `aegisctl` shim 到 `~/.local/bin`
- 安装 nightly evolution cron

3. 确保 `~/.local/bin` 在 PATH 里

```bash
export PATH="$HOME/.local/bin:$PATH"
```

建议把这行写进你的 shell 配置文件，例如 `~/.zshrc`。

4. 验证安装

```bash
aegis ctl doctor
```

### 不装 Claude Code CLI 的手动安装方式

如果你当前只想先在 Codex 里使用控制面和 shims，可以在仓库根目录手动执行：

```bash
python3 -m tools.control_plane doctor
python3 -m tools.control_plane sync-agent-metadata
python3 -m tools.control_plane sync-agents
python3 -m tools.control_plane install-shims
python3 -m tools.control_plane install-cron
```

然后同样确保：

```bash
export PATH="$HOME/.local/bin:$PATH"
```

## 安装后会得到什么

安装完成后，通常会有这些结果：

- `aegis`
  自动化 runner shim
- `aegisctl`
  控制面 shim
- `~/.claude/skills/aegis`
  主入口 skill
- `~/.claude/commands/aegis.md`
  Claude Code slash command

当你安装 Team Pack 时，还会额外生成类似：

- `~/.claude/skills/aegis-video`
- `~/.claude/commands/aegis-video.md`

## 快速开始

### 在 Claude Code 中使用

安装完成后，最主要的使用方式就是在 Claude Code 里直接说：

```text
/aegis 帮我开发一个聊天页面
/aegis 帮我调研 https://github.com/xxx/yyy 项目并输出 PRD
/aegis 帮我处理当前项目里的登录 bug
```

如果你已经创建了长期团队，也可以直接说：

```text
/aegis-video 帮我剪一条 30 秒科技短视频
/aegis-nx 帮我逆向一下 xx app 的登录流程
```

### 在 Codex 中使用

在 Codex 里，推荐直接调用当前 session 已安装的 skill：

- `aegis`
- `aegis-video`
- `aegis-nx`

也就是说：

- 用 `aegis` skill 作为主入口
- 用某个 `aegis-*` skill 作为长期团队入口

如果你当前是手动调试，也可以用 CLI fallback：

```bash
aegis bootstrap "帮我开发一个聊天页面"
```

## 在其他项目中使用

AEGIS Core 不要求你把目标项目搬进这个仓库里。

正确方式是：

1. 先把 AEGIS Core 安装好
2. 进入你的目标项目根目录
3. 把这个项目 attach 成 AEGIS workspace
4. 然后在这个项目里使用 `/aegis`

示例：

```bash
cd /path/to/your-project
aegis ctl attach-workspace
aegis ctl workspace-doctor
```

执行后，目标项目里会生成：

- `.aegis/project.yml`

之后这个项目就是一个 AEGIS workspace 了。

然后你就可以在这个项目对应的 Claude Code / Codex 会话里使用：

```text
/aegis 帮我修复一个登录 bug
/aegis 帮我为当前项目写一个 PRD
```

注意：

- 目标项目必须是 Git 仓库根目录
- AEGIS 会严格把 workspace root 绑定到 Git root

## 两种工作模式

### Workflow Mode

适合：

- 研究
- 输出 PRD
- 开发功能
- 修复 bug
- review / 验证 / 发布

常见请求：

- `/aegis 帮我开发一个聊天页面`
- `/aegis 帮我修复当前项目里的支付 bug`
- `/aegis 帮我调研某个开源项目并输出 PRD`

这类请求通常会在 workspace 下创建：

- `.aegis/runs/<workflow-id>/state.json`
- `.aegis/runs/<workflow-id>/intent-lock.json`
- `.aegis/runs/<workflow-id>/project-lock.json`
- `.aegis/runs/<workflow-id>/registry.lock.json`
- `.aegis/runs/<workflow-id>/orchestrator.lock.json`

以及各阶段产物目录。

### Team Pack Mode

适合：

- 长期复用的专业团队
- 某个领域的固定 bot
- 不想每次都重新描述团队分工

创建一个团队：

```text
/aegis 帮我创建一个专业的视频剪辑团队，名字叫 AEGIS-video
```

查看团队：

```bash
aegis ctl show-team-pack --team AEGIS-video --scope global
```

之后长期使用：

```text
/aegis-video 帮我剪一条 30 秒科技短视频
```

Team Pack 存储位置：

- 全局团队：`~/.aegis/teams/global/<TEAM_ID>/`
- 项目团队：`<workspace>/.aegis/teams/<TEAM_ID>/`
- 会话团队：`<workspace>/.aegis/cache/session-teams/<TEAM_ID>/`

## Team Memory 和自动偏好学习

长期团队不是一次性 prompt，它有持久记忆。

当前 Team Memory 会保存：

- run summaries
- stable learnings
- preference memory
- preference observations
- project memory
- retrievable memory cards

查看方式：

```bash
aegis ctl show-team-memory --team AEGIS-video --scope global
```

自动偏好学习规则：

- 强信号如 `默认`、`以后都`、`记住`、`always`
  可以在当前完成的 run 中直接晋升为稳定偏好
- 弱信号如 `优先`、`先给`、`prefer`
  会先记录为 observation，重复出现后才晋升
- 一次性的弱表达不会直接污染长期偏好

如果你确实要强制写入一个稳定偏好，也可以手动执行：

```bash
aegis ctl record-team-preference --team AEGIS-video --scope global --note "默认先给 hook，再给完整脚本"
```

## 常用命令

### 控制面

```bash
aegis ctl doctor
aegis ctl workspace-doctor
aegis ctl attach-workspace
aegis ctl sync-agent-metadata
aegis ctl sync-agents
aegis ctl workflow-dry-run
```

### Team Pack

```bash
aegis ctl compose-team-pack --request "AEGIS 帮我创建一个专业的视频剪辑团队，名字叫 AEGIS-video" --install
aegis ctl create-team-pack --id AEGIS-video --name "AEGIS Video" --mission "Long-lived team for video editing." --domain video-editing --scope global --install
aegis ctl list-team-packs --scope all
aegis ctl show-team-pack --team AEGIS-video --scope global
aegis ctl invoke-team-pack --team AEGIS-video --scope global --request "帮我做一条 30 秒科技短视频"
aegis ctl show-team-run --team AEGIS-video --scope global --run-id <run-id>
aegis ctl complete-team-run --team AEGIS-video --scope global --run-id <run-id> --summary "Delivered first cut." --learning "Hook-first intros convert better."
aegis ctl show-team-memory --team AEGIS-video --scope global
aegis ctl team-doctor --scope all
aegisctl ui
```

### fallback / debug

```bash
aegis bootstrap "帮我开发一个聊天页面"
aegis run "帮我调研某个项目并输出 PRD" --runtime auto
aegis dispatch --workflow <workflow-id> --runtime auto --dry-run
aegis dispatch --workflow <workflow-id> --runtime auto
aegis route "帮我开发一个聊天页面"
aegis resume --workflow <workflow-id> --runtime auto
```

其中 `--runtime auto` 会根据当前 state、可用 CLI、以及可选的 `AEGIS_HOST_RUNTIME` 自动选择 runtime。

如果你希望告诉 AEGIS 当前宿主是什么，可以显式设置：

```bash
export AEGIS_HOST_RUNTIME=claude
```

或：

```bash
export AEGIS_HOST_RUNTIME=codex
```

这样 `auto` 模式会把当前宿主优先视为 orchestrator，再在需要时选择是否用另一种 CLI 做 dispatch worker。

终端可视化工作流控制台：

```bash
aegis ui
aegisctl ui
aegisctl ui --workflow <workflow-id>
```

这个界面不是只读看板，而是 workflow 的主入口。你可以直接在 TUI 里输入请求，然后由 AEGIS 自动：

- 创建 workflow
- 根据当前 state 和可用 CLI 选择 orchestrator / dispatch runtime
- 调用 `claude` 或 `codex`
- 继续 `resume` / `dispatch`

界面会展示：

- 当前工作流列表与 state
- 自动推断的 orchestrator runtime 和 dispatch runtime
- runtime 选择理由
- 关键 artifacts 是否已生成
- 最近一次动作结果

按键：

- `n` 新建请求并直接运行
- `b` 新建请求但只 bootstrap
- `u` 对当前 workflow 执行 resume
- `d` 对当前 workflow 执行 dispatch dry-run
- `x` 对当前 workflow 执行真实 dispatch
- `j` / `k` 或方向键切换工作流
- `r` 刷新
- `q` 退出

## 目录结构

核心仓库：

```text
.aegis/
  core/
  hooks/
  schedules/
agents/
shared-contexts/
tools/
scripts/
```

目标 workspace：

```text
.aegis/
  project.yml
  overrides/
  policies/
  runs/
  teams/
  cache/
```

## 当前推荐使用方式

最推荐的路径只有两步：

1. 安装 AEGIS Core
2. 在 Claude Code / Codex 里用 `/aegis ...` 或某个 `/aegis-* ...`

也就是说，AEGIS 的主产品形态是：

- 宿主内的 AEGIS bot
- 不是让你长期手工敲一堆 CLI

CLI 主要用于：

- bootstrap
- debug
- fallback
- doctor
- 手动检查和补救

## 当前状态和边界

当前 AEGIS 已经可以稳定承担这些角色：

- host-native 多 Agent workflow bot
- 长期 Team Pack 系统
- 跨项目 attach 的控制面
- review/fix/LGTM 治理内核
- Team Memory 与自动偏好学习底座

当前仍然要注意：

- `scripts/bootstrap.sh` 现在要求系统里至少有 `codex` 或 `claude` 其中一个 CLI
- Codex 场景可以用，但更适合通过已安装 skill 来使用
- deploy 阶段仍然会在需要人工信息或环境参数时停下
- fallback runner 是兼容路径，不是主产品入口

## 相关入口

- `agents/aegis/SKILL.md`
  AEGIS 主入口 skill
- `agents/aegis/COMMAND.md`
  Claude Code `/aegis` command
- `tools/control_plane/cli.py`
  控制面实现
- `tools/automation_runner/cli.py`
  fallback automation runner
- `.aegis/core/registry.json`
  Agent 真相源
- `.aegis/core/orchestrator.yml`
  workflow 状态机

如果你只想记住一句使用方式，就记这个：

先安装，再进你的项目，然后在 Claude Code 里说：

```text
/aegis 帮我开发一个聊天页面
```
