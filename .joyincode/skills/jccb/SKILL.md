---
name: jccb
description: 项目框架代码库 RAG 与 grep 搜索技能。需要查看后端框架源码时触发
---

# 技能说明

本技能通过 MCP 端点连接 jccb MCP 服务，提供框架代码的语义搜索、文件读取和 grep 内容搜索能力，供 AI 编码助手需要查看框架源码时使用（了解框架功能、排查框架问题）

## 运行方式

使用 Python 脚本 `scripts/jccb.py` 调用 MCP 端点，配置集中在脚本同目录 `jccb.config.json`（endpoint / timeout / projectId）

```bash
python scripts/jccb.py                       # 列出可用工具
python scripts/jccb.py method ping           # 连通性检查
```

> 工作目录：脚本路径相对 `.joyincode/skills/jccb/` 所在的项目根目录，或使用脚本绝对路径执行。

## 工具说明

所有工具都需要 `projectId` 参数（取配置文件中的值，也可用命令行 `projectId=xxx` 覆盖，优先），用于定位框架代码仓库。

### 1. RAG 语义搜索

| 工具 | 参数 | 用途 |
|------|------|------|
| `searchFrameworkCode` | `search` | 从向量库**语义搜索**框架代码，返回代码片段和元数据。File/Class 类型只返回文件路径（使用`grepFileContent`或`readFileContent`工具获取文件内容），其他类型返回指定行范围内容。搜索范围只包含框架的后端代码 |

### 2. 文件/内容搜索

| 工具 | 参数 | 用途 |
|------|------|------|
| `grepFileContent` | `filePath`、`searchContent` | 在框架代码文件中 **grep 搜索**匹配行（content 模式），返回匹配的行号和行内容 |
| `readFileContent` | `filePath`、`startLine`(可选)、`endLine`(可选) | **读取**框架代码文件的指定行范围内容。不传行号则读整个文件 |
| `grepFiles` | `searchContent` | 在框架代码仓库中搜索包含指定内容的文件列表（**files_with_matches** 模式），只返回文件路径，不返回行内容 |
| `grepCodeFile` | `codePath`、`searchContent` | 根据**代码全路径**（如 `com.aa.xx.XXService.java`）在框架代码中 grep 搜索匹配行 |

## 使用示例

### 1. RAG 语义搜索框架代码

```bash
python scripts/jccb.py searchFrameworkCode search=用户登录
```

返回 JSON 数组，每条含 language、codeType、summary、codeFile、content。适合用自然语言描述（参考查询词最佳实践章节）搜索框架代码。

### 2. grep 搜索指定文件中的匹配行（content 模式）

```bash
python scripts/jccb.py grepFileContent filePath=src/main/java/com/jupiter/BaseService.java searchContent=public class
```

返回 JSON 数组，每条含 line（行号）和 content（行内容）。适合精确定位包含特定内容的行。

### 3. 读取文件指定行范围

```bash
python scripts/jccb.py readFileContent filePath=src/main/java/com/jupiter/BaseService.java startLine=10 endLine=50
```

返回文件第 10-50 行的文本内容。不传 startLine/endLine 则读整个文件。适合查看完整代码实现。

### 4. 搜索仓库中包含内容的文件列表（files_with_matches 模式）

```bash
python scripts/jccb.py grepFiles searchContent="public class"
```

返回 JSON 数组，每条为文件路径（相对于仓库根目录）。适合快速定位哪些文件包含特定内容。排除 .git 目录，最多返回 20 个文件。

### 5. 按代码全路径 grep 搜索

```bash
python scripts/jccb.py grepCodeFile codePath=com.joyintech.jupiter.common.utils.CommonUtil.java searchContent=public static
```

适合按 Java 全限定类名搜索。代码全路径扩展名须与框架后端代码类型一致（JAVA→.java，GO→.go，PY→.py），否则返回不匹配提示。

## 使用规则

