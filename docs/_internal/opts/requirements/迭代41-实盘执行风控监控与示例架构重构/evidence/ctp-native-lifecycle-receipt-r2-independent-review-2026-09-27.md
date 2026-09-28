# G4 native lifecycle receipt r2 独立复核（2026-09-27）

**独立源码复核通过；G4 仍保持 CLOSED。** r2 修复了 r1 在 Trader API generation 0 与 client/SPI generation 1 之间的绑定时序问题。独立副本的 blocked-Init 探针确认 receipt、client、SPI 的 native generation、epoch、API/SPI source IDs 和对象 IDs 一致；fake Join/Release 收敛后，最终 receipt 仍携带同一组冻结标签并且 `clean=True`。这只接受 r2 的源码身份一致性与 fake-only 生命周期合同，不是 native clean-close 或交易验收。

## 冻结身份与独立副本

- 候选：`D:\temp\iteration41_g4_native_lifecycle_receipt_candidate_20260927_r2`
- freeze manifest SHA-256：`E55D077572EE7F071D3D0AD0FD74522618E1E338A6E38E9963ED6EF76D2F15EE`，与任务给定值一致。
- 基线 `D:\q\e` 工作区干净，HEAD `29f8ff171f61a71038328a7067e0909bf44774b2`；r2 candidate HEAD 和 r1 candidate HEAD 也相同。候选不是 e75 源。
- r2 manifest 的两项变更与冻结候选、独立副本逐字节匹配：
  - `src/bt_api_ctp/ctp/client.py`: `C217BE3E064272327535DA7EDF4B4ED4D587845F03AA11C4669699417C14E6FF`
  - `tests/test_ctp_native_lifecycle_receipt.py`: `6CB3837065BBF3A78ADDE5771CF26EF4593A7FEBF7ED8CBC5D0DEBDDB74CA320`
- r1 原候选文件仍为冻结哈希：client `AA166BAF87B391EECED45A503EFF3B8772D4F17D1BD7E6BA8430A67ED39F80E3`，test `B604849B6146D10E1133C58FC2C0E835B04546CD8DB94CDE9D948593A52B3247`。r1 manifest SHA 仍为 `6571328EBBF41E7D168577BE392B04F9FBF23F2A476DD73DF2C6854CE0D82385`。
- 独立副本：`D:\temp\iteration41_g4_native_lifecycle_receipt_r2_independent_qa_20260927\snapshot`。导入来源记录指向副本的 `snapshot\src\bt_api_ctp\ctp\client.py`，不是候选或主仓。

## 独立执行

以下测试都在独立副本上运行，设置 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`、`PYTHONDONTWRITEBYTECODE=1`，并使用 `D:\temp\g5-r3-test-guard\sitecustomize.py`。Guard SHA-256 为 `57A5F39297F24CAFFD689B89BC3E06F4C8E8FB580FC684A789B2BBD4FE01AB5D`，拦截 `_ctp` native 扩展导入。

- 新增 blocked-Trader-Init 定向回归：**1 passed，2 warnings**。
- 完整三文件焦点 `test_ctp_native_lifecycle_receipt.py`, `test_ctp_shutdown.py`, `test_md_startup_locking.py`：无筛选，**66 passed，2 warnings**。
- 复用 r1 exact-object probe（blocked Init + exact API registry 正/反例）：**2 passed，1 warning**。
- MD/Trader 负例矩阵：detach `RegisterSpi(None)` exception、detach 异常返回类型、Join exception、Init exception、Release exception 后不得错误 clean / 不得重试，**10 passed，2 warnings**。
- Ruff `check --no-fix`、测试文件 `ruff format --check`、两文件 `py_compile` 和 `git diff --check` 均通过。

`2 warnings` 是禁用 pytest plugin autoload 后对现有 asyncio 配置项的警告，以及 fake-only guard 拦截 native extension 的提示。没有跳过测试。r1 独立 QA 的首轮焦点曾有 64 passed、1 个 `test_stop_during_first_register_spi_blocks_all_later_startup_calls[trader]` 失败，随后完整无筛选复跑 65 passed；该历史与原始日志仍收在本次归档中。r2 本轮焦点没有复现该竞争失败。

## r1 修复的独立证据

r1 的缺陷是 lifecycle state 在 `self._api = api` 的 property setter 之前绑定；setter 随后递增 native generation 并创建 epoch/API source ID，使 receipt 保留旧值。r2 在 `TraderClient.start()` 的 `_query_state_lock` 内先安装精确 API/SPI，再绑定 lifecycle state。blocked-Init 测试与独立重用探针在 `Init()` 尚未返回时验证：

- receipt API/SPI object IDs 分别等于当前 API 与 SPI 的 `id()`；session/connection generation 与 client 当前值相等。
- receipt/client/SPI `native_api_generation`、`native_client_epoch` 和 `native_api_source_id` 两两相等且为本代次值；`native_spi_source_id` 等于当前 SPI 的 ID。
- Init entered 期间 receipt 不 clean；之后释放 fake Join，Release 恰一次返回，最终 `clean=True`，同一组代次身份没有漂移。
- 错误 API object 的 lifecycle lookup 返回 `None`；精确 API object 返回对应 state。

r2 定向测试复核了 r1 对照失败与 r2 成功。fake-only 探针不是受信 Windows SDK 实证。

## 范围边界

没有加载或调用真实 CTP SDK、provider、账户凭据或网络；没有构建/安装 wheel，没有验证 bounded Job supervisor，也没有进行真实 SimNow 或 production 交易。同步 `RegisterSpi(None)`、`Init`、`Join`、`Release` 仍可能阻塞。本复核只说明 frozen r2 source receipt 的身份/代次绑定和现有 fake 生命周期用例通过。**G4 real-native clean-close remains CLOSED；G5、真实模拟盘写入和 production 实盘交易仍关闭。**

原始包见 [ZIP](ctp-native-lifecycle-receipt-r2-independent-review-2026-09-27.raw.zip)，SHA-256 `20d372bc78e66df741796941be850ec04013b72d1c7ba5833a0304b9a6598e9c`；31 个条目，`ZipFile.testzip()` 为 `None`，索引内所有文件大小和 SHA-256 均经复核。机器回执和逐项哈希见配套 JSON。
