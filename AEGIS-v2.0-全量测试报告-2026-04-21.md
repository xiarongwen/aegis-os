# AEGIS v2.0 全量测试报告

**测试基线文档:** `AEGIS-v2.0-全量测试文档.md`  
**对照设计文档:** `AEGIS-重构方案-多模型协作-v2.0.md`  
**测试日期:** 2026-04-21  
**测试代码版本:** `893135a`  
**测试环境:** macOS 26.0, Python 3.13.9  
**测试结论:** `核心骨架可用，但未达到“AEGIS v2.0 全量完成”状态，建议定位为内部 Alpha，不建议按文档宣称为完整交付`

---

## 1. 执行摘要

本轮测试从三个维度进行了验收：

1. **产品易用度**
2. **功能完成度**
3. **实现与 v2.0 文档的一致性**

总体判断：

| 维度 | 结论 | 说明 |
|------|------|------|
| 产品易用度 | 部分通过 | 基础命令可用，但命令体验和文档不一致，多个预期命令不存在 |
| 功能完成度 | 部分通过 | v2 核心骨架已落地，但成本控制、恢复、动态切换、TUI 等仍缺 |
| 架构一致性 | 部分偏移 | 代码已经进入 v2 内核，但 README、入口形态、配置字段消费仍明显偏 v1 / 半迁移状态 |
| 发布建议 | 不建议对外宣称“v2.0 完成” | 适合继续内部迭代，不适合作为完整成品发布 |

自动化回归结果：

```bash
python3 -m pytest -q tests/test_control_plane.py tests/test_runtime_bridge.py tests/test_automation_runner.py tests/test_aegis_v2.py
```

结果：

```text
79 passed in 9.04s
```

这说明当前代码库没有明显回归，但“测试全绿”不等于“产品达到文档目标”。

---

## 2. 测试方法

本轮没有只依赖单元测试，而是混合了以下方法：

- 阅读 `AEGIS-v2.0-全量测试文档.md`
- 对照 `AEGIS-重构方案-多模型协作-v2.0.md`
- 在临时 workspace 里执行黑盒 CLI 验收
- 使用 `--simulate` 跑通 `pair / swarm / pipeline / moa`
- 验证 `bridge-up / bridge-status / bridge-stop`
- 对关键模块做源码对照，确认文档中提到的能力是否真的被消费

本轮测试限制：

- 未配置 `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`
- 未对真实在线模型调用做大规模性能、预算、超时重试测试
- 未覆盖多操作系统和多 Python 版本矩阵
- 未做真实 5 会话并发压测

因此本报告里的“未验证”不等于“已完成”，只能算“当前环境下无法证明”。

---

## 3. 已验证通过的能力

### 3.1 核心骨架

| 模块 | 结果 | 说明 |
|------|------|------|
| Model Registry | 通过 | `config init`、`models list`、`models test` 可用 |
| Task Router | 通过 | 基础分类、策略选择、dry-run JSON 输出可用 |
| Session Store | 通过 | `run` 会创建 session，`session show` 可查看 checkpoints/messages |
| Collaboration Engine | 通过 | `pair / swarm / pipeline / moa` 在 simulate 模式下可执行 |
| Swarm / MoA 并发 | 通过 | 已改为真并发，配套并发单测通过 |
| Runtime Bridge 控制命令 | 通过 | `bridge-up / bridge-status / bridge-stop` 正常 |

### 3.2 用户侧基础命令

以下用户路径已验证可用：

```bash
bash aegis config init --format json
bash aegis models list --format json
bash aegis router dry-run '实现JWT认证' --format json
bash aegis '实现JWT认证' --format json
bash aegis run '修复登录功能里的 SQL 注入 bug' --execute --simulate --format json
bash aegis collaboration pair '重构认证模块并保持行为不变' --execute --simulate --format json
bash aegis collaboration swarm '生成登录模块测试用例' --execute --simulate --format json
bash aegis collaboration moa '从多个专家角度评审认证设计' --execute --simulate --format json
```

### 3.3 自动化质量基线

自动化测试已经覆盖：

- v2 CLI 入口
- v2 router / registry / session
- simulate 模式下的 pipeline / pair
- Swarm / MoA 并发执行
- control plane / runtime bridge / automation runner 现有回归

---

## 4. 关键未完成项与缺陷

以下问题按“影响 v2.0 完整性”的优先级排序。

### P0-1: 路由结果与执行计划不一致，显式模型选择会被覆盖

这是当前最关键的问题之一。

现象：

- `router` 返回的 `models` 与真正 `plan.steps[*].model` 可能不一致
- `--models` 显式传入的模型，在 `pair` / `swarm` 等模式下会被默认配置覆盖

实测例子：

```bash
bash aegis collaboration swarm '测试显式模型' --models local-llm --format json
```

路由结果：

- `models = ["local-llm"]`

执行计划：