1. **语义搜索优先**：不确定文件路径时先用 `searchFrameworkCode` 用自然语言搜索，从结果中获取文件路径
2. **精确搜索次之**：已知文件路径用 `grepFileContent` grep 搜索，或用 `readFileContent` 读取文件内容
3. **搜索文件列表**：不确定文件路径但知道要搜索的内容时用 `grepFiles`（files_with_matches 模式）搜索整个仓库
4. **按类名搜索**：知道 Java 全限定类名时用 `grepCodeFile` 直接定位文件并 grep 搜索
5. **参数约定**：`key=value` 按字符串传；纯数字参数（如 startLine）自动转整数；含空格的参数用双引号包裹（PowerShell 语法）
6. 所有工具只搜索项目的**框架代码**（非项目业务代码），通过框架信息定位框架代码仓库

## searchFrameworkCode 查询词最佳实践

> 基于多轮实测总结的规律，用于构造高质量查询词。所有原则均跨框架通用，不绑定任何特定框架的专有术语。

### 查询词构造公式

**`目标功能领域词 + 结构语义词 + 期望行为词`**，控制在 3~8 个词。

结构语义词（引导向量召回实现细节）：`表结构`、`字段`、`主键`、`删除`、`分页`、`配置`…
期望行为词（命中具体方法体）：`查询`、`保存`、`修改`、`删除`、`批量`…

构造时的判断标准：
- ✅ 词面宽、能同时命中类名/方法名/注释/注解中的一类或多类（命中面越多样，质量越高）
- ❌ 词面窄且是该框架某个功能独有的叫法时，先确认它是否为框架通用概念，避免查询词只对当前框架有效

### 通用原则（跨框架适用）

1. **避免过于通用的动词**：如 `启动`、`执行`、`处理` 这类词几乎每个框架都有调度器/任务/服务方法使用，命中面过广、噪声高。改用更具体的目标行为组合（如 `启动 提交 引擎` 三词组合代替单个 `启动`）。
2. **避免混入完整类名/符号名**：符号名会把向量相似度推向单一类，导致重复项暴增、覆盖变窄。需要按类名精确查时直接用 `grepCodeFile`。
3. **同义词互补**：单次查询往往只命中某一侧实现（如只召回引擎 A 的实现），换同义词再查一次可互补覆盖，多次查询结果合并使用。
4. **不确定性先探测**：不确定目标功能在代码中的实际叫法时，先用 `grepFiles` 搜索功能相关的通用业务词，从命中的文件/注释中提取框架实际使用的术语，再构造语义查询词——比直接猜更稳。

### 已知局限

- 向量库只索引**后端代码**，SQL 建表脚本/字段定义**搜不到**；确认表结构请用 `grepFiles` + 建表脚本
- 返回结果中的 Class/File 类型，仅有文件路径无内容，需要配合 `readFileContent` 读取

### 使用场景分级

| 目的 | 推荐方式 |
|------|---------|
| 快速定位文件/类入口 | `searchFrameworkCode`，`search=目标功能词+核心行为` |
| 理解某个方法的完整实现 | `searchFrameworkCode`，`search=目标功能词+结构词+方法行为`，命中后 `readFileContent` 读全文件 |
| 确认表/字段/SQL 定义 | **不用语义搜索**，直接 `grepFiles` + 建表脚本 |
| 按已知类名看代码 | `grepCodeFile`，比语义搜索精确 |

## 常见错误与处理

### MCP 服务未启动

**现象**：调用任意工具时，请求超时或连接被拒绝

**处理方式**：确认 codebase MCP 服务已启动，检查 `jccb.config.json` 中 `endpoint` 配置是否正确

### 框架未配置代码库

**现象**：返回 `"框架未配置代码库"`

**处理方式**：请先在JoyinCode管理中台指定项目的具体框架

### 框架代码未索引

**现象**：`searchFrameworkCode` 返回 `"框架代码未索引到向量库，请先索引框架代码"`

**处理方式**：需要联系运维人员并提供框架git代码库信息

### 文件不存在

**现象**：`grepFileContent`/`readFileContent`/`grepCodeFile` 返回 `"文件不存在: {filePath}"`

**处理方式**：先用 `searchFrameworkCode` 或 `grepFiles` 确认文件路径，再使用正确的文件路径调用

## 注意事项
* 当前搜索的框架代码为截止昨日的最新分支，代码可能会与项目使用的框架版本有差异
