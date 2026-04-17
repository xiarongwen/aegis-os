# AEGIS Host-Native Architecture v1

## Summary

AEGIS 的主入口应运行在 Claude Code / Codex 当前宿主会话里，而不是作为外部 CLI 包装器独立存在。

正确架构是：

- Host-native Bot Layer
- Repo-native Control Plane
- External Runner only as fallback/debug

## Primary Entry

主入口形态应是：

- `/aegis 帮我开发一个聊天页面`
- `/aegis 帮我调研 xx 项目并输出 PRD`

在这个形态下：

- 当前 Claude/Codex 会话直接进入 AEGIS orchestrator 模式
- 当前会话读取 control-plane 配置
- 当前会话决定 workflow type、阶段推进、review/fix loop
- 当前会话只在必要时请求人工确认

## Layer Model

### 1. Host-native Bot Layer

职责：

- 接收用户自然语言请求
- 识别 workflow type
- 创建 intent lock
- 驱动 specialist execution
- 管理 review-fix-LGTM loop
- 管理 human approval boundaries

这一层应尽量利用宿主原生能力：

- 长上下文
- 文件读写
- shell 执行
- web / 搜索能力
- 原生子 agent 能力
- 原生用户交互

### 2. Repo-native Control Plane

职责：

- registry
- orchestrator state machine
- requirement lock
- review loop validation
- schemas
- doctor
- hook validation
- auditability

这一层不负责“再起一个模型进程”，而负责“约束当前宿主 agent”。

### 2.5 Workspace Truth Layer

当 AEGIS 在任意业务项目中运行时，还必须存在项目级真相层：

- `.aegis/project.yml`
- `.aegis/overrides/agent-overrides.json`
- `.aegis/policies/workflow-policy.json`

这层的职责是：

- 声明当前项目允许启用哪些 workflow
- 为现有 agent 注入项目上下文
- 为 gate 增加更严格的 reviewer policy

但这层只能加严，不能放松核心治理。

### 3. External Runner

保留：

- `tools/automation_runner/`
- `./aegis`
- `scripts/aegis.sh`

但角色降级为：

- bootstrap helper
- debug helper
- fallback automation path

不应作为主产品入口对外宣称。

## Why This Is The Best Default

相比外部 CLI 再递归调用 `codex exec` / `claude -p`，host-native 方案更好，因为它：

- 保留宿主完整上下文
- 减少多进程 prompt 分裂
- 更容易控制需求漂移
- 更容易在 review/fix 循环中连续记忆
- 更自然地使用宿主原生工具与审批机制
- 更贴近用户真实感知的 “bot” 形态

## Execution Policy

AEGIS 默认执行策略应是：

1. Host session as orchestrator
2. Control plane as governance backend
3. Project truth compiled into runtime snapshot before execution
4. Native sub-agents only for clearly bounded specialist work
5. External runner only for fallback/debug

## Attach Current Workspace

正确的宿主内流程应是：

1. 在当前业务项目目录里收到 `/aegis ...`
2. attach 当前 workspace
3. 读取或创建 `.aegis/project.yml`
4. 读取 `.aegis/overrides/agent-overrides.json` 与 `.aegis/policies/workflow-policy.json`
5. 编译：
   - `project-lock.json`
   - `registry.lock.json`
   - `orchestrator.lock.json`
6. 再开始推动 workflow 状态机

如果 AEGIS Core 仓库和业务项目不在同一目录，fallback/debug 命令必须显式带上 `--workspace /path/to/app`。

## Runtime Truth Rule

一旦 workflow 已启动：

- 允许读 `project-lock.json`
- 允许读 `registry.lock.json`
- 允许读 `orchestrator.lock.json`
- 不允许回头把可变的 project override 当成执行真相

这样才能保证 review/fix loop、中途修复和长链路 build 不会发生配置漂移。

## Current Repository Mapping

本仓库中对应关系为：

- Host-native entry skill: `agents/aegis/SKILL.md`
- Orchestrator rules: `agents/orchestrator/SKILL.md`
- Control plane: `tools/control_plane/`
- Fallback runner: `tools/automation_runner/`

## MVP Recommendation

v1 最稳妥的产品化路径：

1. 以 host-native single-session orchestrator 为主
2. 以 specialist role switching 为主，少量使用原生 sub-agent
3. 在 deploy / change-control / credentials 等节点停下 ask user
4. 保留 external runner 作为测试与兼容路径
