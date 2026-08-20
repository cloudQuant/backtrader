---
name: devwiki
description: Use when the user asks about JoyinCode development workflow, how to use AI coding in this project, or mentions any pipeline step (markitdown Word-to-MD conversion, grill-with-docs requirement analysis, opsx proposal workflow).
---

# 标准开发流程

## 概述
JoyinCode 推荐采用“转换 → 拷问 → 提案 → 实施 → 归档”五步法。每一步必须依次执行，不可跳跃。

## 开发流程

### 步骤 1：需求文档转换（markitdown）
**目的**：将非 Markdown 格式的需求文档（如 Word、PDF）转为纯文本 Markdown，便于后续 AI 读取和拷问

**操作**：
1. 在对话中上传需求文档（.docx/.pdf 等）
2. 输入指令：`转为md`（或 `markitdown`）
3. 工具自动将文档内容提取为 Markdown 格式，并保存至 `docs/` 目录下，文件名与原始文档相同（后缀改为 .md）

**示例**：选择需求word文档并输入 `转为md`

> 📌 转换后的文档仅包含文字内容，图片、表格等复杂元素会被忽略或转为文字描述。若原文档包含关键图表，建议在拷问步骤中人工补充说明

### 步骤 2：需求拷问（grill-with-docs）
**目的**：对转换后的需求 Markdown 进行多轮问答，挖掘隐含需求、识别歧义、补全缺失细节，确保需求可执行

**操作**：
1. 在对话中选中刚生成的 .md 文件（或指定文件路径）
2. 输入指令：`/grill-with-docs 开发[功能名称]`（例如 `/grill-with-docs 开发用户登录模块`）
3. 系统会基于需求内容主动提问（如异常流程、边界条件、性能指标等），开发者逐一回答
4. 拷问完成后，需求文档中所有模糊点应已澄清，并获得一份“拷问纪要”

**示例**：选择需求 md 文档，输入 `/grill-with-docs 开发xxx`

> ⚠️ 关键约束：OpenSpec 无法直接引用拷问过程的成果物，因此 拷问与下一步“发起提案”必须在同一个对话会话中连续进行，以共享上下文。若中途切换对话，拷问成果将丢失

### 步骤 3：发起提案（opsx propose）
**目的**：基于拷问后的需求，生成 OpenSpec 规格变更提案，包括影响范围、变更清单、验收标准等

**操作**：
1. 确保当前对话仍包含步骤 2 的拷问上下文
2. 选中需求 .md 文件（或直接引用）
3. 输入指令：`/opsx 发起提案`
4. OpenSpec 自动分析需求与现有规格，生成提案文档（位于 openspec/changes/<change-id>/）
5. 开发者务必人工审核生成的提案内容，确认：
   - 变更描述准确
   - 影响模块覆盖完整
   - 验收条件可测
   - 与拷问结论一致

**示例**：选择需求 md 文档，输入 `/opsx 发起提案`

> 💡 若提案不完善，可多次调用 `/opsx propose` 进行调整，或手动编辑提案文件后重新运行

### 步骤 4：实施提案（opsx apply）
**目的**：按照已审核通过的提案进行代码开发和测试

**操作**：
1. 确认提案内容已完全符合开发要求（可再次运行拷问或与团队评审）
2. 输入指令：`/opsx 实施提案`（或 `/opsx apply`）
3. OpenSpec 会根据提案生成任务清单，并引导开发者按任务顺序编码
4. 完成所有任务后，运行项目的单元测试、集成测试，确保验收条件全部通过

**示例**：输入 `/opsx 实施提案`

### 步骤 5：归档提案（opsx archive）
**目的**：开发完成且测试通过后，将提案状态标记为“已完成”，并归档规格变更，更新主规格文档

**操作**：
1. 确认代码已合并至目标分支，且所有测试通过
2. 输入指令：`/opsx 归档提案`（或 `/opsx archive`）
3. OpenSpec 会将变更合并到主规格中，并将提案目录移至 `openspec/changes/archive/`

**示例**：输入 `/opsx 归档提案`

---

# 常见问题与最佳实践

**最佳实践**：

| 问题 | 解决方案 |
|---|---|
| 拷问后忘记在同一会话中发起提案 | 若已关闭对话，从 `CONTEXT.md` 和 `docs/adr/*.md` 中获取历史拷问结果 |
| 提案生成后想修改内容 | 可直接编辑 `openspec/changes/<id>/proposal.md`，然后重新运行 `/opsx propose` 更新 |
| 需求文档包含大量图片 | 在拷问时用文字描述图片内容，或上传补充说明文档 |
| 开发中需要新增需求 | 回到步骤 2 重新拷问，再发起新的提案（而非修改当前提案） |
| OpenSpec 命令报错 | 检查 Node.js 版本，重新安装 `@fission-ai/openspec` 修复配置 |

## 环境与项目结构

详见 [references/environment.md](references/environment.md)。