- `split = claude-sonnet-4-6`
- `worker = codex`
- `aggregate = claude-sonnet-4-6`

影响：

- 路由层对用户不可信
- 显式模型选择失效
- 无法保证隐私场景真的走 `local-llm`
- 文档中的“动态路由 + 可配置模型协作”被破坏

结论：

- 这是一个 **P0 级实现缺陷**

### P0-2: 空输入和模糊输入没有被正确处理

测试文档要求：

- 空输入报错
- 模糊请求返回 `AMBIGUOUS` 并要求澄清

实测结果：

```bash
bash aegis '' --format json
bash aegis '优化代码' --format json
```

行为：

- 空字符串会直接创建 `code_gen + single + codex` 任务
- “优化代码”会被直接判为 `code_gen`

影响：

- 用户输入错误时缺少保护
- Router 不满足测试文档定义
- 易用度下降，误执行风险高

### P0-3: 测试文档中的关键 CLI 形态并不存在

测试文档声称支持：

```bash
aegis --mode quality "请求"
aegis --budget 10.00 "请求"
aegis config set key value
```

实测结果：

- `aegis --mode quality "请求"` 失败
- `aegis --budget 10.00 "请求"` 失败
- `aegis config set ...` 失败

这说明：

- 顶层命令交互设计与文档不一致
- CLI 还没有进入“可对外解释的稳定状态”

### P1-1: Session 只有查看能力，没有恢复能力

当前 `session` 仅支持：

- `session list`
- `session show`

不支持：

- `session resume`
- `session recover`
- `session retry-from-checkpoint`

测试文档中对 checkpoint/recovery 有明确要求，但当前实现只有“记录检查点”，没有“从检查点继续执行”。

### P1-2: Cost Controller 只有汇总，没有控制器

当前已实现：

- `actual_cost`
- `estimated_cost`
- `cost report`

当前未实现：

- `--budget` 参数
- 预算阈值告警
- 预算耗尽停止
- input/output token 分拆
- 轮次级成本明细
- 超预算时的降级策略

因此当前只能叫“成本统计”，还不能叫“成本控制器”。

### P1-3: Runtime 异常处理仍然偏原始

实测：

```bash
bash aegis run '离线本地模型测试' --models local-llm --execute --format json
```

返回：

```json
{"error":"claude-sonnet-4-6 execution failed at split with exit code 1"}
```

存在的问题：

- 没有自动 fallback 到备用模型
- 没有 retry
- 没有 timeout policy
- 错误信息缺少“如何修复”的明确指引

而且该用例还暴露了前面的 P0 问题：

- 明明显式要求 `local-llm`
- 实际却还是跑到了 `claude-sonnet-4-6`

### P1-4: `models test` 对 CLI 运行时会产生误报

实测：

- `claude` 二进制存在
- `codex` 二进制存在
- 但 `models test` 因缺少 API env 而直接判不可用

这会导致：

- CLI 已经登录可用，但系统仍显示 unavailable
- 运行时健康检查结果不可靠

对于 `claude-code-cli` / `codex-cli` 这类宿主 CLI，是否可用不应只依赖 API env。

### P1-5: v2 TUI 未完成，当前 `aegis ui` 仍是旧 control-plane UI

设计文档明确写了：

- Phase 4: `交互式 TUI`
- `实时协作可视化`
- 文档中还写到 `Textual`

当前实际情况：

- `aegis ui` 进入的是旧 `tools/control_plane/tui.py`
- 该 UI 是 workflow/control-plane 风格的 curses 界面
- 不是 v2 的多模型协作 TUI

因此：

- “TUI 已存在”这件事成立
- “v2 TUI 已完成”这件事不成立

### P1-6: `execution_state` 在任务完成后仍残留为 `executing`

多个完成态 session 的 metadata 中仍可见：

- `status = completed`
- `execution_state = executing`

这是状态一致性问题，会影响：

- 状态面板展示
- 运维判断
- 后续恢复/继续逻辑

### P2-1: simulate 模式的可测试性还不够真实

观察到两个问题：

1. `pair --simulate` 默认不会产出 `LGTM`，所以通常总是跑满 3 轮  
2. `swarm --simulate` 的 splitter 输出是一行文本，导致 subtasks 解析质量较弱

影响：

- 自动化验收可跑，但业务语义不够像真实系统
- 不利于验证“首次通过”“高质量拆分”等场景

---

## 5. 与测试文档的覆盖对照

### 5.1 功能测试覆盖矩阵

