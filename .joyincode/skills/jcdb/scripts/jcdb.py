#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jcdb MCP 客户端 —— 数据库表结构查询

直连 jupkit MCP 端点（stateless streamable_http，无需认证），
运行配置集中在同目录 jcdb.config.json。

用法：
    python jcdb.py                                    # 列出可用工具
    python jcdb.py queryTable comment=用户            # 按表名注释模糊查询数据库表信息
    python jcdb.py findTable tableName=sys_users      # 按表名精确查询数据库表信息
    python jcdb.py queryTableColumns tableName=sys_users  # 查询数据库表结构信息
    python jcdb.py queryTableData tableName=sys_users fields=USERNAME,STATUS "condition=STATUS = '1'" limit=5  # 查询表数据（condition 为单一查询条件，必填）
    python jcdb.py queryTable projectId=xxx           # 命令行覆盖 projectId
    python jcdb.py method ping                        # 通用 MCP 方法调用

projectId 来源：命令行 projectId=xxx（优先）> 配置文件（jcdb.config.json）

参数约定：key=value 按字符串传；value 以 { 或 [ 开头时自动按 JSON 解析。
"""

import json
import os
import sys
import urllib.request

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jcdb.config.json")

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


# 工具名 -> (参数列表, 描述)
TOOLS = {
    "queryTable": (["tableNameComment"], "按表名注释模糊查询数据库表信息"),
    "findTable": (["tableName"], "按表名精确查询数据库表信息"),
    "queryTableColumns": (["tableName"], "查询数据库表结构信息"),
    "queryTableData": (["tableName", "fields", "condition", "limit"], "查询指定表、指定字段的数据（单一查询条件）"),
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
        out[key] = value
    return out


def list_all(project_id: str = "") -> int:
    print(f"jcdb MCP 端点：{get_endpoint()}")
    print(f"配置文件：{CONFIG_FILE}")
    if project_id:
        print(f"projectId：{project_id}（来自配置文件或命令行）")
    else:
        print("projectId：未解析到（请在配置文件中写入，或用 projectId=xxx 传入）")

    print("\n== 工具（tools/call）==")
    for name, (params, desc) in TOOLS.items():
        sig = ", ".join(params) + "  (必填)"
        print(f"- {name}: {desc}\n    参数: {sig}")

    print("\n== 通用 MCP 方法（method 子命令）==")
    for name, desc in METHODS.items():
        print(f"- {name}: {desc}")

    print("\n示例：")
    print("  python jcdb.py queryTable tableNameComment=用户")
    print("  python jcdb.py findTable tableName=sys_users")
    print("  python jcdb.py queryTableColumns tableName=sys_users")
    print("  python jcdb.py queryTableData tableName=sys_users fields=USERNAME,STATUS \"condition=STATUS = '1'\" limit=5")
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
            print("用法: python jcdb.py method <方法名> [key=value...]", file=sys.stderr)
            return 1
        return call_method(rest[0], parse_args(rest[1:]))

    # 工具调用
    args = parse_args(argv[1:])
    explicit = args.get("projectId", "")
    pid = resolve_project_id(explicit)
    if not pid:
        print("错误：未解析到 projectId。", file=sys.stderr)
        print("请在配置文件 jcdb.config.json 中写入 projectId，", file=sys.stderr)
        print("或用 projectId=xxx 在命令中传入。", file=sys.stderr)
        return 1
    args["projectId"] = pid

    if first not in TOOLS:
        print(f"未知工具: {first}", file=sys.stderr)
        print(f"可用工具: {', '.join(TOOLS)}", file=sys.stderr)
        print("通用方法请用: python jcdb.py method <方法名>", file=sys.stderr)
        return 1

    return call_tool(first, args)


if __name__ == "__main__":
    sys.exit(main())
