## 核心思想

### 对话式修正，而非报告式

```
读文档
    ↓
发现一个问题
    ↓
问一个问题 → 等回答 → 修正文档
    ↓
继续检查
    ↓
重复，直到无问题
```

---

## 文档问题类型

| 问题类型 | 说明 | 处理方式 |
|---------|------|---------|
| **漂移（Drift）** | clarify.md 说 A，spec.md 写 B | 问：以哪个为准？然后修正 |
| **冲突（Conflict）** | 两个文档描述互相矛盾 | 问：应该以哪个为准？然后修正 |
| **遗漏（Gap）** | clarify.md 写了 spec.md 没有 | 问：需要加到 spec.md 吗？ |
| **过度实现** | spec.md/design.md 超出 clarify.md | 问：这个要保留还是删除？ |
| **名词不一致** | 同一个东西，不同名字 | 问：统一用哪个词？然后全局替换 |

---

## 流程（Step-by-Step）

### Step 1️⃣ 收集文档

**动作：** 读取同一子需求下的所有相关文档

```
clarify.md = 01-clarify.md（必须）
spec.md = 02-spec.md（必须）
design.md = 03-design.md（如有）
```

---

### Step 2️⃣ 名词对齐（先做这个）

> ⚠️ 名词不一致是其他所有问题的根源，先统一

**动作：** 扫描三个文档中的关键名词

**发现名词不一致时：**
```
发现名词不一致：
  - clarify.md 用「{词A}」
  - spec.md 用「{词B}」
  - design.md 用「{词C}」（如有）
  
统一用哪个？
  A. 「{词A}」
  B. 「{词B}」
  C. 「{词C}」
  D. 其他：{输入}
```

用户选择后，执行全局替换。

---

### Step 3️⃣ 需求覆盖检查

**动作：** 对比 clarify.md 和 spec.md

**发现遗漏时（clarify.md 有，spec.md 没有）：**
```
发现遗漏：
  - clarify.md 有「{需求点}」
  - spec.md 没有

需要加到 spec.md 吗？
  A. 加到 spec.md
  B. 从 clarify.md 中删除
  C. 其他：{说明}
```

**发现过度实现时（spec.md 有，clarify.md 没有）：**
```
发现过度实现：
  - spec.md 有「{需求点}」
  - clarify.md 没有

这个要保留吗？
  A. 保留，加到 clarify.md
  B. 从 spec.md 中删除
  C. 其他：{说明}
```

---

### Step 4️⃣ 描述漂移检查

**动作：** 对比同一需求的描述是否一致

**发现漂移或冲突时：**
```
发现{漂移/冲突}：
  - clarify.md：「{描述A}」
  - spec.md：「{描述B}»

以哪个为准？
  A. 以 clarify.md 为准 → 修正 spec.md
  B. 以 spec.md 为准 → 修正 clarify.md
  C. 综合两者 → 输入：{综合方案}
```

---

### Step 5️⃣ 设计实现检查（如果 design.md 存在）

**动作：** 对比 spec.md 和 design.md

**发现不一致时：**
```
发现设计不一致：
  - spec.md：「{描述A}」
  - design.md：「{描述B}»

以哪个为准？
  A. 以 spec.md 为准 → 修正 design.md
  B. 以 design.md 为准 → 修正 spec.md
  C. 其他：{说明}
```

---

### Step 6️⃣ 完成

**停止条件：**
```
✅ 无发现问题
```

**完成标记：**
```
在 01-clarify.md 或 02-spec.md 的更新记录中追加：
| {YYYY-MM-DD} | docs-align 完成，无问题 |

如果修正了文档内容，在历史中追加记录（保持原状态不变）：
```yaml
updated: {YYYY-MM-DD}
history:
  - "v1: ..."
  - "v2: docs-align 修正: {简要说明}"
```
```

---

## 修正执行规则

### 修正前必须确认

```
修正前必须问用户，不能直接改。
一次只问一个问题。
等回答后再执行修正。
```

### 修正后验证

```
修正后，再次快速扫描相关文档，确认：
- 没有引入新的不一致
- 没有遗漏其他相关位置
```

---

## 重要提示

- **clarify.md 是基准** — spec.md/design.md 不能超出 clarify.md 范围
- **名词优先统一** — 先统一名词，再检查其他问题
- **不输出报告** — 直接修正，发现一个修一个
- **不累积问题** — 发现问题立即问，不堆在一起问
- **clarify 是源头** — 如果 clarify.md 错了，先修正 clarify.md

---

## 质量检查清单

align 完成后，确认：

```
align 质量自检
━━━━━━━━━━━━━━━━━━━━━━
[ ] 名词已统一（全局替换完成）
[ ] clarify.md 的每个需求点都有 spec.md 对应
[ ] spec.md 没有超出 clarify.md 范围
[ ] 同一需求的描述无漂移
[ ] 无互相冲突的描述
[ ] 如有 design.md，已与 spec.md 对齐
[ ] 无遗漏（clarify.md 有 → spec.md 都有）
[ ] 无过度实现（spec.md 有 → clarify.md 都有或已确认删除）
```
