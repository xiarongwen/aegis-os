# AEGIS v2.0 全量测试报告 - 第二轮

**测试日期:** 2026-04-21  
**测试代码版本:** `893135a` + 本地修改 (11 个文件, +1034 行, -225 行)  
**测试环境:** macOS 26.0, Python 3.13.9  
**测试结论:** `功能大幅改进，P0 问题减少，但仍有关键问题待修复，建议继续内部迭代`

---

## 1. 执行摘要

本轮测试针对 2026-04-21 全量测试报告中发现的问题进行了回归验证，并对新功能进行了全面测试。

| 维度 | 本轮结论 | 对比上一轮 | 说明 |
|------|---------|-----------|------|
| 产品易用度 | 明显改善 | ↑↑ | 新增顶层命令 (pair/swarm/pipeline/moa)，参数传递更一致 |
| 功能完成度 | 部分通过 | ↑ | 新增 session resume/recover，但 Swarm workers 参数缺失 |
| 架构一致性 | 基本一致 | ↑ | 显式模型选择在某些场景仍有问题 |
| 测试覆盖率 | 57% | 新增 | 核心模块覆盖良好，CLI 和 executor 需要加强 |
| 发布建议 | 继续内部迭代 | - | 建议修复关键问题后再进入 Beta |

**自动化测试结果:**

```
pytest tests/test_aegis_v2.py: 19 passed
pytest tests/test_control_plane.py + test_runtime_bridge.py + test_automation_runner.py: 70 passed
总计: 89 passed, 0 failed
```

---

## 2. 已验证通过的能力

### 2.1 新增功能验证

| 功能 | 测试结果 | 说明 |
|------|---------|------|
| **顶层 Pair 命令** | 通过 | `aegis pair '任务'` 可直接进入结对模式 |
| **顶层 Swarm 命令** | 部分通过 | 命令存在但 `--workers` 参数缺失 |
| **顶层 Pipeline 命令** | 通过 | `aegis pipeline '任务'` 可用 |
| **顶层 MoA 命令** | 通过 | `aegis moa '任务'` 可用 |
| **Session Resume** | 部分通过 | 命令存在但未保持原 simulate 模式 |
| **Session Recover** | 部分通过 | 命令存在但默认执行而非 simulate |
| **Budget 参数** | 通过 | `--budget` 可正确传递到 session metadata |
| **Bridge 参数** | 通过 | `--bridge` 正确设置 use_bridge=true |
| **显式模型选择** | 部分通过 | 基本场景工作，但 pair 模式有异常 |

### 2.2 回归验证

| 上一轮问题 | 本轮状态 | 验证结果 |
|-----------|---------|---------|
| 空输入未正确处理 | 已修复 | 空输入返回明确错误信息 |
| 路由与执行计划不一致 | 部分修复 | 大多数场景已一致，pair 模式仍有问题 |
| `--models` 被覆盖 | 部分修复 | 需要进一步验证 |
| 完成态 execution_state | 已修复 | 现在正确显示 completed |
| session 无恢复能力 | 部分修复 | resume/recover 已添加但行为需优化 |

### 2.3 性能指标

| 指标 | 目标 | 实际 | 状态 |
|------|------|------|------|
| 路由决策时间 | < 500ms | ~172ms | 通过 |
| 简单任务响应 | < 30s | ~127ms (simulate) | 通过 |
| 代码覆盖率 | ≥ 80% | 57% | 未达标 |

---

## 3. 关键问题（按优先级排序）

### P0-1: Pair 模式显式模型选择异常

**现象:**
```bash
$ aegis run '测试' --models local-llm --execute --simulate
# 路由结果: models = ["local-llm"]
# 但执行计划中的 steps 仍使用 codex/claude-sonnet-4-6
```

**影响:**
- 隐私场景（强制 local-llm）无法保证
- 用户显式选择被忽略

**证据:**
```json
// 请求
"models": ["local-llm"]

// 执行计划
"steps": [
  {"name": "code", "model": "codex", ...},
  {"name": "review", "model": "claude-sonnet-4-6", ...}
]
```

---

### P0-2: Swarm 命令缺少 `--workers` 参数

**现象:**
```bash
$ aegis swarm '任务' --workers 3
error: unrecognized arguments: --workers 3
```

**影响:**
- Swarm 模式无法调整并行度
- 与测试文档定义不符

**期望:**
- `aegis swarm '任务' --workers 3` 应正常工作
- 默认 workers 数可从配置读取

---

### P0-3: Session Recover/Resume 未保持原 Run Mode

**现象:**
```bash
$ aegis session recover sess-xxx
# 尝试真实执行，而不是保持原 simulate 模式
```

**影响:**
- 恢复 simulate 模式的会话时会真实调用模型
- 可能产生意外成本

**期望:**
- 恢复时应保持原始 session 的 run_mode
- 或明确需要 `--execute` 才真实执行

---

### P1-1: 代码覆盖率不足

| 模块 | 覆盖率 | 状态 |
|------|--------|------|
| collaboration.py | 83% | 良好 |
| registry.py | 81% | 良好 |
| router.py | 77% | 良好 |
| session.py | 78% | 良好 |
| types.py | 85% | 良好 |
| cli.py | 10% | 严重不足 |
| executor.py | 15% | 严重不足 |
| runtime.py | 45% | 需改进 |

**建议:**
- 为 CLI 命令添加更多集成测试
- 为 executor 添加错误场景测试

---

### P1-2: TUI 仍为 v1 版本

**现象:**
`aegis ui` 或 `aegisctl ui` 仍进入旧版 control-plane TUI

