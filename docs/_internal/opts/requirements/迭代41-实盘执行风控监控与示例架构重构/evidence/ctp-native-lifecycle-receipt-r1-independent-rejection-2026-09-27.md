# G4 native lifecycle receipt r1 独立复核：拒绝（2026-09-27）

**结论：冻结候选 r1 不通过独立 QA。** 三文件焦点在完整复跑中为 65 passed，但独立 exact-object 探针发现 Trader receipt 的 native API generation、client epoch 与 API source ID 都取自赋值前旧状态。receipt 最终仍可报告 `clean=True`，故不能把 r1 作为正确的 API/SPI/代次一致性证据。不要据此关闭 G4、验收真实 native clean-close 或开放任何 CTP/trading route。

## 冻结身份与隔离

- 冻结候选：`D:\temp\iteration41_g4_native_lifecycle_receipt_candidate_20260927`
- manifest SHA-256：`6571328EBBF41E7D168577BE392B04F9FBF23F2A476DD73DF2C6854CE0D82385`；与请求值逐字节一致。
- 基线干净仓库 `D:\q\e`，HEAD `29f8ff171f61a71038328a7067e0909bf44774b2`，工作区干净。此候选不是 e75 源。
- manifest 指定两项变化，冻结候选与独立副本 `D:\temp\iteration41_g4_native_lifecycle_receipt_independent_qa_20260927\snapshot` 的 SHA-256 均相符：
  - `src/bt_api_ctp/ctp/client.py`: `AA166BAF87B391EECED45A503EFF3B8772D4F17D1BD7E6BA8430A67ED39F80E3`
  - `tests/test_ctp_native_lifecycle_receipt.py`: `B604849B6146D10E1133C58FC2C0E835B04546CD8DB94CDE9D948593A52B3247`
- 独立副本 HEAD 与基线相同；冻结候选未修改。测试由 `D:\temp\g5-r3-test-guard\sitecustomize.py` 阻止 `_ctp` native 扩展导入，guard SHA-256 为 `57A5F39297F24CAFFD689B89BC3E06F4C8E8FB580FC684A789B2BBD4FE01AB5D`。测试只使用 fake API，无 CTP provider、凭据或网络调用。

## 回归与静态检查

在独立副本对完整三文件焦点执行：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONPATH='D:\temp\g5-r3-test-guard;D:\temp\iteration41_g4_native_lifecycle_receipt_independent_qa_20260927\snapshot\src;D:\source_code\backtrader'
python -m pytest --noconftest tests/test_ctp_native_lifecycle_receipt.py tests/test_ctp_shutdown.py tests/test_md_startup_locking.py -q --tb=short --junitxml='D:\temp\iteration41_g4_native_lifecycle_receipt_independent_qa_20260927\evidence\focused-rerun.xml'
```

第一轮完整焦点为 **64 passed、1 failed**，失败在既有 `test_stop_during_first_register_spi_blocks_all_later_startup_calls[trader]` 时序竞争；没有跳过或改写它。完整原始日志保留。随后不作筛选地重跑全焦点，得到 **65 passed、2 warnings，exit 0**。这只说明该轮焦点通过，不能抵消下面的字段一致性失败。两个 warning 是禁用插件自动加载后 pytest 不认识现有 asyncio 配置，以及 fake-only guard 拦截 `_ctp` 的提示。

下列静态检查通过：Ruff `check --no-fix`、测试文件 `ruff format --check`、两个候选文件 `py_compile`、`git diff --check`。静态检查通过也不证明 receipt provenance 正确。

## 阻断缺陷：Trader receipt 记录落后一代的 native 身份

QA-only 探针让 fake `Init()` 暂停在调用内，并从公开 `native_lifecycle_receipt` 读取快照。该时点确认 `init_state='entered'`、`clean=False`、receipt 中 API/SPI object ID 精确匹配且 `session_generation` 匹配。与此同时，Trader 客户端与 SPI 的当前身份均已处于 generation 1，而 receipt 内部 ledger 仍保留绑定时的 generation 0：

| 字段 | receipt | client / SPI 实际当前值 |
| --- | --- | --- |
| `native_api_generation` | `0` | `client=1`, `SPI=1` |
| `native_client_epoch` | `None` | client 与 SPI 均为本代次非空 epoch |
| `native_api_source_id` | `None` | client 与 SPI 均为本代次非空 source ID |
| `native_spi_source_id` | 本代次 SPI ID | 与 SPI 一致 |

受控 QA 探针继续释放 fake Init 与 Join，确认 detach/Join/Release 收敛且 Release 恰一次；终态仍为 `clean=True`，但上述三个身份字段继续不一致。第二个 QA-only 对照探针通过：lifecycle registry 对同一个 API 对象返回其 state，对不同 impostor API 返回 `None`。所以失败不是对象查找混淆，而是 generation/source metadata 的绑定时机错误。

静态根因可定位于 Trader `start()`：先调用 `_bind_ctp_native_lifecycle_state(...)` 捕获 metadata；随后 `self._api = api` 的 setter 才递增 `_native_api_generation` 并分配 `_native_client_epoch`、`_native_api_source_id`；再随后把这些新值复制到 SPI。receipt state 没有同步到新一代。`clean` 属性不包含 metadata 一致性谓词，因此这些 stale fields 不会阻止 clean。

r2 修复后应重新冻结并重跑独立 QA。最低复验要求：在第一次 RegisterSpi/Init 之前，receipt、client 与对应 SPI 对同一 API 都绑定同一个非空 native generation、client epoch、API source ID、SPI source ID 与 session generation；旧 API 或错代次对象不得取到新 state；在 `Init` entered、Join pending、Release entered、异常与最终 clean 各态仍满足现有 fail-closed 规则。不要由 fake verifier 推断 Windows native lifecycle 实证。

## 范围限制与原始材料

这是独立的 source/fake-only review。没有加载或调用真实 CTP SDK、连接 provider、读入账户凭据、联网、构建或安装 wheel，也没有执行原生 supervisor/Job containment 验收。同步 `RegisterSpi(None)`、`Join`、`Release` 仍可能阻塞。G4 real-native clean-close 仍未验收，G5 与真实模拟盘/实盘交易仍关闭。

原始材料归档为 [ZIP](ctp-native-lifecycle-receipt-r1-independent-rejection-2026-09-27.raw.zip)，SHA-256 `f1fea616dda19e0829340675fdf4c6c9223f70139a983db87f0388e09ecfedd9`。归档含冻结 manifest、基线与候选 `client.py`、候选测试、native guard、完整焦点首轮/复跑日志与 JUnit、静态检查日志、exact-object QA-only 探针和两轮原始输出；共 22 个 ZIP 条目，`ZipFile.testzip()` 为 `None`。机器可读字段、逐项哈希与 archive index SHA 见配套 JSON。


