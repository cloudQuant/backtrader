---
name: jcdb
description: 数据库只读查询技能。用于写 SQL/代码/配置前核对真实表名与字段定义，防止臆造。能力：按表注释模糊搜索表（queryTable）、按表名精确查表及字段（findTable）、查字段结构（queryTableColumns）、查指定表指定字段数据（queryTableData）。用户提到查库表、查表结构、查字段定义、字段含义、表注释、queryTable、findTable、queryTableColumns、queryTableData 时触发
---

# jcdb — 数据库表结构与数据查询

本技能通过 MCP 端点连接数据库，获取表名、表结构与表数据信息，供开发过程中定位业务表、查看字段定义、核对数据使用

## 运行方式

使用 Python 脚本 `scripts/jcdb.py` 调用 MCP 端点，配置集中在同目录 `jcdb.config.json`（endpoint / timeout / projectId）

```bash
python scripts/jcdb.py                       # 列出可用工具
python scripts/jcdb.py method ping           # 连通性检查
```

> 工作目录：脚本路径相对 `.joyincode/skills/jcdb/` 所在的项目根目录，或使用脚本绝对路径执行。

## 工具说明

| 工具 | 参数 | 用途 |
|------|------|------|
| `queryTable` | `tableNameComment` | 按表名注释**模糊**查询数据库表信息（返回表名 + 表注释） |
| `findTable` | `tableName` | 按表名**精确**查询数据库表信息（返回表名 + 表注释 + 全部字段） |
| `queryTableColumns` | `tableName` | 查询数据库表**结构**信息（返回字段名 + 类型 + 字段注释） |
| `queryTableData` | `tableName`、`fields`、`condition`、`limit` | 查询指定表、指定字段的**数据**（返回 Markdown 表格；`fields` 逗号分隔、为空时实测返回空需显式传；`condition` 为单一查询条件、必填；`limit` 默认 50、最大 100） |

`projectId` 默认取配置文件中的值，也可用命令行 `projectId=xxx` 覆盖（优先）

## 使用示例

### 1. 不知道表名，按业务注释模糊搜索

```bash
python scripts/jcdb.py queryTable tableNameComment=用户
```

输出示例：

```
Table sys_users [note: '用户信息表'] {
}
Table tm_user_ext [note: '用户信息拓展表'] {
}
...
```

用于：定位某业务对应的表名，再从结果中挑选目标表

### 2. 已知表名，精确查询表及字段

```bash
python scripts/jcdb.py findTable tableName=sys_users
```

### 3. 查询表结构（字段定义）

```bash
python scripts/jcdb.py queryTableColumns tableName=sys_users
```

输出示例：

```
Table sys_users {
  USERID varchar [note: '用户ID']
  ORGID varchar [note: '机构代码']
  USERNAME varchar [note: '用户姓名']
  STATUS int [note: '启用状态[BLACKFLAG]']
  ...
}
```

### 4. 查询表数据（指定表、指定字段、单一条件）

```bash
python scripts/jcdb.py queryTableData tableName=sys_users fields=USERNAME,STATUS "condition=STATUS = '1'" limit=5
```

输出示例（Markdown 表格）：

```
| USERNAME | STATUS |
| --- | --- |
| admin | 1 |
| batch | 1 |
```

`condition` 为单一查询条件（必填），支持 `=、!=、<>、>、<、>=、<=、LIKE、IN、BETWEEN`，不支持 AND/OR；无需过滤时传恒真条件如 `"condition=USERNAME LIKE '%'"`。命令行中含空格/单引号的 condition 需用双引号包裹整个参数（PowerShell 语法）

用于：核对数据是否存在、查看枚举字段实际取值、判断字典含义等

## 使用规则

1. **模糊搜索优先**：不清楚表名时先 `queryTable` 按业务注释模糊查询，再从结果确定目标表
2. **精确查询次之**：已知表名用 `findTable` 或 `queryTableColumns` 获取完整字段定义
3. **禁止臆造表名/字段**：写 SQL、写配置、写代码引用表或字段前，必须用本技能查询真实结构，不得凭空假设字段名
4. **字段注释含字典**：字段注释中方括号（如 `[BLACKFLAG]`、`[SEX_TYPE]`）表示该字段关联的数据字典编码，查询数据字典需另行使用其它工具
5. **queryTableData 参数**：实测 `fields` 传空时返回空结果（与 schema 描述"为空查全部"不符），需先 `queryTableColumns` 确认字段名后，再显式列出所需字段；`condition` 为单一查询条件、**必填**（如 `CLSNO = 'TMFLAG'`，支持 `=、!=、<>、>、<、>=、<=、LIKE、IN、BETWEEN`，不支持 AND/OR），无需过滤时用恒真条件如 `CLSNO LIKE '%'`；`limit` 默认 50、最大 100，建议显式传
6. 本技能仅用于**查表、查结构与查数据**，不生成任何配置

## 常见错误与处理

### 未配置项目数据源

**现象**：调用任意数据库工具（`queryTable`、`findTable`、`queryTableColumns`、`queryTableData`）时，MCP 服务返回消息包含 `未配置项目数据源`

**含义**：服务端没有为当前 `projectId` 对应的项目配置数据源，数据库工具无法执行

**处理方式**：数据库工具本身无法修复此问题，**需要用户在服务端维护好数据源**（配置当前项目的数据库连接）后，再重新调用数据库工具。发现该错误时，应停止尝试调用数据库工具，向用户说明：请在服务端为项目配置/维护数据源后重试

### 初始化数据源失败

**现象**：调用任意数据库工具时，MCP 服务返回 `初始化数据源失败`

*含义**：服务端无法连接当前 `projectId` 对应的项目数据源

**处理方式**：**需要用户确认服务端的数据源配置**后，再重新调用数据库工具。发现该错误时，应停止尝试调用数据库工具，向用户说明：请在服务端测试数据源连通性后重试
