# G4 CTP native lifecycle receipt r2 作者候选（2026-09-27）

**状态：r2 的[独立源码身份一致性 QA](ctp-native-lifecycle-receipt-r2-independent-review-2026-09-27.md)已通过；G4 仍 CLOSED。** 独立副本三文件焦点 66 项、blocked-Init 及异常负测通过，确认 receipt/client/SPI 同代次；该结果仍是 fake-only 源码合同，不构成真实 CTP clean-close 验收。

## 来源与修复

r2 位于 `D:\temp\iteration41_g4_native_lifecycle_receipt_candidate_20260927_r2`，基于 `D:\q\e` 的干净 HEAD `29f8ff171f61a71038328a7067e0909bf44774b2`。基线 `client.py` SHA-256：`bf915128c41da83efdff517e3ea711c43d7555406bd831a0dfcd775b64840d1c`。r2 只改 `client.py` 并新增生命周期测试。修复在 Trader `_api` setter 生成当前 API generation/epoch/source IDs 且设置同一 SPI 后绑定不可变 lifecycle receipt，并在锁内完成，避免 Init 已进入时 receipt 仍快照旧 generation。

新增 `test_blocked_trader_init_receipt_matches_installed_api_spi_generation`：fake `Init` 阻塞期间逐项核对 receipt、client 与该 API/SPI 的对象 ID、generation、epoch 和 source IDs；Init 完成、Join/Release 后再次确认 receipt 保留同一组身份。该用例在 r1 上按预期失败，显示 `receipt.native_api_generation=0`、而 `client._native_api_generation=1`；在 r2 上通过。r1 原独立拒绝材料保留且未修改：[r1 独立拒绝报告](ctp-native-lifecycle-receipt-r1-independent-rejection-2026-09-27.md)、[r1 原拒绝归档](ctp-native-lifecycle-receipt-r1-independent-rejection-2026-09-27.raw.zip)。

本候选**不是 e75 wheel 的源码**：e75 对照 `client.py` SHA-256 为 `2d31bf75b801847d185db5cbcbf284752736e96b4874449fb34bdab0dc5cbf09`。没有从 e75 制品继承来源或验收。

## 验证

从 r2 根目录执行完整 fake-only 焦点：

```powershell
$env:PYTHONPATH='D:\temp\g5-r3-test-guard;D:\temp\iteration41_g4_native_lifecycle_receipt_candidate_20260927_r2\src;D:\source_code\backtrader'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest --noconftest tests/test_ctp_native_lifecycle_receipt.py tests/test_ctp_shutdown.py tests/test_md_startup_locking.py -q --tb=short --junitxml='D:\temp\iteration41_g4_native_lifecycle_receipt_evidence_20260927_r2\junit.xml'
```

结果：**66 passed，2 warnings，exit 0**。Ruff、测试文件格式检查、`py_compile` 与 `git diff --check` 均通过。native import guard 拦截 `_ctp` 导入；没有真实 native、provider、凭据或网络调用。两条 warning 是禁用 pytest 插件自动加载时的既有配置项 warning，以及 native import guard 提示。

同步 native 生命周期操作仍可能阻塞；receipt 不提供有界 supervisor 证明，也不把 Job/进程终止视为 native cleanup。未运行真实 CTP 会话或 clean-close 验证，未构建 wheel，也未改默认 pin。完整逐项 SHA-256、日志/JUnit、环境和归档校验记录见[机器回执](ctp-native-lifecycle-receipt-r2-author-candidate-2026-09-27.json)。原始候选和测试证据见[ZIP](ctp-native-lifecycle-receipt-r2-author-candidate-2026-09-27.raw.zip)。独立 QA 完成前，G4 保持 CLOSED。
