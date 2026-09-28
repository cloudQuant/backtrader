# BtApiStore AccountActorPort wiring r0 — 独立 QA 收据

日期：2026-09-27（Windows / CPython 3.11.5）。范围仅为冻结源码、离线 fake 和本地测试；没有导入/调用 CTP native/provider，没有账号、凭据或网络操作。主仓和冻结候选未被修改。

## 冻结输入与基线

- 候选 manifest SHA-256 与委托值相符：`ef68998d2b8b75a2125f85bb5720c2e8ba737c818b9d76217767b627cb8b6d14`。独立候选 ZIP SHA-256：`9d3453faa8093d4b8e01fd14aeffb400b3e2e72a6d7de5babaa6f9f37b654ebf`；ZIP `testzip()` 为 `None`，613 项 payload 均按 manifest 核对。
- 共享三文件 apply patch SHA-256：`4b208cc745f8d3fb153cb5dff65c92008d928bc38c06ae12acc559659a6258cb`。候选声明的 main Store 输入与当前 main 工作树文件均为 `dba2989252db76fe010fbee7caacdcdba34a9b951e3702724156482b67fae826`。我重建该精确工作树基线后，`git apply --check` 和 apply 均成功；Store 与候选测试文件输出 byte-exact，actor-port 文件 LF-normalized 后相同。当前 main HEAD 为 `ad2c142b9a8b42cede85886528c681abdfcb8096`，其 Store 早于该脏工作树基线；因此这不是针对旧 HEAD 的 patch 验证。
- 候选源码 SHA-256：`btapistore.py` `e41dd9189059911a180e7fb27bde546cb90a1f7bd2a0c59df6ed624f12c3e179`；`ctp_account_actor_port.py` `e0d3147ec7ce867ec96f29e5dc3e8c4a9343b6ef2845b03e712a7676c9c55a48`；聚焦测试 `19afe01afbe3679018a861ca00c16f5aa0ddd1f4c32823b52812bccce6ccfcdf`。

## 复跑结果

- 候选聚焦 11 项：`11 passed`（一个既有 Quandl deprecation warning）。日志：`candidate-11.log`。
- 原有 Store adapter 30 项，在候选副本：`28 failed, 2 passed`；同一组测试在恢复精确 base Store、移除 actor-port 文件的副本：`30 passed`（一个既有 Quandl deprecation warning）。这是确定的候选回归。
- 28 个候选失败均在 `BtApiStore.__init__` 的 `btapistore.py:3701` 进入 `require_account_actor_before_local_client` 后，以 `store route ambiguous` / `external account actor unavailable` 拒绝。失败包括 CTP fake 合同，也包括历史普通 `provider="btapi"` + 注入 fake `api` + `managed_execution_adapter` 的 managed adapter 正例。该路径构造时只需保存 API 与投影 adapter，成功的适配器测试预期调用 adapter 且不触碰 raw API；现在由于 `route.api is not None` 被统一归为 AMBIGUOUS，构造提前失败。
- `test_managed_execution_store_adapter.py` 的普通 adapter 用法中，以下六个用例在候选失败、base 通过：`test_store_delegates_to_explicit_managed_adapter_without_direct_provider_write`、`test_managed_submit_failure_never_retries_through_direct_provider_path`、`test_missing_managed_projection_is_rejected_without_direct_provider_write`、`test_managed_cancel_without_explicit_port_is_rejected_without_direct_fallback`、`test_store_passes_the_full_order_to_the_explicit_managed_cancel_port`、`test_managed_cancel_failure_never_retries_through_direct_provider_path`。另有 `test_store_rejects_an_object_that_is_not_a_managed_adapter` 因更早的 route 错误码而失败；它属于拒绝顺序/错误分类变化。
- 补充 11 个 Store 测试文件、以 QA-only `optional_sdk` stub 禁止任何真实 SDK import 的候选回归：`386 failed, 68 passed, 145 skipped`。这组包含大量以旧本地 CTP fake 为前提的测试，不能当作普通非 CTP 的独立兼容计数；完整日志保留。gateway 集成测试因会从 SDK 源树导入 `bt_api_py.runtime_plugins`，没有运行。一次先前 harness 尝试因 pytest-asyncio 收集异常中止，原始日志也保留；使用 `-p no:asyncio` 后的重跑才是上面的 broad 结果。

## 结论与边界

**r0 不应合入。** 聚焦候选测试证明其 fail-closed 负例，但精确 base 对照证明它同时切断了普通 `btapi` + raw API 注入 + managed adapter 的既有 public Store 用法。最小安全方向是为“adapter-only / route 尚 ambiguous”的惰性构造提供显式状态；不得把它升级为 `NON_CTP`，不得读取 API 属性或构造客户端，并且每个 client/dispatch 边界仍须重判 sealed route；CTP、unknown、nested CTP、gateway/forwarding 冲突及路由变异必须先拒绝。

r0 中的 Actor receipt/replay 只在本进程 fake 层成立：`FakeLocalActorReplayLedger`（`ctp_account_actor_port.py:266-282`）持有普通内存字典与锁；`ActorCommandReceiptV2` 的 docstring 明示它只是本地可比 receipt、不是 provider acknowledgement（约 `:206`）；`validate_actor_receipt` 逐字段本地比较（约 `:471-497`）。没有持久化、跨进程认证或权威 actor 服务，故 receipt、epoch 或重放结果不能提升运行时准入，也不能证明 CTP lifecycle。

本结果只分类为 **local fake/offline QA**。不代表 native/SDK/生产 route、G4、F14 或任何 CTP Join/Release 接受。

## 原始日志 SHA-256

- `candidate-11.log`: `CCD7C6112CC84C774A69870AE1C26A9C6BB3A878E639789180AA02976713827B`
- `original-30-in-candidate-retry.log`: `5D3452C615C61980367422A0787B5CE220DE1C0BD49886FF594DBDEA38C7DC7D`
- `original-30-on-exact-base.log`: `839D42729977EB9D97B13F307501DAFB8B21F02757A1A2CED2A8E42E008EA87D`
- `broad-ordinary-store-candidate.log`: `220572A5DA16E8D29CA2B41B4DAF423805DC060C24162FD1A6A8760E8FE8DC5E`
- `broad-store-forwarding-gateway-candidate.log` (初次 harness collection 异常): `8F76241EE28AAC39F005B132225C990F6ADB574D22A2A1C4421FF8F964B43210`
- `worktree-base-patch-verification.json`: `24CF3E298C98A244EF8BDF06714134F0B4F00268D702DD1552C4E24A9798EAA3`