**期望:**
- 根据 v2.0 设计文档实现新的多模型协作 TUI
- 支持实时协作可视化

---

## 4. 与测试文档的覆盖对照

### 4.1 功能测试覆盖矩阵

| 测试域 | 文档目标 | 当前结论 | 覆盖率 |
|--------|---------|---------|--------|
| Model Registry | 注册 / 发现 / 基础健康检查 | 通过 | 81% |
| Task Router | 分类 / 选择 / 边界处理 | 部分通过 | 77% |
| Collaboration Engine | Pair / Swarm / Pipeline / MoA | 部分通过 | 83% |
| Message Bus / Context Sync | 基本可用 | 部分通过 | - |
| Session Manager | 生命周期 / checkpoint / 恢复 | 部分通过 | 78% |
| Runtime Adapters | CLI 调用 / 异常处理 / fallback | 部分通过 | 45% |
| Cost Controller | 追踪 / 预算告警 / 报告 | 部分完成 | - |
| CLI | 基础命令可用 | 部分通过 | 10% |
| TUI | 交互式 v2 可视化 | 未完成 | - |

### 4.2 测试用例执行状态

**P0 用例:**
- [x] TC-MR-001: 模型注册
- [x] TC-MR-002: 能力匹配
- [x] TC-TR-001: 任务分类 - 简单任务
- [x] TC-TR-002: 任务分类 - 边界情况（空输入）
- [ ] TC-TR-002: 模糊请求处理（需改进）
- [x] TC-TR-003: 模型选择策略（quality/cost 模式）
- [x] TC-TR-004: 路由决策可视化
- [x] TC-CE-001: Pair Programming 模式
- [ ] TC-CE-003: Swarm 模式（缺少 workers 参数）
- [x] TC-CE-004: Pipeline 模式
- [x] TC-CE-005: MoA 模式
- [x] TC-SM-001: 会话生命周期
- [ ] TC-SM-002: 检查点管理（部分完成）
- [ ] TC-CLI-002: 参数传递（部分问题）

**P1 用例:**
- [ ] TC-CC-002: 预算告警（只有统计，无告警）
- [ ] TUI 相关用例（未完成）

---

## 5. 推荐修复顺序

### 第一优先级（阻塞发布）

1. **修复 Pair 模式显式模型选择问题**
   - 确保 `--models` 参数在执行计划中被尊重
   - 添加自动化测试覆盖

2. **添加 Swarm 的 `--workers` 参数**
   - 支持自定义并行度
   - 默认从配置读取

3. **修复 Session Recover/Resume 的 run_mode 处理**
   - 保持原始 session 的 simulate/execute 模式
   - 或要求显式 `--execute` 参数

### 第二优先级（提升体验）

1. **提升代码覆盖率到 80%**
   - 重点补充 cli.py 和 executor.py 测试
   - 添加错误场景测试

2. **实现 v2 TUI**
   - 基于 Textual 的多模型协作可视化
   - 实时显示各模型执行状态

3. **完善预算告警**
   - 实现预算阈值告警
   - 预算耗尽时优雅停止

### 第三优先级（锦上添花）

1. **模糊请求处理增强**
   - 识别模糊请求并提示澄清
   - 示例："优化代码" → "请指定要优化的文件或功能"

2. **性能优化**
   - 缓存路由决策结果
   - 优化并行执行效率

---

## 6. 最终判断

当前 AEGIS v2.0 的真实状态可以定义为：

**"多模型协作内核已经成形，基础 CLI 可用，协作模式可跑，但仍有 3 个 P0 关键问题需要修复。"

更准确的产品阶段建议：

| 阶段 | 是否匹配当前状态 |
|------|----------------|
| 原型 Prototype | 已超出 |
| 内部 Alpha | 匹配 |
| 可公开 Beta | 暂不匹配（需修复 P0 问题） |
| 完整 v2.0 发布 | 不匹配 |

### 建议

1. **当前版本 (893135a + 修改)** 已显著改进，但仍定位为 **内部 Alpha**
2. **不要** 把当前版本对外描述成 "v2.0 已完成"
3. 先修复 P0-1、P0-2、P0-3 这三个关键问题
4. 提升代码覆盖率到 80% 以上
5. 然后进入下一轮验收

---

## 7. 附录：测试脚本

以下是本次测试使用的关键命令：

```bash
# 基础功能测试
bash aegis config init --format json
bash aegis models list --format json
bash aegis router dry-run '实现JWT认证' --format json
bash aegis '实现JWT认证' --format json

# 协作模式测试
bash aegis run '修复登录bug' --execute --simulate --format json
bash aegis pair '重构模块' --execute --simulate --format json
bash aegis swarm '生成测试' --execute --simulate --format json  # workers 参数缺失
bash aegis pipeline '开发功能' --execute --simulate --format json
bash aegis moa '评审设计' --execute --simulate --format json

# 会话管理测试
bash aegis session list --format json
bash aegis session show <id> --format json
bash aegis session resume <id> --format json  # 需要改进
bash aegis session recover <id> --format json  # 需要改进

# 成本和预算测试
bash aegis run '测试' --budget 5.00 --execute --simulate --format json
bash aegis cost report --format json

# 路由策略测试
bash aegis router dry-run '架构设计' --mode quality --format json
bash aegis router dry-run '简单任务' --mode cost --format json

# 显式模型选择测试（有问题）
bash aegis run '测试' --models local-llm --execute --simulate --format json
```

---

*测试报告生成: 2026-04-21*  
*测试执行者: Claude Code*  
*版本: 第二轮全量测试*
