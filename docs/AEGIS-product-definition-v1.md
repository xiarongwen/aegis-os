# AEGIS 产品定义 v1

## 1. 文档目的

这份文档用于明确 AEGIS 的真正产品定位、系统边界、核心对象、核心机制和未来演进方向，防止后续设计与实现过程中出现理解偏移。

本文件要解决的核心问题不是“AEGIS 现在能做什么”，而是：

- AEGIS 从根上到底是什么
- AEGIS 不是什么
- AEGIS 为谁服务
- AEGIS 的核心价值是什么
- 为什么它必须强调治理、锁定、复审与审计
- 为什么它不能退化成一个普通的代码脚手架、产物目录系统或单次执行 Agent

---

## 2. 一句话定义

**AEGIS 是一个面向个人公司场景的、多 Agent 专业执行操作系统。**

它运行在 Codex、Claude Code 等 Agent CLI 之上，把自然语言目标转化为受控工作流，并通过需求锁定、执行边界、复审闭环、变更控制和审计链路，确保 AI 在持续执行过程中不偏航。

---

## 3. 产品定位

### 3.1 正确定位

AEGIS 的正确定位是：

- 一个多 Agent 协作治理系统
- 一个 Agent CLI 上层的工作流操作系统
- 一个帮助个人公司像专业团队一样运转的执行中枢
- 一个用于约束 AI 想法漂移、需求偏移和执行失真的控制面
- 一个灵活、可扩展、可持续长能力的 Agent 工作流 Bot 底座

### 3.2 错误定位

AEGIS 不是：

- 一个单纯的代码生成工具
- 一个固定目录结构的产物框架
- 一个仅服务于软件研发的脚手架
- 一个只会把任务分配给多个 Agent 的编排器
- 一个“一次问答式”的智能助手
- 一个被某一种功能永久锁死的垂直工具

如果后续设计开始偏向下面这些方向，就说明理解已经偏移：

- 重点放在“文件放哪”而不是“目标怎么被锁住”
- 重点放在“怎么多开几个 Agent”而不是“怎么防止它们跑偏”
- 重点放在“自动做更多事”而不是“在可控前提下做对事”
- 重点放在“生成更多产物”而不是“沉淀可审计的执行过程”

---

## 4. 目标用户

### 4.1 核心目标用户

AEGIS 的核心目标用户不是大团队，而是：

- 个人开发者
- 一人公司
- 超轻创业团队
- 需要 AI 帮忙做专业执行，但又不能接受失控的人

这类用户通常具备以下特征：

- 目标很多，但时间和带宽有限
- 需要 AI 不只是写代码，而是协助经营“一个小公司”
- 不希望 AI 每次都从零理解上下文
- 不希望 AI 自己脑补需求和方向
- 希望 AI 能像专业团队一样推进事情，而不是像聊天机器人一样发散

### 4.2 用户在系统中的角色

用户在 AEGIS 中更像：

- Owner
- Founder
- CEO
- 最终决策者

用户不应该被迫像流程操作员一样逐步驱动系统，而应该更多是：

- 给目标
- 给约束
- 给优先级
- 做关键审批
- 在必要时做 change approval

AEGIS 要负责把这些高层输入转化为受控执行。

---

## 5. 北极星问题

AEGIS 要解决的北极星问题是：

> 如何让 AI 在复杂、多步骤、长期的执行过程中，持续代表用户推进事情，同时不偏离用户真实目标。

这里面包含四个关键词：

- 持续
- 多步骤
- 代表用户
- 不偏航

大多数 Agent 系统目前只能解决“做一次事”，但不能解决“长期替你做事还不跑偏”。  
AEGIS 的价值就在这里。

---

## 6. 核心价值主张

AEGIS 的核心价值不是“更强模型”，而是“更强治理”。

### 6.1 价值一：把模糊目标变成可控执行

用户给出的是自然语言目标，例如：

- `/aegis 帮我开发一个聊天页面`
- `/aegis 帮我研究某个赛道是否值得做`
- `/aegis 帮我整理一个 PRD`
- `/aegis 帮我 review 这个项目`

AEGIS 要做的是：

- 识别任务意图
- 归类为对应 workflow type
- 生成执行边界
- 冻结关键目标
- 分配专业 agent
- 推进状态机

