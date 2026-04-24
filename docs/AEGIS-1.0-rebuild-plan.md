# AEGIS 1.0 彻底重构计划

**版本:** 1.0 rebuild baseline  
**日期:** 2026-04-21  
**状态:** 新开发主线决策  

---

## 1. 重构结论

AEGIS 1.0 不是在旧版本上继续修补。

AEGIS 1.0 是一条新的产品主线：

> 从零收口产品体验，以 `aegis ulw "<task>"` 为主入口，构建一个多模型协作编程 autopilot。

旧 v1/v2 的代码、文档、命令和 workflow 只能作为参考材料。任何旧模块进入 1.0 前都必须经过重新归类、重新命名、重新测试。

---

## 2. 为什么必须重构

旧版本的问题不是单个 bug，而是产品主线混乱：

1. v1 是治理型 workflow 系统，和当前目标不一致。
2. v2 是多模型协作内核，但仍受旧控制面、旧文档和不一致 CLI 影响。
3. 用户入口不锋利，`run/pair/swarm/pipeline/moa` 暴露太早。
4. 缺少 `ulw` 这样的第一主功能。
5. 缺少终端 cockpit，长任务不可观察。
6. 模型路由偏 model-centric，缺少 role/category 层。
7. README、Quickstart、bootstrap、真实 CLI 之间不完全一致。

因此 1.0 的任务不是“修旧版本”，而是“重建一个可用版本”。

---

## 3. 重构原则

### 3.1 主功能唯一

1.0 只围绕一个主功能设计：

```bash
aegis ulw "<coding task>"
```

其他能力都必须服务这条链路。

### 3.2 legacy 冻结

以下模块冻结为 legacy，不再扩展新功能：

```text
tools/control_plane/
tools/automation_runner/
.aegis/core/
.aegis/runs/
shared-contexts/
旧 agents/team-pack/workflow 文档
```

可以读，可以迁移思路，不允许继续把 1.0 新功能写进去。

### 3.3 新主线独立

1.0 新主线需要独立目录、独立命令契约、独立测试。

建议新目录：

```text
tools/aegis_1/
tests/test_aegis_1_*.py
docs/AEGIS-1.0-*.md
```

旧 `tools/aegis_v2/` 可以作为迁移来源，但不直接作为 1.0 的最终命名空间。

### 3.4 先产品链路，后高级能力

1.0 先保证：

```text
task -> route -> plan -> execute/simulate -> cockpit -> session -> recover
```

不先做：

```text
team pack
enterprise governance
nightly evolution
复杂插件市场
完整 LSP/AST 工具体系
```

---

## 4. 1.0 新架构

```text
CLI
  -> IntentRouter
  -> RolePlanner
  -> ModelResolver
  -> RunPlanner
  -> CollaborationEngine
  -> RuntimeManager
  -> SessionStore
  -> EventProjector
  -> Cockpit
```

### 模块建议

```text
tools/aegis_1/cli.py
  命令入口，ulw/run/watch/session/models/config

tools/aegis_1/router.py
  请求校验、任务分类、复杂度、策略建议

tools/aegis_1/roles.py
  orchestrator/planner/builder/reviewer/researcher/verifier/aggregator

tools/aegis_1/models.py
  model registry、role/category fallback、可用性检查

tools/aegis_1/planner.py
  将 intent + roles + models 转成 run plan

tools/aegis_1/engine.py
  single/pair/swarm/pipeline/moa 执行引擎

tools/aegis_1/runtime.py
  codex/claude/ollama/simulate/tmux bridge adapter

tools/aegis_1/session.py
  sqlite session、events、checkpoints、outputs

tools/aegis_1/events.py
  统一事件模型和 cockpit projection

tools/aegis_1/cockpit.py
  Textual/Rich 终端驾驶舱

tools/aegis_1/config.py
  workspace config、paths、defaults
```

---

## 5. 可迁移资产

旧代码可以迁移以下资产：

```text
tools/aegis_v2/router.py
  任务分类关键词、复杂度估算思路

tools/aegis_v2/collaboration.py
  pair/swarm/pipeline/moa 的执行经验

tools/aegis_v2/runtime.py
  codex/claude/ollama adapter 思路

tools/aegis_v2/session.py
  sqlite session schema 思路

tools/runtime_bridge/cli.py
  tmux bridge 可直接保留或包装

tests/test_aegis_v2.py
  可迁移成 1.0 回归测试
```

迁移规则：

- 只迁移必要逻辑，不照搬旧命名。
- 迁移后必须有 1.0 测试。
- 迁移后必须服从 1.0 PRD 的命令和数据模型。

---

## 6. 新开发阶段

### Phase 0: 冻结旧线

交付：

- README 标注旧 v1/v2 为 legacy。
- 新增 1.0 PRD 和重构计划。
- 明确 1.0 新目录。

验收：

- 开发者知道新功能只写入 1.0 主线。

### Phase 1: 新 CLI 骨架

交付：

```bash
aegis ulw "<task>"
aegis run "<task>"
aegis watch <session_id>
aegis session list
aegis session show <session_id>
```

验收：

- 命令可以创建 1.0 session。
- `ulw` 默认执行 simulate 或 dry-run fallback。

### Phase 2: 新 session/event 模型

交付：

- session schema。
- event schema。
- event projection。
- session show 输出。

验收：

- cockpit 所需数据全部可从 session/event 获取。

### Phase 3: 新 routing/planning/model resolver

交付：

- IntentRouter。
- RolePlanner。
- ModelResolver。
- RunPlanner。

验收：

- `aegis ulw --simulate` 能生成 role-aware run plan。
- 显式模型不会被覆盖。

### Phase 4: CollaborationEngine

交付：

- single。
- pair。
- swarm。
- pipeline。
- moa。

验收：

- 所有模式支持 simulate execute。
- stage events 完整写入。

### Phase 5: Cockpit

交付：

- AEGIS AUTOPILOT 终端页面。
- 顶部总览。
- 任务进展。
- 动态事件。

验收：

- `aegis ulw "<task>"` 默认进入 cockpit。
- `aegis watch <session_id>` 可复看运行中 session。

### Phase 6: Runtime 接入

交付：

- codex adapter。
- claude adapter。
- ollama adapter。
- tmux bridge。
- runtime fallback。

验收：

- simulate 和真实 runtime 都走同一套 event/session。
- runtime 失败可理解、可恢复。

---

## 7. 1.0 最小可用标准

1.0 可用版本必须满足：

```bash
aegis ulw "修复一个 bug" --simulate
```

能完成：

1. 创建 session。
2. 路由任务。
3. 生成 role-aware plan。
4. 执行至少一个 collaboration pattern。
5. 写入 events。
6. 展示 cockpit。
7. `session show` 可复盘。

真实模型执行可以作为 1.0 beta 后半段完成，但数据链路和 cockpit 必须先成立。

---

## 8. 不做的事

1.0 重构期间不做：

- 修复 v1 workflow。
- 扩展 Team Pack。
- 继续维护 L1-L5 文档。
- 给旧 automation runner 加新功能。
- 让 control plane 继续承担主入口。
- 做 Web UI。
- 做完整插件市场。

---

## 9. 最终目标

重构完成后，AEGIS 应该呈现为：

```text
一个清晰的新 1.0 产品：
  aegis ulw "<task>"

一个清晰的新架构：
  route -> role plan -> model resolve -> execute -> events -> cockpit

一个清晰的新体验：
  终端里实时看到多个模型协作完成编程任务
```

这才是 AEGIS 1.0。

