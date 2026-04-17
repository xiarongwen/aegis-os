# AEGIS v2 重构需求文档

## 1. 文档目的

本文件用于定义 AEGIS 下一阶段的正式重构方向，防止项目继续沿着“治理优先的多 agent 工作流框架”路线演化，而偏离用户真正需要的产品形态。

这次重构要回答的核心问题不是：

- 还能不能继续补 schema
- 还能不能继续加 gate
- 还能不能继续强化状态机

而是：

- AEGIS 在 Claude Code / Codex 里的真正角色是什么
- AEGIS 应该怎样增强宿主，而不是替代宿主
- AEGIS 怎样生成、安装、运营和进化长期可用的专业团队
- 用户怎样在日常高频场景里轻量使用这些团队，而不感到臃肿
- 现有满意的多 agent 分工与 review/fix 能力，怎样保留下来并产品化

本文件是 v2 重构的需求基线，后续架构设计、控制面调整、Team Pack 模型、宿主集成与演进机制，都必须以本文件为准。

---

## 2. 一句话定义

**AEGIS 是一个运行在 Claude Code / Codex 等 Agent CLI 宿主之上的、多功能专业团队生成与运营系统。**

它本身不是底层通用执行引擎，而是宿主之上的增强层，用来：

- 围绕用户目标自动搜索和理解任务
- 自动生成或组装专业团队
- 让团队内部自动分工、并行执行、review/fix
- 让这些团队长期可调用、可复用、可进化

---

## 3. 产品重构结论

### 3.1 正确定位

AEGIS v2 的正确定位是：

- Claude Code / Codex 的增强层
- 一个 Team Pack 生成器
- 一个 Team Pack 运营系统
- 一个多功能专业团队 Bot 平台
- 一个围绕目标自动组织团队的元系统

### 3.2 错误定位

AEGIS v2 不是：

- 一个要替代 Claude Code / Codex 的独立执行器
- 一个以重治理为主的企业流程框架
- 一个只服务软件开发的系统
- 一个只会一次性编排 agent 的任务流水线
- 一个要求用户频繁操作状态机、hook、artifact 的复杂平台

### 3.3 重构原则

这次重构必须坚持以下原则：

- 宿主优先：Claude Code / Codex 继续承担底层执行
- 增强优先：AEGIS 负责“组团队、跑团队、进化团队”
- 体验优先：日常使用必须轻量
- 团队优先：核心对象从 workflow 转向 Team Pack
- 进化优先：持续进化是一级能力，不是附属脚本
- 质量保留：现有多 agent 分工和 review/fix 能力保留并升级

---

## 4. 背景与当前问题

当前 AEGIS 已经具备这些优点：

- 有清晰的 agent 分工
- 有可用的 review / fix / re-review / LGTM 机制
- 有控制面、状态机、hook、schema 和 doctor
- 有跨项目 attach 的基础能力
- 有 host-native `/aegis ...` 入口语义

但当前版本仍存在明显问题：

### 4.1 产品重心偏治理，不偏增强

当前系统更像一个“治理正确的工作流控制面”，而不是一个“日常好用的增强型团队 bot”。

### 4.2 用户日常感知过重

对于高频场景，例如：

- 修一个 bug
- 写一个需求
- 搜一个方向
- 做一个第一版 MVP

用户并不想感知：

- 复杂状态机
- 大量 artifact
- 显式 gate 流程
- 过重的 schema 和 JSON

### 4.3 没有“长期团队”这一产品对象

用户真正想要的不是每次都从零跑 workflow，而是：

- 创建一个长期可用的逆向团队
- 创建一个长期可用的视频剪辑团队
- 创建一个长期可用的 MVP 团队

然后在未来的 Claude Code / Codex 会话里直接调用这些团队。

### 4.4 对宿主能力的利用还不够产品化

Claude Code / Codex 已经有：

- 搜索
- 代码库理解
- 编辑和执行
- 子 agent
- 技能扩展

AEGIS 的任务不是重复造底层能力，而是把这些能力组织成“长期专业团队”。

### 4.5 需求漂移控制不是产品主轴

用户明确反馈：

- 严格防需求漂移不是本产品的主重心
- 多 agent 分工和 review/fix 才是最满意、最该保留的部分

因此 v2 必须从“强治理中心”切换到“执行增强中心”，治理只保留轻量兜底能力。

---

## 5. v2 核心目标

