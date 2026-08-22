---
name: specx
description: 企业级 AI 研发流程 — 需求 → 澄清 → 规格 → 设计 → 任务 → 执行 → 归档
---

# 执行规则
1. 结合上下文确定当前处于研发流程的哪个阶段
2. 根据触发条件确定需要哪些子技能后，**主动读取**对应的 `references/xxx.md` 文件
3. 严格按照读取到的内容执行任务
4. 当前任务执行结束后，使用`question`工具询问用户下一步怎么做

> 若需要访问当前项目的数据库，可使用技能 jcdb

# specx-demystify — 需求拆解与任务化
design → writing-plans 提供输入。核心策略：抽象层优先，先拆数据模型/状态机/数据流地基，后拆页面/交互实现层。

## 触发条件

在以下情况**必须**执行 demystify：
- 接收到原始需求文档（PRD / BRD / 产品需求 / 用户反馈等），需要拆解为可执行任务
- 用户明确要求「拆需求」、「任务化」、「分解」
- 进入 specx 流程的第一步（demystify → clarify → design → writing-plans）

# specx-clarify 需求澄清 & 规格输出
specx 流程第二步 — 需求澄清 & 规格输出。通过迭代式提问，逐步完善需求文档并输出规格说明书。

## 触发条件

当有一个已拆解的子需求 `00-子需求.md`，需要生成 `01-clarify.md` 和 `02-spec.md` 时使用。

**输入：** `00-子需求.md`
**输出：** `01-clarify.md` + `02-spec.md`

# specx-design：实现规划
specx 流程第三步 — 实现规划。在既有框架下规划功能落地。

## 触发条件

当 spec.md 完成，需要规划「在现有框架下怎么实现」时使用。

**输入：** `01-clarify.md` + `02-spec.md`
**输出：** 按 `docs/specx/templates/` 下的项目专属模板填写（文件名和结构由项目模板定义）

# specx-create-design-template：生成项目专属 design 模板

## 触发条件

项目初始化时或引入 specx 时执行一次，生成的功能设计模板供后续每个需求使用。

## 输入

无（纯交互式）

## 输出

`{项目根目录}/docs/specx/templates/` 下的项目专属模板（功能设计文档结构）

# specx-docs-align：文档对齐检查
specx 流程第三步 — 文档对齐。通过对话式逐个问题检查 clarify.md、spec.md、design.md 之间的一致性，发现问题立即修正。

## 触发条件

当需要检查 specx 文档链的一致性时使用：

- clarify.md 完成 → 检查与 spec.md 之间是否对齐
- spec.md 完成 → 检查与 design.md 之间是否对齐
- 任意文档修改后 → 发现不一致需要修正

**输入：** `01-clarify.md`、`02-spec.md`、`03-design.md`（可选）
**输出：** 直接修正文档，不输出报告

# specx-archive：归档沉淀
specx 流程最后一步 — 将已完成的需求文档（clarify.md / spec.md / design.md）归纳总结，写入项目 docs/specx/wiki/ 目录，形成可查询的知识库。

## 触发条件

当一个子需求完成（clarify → spec → design → code 全部走完）后，用户说"归档"、"沉淀到 wiki"、"完成这个需求"时使用。

**前置判断：** 子需求目录 `t-xx/` 下已有 `clarify.md`、`spec.md`、`design.md`（及可选 `code` 相关文档）。

**不是触发的情况：**
- 需求还在中途（未完成 code）
- 用户只是问问题，不是正式完成需求

# specx-writing-plans：设计文档转任务清单
Use after specx-design completes — converts the design document into an actionable task list with file changes, dependencies, and parallel execution groups.

## 触发条件

当 specx-design 完成设计文档后，需要拆解为可执行任务时使用。

# specx-executing-plans：执行任务清单
Use when you have a task list (04-tasks.md) ready and need to implement it — executes tasks in order, marks progress, and stops when blocked.

## 触发条件

当 `04-tasks.md` 已完成，需要按清单执行编码时使用。

# specx-fix：Bug 修复
specx 流程的 bug 修复 skill — 自动判断验收 bug（场景 A）和独立 bug（场景 B），提供根因分析、修复方案、归档沉淀

## 触发条件

当用户反馈 bug 相关问题时触发本 skill。不需要用户说特定的关键词，通过上下文自动判断走哪条路径。

# specx-create-rule：规则建立
specx 流程辅助 skill — 为企业项目建立和维护开发规范。在适当时机帮助用户将隐性约定显性化，形成可持续遵循的规则文档

## 触发条件

**主动触发（无需用户明确要求）：**

当对话中出现以下信号时，自动考虑触发本 skill：
- 用户对 AI 输出表达了不满（"不对"、"不是这个意思"、"应该按我的习惯"）
- 同一类错误出现 2 次以上
- 用户纠正了 AI 的编码风格或习惯
- 讨论中涉及项目特有的约束、边界、默认值

**明确触发：**

用户说"加个规则"、"把这个记下来"、"以后都这样写"等明确意图时，直接触发。
