---
name: markitdown
description: 将 Word/PDF/PPT/Excel 等文档转为 Markdown 文件。用户提到 markitdown、word转markdown、word转md、convert_to_markdown 时触发
---

# 文档转 Markdown

三步流程：**curl 上传文件拿 URI → 脚本调用 MCP 转换 → stdout 重定向保存 .md**。脚本仅标准库实现、内部强制 UTF-8 输出（Windows 控制台无乱码）；端点/超时配置在 `scripts/markitdown.config.json`。

## 步骤1：上传文件（获取 URI）

将文件通过接口`https://jc.joyintech.com/jupiter-ai/codehelper/markitdown/upload`上传

响应示例：
```json
{"code":"000","data":"file:///data/2026xxxx/xxx.docx","message":"上传成功"}
```
从响应的 `data` 字段获取文件 URI，用于下一步。

### 推荐方式：用 bash 工具执行 curl 上传
```bash
# Linux / macOS
curl -s -X POST -F "file=@<源文件路径>" "https://jc.joyintech.com/jupiter-ai/codehelper/markitdown/upload" -H "Accept: application/json" -o "<临时响应文件>" --max-time 120
```
> Windows PowerShell 下用 `curl.exe`（`curl` 是 `Invoke-WebRequest` 别名）

## 步骤2：调用 MCP 转换服务

**推荐：用 `-o` 直接输出到文件**（脚本以 UTF-8 写入，不受 Shell 重定向编码影响）：

```bash
python .joyincode/skills/markitdown/scripts/markitdown.py convert_to_markdown uri=file:///data/2026xxxx/xxx.docx -o document.md
```

> 以上命令从项目根目录执行。脚本路径为 `.joyincode/skills/markitdown/scripts/markitdown.py`（项目根目录下没有 `scripts/` 目录），也可改用脚本绝对路径。

如需 stdout 输出（管道/重定向场景），也可不加 `-o`：

```bash
python .joyincode/skills/markitdown/scripts/markitdown.py convert_to_markdown uri=file:///data/2026xxxx/xxx.docx > document.md
```

> 注意：Windows PowerShell 下 `>` 重定向会把输出转成 UTF-16 并按 GBK 解码，导致中文乱码。

无需手动解析 JSON-RPC 或处理临时响应文件编码——脚本已封装。

## 步骤3（可选）：下载图片

若生成的md文件中包含图片 `![xxxx](docx_images/xxxx.png)`，可调用以下接口批量获取图片文件

接口地址：
`POST https://jc.joyintech.com/jupiter-ai/codehelper/markitdown/download`

请求入参：
请求体为 JSON 数组，如：`["文件路径1","文件路径2","文件路径3",...]` 每个元素是md中的文件引用(docx_images/xxxx.png)

请求响应：
- 成功返回 `application/zip` 文件流。部分文件不存在或路径非法时自动跳过，仅打包有效文件
- 若无文件可下载，返回json：`{ "code":"没有可下载的文件", "data":"4d7c11690c0c468e8ce8246fb7c268dc", "message":"没有可下载的文件" }`

## 使用规则

1. **先上传再转换**：脚本不含上传，必须先经步骤1拿到 `file:///...` URI
2. **乱码已由脚本解决**：直接重定向到文件即可；不要用 PowerShell `Invoke-RestMethod`/`Invoke-WebRequest` 手动调 MCP（GBK 乱码），也不要安装本地 markitdown 包绕路转换
3. **通用方法**：`python .joyincode/skills/markitdown/scripts/markitdown.py method <方法名>` 可调用任意 MCP 方法（如 `ping`/`tools/list`）；无参数运行列出全部工具与方法

## 故障排查

| 现象 | 处理 |
|---|---|
| 连接失败/超时/406 | `python .joyincode/skills/markitdown/scripts/markitdown.py method ping` 验证连通性；确认 `markitdown.config.json` 的 endpoint 为 `https://jc.joyintech.com/jc/mcp/markitdown`、timeout 足够 |
| 报错找不到配置文件 | 从项目根目录运行，或用脚本绝对路径 |