AEGIS v2 的目标是让用户能够在宿主中做到：

### 5.1 生成团队

例如：

- `AEGIS 帮我创建一个逆向团队，名字叫 AEGIS-nx`
- `AEGIS 帮我创建一个视频剪辑团队，名字叫 AEGIS-video`
- `AEGIS 帮我创建一个研究 + 产品 + 开发团队，用来做 MVP`

### 5.2 长期使用团队

例如：

- `AEGIS-nx 帮我逆向一下 xx app，找出 xx 功能是怎么写的`
- `AEGIS-video 帮我制作一个 xxx 视频，风格是 xxx`
- `AEGIS-mvp 帮我做这个想法的第一版产品`

### 5.3 团队内部自动协作

用户不应手动调多个 agent。团队内部应自动完成：

- 搜索
- 代码库理解
- 任务拆解
- 并行执行
- review
- fix
- re-review
- 汇总结果

### 5.4 团队持续进化

团队不是固定 prompt 集，而是长期可优化的资产。系统应支持：

- 复盘最近任务
- 调整团队结构
- 优化角色职责
- 优化内部 review/fix 机制
- 沉淀成功执行策略

---

## 6. 非目标

本次 v2 重构明确不做以下事情：

- 不把 AEGIS 重新做成一个重型外部 CLI 平台
- 不把 AEGIS 继续定义成企业级强治理流程产品
- 不强制所有任务都走完整 workflow 状态机
- 不要求用户显式管理所有 artifact
- 不要求用户每次选择 agent、review 层级、并行规模
- 不把所有团队都做成长期固定内置团队

---

## 7. 核心对象模型

v2 必须正式引入新的产品对象。

### 7.1 AEGIS Core

AEGIS Core 是元系统，负责：

- 创建团队
- 安装团队
- 管理团队
- 调度团队
- 进化团队
- 维护团队注册表

AEGIS Core 不是日常高频执行团队本身。

### 7.2 Team Pack

Team Pack 是 v2 的核心对象。

示例：

- `AEGIS-nx`
- `AEGIS-video`
- `AEGIS-mvp`
- `AEGIS-research`
- `AEGIS-bugfix`

每个 Team Pack 必须包含：

- `team_id`
- `display_name`
- `mission`
- `domain`
- `roles`
- `playbooks`
- `review_mode`
- `tooling_policy`
- `memory_policy`
- `evolution_policy`
- `lifecycle_scope`

### 7.3 Team Role

Role 是 Team Pack 内部的专业角色。

例如在 `AEGIS-video` 中：

- trend researcher
- content structure planner
- editing director
- hook / caption specialist
- quality reviewer

例如在 `AEGIS-nx` 中：

- reverse research analyst
- static analysis specialist
- behavior mapping specialist
- conclusion reviewer

### 7.4 Team Run

Team Run 是 Team Pack 的一次执行实例。

例如：

- 一次 `AEGIS-nx` 的逆向分析任务
- 一次 `AEGIS-video` 的视频制作任务
- 一次 `AEGIS-mvp` 的 MVP 生成任务

### 7.5 Team Memory

Team Memory 是团队的长期经验层，记录：

- 过往任务摘要
- 常用工作方式
- 有效团队组合
- 领域偏好
- 表现好的 playbook

### 7.6 Team Template

Team Template 是可复制的团队蓝图。

当一个动态生成团队表现稳定后，应能沉淀为模板，供后续快速复用或升级为正式 Team Pack。

---

## 8. 生命周期模型

v2 需要明确三种团队生命周期。

### 8.1 Session Team

只服务一次任务的临时团队。

适用场景：

- 一次性调研
- 一次性分析
- 一次性复杂执行

### 8.2 Project Team

绑定某个具体项目或仓库的长期团队。

适用场景：

- 某个代码仓库的 bug 处理团队
- 某个项目的 MVP 交付团队
- 某个 repo 的长期逆向分析团队

### 8.3 Global Team

可在多个项目和多个会话中长期复用的团队。

适用场景：

- `AEGIS-nx`
- `AEGIS-video`
- `AEGIS-research`

---

## 9. 使用模式

v2 必须支持三类主要使用模式。

### 9.1 模式一：创建团队

用户通过 AEGIS Core 创建一个团队。

示例：

- `AEGIS 帮我创建一个逆向团队，名字叫 AEGIS-nx，长期用于分析移动 app`
- `AEGIS 帮我创建一个专业的视频剪辑团队，名字叫 AEGIS-video`