| 测试域 | 文档目标 | 当前结论 |
|------|------|------|
| Model Registry | 注册 / 发现 / 基础健康检查 | 部分通过 |
| Task Router | 分类 / 选择 / 边界处理 | 部分通过 |
| Collaboration Engine | Pair / Swarm / Pipeline / MoA | 通过 |
| Message Bus / Context Sync | 基本可用 | 部分通过 |
| Session Manager | 生命周期 / checkpoint / 恢复 | 部分通过 |
| Runtime Adapters | CLI 调用 / 异常处理 / fallback | 部分通过 |
| Cost Controller | 追踪 / 预算告警 / 报告 | 未完成 |
| CLI | 基础命令可用 | 部分通过 |
| TUI | 交互式 v2 可视化 | 未完成 |

### 5.2 性能与兼容性

| 项目 | 当前结论 | 备注 |
|------|------|------|
| Router 本地响应时间 | 通过 | 实测约 0.49s |
| Simulate 模式端到端 | 通过 | 实测约 0.48s - 0.52s |
| 真实模型性能阈值 | 未验证 | 当前环境未做真实在线压测 |
| 多操作系统兼容性 | 未验证 | 仅在当前 macOS 环境测试 |
| 多 Python 版本兼容性 | 未验证 | 仅当前 3.13.9 环境实测 |
| 多会话并发压测 | 未验证 | 本轮未做 5 会话压测 |

---

## 6. 架构与文档偏移

### 6.1 README 与 v2 核心叙事明显偏移

当前 README 的主叙事仍然是：

- Workflow
- Team Pack
- Governance / Lock Files / Review Loop
- 旧 control-plane / automation runner

而不是：

- Model Registry
- Task Router
- Collaboration Engine
- Session Manager

这会直接影响用户理解，导致：

- 用户以为当前产品仍是 v1 主体
- v2 CLI 被当成“附加能力”而不是新主入口

### 6.2 顶层入口仍是“v1 + v2 混合态”

当前顶层 `aegis` 的行为是：

- `ctl` / `ui` 走旧 control plane
- `bootstrap/resume/dispatch/route` 走旧 automation runner
- 其它命令走 v2 CLI

这说明当前项目处于**迁移中间态**，不是纯 v2 产品面。

### 6.3 默认配置里有多块字段尚未被真正消费

以下配置当前基本仍是“声明存在”，而不是“实际生效”：

- `models.overrides.max_budget_per_task`
- `routing.task_patterns`
- `routing.context_thresholds`
- `cost_control.alerts`
- `performance.cache_responses`
- `performance.cache_ttl`

这会带来两个问题：

- 用户改了配置却不一定生效
- 文档写得比实际实现更完整

### 6.4 设计文档里的多个核心模块仍未落地

未看到完整落地的模块包括：

- Output Consolidator
- 结果冲突合并 / 代码级 merge
- Load Balancer / Queue Manager
- 动态模型切换
- 路由决策可视化
- v2 Textual TUI
- 团队协作模式迁移后的新产品面

### 6.5 Runtime Bridge 仍是“部分达到 v2 目标”

当前状态：

- Bridge session 管理可用
- v2 runtime 已支持 `--bridge`
- Swarm/MoA 模式本身已经真并发

但仍有潜在限制：

- Bridge 的 pane 分配更偏“按模型类型”
- 对“同模型多 lane 完全并发”的表达还不够强

因此它更接近：

- `多模型 bridge 已接入`

而不是：

- `完整的多模型并发调度层已完成`

---

## 7. 推荐修复顺序

建议按下面顺序继续推进。

### 第一优先级

1. 修复 `routing.models` 与 `execution_plan.steps[*].model` 不一致的问题  
2. 让 `--models` 对 pair/swarm/pipeline/moa 真正生效  
3. 加入空输入、模糊输入、超长输入校验  
4. 对外统一 CLI 语义，决定是否支持顶层 `--mode / --budget`

### 第二优先级

1. 实现预算参数、预算阈值告警、预算耗尽处理  
2. 实现 `session resume / recover`  
3. 为 runtime 增加 timeout / retry / fallback / installation hint  
4. 修正完成态 metadata 中的 `execution_state`

### 第三优先级

1. 更新 README，切换到 v2 主叙事  
2. 清理未消费配置，或者真正把它们接上  
3. 落地 v2 TUI 与实时协作可视化  
4. 继续增强 bridge 的同模型多 lane 并发能力

---

## 8. 最终判断

当前 AEGIS v2.0 的真实状态可以定义为：

**“多模型协作内核已经成形，基础 CLI 和协作模式可跑，但离测试文档所定义的‘完整 v2.0 产品’还有明显距离。”**

更准确的产品阶段建议：

| 阶段 | 是否匹配当前状态 |
|------|----------------|
| 原型 Prototype | 已超出 |
| 内部 Alpha | 匹配 |
| 可公开 Beta | 暂不匹配 |
| 完整 v2.0 发布 | 不匹配 |

我的建议是：

- 可以继续在这个基础上迭代
- 不要把当前版本对外描述成“v2.0 已完成”
- 先把 `模型选择一致性 + 预算控制 + 恢复能力 + v2 文档统一` 这四件事补齐，再进入下一轮验收

