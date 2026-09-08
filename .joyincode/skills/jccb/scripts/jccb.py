#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
codebase MCP 客户端 —— 代码 RAG 搜索与文件/grep 搜索

直连 codebase MCP 端点（stateless streamable_http，无需认证），
运行配置集中在同目录 jccb.config.json。

用法：
    python jccb.py                                              # 列出可用工具
    python jccb.py searchFrameworkCode search=RAG搜索关键词      # 从向量库搜索框架代码
    python jccb.py grepFileContent filePath=src/Main.java searchContent=public class   # 在框架代码文件中 grep 搜索匹配行
    python jccb.py readFileContent filePath=src/Main.java startLine=10 endLine=50      # 读取指定行范围
    python jccb.py grepFiles searchContent=public class         # 在框架代码仓库中搜索包含内容的文件列表
    python jccb.py grepCodeFile codePath=com.aa.xx.XXService.java searchContent=public class   # 按代码全路径 grep 搜索
    python jccb.py projectId=xxx searchFrameworkCode search=关键词   # 命令行覆盖 projectId
    python jccb.py method ping                                  # 通用 MCP 方法调用

projectId 来源：命令行 projectId=xxx（优先）> 配置文件（jccb.config.json）

参数约定：key=value 按字符串传；value 以 { 或 [ 开头时自动按 JSON 解析。
"""

import json
import os
import sys
import urllib.request

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jccb.config.json")

# 强制 stdout/stderr 使用 UTF-8，避免 Windows 控制台 GBK 乱码
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


def get_configured_project_id() -> str:
    """读取配置 projectId。"""
    val = CFG.get("projectId")
    return val.strip() if isinstance(val, str) else ""


# 工具名 -> (必填参数列表, 可选参数列表, 描述)
TOOLS = {
    # === RAG 语义搜索 ===
    "searchFrameworkCode": (
        ["search"],
        [],
        "从向量库中搜索框架代码，返回代码片段和元数据",
    ),
    # === 文件/内容搜索（GrepSearchMcpTool）===
    "grepFileContent": (
        ["filePath", "searchContent"],
        [],
        "在框架代码文件中 grep 搜索匹配行（content 模式），返回行号和行内容",
    ),
    "readFileContent": (
        ["filePath"],
        ["startLine", "endLine"],
        "读取框架代码文件的指定行范围内容",
    ),
    "grepFiles": (
        ["searchContent"],
        [],
        "在框架代码仓库中搜索包含指定内容的文件列表（files_with_matches 模式），只返回文件路径",
    ),
    "grepCodeFile": (
        ["codePath", "searchContent"],
        [],
        "根据代码全路径（如 com.aa.xx.XXService.java）在框架代码中 grep 搜索匹配行",
    ),
}

# 常用 MCP 方法说明
METHODS = {
    "initialize": "协议握手（stateless 端点通常可跳过）",
    "ping": "连通性检查",
    "tools/list": "列出服务器所有工具",
    "tools/call": "调用工具（与直接子命令等价）",
    "resources/list": "列出服务器资源",
}


def resolve_project_id(explicit: str = "") -> str:
    """projectId 两个来源：命令行传入（优先）> 配置文件。"""
    return explicit or get_configured_project_id()


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
        # 尝试将纯数字字符串转为整数（用于 startLine/endLine）
        if stripped.lstrip("-").isdigit():
            out[key] = int(stripped)
        else:
            out[key] = value
    return out


def list_all(project_id: str = "") -> int:
    print(f"codebase MCP 端点：{get_endpoint()}")
    print(f"配置文件：{CONFIG_FILE}")
    if project_id:
        print(f"projectId：{project_id}（来自配置文件或命令行）")
    else:
        print("projectId：未解析到（请在配置文件中写入，或用 projectId=xxx 传入）")

    print("\n== RAG 语义搜索 ==")
    for name, (required, optional, desc) in TOOLS.items():
        if name.startswith("search"):
            params = ", ".join(required) + "  (必填)"
            if optional:
                params += "  | " + ", ".join(optional) + "  (可选)"
            print(f"- {name}: {desc}\n    参数: {params}")

    print("\n== 文件/内容搜索 ==")
    for name, (required, optional, desc) in TOOLS.items():
        if not name.startswith("search"):
            params = ", ".join(required) + "  (必填)"
            if optional:
                params += "  | " + ", ".join(optional) + "  (可选)"
            print(f"- {name}: {desc}\n    参数: {params}")

    print("\n== 通用 MCP 方法（method 子命令）==")
    for name, desc in METHODS.items():
        print(f"- {name}: {desc}")

    print("\n示例：")
    print("  python jccb.py searchFrameworkCode search=用户登录")
    print("  python jccb.py grepFileContent filePath=src/Main.java searchContent=public")
    print("  python jccb.py readFileContent filePath=src/Main.java startLine=10 endLine=50")
    print("  python jccb.py grepFiles searchContent=public class")
    print("  python jccb.py grepCodeFile codePath=com.aa.xx.XXService.java searchContent=public class")
    return 0


def call_tool(name: str, args: dict) -> int:
    result = rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                  "params": {"name": name, "arguments": args}})
    if result.get("isError"):
        print(f"错误：{result}", file=sys.stderr)
        return 1
    for block in result.get("content", []):
        if block.get("type") == "text":
            print(block.get("text", ""))
        else:
            print(json.dumps(block, ensure_ascii=False, indent=2))
    return 0


def call_method(method: str, args: dict) -> int:
    result = rpc({"jsonrpc": "2.0", "id": 1, "method": method, "params": args})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        return list_all(resolve_project_id())

    first, rest = argv[0], argv[1:]

    # method 子命令
    if first == "method":
        if not rest:
            print("用法: python jccb.py method <方法名> [key=value...]", file=sys.stderr)
            return 1
        return call_method(rest[0], parse_args(rest[1:]))

    # 工具调用
    args = parse_args(argv[1:])
    explicit = args.get("projectId", "")
    pid = resolve_project_id(explicit)
    if not pid:
        print("错误：未解析到 projectId。", file=sys.stderr)
        print("请在配置文件 jccb.config.json 中写入 projectId，", file=sys.stderr)
        print("或用 projectId=xxx 在命令中传入。", file=sys.stderr)
        return 1
    args["projectId"] = pid

    if first not in TOOLS:
        print(f"未知工具: {first}", file=sys.stderr)
        print(f"可用工具: {', '.join(TOOLS)}", file=sys.stderr)
        print("通用方法请用: python jccb.py method <方法名>", file=sys.stderr)
        return 1

    # 校验必填参数
    required, optional, desc = TOOLS[first]
    missing = [p for p in required if p not in args]
    if missing:
        print(f"错误：工具 {first} 缺少必填参数: {', '.join(missing)}", file=sys.stderr)
        print(f"  必填: {', '.join(required)}", file=sys.stderr)
        if optional:
            print(f"  可选: {', '.join(optional)}", file=sys.stderr)
        return 1

    return call_tool(first, args)


if __name__ == "__main__":
    sys.exit(main())