系统必须完成：

1. 理解用户要什么团队
2. 判断团队领域和目标
3. 搜索该领域常见专业角色与最佳实践
4. 自动设计团队结构
5. 生成团队角色与 playbook
6. 生成团队 review/fix 机制
7. 安装为一个可长期调用的 Team Pack

### 9.2 模式二：调用团队

用户直接调用已有团队，而不是重新描述流程。

示例：

- `AEGIS-nx 帮我逆向一下 xx app`
- `AEGIS-video 帮我制作一个 xxx 风格的视频`
- `AEGIS-bugfix 帮我处理这个支付 bug`

系统必须完成：

1. 识别目标团队
2. 加载团队配置、记忆和 playbook
3. 自动执行团队内部编排
4. 输出结果和必要的进展

### 9.3 模式三：进化团队

用户对已有团队进行优化。

示例：

- `AEGIS 优化一下 AEGIS-video 的剪辑风格判断`
- `AEGIS 复盘一下 AEGIS-nx 最近三次任务，提升它的逆向效率`

系统必须完成：

1. 读取团队最近执行记录
2. 识别瓶颈和可改进点
3. 更新团队角色、playbook 或 prompt
4. 记录版本演进

---

## 10. 日常使用体验要求

v2 最关键的体验要求是：

**日常使用必须轻量，复杂度默认隐藏。**

### 10.1 单入口

用户日常不应看到复杂编排界面，主要入口应保持简单自然语言调用：

- `AEGIS ...`
- `AEGIS-nx ...`
- `AEGIS-video ...`

### 10.2 默认隐藏内部 agent

用户默认不看见内部角色列表，不手动点选 agent。

内部角色只在以下情况下按需展开：

- 用户明确询问团队构成
- 用户询问当前谁在做什么
- 调试或复盘
- 团队创建阶段需要确认核心结构

### 10.3 默认最小团队

系统必须优先使用“最小足够团队”，而不是默认豪华阵容。

建议规则：

- 小任务：2 到 3 个角色
- 中任务：3 到 5 个角色
- 大任务：按需扩编

### 10.4 结果优先展示

默认展示内容应是：

- 我理解的目标
- 我已经启动的工作
- 当前进展
- 当前风险
- 最终结果

默认不优先展示：

- 状态机
- artifact 清单
- schema 校验细节
- 内部多 agent 噪音

### 10.5 团队内部流程感后置

团队内部可以有复杂流程，但不应该成为用户主界面的主要体验。

### 10.6 支持持续接管

团队应支持跨会话持续工作，而不是每次重新初始化。

---

## 11. 深度使用要求

AEGIS 不仅要适合一次性任务，还要适合长期深度使用。

### 11.1 持续团队

用户创建好的 Team Pack 必须可长期存在、长期调用。

### 11.2 任务连续性

团队必须能延续上一次任务上下文，而不是每轮都从零开始。

### 11.3 项目绑定能力

Project Team 必须能绑定到某个项目，在后续 bug 修复、需求开发、维护分析中持续使用。

### 11.4 团队版本化

每个 Team Pack 应该有版本概念，便于：

- 演进记录
- 回滚
- 升级
- A/B 验证

### 11.5 团队模板化

表现稳定的动态团队应能沉淀成模板，用于后续快速复制。

---

## 12. 多 agent 分工与 review/fix 要求

用户明确反馈现有多 agent 分工与 review/fix 设计是满意的，因此 v2 必须保留并升级。

### 12.1 保留自动分工

Team Pack 内部必须继续支持：

- 按角色分工
- 任务拆解
- 可并行任务自动并行
- 结果汇总

### 12.2 review/fix 作为团队内建能力

review/fix 不应再主要表现为一个沉重的外部 workflow，而应成为 Team Pack 的内建质量机制。

### 12.3 默认自动 review/fix

对中高价值任务，团队内部默认执行：

`execute -> review -> fix -> re-review -> LGTM`

### 12.4 轻重分级

review/fix 应支持轻重分级：

- 轻任务：轻 review
- 关键任务：完整 review/fix/re-review

### 12.5 团队内建 reviewer

每个 Team Pack 在定义时必须明确 reviewer 角色或 reviewer 机制。

---

## 13. 搜索与外部信息获取要求

搜索不是附属功能，而是多个 Team Pack 的核心能力之一。

