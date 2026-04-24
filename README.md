# AEGIS v2

AEGIS v2 是一个多模型协作编程框架，运行在 Claude Code / Codex CLI 等 host-native agent 之上。

核心能力是将一次编程任务通过 **Intent Router → Collaboration Engine → Runtime/Verification** 的链路，转成可观察、可恢复、可复盘的运行。

## 主入口

### 1. 交互式 TUI（推荐）

直接运行，进入 Dashboard 主界面：

```bash
aegis
```

当前主界面特性：

- **默认欢迎页**：居中显示 AEGIS ASCII Logo 与当前工作区
- **Tab 切换模式**：默认是 `MOA 专家`，可切到 `Pair / Swarm / Pipeline / Run`
- **模式说明**：当前模式下方会显示一句简短说明
- **启动过程可见**：任务启动时会显示 `advisor / routing / planning / dispatch` 的实时步骤
- **快捷命令**：`/session` 查看会话，`/models` 查看模型状态，`/execute` 真实执行，`/simulate` 模拟执行
- **全屏终端模式**：启动后占满终端页面，退出时恢复原终端内容

### 2. 命令行直接运行

```bash
aegis "修复登录 bug 并补测试"
```

指定协作模式：

```bash
aegis run "实现用户注册接口"
aegis pair "重构数据库层"
aegis swarm "批量处理图片" --workers 3
aegis pipeline "发布 v1.2.0"
aegis moa "设计新架构方案"
```

## 当前能力

- **TUI Dashboard**：默认无参数进入交互式终端主界面
- **启动可视化**：任务启动阶段会实时显示 advisor、routing、planning、dispatch
- **五种协作模式**：Run / Pair / Swarm / Pipeline / MOA
- **默认 MOA 模式**：主界面默认模式为 `MOA 专家`
- **Intent Router**：自动选择路由策略（quality / speed / cost / balanced）
- **Agentic Route Advisor**：先由本地 `claude -p` / `codex exec` 提供路由建议，再进入 scheduler
- **Model Registry**：多模型注册、测试、启用/禁用管理
- **Session Store**：sqlite 持久化会话、事件、产物
- **Session 恢复**：resume / recover 从失败或中断点继续
- **RunPolicy Gate**：防止假 completed，未通过验证不计为完成
- **Cost 追踪**：report 汇总消耗
- **Host Runtime Adapter**：Codex CLI / Claude Code 运行时适配
- **Bridge 模式**：tmux bridge 包装真实执行

## 安装

### 依赖

必需：

```text
python3
git
pyyaml
```

TUI 额外需要：

```text
bun
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

安装 TUI 依赖：

```bash
bun install
```

## 快速开始

### 1. 检查环境

```bash
aegis doctor
```

### 2. 初始化配置

```bash
aegis v2 config init
aegis v2 config show
```

### 3. 启动 TUI

```bash
aegis
```

默认首页不会直接显示最近会话或运行详情：

- `/session`：显式打开最近会话与详情
- `/models`：显式打开模型状态
- 任务执行中：自动切换到任务面板

### 4. 命令行直接运行

模拟执行：

```bash
aegis "修复登录 bug" --simulate
```

真实执行：

```bash
aegis "修复登录 bug" --execute
```

通过 bridge 执行：

```bash
aegis "修复登录 bug" --execute --bridge
```

## 命令参考

### 运行任务

```bash
aegis "<task>"                    # 默认 run 模式
aegis run "<task>"                # 单模型运行
aegis pair "<task>"               # 配对协作
aegis swarm "<task>"              # 蜂群并行
aegis pipeline "<task>"           # 流水线
aegis moa "<task>"                # 多专家聚合
```

通用参数：

```bash
--mode quality|speed|cost|balanced   # 质量/速度/成本/平衡
--models <name>                      # 显式指定模型
--budget <USD>                       # 预算上限
--execute                            # 真实执行
--simulate                           # 模拟执行
--bridge                             # 使用 tmux bridge
--strategy <strategy>                # 路由策略（run 模式可用）
--workers <N>                        # swarm 并行数
```

### Session 管理

```bash
aegis v2 session list
aegis v2 session show <session_id>
aegis v2 session resume <session_id> --simulate
aegis v2 session recover <session_id> --simulate
aegis v2 watch <session_id>
aegis v2 watch <session_id> --live
```

### 模型管理

```bash
aegis v2 models list
aegis v2 models list --enabled-only
aegis v2 models test
aegis v2 models test codex
```

### 配置

```bash
aegis v2 config init
aegis v2 config show
```

### Cost / Doctor

```bash
aegis v2 cost report
aegis doctor
```

### Router 预览

```bash
aegis v2 router dry-run "修复登录 bug" --mode balanced
```

## 协作模式

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| **Run** | 单路径直接执行，适合明确且简单的任务 | 常规开发任务 |
| **Pair** | 两个模型结对，来回编写与审查 | 复杂逻辑、需要交叉验证 |
| **Swarm** | 多模型并行拆分执行，再统一聚合 | 批量处理、独立子任务 |
| **Pipeline** | 按阶段顺序传递上下文与结果 | 发布、大型重构 |
| **MOA** | 多专家先独立判断，再讨论后聚合裁决 | 架构设计、技术决策、复杂评审 |

## Session 与产物

每次运行会写入：

```text
.aegis/state/sessions.db
.aegis/runs/<session_id>/run_manifest.json
.aegis/runs/<session_id>/events.jsonl
.aegis/runs/<session_id>/summary.md
```

## v1 Legacy（已废弃）

v1.0 的 `ulw` / `ultrawork` / `workflow` / `gate` / `team pack` / `control plane` 代码仍保留在仓库中，但已不再是产品主线。

如需访问旧命令，使用逃生口：

```bash
aegis v1 <command>
aegis legacy <command>
```

旧 CLI 功能（bridge / doctor / agents）目前仍通过 v1 模块代理。

## 开发验证

运行 v2 测试：

```bash
python3 -m unittest discover -s tests -p 'test_aegis_v2*.py'
```

运行全部测试：

```bash
python3 -m unittest discover -s tests
```

编译检查：

```bash
python3 -m compileall -q tools/aegis_v2
```