### 6.2 价值二：严格控制 AI 想法漂移

AI 最大的风险不是不会做，而是会“做着做着变成它自己理解的需求”。

AEGIS 必须压制这种行为，核心机制包括：

- intent lock
- requirement lock
- scope control
- change control
- review-fix-LGTM loop

### 6.3 价值三：让 AI 像专业团队而不是聊天机器人

专业团队的特征不是回答快，而是：

- 先澄清，再执行
- 有角色分工
- 有审查机制
- 有问题闭环
- 有变更流程
- 有历史记忆
- 有复盘能力

AEGIS 的目标是让多个 Agent 的组合表现出这种“专业组织行为”。

### 6.4 价值四：让用户成为 Owner，而不是 Agent babysitter

AEGIS 不能让用户每一步都盯着 AI 怎么做。  
它应该让用户更多只关注：

- 目标有没有被正确理解
- 风险有没有被暴露
- 是否需要修改方向
- 最终结果是否满意

### 6.5 价值五：让系统可以持续扩展能力，而不是一次性定型

AEGIS 不应该随着第一个成功场景就被定义死。

它必须支持：

- 增加新的 workflow 类型
- 增加新的 specialist agents
- 增加新的外部工具和集成
- 增加新的业务领域能力
- 增加新的治理规则和 review 机制

也就是说，AEGIS 的价值不只是“当前已经有哪些能力”，而是“它是否具备一个可以长期扩展的底层结构”。

---

## 7. 产品边界

### 7.1 AEGIS 负责什么

AEGIS 负责：

- 目标接收
- workflow 类型识别
- 需求锁定
- agent 分工
- 执行边界控制
- review 和 re-review 机制
- 变更控制
- 执行审计
- 长期上下文一致性

### 7.2 AEGIS 不直接负责什么

AEGIS 不应该过度承担这些职责：

- 具体领域执行逻辑本身
- 所有业务系统的数据存储
- 固定产物管理哲学
- 替代所有业务应用
- 取代用户的最终商业判断

AEGIS 也不应该把自己收窄成：

- 只做 coding workflow
- 只做 PRD 流程
- 只做某一个部门的自动化
- 只围绕某一个 Agent runtime 存在

也就是说，AEGIS 是执行治理层，不是业务系统本体。

---

## 8. 核心设计原则

### 8.1 Governance Over Raw Capability

治理优先于能力堆叠。  
不是先问“还能不能让 AI 多做点”，而是先问“怎么确保它做得对、做得稳、做得可追踪”。

### 8.2 Lock Before Scale

在工作流进入多 Agent 执行前，必须先锁定目标、范围和成功标准。  
否则 Agent 越多，偏航越严重。

### 8.3 Review Is A Loop, Not A Gate Checkbox

review 不是“一次性打分”，而是：

`review -> fix -> re-review -> ... -> LGTM`

只有问题真正关闭，质量控制才成立。

### 8.4 Explicit Change Beats Silent Drift

需求变化可以发生，但必须显式发生。  
禁止 silent reinterpretation。

### 8.5 Execution Must Be Auditable

系统需要能回答：

- 为什么做这个决定
- 是谁做的
- 根据什么做的
- 改过几轮
- 为什么最终通过

### 8.6 The Owner Must Stay In Control

即使 AI 可以自动推进，Owner 的目标、边界和审批权不能被系统稀释。

### 8.7 Extensibility Is A First-Class Requirement

可扩展性不是锦上添花，而是一等约束。

AEGIS 的设计必须保证：

- 新能力通过扩展接入，而不是推翻核心
- 新 workflow 通过注册接入，而不是硬编码进主流程
- 新 agent 通过声明式元数据接入，而不是散落在脚本里
- 新领域通过 capability 组合接入，而不是复制一套新系统

如果某个设计让系统越来越难以增加能力，就说明它违背了 AEGIS 的长期目标。

### 8.8 Core Must Stay Small, Capabilities Must Stay Pluggable

AEGIS 的核心应该尽可能小。

核心只负责：

- 目标接入
- 锁定与边界控制
- 状态机推进
- review / fix / LGTM 闭环
- 变更控制
- 审计与追踪

而具体能力应该尽可能插件化、模块化、agent 化。