### 13.1 创建团队时可搜索

创建团队阶段，AEGIS Core 应能搜索该领域的角色结构、工作方式和最佳实践。

### 13.2 执行团队任务时可搜索

例如：

- `AEGIS-nx` 搜索相关逆向资料
- `AEGIS-video` 搜索风格参考与趋势
- `AEGIS-mvp` 搜索竞品和常见方案

### 13.3 搜索不是强制动作

并非所有任务都要搜索，系统应按目标自动判断是否需要外部检索。

---

## 14. 宿主集成要求

v2 必须明确：

**Claude Code / Codex 是宿主，AEGIS 是增强层。**

### 14.1 不重复造宿主基础能力

AEGIS 不应重做：

- 通用编辑器能力
- 通用代码执行能力
- 通用搜索能力
- 通用子 agent 能力

### 14.2 Team Pack 必须以宿主可调用对象存在

例如：

- `AEGIS-nx`
- `AEGIS-video`

这些团队应该在宿主中表现为长期可用的入口对象，而不是一次性脚本。

### 14.3 Core 与 Team Pack 分层

宿主集成必须区分：

- `AEGIS`：创建团队、运营团队、优化团队
- `AEGIS-xxx`：执行该领域的具体任务

### 14.4 保持 host-native 交互

主产品交互应继续以宿主会话自然语言为主，而不是把用户赶回外部 CLI。

---

## 15. 轻治理原则

v2 不是放弃治理，而是治理降权。

### 15.1 轻治理而非重治理

治理目标从“严格防漂移”切换为：

- 保证团队结构清晰
- 保证 review/fix 有效
- 保证关键结果可复盘
- 保证团队可以长期演进

### 15.2 保留的治理能力

以下能力保留：

- 团队注册表
- 团队版本
- review/fix 记录
- 任务摘要
- 演进日志

### 15.3 降低显式流程暴露

以下能力不应继续作为用户主体验核心：

- 重状态机显式感
- 过多 schema 暴露
- 大量 artifact 强感知
- 过重的 requirements lock 流程

---

## 16. 团队进化要求

持续进化是 v2 的一级能力，不是附属脚本。

### 16.1 进化对象

进化不只针对单个 agent prompt，还必须包括：

- 团队结构
- 团队角色职责
- 团队 playbook
- review/fix 机制
- 工具使用策略
- 团队默认规模

### 16.2 进化输入

团队进化应基于：

- 任务结果质量
- review/fix 循环表现
- 用户反馈
- 成功案例复盘
- 失败案例复盘

### 16.3 进化输出

进化后可输出：

- 新版本 Team Pack
- 新角色
- 角色删减
- 更优 playbook
- 更优 review 流程

### 16.4 进化节奏

应支持：

- 手动触发优化
- 定期复盘优化
- 团队级而不是仅 agent 级的持续优化

---

## 17. 功能需求

以下功能需求按必须实现的能力定义。

### FR-1 Team Creation

系统必须支持通过自然语言创建新的 Team Pack。

验收标准：

- 用户能通过 `AEGIS ...` 发起团队创建
- 系统能为团队命名或使用用户指定名称
- 系统能生成团队角色与职责
- 系统能为团队生成内部 playbook

### FR-2 Team Installation

系统必须支持把 Team Pack 安装成可长期调用的宿主对象。

验收标准：

- 团队创建后可在后续会话中继续调用
- 团队具备唯一 id 和版本
- 团队有清晰的可调用入口名

### FR-3 Team Invocation

系统必须支持直接调用 Team Pack 执行任务。

验收标准：

- 用户能直接说 `AEGIS-xxx ...`
- 系统能正确加载对应团队
- 系统能执行团队内部流程并返回结果

### FR-4 Dynamic Team Composition

系统必须支持围绕目标动态生成团队结构。

验收标准：

- 系统能为不同领域生成不同团队
- 系统能决定哪些角色是常驻、哪些是临时
- 系统能为不同任务决定不同团队规模

### FR-5 Internal Task Decomposition

Team Pack 必须支持自动拆任务。

验收标准：

- 系统能把目标拆成角色级工作项
- 系统能标记可并行部分
- 系统能汇总任务执行结果

### FR-6 Parallel Execution

系统必须支持多角色并行执行。

验收标准：

- 适合并行的任务能自动并行
- 系统能在并行后统一汇总结果
- 并行不要求用户手动管理

