---
name: markitdown
description: 将Word文档转为markdown文件
---

# Word转Markdown
## 步骤1：上传文件
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
- 使用MCP服务`https://jc.joyintech.com/jc/mcp/markitdown`的 convert_to_markdown 工具
- 将步骤1返回的 `data` 值作为 `uri` 参数
- 请求头为 `Accept: application/json, text/event-stream`

### ⚠️ **乱码问题**
**不要用 PowerShell 的 `Invoke-RestMethod` / `Invoke-WebRequest` 调用此服务。**

根因：PowerShell 5.1 默认不按 UTF-8 解码 HTTP 响应体，`Get-Content`（即使指定 `-Encoding UTF8`）输出到控制台时也按 GBK 编码，会把 MCP 返回的 UTF-8 中文显示成乱码，误导你以为"服务端返回乱码"，实际是客户端显示层问题。

## 步骤3：提取并保存 Markdown
- 响应是 JSON-RPC 格式，Markdown 内容在 `result.content[0].text` 中
- 必须以 UTF-8 读取步骤2的临时响应文件再解析，避免编码二次污染
- 保存后删除临时文件

### 图片下载
若生成的md文件中包含图片 `![xxxx](docx_images/xxxx.png)`，可调用以下接口批量获取图片文件

接口地址：
`POST https://jc.joyintech.com/jupiter-ai/codehelper/markitdown/download`

请求入参：
请求体为 JSON 数组，如：`["文件路径1","文件路径2","文件路径3",...]` 每个元素是md中的文件引用(docx_images/xxxx.png)

请求响应：
- 成功返回 `application/zip` 文件流。部分文件不存在或路径非法时自动跳过，仅打包有效文件
- 若无文件可下载，返回json：`{ "code":"没有可下载的文件", "data":"4d7c11690c0c468e8ce8246fb7c268dc", "message":"没有可下载的文件" }`

### 排障指引
若看到乱码，**优先怀疑客户端读取/显示层编码，而非服务端**：
- Windows 下用 Read 工具读取步骤2保存的响应文件——若内容正确，说明服务端无问题
- **不要因此去安装本地 markitdown 包绕路转换。**