这样 AEGIS 才能从研发场景起步，但不被研发场景永久绑死。

---

## 9. 核心对象模型

如果 AEGIS 要服务“个人公司 bot”场景，它的核心对象不能只有 workflow。

### 9.1 Owner Profile

记录用户的长期偏好与决策风格，例如：

- 业务方向
- 品牌偏好
- 风险偏好
- 沟通风格
- 默认质量门槛
- 允许的自动化级别

作用：

- 让系统长期代表同一个 Owner 行事
- 避免每次 workflow 都重新建立人格和标准

### 9.2 Company Profile

定义这家“个人公司”的稳定上下文，例如：

- 公司定位
- 产品方向
- 目标用户
- 商业模式
- 当前优先级
- 已放弃方向
- 已在推进项目

作用：

- 给 agent 一个公司级稳定上下文
- 避免每次执行都只针对局部任务思考

### 9.3 Initiative

Initiative 是业务层面的目标单元，例如：

- 做一个聊天页面
- 研究一个 SaaS 机会
- 发布新官网
- 提升转化率
- 复盘用户反馈

它比 workflow 更稳定，也更贴近业务目标。

### 9.4 Workflow

Workflow 是一次具体执行实例。  
它服务于某个 initiative，并拥有：

- 当前状态
- 参与 agents
- 中间产物
- review 记录
- 审计记录
- 变更历史

### 9.5 Intent Lock

Intent Lock 负责锁定用户当前这次请求真正要达成的目标。  
它回答的是：

- 用户这次到底想要什么
- 用户不想要什么
- 本轮任务的目标边界是什么

### 9.6 Requirement Lock

Requirement Lock 是从规划阶段开始冻结可执行需求的机制。  
它回答的是：

- 这轮执行允许做什么
- 不允许做什么
- 验收标准是什么
- 哪些是假设
- 哪些是 out of scope

### 9.7 Review Loop

Review Loop 是质量控制对象。  
它不是附属产物，而是工作流中的正式对象，记录：

- 当前轮次
- open issues
- fixed issues
- residual risk
- verdict
- 是否 LGTM

### 9.8 Change Request

当 locked intent / requirement 被挑战时，需要引入 change request，而不是让 agent 默默改方向。

### 9.9 Knowledge Base

Knowledge Base 保存长期上下文，例如：

- 历史 workflow 结论
- 常见失败模式
- 已经拒绝过的方向
- 重复出现的问题
- 产品和公司的稳定知识

---

## 10. 系统层次

AEGIS 最适合被理解为三层系统。

### 10.1 Owner Layer

这一层是用户本人。

职责：

- 给目标
- 给边界
- 给优先级
- 做审批
- 接受结果

### 10.2 Management Layer

这是 AEGIS 的核心管理层。

典型角色包括：

- orchestrator
- planner
- reviewer
- change controller
- knowledge keeper

职责：

- 理解目标
- 拆解工作
- 锁定需求
- 分配 agent
- 管状态
- 管 review
- 管变更
- 向 owner 汇报

### 10.3 Specialist Layer

这层是执行专家 agents。

例如：

- research
- product planning
- frontend engineering
- backend engineering
- code review
- security
- QA
- deploy
- content
- support
- operations

职责：

- 在被分配的边界内完成专业工作

### 10.4 Capability Layer

在 Specialist Layer 之下，还应存在一个显式的 Capability Layer。

这层关注的不是“谁来做”，而是“系统会什么”。

例如未来可以独立扩展的 capability 包括：

- research
- planning
- build
- review
- audit
- deploy
- operate
- support
- content
- sales
- analytics
- memory management
- external integrations

这层的意义在于：

- 让 AEGIS 扩展的是能力，不只是扩展 agent 数量
- 避免把系统变成“当前这些 agent 的硬编码编排器”
- 让新增能力时仍然挂在统一治理协议之下

---

## 11. Workflow 类型系统

AEGIS 不应只有一种工作流，而应支持多种“公司级动作”。

这里要特别强调：

workflow type 不是一个封闭列表，而是一个可扩展系统。

v1 可以先支持有限类型，但架构上必须假设未来会不断增加新的 workflow type，而不是默认“当前这些就够了”。

### 11.1 Research Workflow

适合场景：

