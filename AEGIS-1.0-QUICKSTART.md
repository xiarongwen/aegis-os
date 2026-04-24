# AEGIS 1.0 快速开始

AEGIS 1.0 的主入口是：

```bash
aegis ulw "<task>"
```

它会启动一个本地 agent CLI 协作编程 autopilot，并在终端 cockpit 里展示任务进度、角色、验证、事件和产物。

---

## 1. 环境检查

在仓库根目录运行：

```bash
aegis doctor
```

如果 `aegis` shim 还没装好，可以先用：

```bash
./aegis doctor
```

JSON 输出：

```bash
aegis doctor --format json
```

必需项：

- Python 3.10+
- git
- rich
- textual
- 当前 workspace 可写

可选项：

- codex
- claude
- tmux

---

## 2. 初始化配置

```bash
aegis config init
aegis config show
```

配置文件：

```text
.aegis/aegis-1.json
```

示例：

```json
{
  "version": "1.0",
  "mode": "balanced",
  "runtime": {
    "simulate_by_default": true,
    "timeout_seconds": 180,
    "bridge": "manual"
  },
  "verification": {
    "commands": [],
    "auto_detect": true
  },
  "cost": {
    "per_task_budget": null
  }
}
```

---

## 3. 第一次运行

安全模拟：

```bash
aegis ulw "修复登录 bug"
```

动态 TUI：

```bash
aegis ulw "修复登录 bug" --live
```

看清每个阶段：

```bash
aegis ulw "修复登录 bug" --live --interval 0.1 --step-delay 0.6
```

真实执行：

```bash
aegis ulw "修复登录 bug" --execute
```

通过 tmux bridge 执行：

```bash
aegis bridge up
aegis ulw "修复登录 bug" --execute --bridge --live
```

---

## 4. 常用命令

### 自动模式

```bash
aegis "实现 JWT 登录"
aegis run "实现 JWT 登录"
aegis ulw "实现 JWT 登录"
```

### 显式协作模式

```bash
aegis pair "重构认证模块"
aegis swarm "为支付模块生成测试"
aegis pipeline "修复登录 bug 并验证"
aegis moa "评审当前插件架构"
```

### Session

```bash
aegis session list
aegis session show <session_id>
aegis watch <session_id>
aegis watch <session_id> --live
```

恢复或重新运行：

```bash
aegis session resume <session_id> --simulate
aegis session recover <session_id> --simulate
```

### Agent Runtimes

推荐命令：

```bash
aegis agents list
aegis agents test
aegis agents test codex
```

兼容旧命令：

```bash
aegis models list
aegis models test
aegis models test codex
```

### Bridge

```bash
aegis bridge up
aegis bridge status
aegis bridge stop
```

### Cost / Config

```bash
aegis cost report
aegis config show
```

---

## 5. Cockpit 里会看到什么

`aegis ulw --live` 会显示：

- 顶部进度
- 任务进展表格
- 八大底层能力
- 双向共验证
- 方圆会议
- 自动复盘
- 七业大师协同在场
- 三层一致的共识层
- 十二铁律
- 动态事件流

非 TTY 环境会自动退回纯文本 cockpit。

---

## 6. 八段流水线

debugging / pipeline 类型任务会进入八段流水线：

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

完成前会经过 RunPolicy：

- stage 必须完成
- review 必须完成
- verification 必须 passed
- done gate 必须 passed
- 有 error 或 policy violation 时不能 completed

---

## 7. 配置真实验证

编辑：

```text
.aegis/aegis-1.json
```

添加：

```json
{
  "verification": {
    "commands": [["python3", "-m", "pytest"]],
    "auto_detect": true
  }
}
```

AEGIS 也会自动检测：

```text
package.json -> npm test
pyproject.toml / pytest.ini / tests -> python3 -m pytest
go.mod -> go test ./...
```

验证失败会让 session 进入 `failed`，不会假 completed。

---

## 8. 运行产物

每次运行会写：

```text
.aegis/state/aegis1_sessions.db
.aegis/runs/aegis-1/<session_id>/run_manifest.json
.aegis/runs/aegis-1/<session_id>/events.jsonl
.aegis/runs/aegis-1/<session_id>/summary.md
```

查看：

```bash
aegis session show <session_id>
```

---

## 9. 故障排除

### 找不到 `tools.aegis_1`

确认当前 `aegis` shim 指向仓库脚本：

```bash
which aegis
ls -l "$(which aegis)"
```

仓库脚本已经支持 symlink 解析。如果仍有问题，先用：

```bash
./aegis doctor
```

### Codex / Claude 不可用

检查：

```bash
aegis models test
aegis doctor
```

如果只是想试用产品链路，请使用默认 simulate：

```bash
aegis ulw "修复 bug"
```

### 真实验证失败

查看事件：

```bash
aegis session show <session_id>
```

关注：

```text
verification
policy_violation
recovery_hint
```

---

## 10. 旧版本入口

旧 v2 CLI：

```bash
aegis v2 <command>
```

旧 control plane：

```bash
aegis ctl <command>
```

这些是 legacy/internal，不是 1.0 主产品入口。
