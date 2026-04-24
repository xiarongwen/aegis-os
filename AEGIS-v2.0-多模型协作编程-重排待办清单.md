# AEGIS v2.0 多模型协作编程重排待办清单

**依据文档:** `AEGIS-v2.0-产品定位与需求文档.md`  
**目标:** 只保留和“多模型协作编程”直接相关的研发任务  
**原则:** 不再把严格门控 workflow、重治理、Team Pack 作为 v2.0 主线

---

## 一、主线目标

当前开发主线只保留这 6 个方向：

1. 可信的模型路由
2. 清晰的协作模式
3. 简洁的编程 CLI
4. 稳定的 runtime 执行
5. 可追踪的 session/context/message
6. 基础成本与性能控制

以下内容不进入当前主线：

- 严格门控 workflow
- 强制状态机
- 重型 governance
- Team Pack 产品面
- Evolution / Nightly Schedule

---

## 二、P0

### [ ] P0-1 模型选择可信化

**目标**

- `router` 选中的模型必须和真正执行的模型一致
- `--models` 显式指定必须真实生效

**保留原因**

- 这是多模型协作产品最核心的可信度基础

**涉及模块**

- `tools/aegis_v2/router.py`
- `tools/aegis_v2/executor.py`
- `tools/aegis_v2/cli.py`
- `tests/test_aegis_v2.py`

**验收**

- `routing.models == execution_plan.steps[*].model` 的映射规则清晰
- `pair/swarm/moa/pipeline` 都支持显式模型覆盖

---

### [ ] P0-2 输入与任务分类可信化

**目标**

- 空输入、模糊输入、超长输入都能被正确处理
- 分类结果更贴近编程场景，而不是一律掉回 `code_gen`

**保留原因**

- 这是用户第一步体验，不可靠会直接破坏产品感知

**涉及模块**

- `tools/aegis_v2/router.py`
- `tools/aegis_v2/cli.py`
- `tools/aegis_v2/types.py`
- `tests/test_aegis_v2.py`

**验收**

- 空输入报错
- 模糊请求要求澄清
- 超长输入不崩溃

---

### [ ] P0-3 CLI 产品面收敛

**目标**

- 把 v2 CLI 收敛成“run + 协作模式 + 查看入口”的最小产品面

**建议命令面**

```bash
aegis "实现登录功能"
aegis run "修复 SQL 注入"
aegis pair "重构认证模块"
aegis swarm "生成测试用例"
aegis pipeline "修复并验证 bug"
aegis moa "评审架构方案"
aegis models list
aegis session list
aegis cost report
```

**保留原因**

- 这是用户真正接触产品的方式

**涉及模块**

- `aegis`
- `tools/aegis_v2/cli.py`
- `README.md`

**验收**

- 顶层命令清晰
- `--help` 一致
- 文档中的命令都能执行

---

### [ ] P0-4 协作模式稳定化

**目标**

- Pair / Swarm / Pipeline / MoA 都可稳定执行
- 结果聚合逻辑清晰、可预测

**当前重点**

- Pair 的轮次终止条件
- Swarm 的子任务拆分质量
- Pipeline 的上下文传递
- MoA 的专家结果汇总

**涉及模块**

- `tools/aegis_v2/collaboration.py`
- `tools/aegis_v2/executor.py`
- `tests/test_aegis_v2.py`

**验收**

- 四种模式都能稳定执行
- session 中能看到完整 stage 和 messages
- simulate 模式更接近真实行为

---

### [ ] P0-5 Runtime 错误体验升级

**目标**

- 运行失败时给出对用户有用的错误，而不是裸 exit code

**保留原因**

- 多模型协作产品一定会频繁碰 runtime 问题，这直接影响可用性

**涉及模块**

- `tools/aegis_v2/runtime.py`
- `tools/aegis_v2/executor.py`
- `tools/aegis_v2/registry.py`
- `tests/test_aegis_v2.py`

**验收**

- 区分 binary missing / auth missing / timeout / runtime failed
- 错误信息可理解
- 可 fallback 的场景支持降级

---

## 三、P1

### [ ] P1-1 Session 恢复能力

**目标**

- 从“可记录”升级到“可恢复”

**保留原因**

- 协作任务往往更长，恢复能力属于核心体验增强

**涉及模块**

- `tools/aegis_v2/session.py`
- `tools/aegis_v2/executor.py`
- `tools/aegis_v2/cli.py`

**验收**

- 支持 `session resume`
- 支持从最后一个有效 checkpoint 继续

---

### [ ] P1-2 Cost Controller

**目标**

- 增加预算、告警、超预算策略

**保留原因**

- 多模型协作如果没有成本控制，很难长期使用

**涉及模块**

- `tools/aegis_v2/runtime.py`
- `tools/aegis_v2/session.py`
- `tools/aegis_v2/cli.py`
- `tools/aegis_v2/defaults.py`

**验收**

- `--budget` 可用
- 告警阈值生效
- session/cost report 能看到更细成本

---

### [ ] P1-3 Runtime Health 检查修正

**目标**

- `models test` 更准确反映实际可用性

**保留原因**

- 这会直接影响用户是否信任系统的运行判断

**涉及模块**

- `tools/aegis_v2/registry.py`
- `tools/aegis_v2/runtime.py`

**验收**

- CLI runtime 不再被 API env 误伤
- local runtime 有更清晰诊断

---

### [ ] P1-4 Session 状态一致性修正

**目标**

- 清理 `completed` 但 `execution_state=executing` 这类脏状态

**涉及模块**

- `tools/aegis_v2/session.py`
- `tools/aegis_v2/executor.py`

**验收**

- session metadata 状态统一

---

### [ ] P1-5 配置项清理与生效

**目标**

- 删除或接上目前“写了但没生效”的配置

**优先保留**

- 模型启用与默认策略
- 协作模式默认配置
- cost control
- performance 并发配置

**降级处理**

- 先不做复杂 routing DSL
- 先不做无用缓存字段堆积

---

### [ ] P1-6 产品文档与 README 重写

**目标**

- 让仓库首页和主文档都切换到“多模型协作编程助手”叙事

**重点内容**

- 产品是什么
- 用户怎么用
- 四种协作模式是什么
- 为什么 Claude + Codex 协作比单模型更强

---

### [ ] P1-7 v2 轻量可视化界面

**目标**

- 如果继续做 UI，就做面向 v2 的协作可视化

**只保留的方向**

- session 列表
- 当前 stages
- messages
- selected models
- estimated/actual cost

**不做**

- 旧 workflow 主导式 UI 心智

---

## 四、降级到兼容层的内容

以下能力不删除，但从 v2.0 主待办移出：

- 旧 workflow orchestration
- gate reviewer / lock file 主流程
- Team Pack 产品化
- heavy governance
- evolution / nightly schedule

后续如需保留，应归类为：

- `legacy`
- `advanced`
- `enterprise`

而不是当前主线。

---

## 五、建议开发顺序

### 第一轮

1. `P0-1` 模型选择可信化
2. `P0-2` 输入与任务分类可信化
3. `P0-3` CLI 产品面收敛

### 第二轮

1. `P0-4` 协作模式稳定化
2. `P0-5` Runtime 错误体验升级

### 第三轮

1. `P1-1` Session 恢复能力
2. `P1-2` Cost Controller
3. `P1-3` Runtime Health 检查修正
4. `P1-4` Session 状态一致性修正

### 第四轮

1. `P1-5` 配置项清理与生效
2. `P1-6` README / 产品文档重写
3. `P1-7` v2 轻量可视化界面