- 调研某个方向
- 分析竞品
- 判断某个市场是否值得进入

典型输出：

- market report
- competitive analysis
- feasibility assessment
- recommendation

### 11.2 Planning Workflow

适合场景：

- 把想法变成 PRD
- 规划 MVP
- 任务拆解

典型输出：

- PRD
- architecture
- task breakdown
- requirement lock

### 11.3 Build Workflow

适合场景：

- 开发功能
- 搭建页面
- 实现后端服务

典型输出：

- code changes
- tests
- review loop
- QA signoff

### 11.4 Audit Workflow

适合场景：

- review 项目
- 做安全审计
- 查找偏航原因
- 做问题复盘

典型输出：

- audit report
- blockers
- remediation plan

### 11.5 Launch Workflow

适合场景：

- 发布功能
- 上线页面
- 做部署验证

典型输出：

- deploy plan
- release checklist
- rollback plan
- post-deploy validation

### 11.6 Operate Workflow

适合场景：

- 收集反馈
- 处理用户支持
- 做运营跟进
- 做节奏回顾

典型输出：

- issue summary
- user insight
- priority updates
- next actions

### 11.7 Future Workflow Categories

未来很可能继续增加例如：

- outreach workflow
- marketing workflow
- customer-success workflow
- finance-assist workflow
- founder-daily-ops workflow

因此，workflow 类型系统必须是注册式、可演进的，而不是写死在某个版本里。

### 11.8 Capability Extensibility Requirements

为了保证 AEGIS 不被局限于某一种功能，未来所有新能力都应满足这些接入原则：

#### A. 新能力必须通过声明式方式接入

例如通过：

- registry
- workflow type definition
- tool contracts
- agent metadata

而不是把逻辑散落到 shell 脚本或 prompt 文本里。

#### B. 新能力必须复用同一套治理机制

无论是开发、调研、运营还是销售，新增能力都应复用：

- intent lock
- requirement lock 或等价锁定对象
- scope control
- review / re-review
- change control
- audit trail

#### C. 新能力不能绕过 Owner 对齐机制

任何新增能力都不能因为“这是新功能”就绕过：

- 用户目标确认
- 成功标准定义
- 风险暴露
- 审批边界

#### D. 新能力应该通过组合产生，而不是重新发明一套系统

AEGIS 的理想形态不是为每个新场景都造一个新的 mini-framework，
而是通过组合已有核心机制和 specialist capabilities 生成新的 workflow。

---

## 12. 需求准确性与防漂移机制

AEGIS 的灵魂是“防偏航”，这里必须明确写死。

### 12.1 为什么这是最重要的机制

AI 执行系统最大的风险不是“不会做”，而是：

- 会过度发挥
- 会补全不存在的需求
- 会局部优化成别的东西
- 会在多轮执行中不断偏离原始目标

而系统一旦开始扩展更多能力，这个问题只会更严重，不会更轻。

所以“可扩展”绝不能等于“可随意发散”，而必须意味着：

**能力扩展得越多，治理也必须保持一致。**

因此，系统的第一优先级不是更强执行，而是更强约束。

### 12.2 防漂移的五层机制

#### 第一层：Intent Clarification

在进入执行前，先澄清用户真正要什么。

#### 第二层：Requirement Lock

把执行需求冻结成结构化对象。

#### 第三层：Scope Enforcement

Agent 只能在当前状态允许的范围内执行。

#### 第四层：Review-Fix-LGTM Loop

任何重要输出都不能一次通过，必须经过复审闭环。

#### 第五层：Change Control

任何偏离锁定需求的动作都必须进入显式变更流程。

### 12.3 系统必须明确禁止的行为

AEGIS 必须从机制上禁止：

- 未经确认自行扩 scope
- 为了“看起来更好”而擅自改目标
- 用模糊理解替代 locked requirement
- 把 reviewer 建议直接解释为需求变更
- 在没有 change approval 的情况下重写方向

---

## 13. Review-Fix-LGTM 闭环

Review 在 AEGIS 中不应只是单次门禁，而应是正式的闭环流程。

标准形态：

`review -> fix -> re-review -> ... -> LGTM`

它的作用不是让系统更复杂，而是让“发现问题”真正变成“问题被关闭”。

这个机制应适用于：

