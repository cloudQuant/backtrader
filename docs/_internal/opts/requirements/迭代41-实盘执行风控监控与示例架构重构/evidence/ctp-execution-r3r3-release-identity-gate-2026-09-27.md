# Execution R3r3 发行身份与精确 pin 门

**当前安装制品不通过。**R3r2 与 R3r3 源码 manifest 都声明 `bt_api_execution 0.2.0`；复用版本会得到同版本不同哈希的 wheel。唯一的 `0.2.1` 被 parent76 `_execution_session.py` 和主仓五处运行时精确版本/文件名门拒绝。root 复核了 11 份审计制品、parent 源和五处主仓 pin 的 SHA-256。没有为 R3r3 构建或安装 wheel，此前 `284 passed / 2 skipped` 仅是源码测试。下一步须协调 parent 与主仓 pin，再做双构建、RECORD、安装来源和联调。默认 CTP 写入与 live 路由保持关闭。

[机器记录](ctp-execution-r3r3-release-identity-gate-2026-09-27.json)与[原始归档](ctp-execution-r3r3-release-identity-gate-2026-09-27.raw.zip)保留精确文件；归档 SHA-256 `df895745e0679df47de923cfec628822f6020454ad3ea6cb0c38a7f83f73d5a0`，共 20 项。
