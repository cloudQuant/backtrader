## 输入

- `t-xx/00-子需求.md` — 原始需求
- `t-xx/01-clarify.md` — 澄清后的需求
- `t-xx/02-spec.md` — 规格说明书
- `t-xx/03-design.md` — 设计方案
- `t-xx/04-tasks.md` — 任务清单（已完成的）

---

## 输出

写入 `docs/specx/wiki/` 下的页面文件，形成项目知识库，供后续查询和复用。

---

## wiki 目录结构

每个条目独立文件，不放在单个大文件里。避免膨胀，难以维护。

```
docs/specx/wiki/
├── README.md                    # 知识库入口 & 总索引
├── entities/                    # 领域概念
│   └── {slug}.md
├── features/                    # 功能模块
│   └── {slug}.md
├── decisions/                   # 技术决策
│   └── {slug}.md
└── components/                  # 组件说明
    └── {slug}.md
```

### 命名规则

- 文件名：`{t-xx}-{简短英文名}.md`，小写，连字符分隔
- 示例：`t01-stock-card.md`、`t03-redis-cache.md`

> 首次归档时由本 skill 创建 `docs/specx/wiki/` 目录和 `README.md`。

---

## Step 1️⃣ 读取子需求文档

按顺序读：
1. `00-子需求.md` — 了解原始需求背景
2. `01-clarify.md` — 核心澄清点（消歧后的需求）
3. `02-spec.md` — 验收标准
4. `03-design.md` — 实现要点
5. `04-tasks.md` — 任务完成情况

---

## Step 2️⃣ 判断写入哪个 wiki 分类

根据内容判断归档到哪个子目录：

| 内容类型 | 写入子目录 |
|---------|---------|
| 新概念/名词/领域模型 | `entities/` |
| 功能模块描述（做什么）| `features/` |
| 技术选型、架构决策、为什么这样做 | `decisions/` |
| UI 组件、复用组件说明 | `components/` |

> 如果不确定，写入 `features/`。

---

## Step 3️⃣ 提炼写入内容

### 对每个分类的提炼要求

**entities/ — 实体沉淀：**
- 核心领域名词的定义
- 概念之间的关系（与哪些其他实体相关）
- 业务含义（区别于纯技术命名）

**features/ — 功能沉淀：**
- 功能名称和一句话描述
- 触发场景（用户怎么用到这个功能）
- 输入/前置条件
- 输出/后置结果
- 与其他功能的依赖关系

**decisions/ — 决策沉淀：**
- 决策点（"为什么选择 X 而不是 Y"）
- 约束条件（技术限制、业务限制）
- 最终选择及理由
- 替代方案及否定原因

**components/ — 组件沉淀：**
- 组件名称和职责
- Props / 参数说明
- 使用场景
- 与其他组件的组合关系

---

## Step 4️⃣ 写入 wiki 页面

按相关性分组写到同一文件。文件内容超过 200 行时，拆分为独立文件。

### 文件命名

- 路径：`docs/specx/wiki/{分类}/{英文名}.md`
- 示例：`docs/specx/wiki/features/stock-card.md`

### 单文件内容格式

**独立条目：** 每个文件一个 `##` 标题。
**合并组：** 多个 `##` 条目共享一个文件级别的 `**分类**`、`**最后更新时间**`。

```markdown
# {组名/条目名}

**分类：** {entities/features/decisions/components}
**最后更新时间：** {YYYY-MM-DD}
**关联需求：**
- [t-xx](../{需求目录}/t-xx/00-子需求.md)

---

## {条目名}

{内容}

---

## {条目名}

{内容}
```

### 更新 README.md 索引

首次创建 wiki 时写入：

```markdown
# Wiki

> 项目知识库 — 由 specx-archive 维护

## 分类

- `entities/` — 领域概念、名词解释
- `features/` — 功能模块说明
- `decisions/` — 技术决策记录
- `components/` — 组件说明

## 最近更新

| 日期 | 分类 | 文件 | 内容摘要 |
|------|------|------|---------|
| {YYYY-MM-DD} | {分类} | {文件名} | {一句话描述} |
```

后续归档时，在"最近更新"表格**顶部**插入新行。

---

## Step 5️⃣ 更新文档状态为 archived

归档完成后，更新子需求目录下所有产出文档的文件头状态为 `archived`：

```markdown
// 对 01-clarify.md / 02-spec.md / 03-design.md / 04-tasks.md 逐一更新

---
status: archived
updated: {YYYY-MM-DD}
history:
  - "v1: 初始创建"
  - "v2: ..."
  - "v3: docs-align 修正: ..."
  - "v4: 已归档到 wiki"
---
```

## Step 6️⃣ 更新子需求目录状态

在 `t-xx/` 下的 `README.md`（如果没有就创建）标注归档状态：

```markdown
# t-{xx}-{子需求名称}

**状态：** ✅ 已归档
**最后更新时间：** {YYYY-MM-DD}
**Wiki 沉淀位置：**
- [t-xx-{slug}](../wiki/{分类}/t-xx-{slug}.md)
```

---

## 归档质量清单

```
[ ] 已读取全部子需求文档（00-子需求/clarify/spec/design/tasks）
[ ] 判断了正确的 wiki 分类（entities/features/decisions/components）
[ ] 每个提炼内容写成独立文件
[ ] 文件名符合命名规则 {t-xx}-{slug}.md
[ ] 更新了 README.md 索引（顶部插入新行）
[ ] 标注了子需求目录为已归档
[ ] 未污染原始文档（clarify/spec/design.md 未被修改）
```

---

## 重要提示

- **不是复制粘贴** — 提炼精华，不是把整个文档搬进去
- **不修改原始文档** — 归档是新建文件，原始 clarify/spec/design.md 保持不变
- **先判断分类再写** — 不确定时优先选 features/
- **按相关性分组** — 相关条目放同一文件，超过 200 行则拆分
- **索引要维护** — 每次归档都要更新 README.md 的最近更新表格（顶部插入）