- PRD / planning review
- code review
- security review
- QA review
- release review

AEGIS 必须把 review loop 视为核心机制，而不是未来补丁功能。

---

## 14. Change Control

Change Control 的存在是为了把“合理变更”和“AI 偏航”区分开。

### 14.1 合法变更来源

只有以下来源应被认为是合法 change trigger：

- 用户明确提出修改
- 外部事实变化
- reviewer / auditor 提出必须回退到 planning 的结论

### 14.2 不合法变更来源

以下情况不应被系统自动接受：

- agent 自己觉得这样更好
- 实现过程中临时想扩功能
- 为了减少工作量而偷换需求
- 为了通过 review 而篡改原需求定义

### 14.3 变更结果

一旦变更被接受，系统应触发：

- requirement re-lock
- workflow state rollback or replay
- review baseline 更新

---

## 15. 记忆与长期一致性

如果 AEGIS 要成为“个人公司 bot”，就不能每次只处理单次任务。

它需要保留长期一致性。

### 15.1 需要记住什么

- 用户是谁
- 用户当前在做什么
- 公司定位
- 长期目标
- 已经做过的决定
- 被明确拒绝的方向
- 历史上经常出现的质量问题

### 15.2 为什么不能完全靠聊天历史

聊天历史：

- 太松散
- 不稳定
- 不结构化
- 无法作为治理依据

因此 AEGIS 需要自己的结构化记忆对象。

---

## 16. 产物与代码的关系

AEGIS 的主目标不是管理某一类产物目录，而是治理执行过程。

所以它应该坚持这条原则：

> 产物是执行痕迹，不是产品本体。

也就是说：

- `workflow` 主要承载状态、决策、审查和审计
- 真正的交付代码是否驻留在 workflow 目录中，不应该成为 AEGIS 的核心价值定义
- 产物管理可以灵活，但治理机制必须稳定

这意味着：

- AEGIS 可以支持在 workflow 内生成代码
- 也可以支持指向外部工程目录
- 还可以支持对已有项目执行受控变更

但这些都是“承载策略”，不是“产品本质”

这里再次明确：

AEGIS 的目标不是做“某一种功能很强”的 Bot，
而是做“可以持续接入新能力、但仍然受统一治理约束”的 Agent 工作流操作系统。

---

## 17. 成功标准

如果 AEGIS 成功，用户会感受到：

- 我不用每一步盯着 AI
- AI 理解我的目标越来越稳定
- AI 不会轻易自己改需求
- 事情会像专业团队一样被推进
- review 不再流于形式
- 我可以追踪为什么事情变成现在这样
- 我可以放心让系统替我推进更复杂的工作

### 17.1 核心成功指标

未来可用这些维度衡量：

- requirement drift rate
- review loop closure rate
- blocked workflow explainability
- owner correction frequency
- workflow completion quality
- repeated-context reuse quality

---

## 18. 当前阶段优先级

如果按这个产品定义继续演进，建议优先级如下：

### P0

- workflow type system
- intent lock / requirement lock
- review-fix-LGTM loop

### P1

- change control
- owner/company profile
- workflow resume / status

### P2

- structured long-term knowledge
- cross-workflow planning
- company-wide operational workflows

### P3

- 更广的 specialist agent 生态
- 多平台 agent runtime 兼容层
- 更完整的公司级 dashboard / observability

---

## 19. 最后的定义确认

为了防止后续理解偏移，这里再次明确：

AEGIS 的目标不是做一个“帮你写代码的多 Agent 工具”。

AEGIS 的目标是做一个：

**能代表个人公司 owner，在明确目标、明确边界、明确审查和明确变更控制下，持续推进工作的多 Agent 专业执行系统。**

并且，这个系统必须是：

- 灵活的
- 可扩展的
- 能持续长能力的
- 不被某一种功能锁死的
- 能随着 owner 的公司需求演进而演进的

如果后续任何设计让系统越来越像：

- 文件模板
- 项目脚手架
- 单轮 agent 编排器
- 一次性任务执行器

那就说明偏离了这份产品定义。

AEGIS 必须始终围绕这几个关键词演进：

- owner-aligned
- governance-first
- drift-resistant
- review-driven
- audit-friendly
- professional multi-agent execution
- capability-extensible
