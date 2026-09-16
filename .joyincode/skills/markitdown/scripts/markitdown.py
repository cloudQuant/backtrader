#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
markitdown MCP 客户端 —— 文档转 Markdown

直连 markitdown MCP 端点（stateless streamable_http，无需认证），
运行配置集中在同目录 markitdown.config.json。

用法：
    python markitdown.py                                            # 列出可用工具与方法
    python markitdown.py convert_to_markdown uri=file:///data/2026xxxx/xxx.docx   # 转换文档URI为Markdown
    python markitdown.py convert_to_markdown uri=file:///data/2026xxxx/xxx.docx -o out.md  # 转换并直接写入文件（UTF-8，避免Shell重定向乱码）
    python markitdown.py method ping                               # 通用 MCP 方法调用
    python markitdown.py method tools/list                         # 列出服务器所有工具

转换所需的文件 URI 来源：先调用上传接口
    POST https://jc.joyintech.com/jupiter-ai/codehelper/markitdown/upload
    取响应 data 字段（file:///... URI）作为本脚本的 uri 参数。

参数约定：key=value 按字符串传；value 以 { 或 [ 开头时自动按 JSON 解析。
"""

import json
import os
import sys
import urllib.request

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "markitdown.config.json")

# 强制 stdout/stderr 使用 UTF-8，避免 Windows 控制台 GBK 乱码
# （markitdown 转换结果含大量中文，客户端显示层必须按 UTF-8 解码）
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


def load_config() -> dict:
    """读取配置文件；缺失或损坏则报错退出。"""
    if not os.path.isfile(CONFIG_FILE):
        print(f"错误：找不到配置文件 {CONFIG_FILE}", file=sys.stderr)
        sys.exit(1)
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f) or {}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        print(f"错误：配置文件解析失败 {CONFIG_FILE}：{e}", file=sys.stderr)
        sys.exit(1)
    return cfg


CFG = load_config()


def _require(key: str) -> str:
    """取必填字符串配置项，缺失则报错退出。"""
    val = CFG.get(key)
    if not isinstance(val, str) or not val.strip():
        print(f"错误：配置缺失必填项 {key}（{CONFIG_FILE}）", file=sys.stderr)
        sys.exit(1)
    return val.strip()


def get_endpoint() -> str:
    """端点：仅来自配置文件 endpoint（必填）。"""
    return _require("endpoint")


def get_timeout() -> int:
    """超时：配置 timeout（须为正整数）。"""
    t = CFG.get("timeout")
    try:
        t = int(t)
    except (TypeError, ValueError):
        print(f"错误：配置 timeout 须为整数（{CONFIG_FILE}）", file=sys.stderr)
        sys.exit(1)
    if t <= 0:
        print(f"错误：配置 timeout 须为正整数（{CONFIG_FILE}）", file=sys.stderr)
        sys.exit(1)
    return t


# 工具名 -> (参数列表, 描述)
TOOLS = {
    "convert_to_markdown": (["uri"], "将文档(Word/PDF/PPT/Excel等)URI转换为Markdown"),
}

# 常用 MCP 方法说明
METHODS = {
    "initialize": "协议握手（stateless 端点通常可跳过）",
    "ping": "连通性检查",
    "tools/list": "列出服务器所有工具",
    "tools/call": "调用工具（与直接子命令等价）",
    "resources/list": "列出服务器资源",
}


def rpc(payload: dict) -> dict:
    """发送 JSON-RPC 请求，返回 result 部分。"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        get_endpoint(),
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=get_timeout()) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if "error" in data:
        raise RuntimeError(f"MCP error: {data['error']}")
    return data["result"]


def parse_args(items) -> dict:
    """key=value -> dict；value 以 { 或 [ 开头时按 JSON 解析。"""
    out = {}
    for item in items:
        if "=" not in item:
            continue
        key, _, value = item.partition("=")
        stripped = value.strip()
        if stripped.startswith(("{", "[")):
            try:
                out[key] = json.loads(stripped)
                continue
            except json.JSONDecodeError:
                pass
        out[key] = value
    return out


def extract_output_flag(argv: list) -> tuple:
    """提取 -o/--output 输出文件参数，返回 (剩余参数, 输出路径或None)。"""
    out = None
    rest = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("-o", "--output") and i + 1 < len(argv):
            out = argv[i + 1]
            i += 2
            continue
        rest.append(arg)
        i += 1
    return rest, out


def list_all() -> int:
    print(f"markitdown MCP 端点：{get_endpoint()}")
    print(f"配置文件：{CONFIG_FILE}")

    print("\n== 工具（tools/call）==")
    for name, (params, desc) in TOOLS.items():
        sig = ", ".join(params) + "  (必填)"
        print(f"- {name}: {desc}\n    参数: {sig}")

    print("\n== 通用 MCP 方法（method 子命令）==")
    for name, desc in METHODS.items():
        print(f"- {name}: {desc}")

    print("\n说明：")
    print("  转换所需的文件 URI 需先经上传接口获取：")
    print("    POST https://jc.joyintech.com/jupiter-ai/codehelper/markitdown/upload")
    print("  取响应 data 字段（file:///... URI）作为 uri 参数传入。")

    print("\n示例：")
    print("  python markitdown.py convert_to_markdown uri=file:///data/2026xxxx/xxx.docx")
    print("  python markitdown.py convert_to_markdown uri=file:///data/2026xxxx/xxx.docx -o out.md")
    print("  python markitdown.py method ping")
    print("  python markitdown.py method tools/list")
    return 0


def call_tool(name: str, args: dict, output_file: str = None) -> int:
    result = rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                  "params": {"name": name, "arguments": args}})
    if result.get("isError"):
        print(f"错误：{result}", file=sys.stderr)
        return 1
    texts = []
    for block in result.get("content", []):
        if block.get("type") == "text":
            texts.append(block.get("text", ""))
        else:
            texts.append(json.dumps(block, ensure_ascii=False, indent=2))
    content = "\n".join(texts)
    if output_file:
        try:
            with open(output_file, "w", encoding="utf-8", newline="") as f:
                f.write(content)
        except OSError as e:
            print(f"错误：写入输出文件失败 {output_file}：{e}", file=sys.stderr)
            return 1
        print(f"已写入 {output_file}（{len(content.encode('utf-8'))} 字节）")
    else:
        print(content)
    return 0


def call_method(method: str, args: dict) -> int:
    result = rpc({"jsonrpc": "2.0", "id": 1, "method": method, "params": args})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        return list_all()

    argv, output_file = extract_output_flag(argv)

    first, rest = argv[0], argv[1:]

    # method 子命令
    if first == "method":
        if not rest:
            print("用法: python markitdown.py method <方法名> [key=value...]", file=sys.stderr)
            return 1
        return call_method(rest[0], parse_args(rest[1:]))

    # 工具调用
    args = parse_args(argv[1:])

    if first not in TOOLS:
        print(f"未知工具: {first}", file=sys.stderr)
        print(f"可用工具: {', '.join(TOOLS)}", file=sys.stderr)
        print("通用方法请用: python markitdown.py method <方法名>", file=sys.stderr)
        return 1

    return call_tool(first, args, output_file)


if __name__ == "__main__":
    sys.exit(main())
