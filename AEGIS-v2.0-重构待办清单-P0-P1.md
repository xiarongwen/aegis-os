# AEGIS v2.0 重构待办清单

**来源:** `AEGIS-v2.0-全量测试报告-2026-04-21.md`  
**目标:** 把当前 v2 从“内部 Alpha”推进到“可持续迭代的 Beta 基线”  
**排序原则:** 先修影响正确性和产品可信度的问题，再补恢复、成本控制和体验层能力

---

## P0

### [ ] P0-1 修复 Router 与 Execution Plan 的模型不一致问题

**目标**

- 保证 `routing.models`、`execution_plan.steps[*].model`、实际 runtime 使用的模型三者一致
- 保证 `--models` 显式传参在 `single / pair / swarm / pipeline / moa` 下都真正生效

**当前问题**

- `router` 选出的模型会在 `executor.build_plan()` 里被默认配置覆盖
- `--models local-llm` 这类用户显式选择，在 `swarm/pair` 中会被替换成 `codex` / `claude`

**改动范围**

- `tools/aegis_v2/router.py`
- `tools/aegis_v2/executor.py`
- `tools/aegis_v2/cli.py`
- `tests/test_aegis_v2.py`

**实施要点**

- 定义“路由结果是执行计划唯一输入源”的约束
- 为协作模式引入显式角色分配规则
- 区分“用户显式模型”与“系统默认模型”
- 当模型数量不足以覆盖协作角色时，返回清晰错误或降级，而不是静默覆盖

**验收标准**

- `router dry-run` 与 `run/collaboration` 生成的 plan 模型一致
- `--models local-llm` 不会被静默替换
- 新增 `pair/swarm/moa/pipeline` 显式模型回归测试

---

### [ ] P0-2 增加输入校验与模糊请求处理

**目标**

- 阻止空输入、无意义输入直接进入执行链
- 对模糊请求返回澄清提示，而不是直接按 `code_gen` 执行

**当前问题**

- 空字符串会被创建成合法 session
- “优化代码”会被直接归类为 `code_gen`

**改动范围**

- `tools/aegis_v2/router.py`
- `tools/aegis_v2/cli.py`
- `tools/aegis_v2/types.py`
- `tests/test_aegis_v2.py`

**实施要点**

- 在 CLI 层和 router 层都做防御
- 增加 `AMBIGUOUS` 或等价状态表达
- 为超长输入增加截断或拒绝策略
- 保证错误信息是用户可理解的，不是裸异常

**验收标准**

- 空输入返回非 0 状态并提示有效输入
- 模糊请求返回澄清信息
- 超长输入不会导致崩溃

---

### [ ] P0-3 统一 v2 CLI 契约与文档写法

**目标**

- 让用户命令形态稳定、可预期
- 消除“测试文档写支持，但 CLI 实际不支持”的落差

**当前问题**

- `aegis --mode quality "请求"` 不支持
- `aegis --budget 10.00` 不支持
- `aegis config set key value` 不支持

**改动范围**

- `tools/aegis_v2/cli.py`
- 顶层入口 `aegis`
- `README.md`
- `AEGIS-v2.0-全量测试文档.md`

**实施要点**

- 决定是否支持顶层全局参数透传
- 如果不支持，就统一改文档
- 如果支持，就补齐 parser 和上下文传递
- 补 CLI `--help` 示例，减少隐式用法

**验收标准**

- CLI 文档与真实命令完全一致
- 所有保留命令都有可执行示例
- 新增对应 CLI 回归测试

---

### [ ] P0-4 为 Runtime 失败场景提供可恢复的错误处理

**目标**

- 避免 runtime 失败时只抛出原始 exit code
- 让用户知道失败原因、替代方案和下一步动作

**当前问题**

- 当前失败信息偏原始
- 无 fallback、无 retry、无安装/配置指引

**改动范围**

- `tools/aegis_v2/runtime.py`
- `tools/aegis_v2/executor.py`
- `tools/aegis_v2/registry.py`
- `tests/test_aegis_v2.py`

**实施要点**

- 统一 runtime error 类型
- 为 CLI missing / auth missing / timeout / non-zero exit 做细分
- 对可降级场景执行 fallback
- 将错误上下文写入 session/messages/checkpoints

**验收标准**

- 失败时返回结构化错误信息
- 可降级场景能切到备用模型
- 错误日志可从 session show 里看到

---

## P1

### [ ] P1-1 实现 Session 恢复与断点续跑

**目标**

- 让 checkpoint 不只是“记录”，而是真的可以恢复执行

**当前问题**

- 只有 `session list/show`
- 没有 `resume/recover/retry-from-checkpoint`

**改动范围**

- `tools/aegis_v2/session.py`
- `tools/aegis_v2/executor.py`
- `tools/aegis_v2/cli.py`
- `tests/test_aegis_v2.py`

**实施要点**

- 定义 session 恢复状态机
- 为 checkpoint 增加“恢复入口点”语义
- 支持从最后成功 stage 继续
- 保证共享上下文和 stage outputs 不丢失

