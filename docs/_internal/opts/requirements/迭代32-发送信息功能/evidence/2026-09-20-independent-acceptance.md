# 迭代 32 独立验收证据（2026-09-20）

## 结论

通知框架的离线合同验收为 `PASS`，但总体状态是
`ACCEPTED_WITH_BLOCKED_EXTERNALS_AND_GLOBAL_GATE`：微信 ClawBot / QQ 的真实送达没有
凭据与平台状态证据；仓库全量快速门禁也不能在当前外部 `bt_api_py` 安装状态下复现。
本文件不把任一离线结果表述为真实渠道送达、生产可靠性或交易验收。

## 基线与变更

- 分支：`dev`；独立干净基线：`f1c13117`
  （`test(notifications): lock signature vectors and isolate proxy env`）。
- 本轮最小修复：同步 `wait=True` 调用将每次 `timeout=` 透传到渠道 `deliver()`；异步 worker
  保持使用配置默认超时。
- 最终源码 SHA-256：

  ```text
  a02b488a58c2cc1799f6cf9224883edeebf6420b9187b8cc37cace47feffa66c  backtrader/notifications/core.py
  7a8049483768b3d3ffd48b7d1c7fd01755108d54716c95364f07e43aabc94b71  tests/unit/notifications/test_config.py
  ```

## F9 缺陷与回归

| 项 | 独立检查结果 |
| --- | --- |
| 缺陷 | `Notifier.send_now(..., timeout=x)` 接收 `x` 后未传给 `_ChannelRuntime._process()`，所以同步 HTTP 调用仍采用配置默认 `request_timeout`。 |
| 风险 | 公开 API 与文档的每次同步调用超时语义失效，调用方无法缩短或放宽该请求。 |
| 修复 | `_process(notification, timeout=None)` 将值传入 `deliver(notification, timeout=timeout)`；`send_now()` 逐渠道传入该值。 |
| 回归 | `test_sync_request_timeout_override_and_configured_default` 断言请求超时依次为 `2.5`（逐调用）和 `0.75`（配置回退）。 |

## 已执行门禁

| ID | 命令/检查 | 结果 | 状态 |
| --- | --- | --- | --- |
| AC32-R1 | `conda run -n base python -m pytest tests/unit/notifications tests/integration/test_notifications_lifecycle.py -q` | `144 passed in 17.55s` | `PASS` |
| AC32-R2 | black check（通知包 + 改动测试） | `24 files would be left unchanged` | `PASS` |
| AC32-R3 | ruff check（通知包 + 改动测试） | `All checks passed` | `PASS` |
| AC32-R4 | mypy `backtrader/notifications` | `9 source files; 0 errors` | `PASS` |
| AC32-R5 | bandit `backtrader/notifications` | High / Medium / Low = `0 / 0 / 0` | `PASS` |
| AC32-R6 | `make test-strategies` | `1271 passed in 231.96s` | `PASS` |
| AC32-R7 | `scripts/notify_smoke.py --list-unverified` | 无凭据，仅列出待验证渠道，无网络发送 | `PASS`（离线） |
| AC32-R8 | `make -C docs html-all` | English + Chinese HTML 均生成；退出 0 | `PASS_WITH_PREEXISTING_WARNINGS` |

文档构建仍报告 135 个既有 Sphinx 警告（主要是仓库内既有 Markdown/RST 结构和代码块问题）。
本次新建的 `user-guide/notifications.md` 与 `user-guide/notifications_zh.md` 已进入构建，
未观察到归因于这两页的警告；警告基线清理不是本轮通知功能完成的替代证据，已转入后续计划。

## 明确 BLOCKED / 非通过项

| ID | 项 | 状态 | 原因与下一步 |
| --- | --- | --- | --- |
| AC32-B1 | 微信 ClawBot 真实送达 | `BLOCKED` | 缺灰度资格、真实 bot token 与入站 `context_token`；按验收文档 §10.4 手工冒烟，证据不得含凭据。 |
| AC32-B2 | QQ 机器人真实送达 | `BLOCKED` | 缺开放平台 appid/appsecret/openid 与沙箱状态；按验收文档 §10.4 手工冒烟。 |
| AC32-B3 | 当前脏工作树 `make test-fast` | `FAIL`（非通知归属） | 2 failures + 2 errors，位于 CTP/SDK 测试；不可作为通知验收失败或全仓绿灯。 |
| AC32-B4 | 干净 `f1c13117` worktree 的 `make test-fast` | `BLOCKED` | 环境中的 `bt_api_py` 缺少 `CrossVenueLeg` 和 `CtpExecutionApprovalCapability`，导致 165 failures + 51 errors；须建立可复现 SDK 安装/契约边界。 |

`make test-strategies` 的通过不抵消 AC32-B3/B4；反之，外部 SDK 问题也不推翻已独立执行的
通知专项与策略回归证据。后续全仓质量迭代必须分别关闭这些缺口，才能声明完整仓库门禁为绿。
