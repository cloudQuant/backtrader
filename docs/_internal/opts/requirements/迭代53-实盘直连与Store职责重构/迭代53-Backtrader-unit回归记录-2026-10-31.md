# 迭代53 Backtrader unit 回归记录（2026-10-31）

- 仓库：`D:\source_code\backtrader`
- 分支：`dev`
- Git HEAD：`b49938cb3f7aa40da6e0d2629a58584a00fd9547`
- Python：3.11
- 结果来源：当前工具会话 `37909`，退出码 `0`
- 执行耗时：`130.38s`

## 执行命令

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:asyncio tests/unit -n 12 -m 'not slow and not performance' --tb=short -q
```

## 结果

- `3,615 passed`
- `50 skipped`
- `13 warnings`；告警中包含未知配置项 `asyncio_default_fixture_loop_scope`
- pytest 进程退出码为 `0`

## 范围与限制

本次只运行 `tests/unit`，并通过 `-m 'not slow and not performance'` 排除了 `slow` 和 `performance` 标记项。该命令不包含已删除的账户流程测试，也没有执行真实账户、真实 CTP/SimNow 流程或交易验收。

因此，这一结果只记录该次 Backtrader unit 回归运行；不能外推为完整迭代53、跨 SDK/Store 集成、慢测/性能门禁或任何真实账户验收通过。50 项跳过及 13 项 warning 按本次执行结果原样记录，不据此推定其余门禁状态。

执行时工作区存在其他未提交改动。HEAD 用于标识提交基线；本记录不声称执行环境等同干净 checkout，也不把结果归因于特定的未提交改动。

本记录按工具会话 `37909` 的结果整理，未重跑测试；不修改或替代迭代53实施记录及其他已有工作区文件。