### FR-7 Built-in Review/Fix

系统必须支持 Team Pack 内建 review/fix。

验收标准：

- 团队能在关键任务后自动 review
- review 后能自动进入 fix
- 能支持 re-review 与 LGTM

### FR-8 Search and Research

系统必须支持 Team Pack 在必要时进行外部搜索或领域研究。

### FR-9 Team Memory

系统必须支持团队保留长期记忆与经验摘要。

### FR-10 Team Evolution

系统必须支持团队级演进。

### FR-11 Project Binding

系统必须支持 Project Team 绑定具体项目。

### FR-12 Team Template Promotion

系统必须支持把高质量的动态团队沉淀为模板或正式 Team Pack。

---

## 18. 非功能需求

### NFR-1 轻量交互

日常主交互不得被复杂配置淹没。

### NFR-2 低臃肿感

系统默认输出必须压缩，不应让用户长期承受内部流程噪音。

### NFR-3 可复用

创建好的团队必须可以长期复用。

### NFR-4 可扩展

系统必须支持继续增加新的团队领域。

### NFR-5 可演进

团队必须具备版本化和进化能力。

### NFR-6 可调试

虽然默认隐藏复杂度，但系统必须保留团队展开与调试能力。

### NFR-7 宿主兼容

设计必须优先兼容 Claude Code / Codex 这类宿主交互模式。

---

## 19. 样板场景

### 19.1 场景 A：逆向团队

用户先创建：

`AEGIS 帮我创建一个逆向团队，名字叫 AEGIS-nx`

之后日常使用：

`AEGIS-nx 帮我逆向一下 xx app，找出 xx 功能是怎么写的`

团队内部可能自动分裂为：

- reverse research
- static analysis
- behavior mapping
- conclusion review

### 19.2 场景 B：视频剪辑团队

用户先创建：

`AEGIS 帮我创建一个专业的视频剪辑团队，名字叫 AEGIS-video`

之后日常使用：

`AEGIS-video 帮我制作一个 xxx 视频，风格是 xxx`

团队内部可能自动分裂为：

- trend research
- structure planning
- editing direction
- hook and caption
- quality review

### 19.3 场景 C：项目级 bug 团队

用户在某个项目中创建：

`AEGIS 帮我创建一个处理当前项目 bug 的团队`

之后可长期使用：

`AEGIS-bugfix 帮我处理这个支付 bug`

---

## 20. 第一阶段实现范围

v2 第一阶段应重点交付以下内容：

### 20.1 必须完成

- AEGIS Core 与 Team Pack 的对象模型
- Team Pack 的创建、安装、调用机制
- `AEGIS` 与 `AEGIS-xxx` 的双层入口模式
- Team Pack 内部自动拆任务和并行执行
- 保留并集成现有 review/fix 机制
- Team Memory 基础能力
- Team Evolution 基础能力

### 20.2 暂缓但预留接口

- 过于复杂的企业级治理
- 过多的强 schema 暴露
- 全量领域覆盖
- 大规模团队市场或共享分发机制

---

## 21. 成功标准

如果 v2 重构成功，用户应该能做到：

### 21.1 创建团队成功

用户能够通过 `AEGIS` 创建一个长期可复用的专业团队。

### 21.2 调用团队成功

用户能够在 Claude Code / Codex 中直接使用：

- `AEGIS-nx`
- `AEGIS-video`
- `AEGIS-mvp`

### 21.3 日常使用不臃肿

用户在日常使用中感受到的是：

- 一个团队在工作
- 不是一套复杂流程在压人

### 21.4 团队内部自动化有效

团队能自动完成：

- 搜索
- 理解
- 拆任务
- 并行
- review/fix

### 21.5 团队会持续变强

用户能感知到团队不是静态死物，而是越用越顺手。

---

## 22. 最终产品判断标准

v2 的最终判断标准不是：

- schema 是否更多
- hook 是否更复杂
- 状态机是否更完整

而是：

**用户是否真的拥有了一套长期可用、可进化、可直接调用的专业团队。**

如果用户以后能自然地在宿主里说：

- `AEGIS-nx 帮我逆向一下 xx app`
- `AEGIS-video 帮我做一个 xxx 风格的视频`
- `AEGIS-mvp 帮我做这个想法的第一版产品`

并且这些团队真的会自己搜索、自己分工、自己 review/fix、自己持续进化，那么这次重构才算真正成功。
