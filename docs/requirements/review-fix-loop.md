# Review-Fix-LGTM Loop

## Summary

将当前 AEGIS 的一次性 gate review 升级为闭环审查流：

`review -> fix -> re-review -> ... -> LGTM`

目标是让 gate 不再只是“发现问题并打回”，而是要求问题必须经过修复、复审和收敛，直到 reviewer 明确给出 `LGTM`，或者达到阻断条件。

## Problem

当前 review gate 更接近单次判定：

- reviewer 发现问题
- 工作流退回上一个阶段修复
- 再次进入 review

这种模式的问题是：

- 缺少显式的 review / fix 往返记录
- reviewer 无法围绕“上一轮问题是否解决”进行持续复审
- 容易把每一轮 review 变成“重新从头审”，而不是 issue closure
- 缺少明确的 `LGTM` 终态语义

## Goal

为 gated review 引入显式的循环状态和产物：

1. reviewer 提出问题
2. 执行 agent 逐条修复并响应
3. reviewer 复审上轮问题
4. 重复直到：
   - 所有 blocker 被关闭并给出 `LGTM`
   - 或超过循环上限进入 `BLOCKED`

## Scope

优先适用于以下 gate：

- `L2_REVIEW`
- `L3_CODE_REVIEW`
- `L3_SECURITY_AUDIT`
- `L4_REVIEW`
- `L5_REVIEW`

首批重点应放在：

- code review
- security audit
- QA / release review

## Proposed Flow

建议引入 review loop 子状态：

- `pending_review`
- `changes_requested`
- `in_fix`
- `re_review`
- `lgtm`
- `blocked`

如果不想改顶层状态机，也可以在 gate 内增加 `review_loop_status` 字段，而不是新增顶层 workflow state。

## Required Artifacts

每一轮 review / fix 都应有独立产物：

### 1. `review-round-N.md`

记录：

- 本轮问题列表
- 问题级别
- 是否继承自上一轮
- reviewer verdict

### 2. `fix-response-round-N.md`

记录：

- 修复 agent 对每条问题的响应
- 修复方式
- 无法修复的原因
- 风险说明

### 3. `review-loop-status.json`

建议字段：

```json
{
  "workflow_id": "example",
  "gate": "L3_CODE_REVIEW",
  "round": 2,
  "status": "re_review",
  "open_issues": ["CR-2", "CR-4"],
  "closed_issues": ["CR-1", "CR-3"],
  "verdict": "changes_requested",
  "lgtm": false,
  "max_rounds": 3
}
```

### 4. `review-passed.json`

只有在 reviewer 明确给出 `LGTM` 时才允许作为通过产物写入或更新。

## LGTM Criteria

只有同时满足以下条件时，reviewer 才能给出 `LGTM`：

- 上一轮 blockers 全部关闭
- 没有未处理的高优先级问题
- 修复没有引入新的阻断问题
- 本轮审查产物完整
- 仍满足 gate 的 score threshold
- reviewer 显式给出 `verdict: LGTM`

## Failure Conditions

不允许无限循环。以下情况应中断并进入阻断或回退逻辑：

- review / fix loop 超过最大轮次
- 同一 blocker 多轮未关闭
- 修复引入新的严重问题
- 安全审计发现 critical finding
- 需求锁被破坏
- reviewer 判断当前实现方向错误，需要退回 planning

## Requirements Accuracy And Drift Control

这个机制必须和 `requirements-lock.json` 联动：

- fix 不允许静默改变原始需求语义
- reviewer 需要检查 fix 是否导致 scope 漂移
- 如果为了解决 review 问题而改变需求定义，必须走 planning / change-control，而不是继续留在 review loop

## Acceptance Criteria

1. 每个 gated review 都支持多轮 review / fix 循环。
2. 每一轮都有独立的 review artifact 和 fix artifact。
3. reviewer 可以显式标记 issue 为 `open / fixed / rejected / deferred`。
4. gate 只有在 `LGTM` 时才算真正通过。
5. loop 超限时，系统自动进入阻断或回退逻辑。
6. 如果 fix 导致 requirements lock 不一致，流程会被控制面拦下。
7. 最终可以清晰追踪：
   - review 了多少轮
   - 每轮修了什么
   - 哪些问题关闭了
   - 为什么最终 LGTM

## Implementation Notes

后续实现时建议同时改动：

- `.aegis/core/orchestrator.yml`
- control plane 的 gate 校验逻辑
- review artifact schema
- reviewer / fixer agent 的输出约定
- `README.md` 与 `CLAUDE.md` 的流程说明