**验收标准**

- 可以从 checkpoint 继续执行 pipeline/swarm/moa
- `session resume` / `session recover` 可用
- 恢复后的上下文与中断前一致

---

### [ ] P1-2 把 Cost Report 升级为 Cost Controller

**目标**

- 从“统计成本”升级到“控制成本”

**当前问题**

- 没有 `--budget`
- 没有预算阈值告警
- 没有超预算终止/降级
- 没有 input/output token 区分

**改动范围**

- `tools/aegis_v2/runtime.py`
- `tools/aegis_v2/session.py`
- `tools/aegis_v2/cli.py`
- `tools/aegis_v2/defaults.py`
- `tests/test_aegis_v2.py`

**实施要点**

- 支持 per-task budget
- 支持 alert thresholds
- 支持超预算后的 stop / downgrade 策略
- 在 pair/swarm/moa 中记录分阶段成本

**验收标准**

- `--budget` 可用
- 50% / 80% / 100% 阈值能触发事件
- session/cost report 能看到更细粒度成本数据

---

### [ ] P1-3 修复 Session 元数据状态一致性

**目标**

- 保证 `status`、`execution_state`、`final_output` 等字段在完成后保持一致

**当前问题**

- 已完成 session 中仍残留 `execution_state=executing`

**改动范围**

- `tools/aegis_v2/session.py`
- `tools/aegis_v2/executor.py`
- `tests/test_aegis_v2.py`

**验收标准**

- `completed` 状态下不会残留 `executing`
- `failed` / `planned` / `running` / `completed` 元数据清晰可判定

---

### [ ] P1-4 修正 Runtime 健康检查逻辑

**目标**

- 让 `models test` 反映真实可用性，而不是产生误报

**当前问题**

- CLI runtime 因缺 API env 被判 unavailable
- 本地运行时健康检查过于粗糙

**改动范围**

- `tools/aegis_v2/registry.py`
- `tools/aegis_v2/runtime.py`
- `tests/test_aegis_v2.py`

**实施要点**

- 区分 CLI-based runtime 与 API-based runtime
- `claude` / `codex` 健康检查不应硬依赖 env
- 对 `ollama` 增加更明确的 binary / service 检查

**验收标准**

- `models test` 输出与真实运行方式一致
- 不再把“CLI 已安装可用”误报为 unavailable

---

### [ ] P1-5 补齐 v2 TUI 或明确下线该目标

**目标**

- 解决“文档说有 v2 TUI，实际还是旧 control-plane TUI”的偏差

**当前问题**

- `aegis ui` 仍是旧 workflow/control-plane 界面
- 没有 v2 协作模式视图、成本视图、session 视图

**改动范围**

- 顶层入口 `aegis`
- `tools/control_plane/tui.py` 或新增 `tools/aegis_v2/tui.py`
- `README.md`
- v2 文档

**两条可选路径**

- 路径 A：真正实现 v2 TUI
- 路径 B：短期明确说明“v2 CLI only，TUI 未上线”

**验收标准**

- 产品文档与实际能力一致
- 如果保留 TUI 目标，则至少能查看 session、stage、cost、messages

---

### [ ] P1-6 清理“声明存在但未生效”的配置项

**目标**

- 让配置文件里的字段要么真正生效，要么先删除，避免假能力

**当前问题**

- 以下字段目前基本未被消费：
- `models.overrides.max_budget_per_task`
- `routing.task_patterns`
- `routing.context_thresholds`
- `cost_control.alerts`
- `performance.cache_responses`
- `performance.cache_ttl`

**改动范围**

- `tools/aegis_v2/defaults.py`
- `tools/aegis_v2/router.py`
- `tools/aegis_v2/runtime.py`
- `tools/aegis_v2/cli.py`
- 配套文档

**验收标准**

- 配置项全部有真实行为
- 或者被明确从默认配置和文档中移除

---

### [ ] P1-7 README 与产品定位切换到 v2 主叙事

**目标**

- 让用户一打开仓库就知道当前产品主入口是什么、主能力是什么

**当前问题**

- README 仍以 v1 的 Workflow / Team Pack / Governance 为中心
- v2 只存在于实现里，不存在于主叙事里

**改动范围**

- `README.md`
- v2 相关文档
- 安装说明与快速开始

**验收标准**

- README 首页明确写 v2 主入口
- 示例命令与当前 CLI 一致
- v1/v2 迁移状态对用户透明

---

## 建议执行顺序

### 第一轮

1. `P0-1` 模型一致性
2. `P0-2` 输入校验与模糊请求
3. `P0-3` CLI 契约统一

### 第二轮

1. `P0-4` Runtime 错误处理
2. `P1-3` Session 状态一致性
3. `P1-4` 健康检查修正

### 第三轮

1. `P1-1` Session 恢复
2. `P1-2` Cost Controller
3. `P1-6` 配置项清理

### 第四轮

1. `P1-5` v2 TUI 决策
2. `P1-7` README/v2 文档统一

