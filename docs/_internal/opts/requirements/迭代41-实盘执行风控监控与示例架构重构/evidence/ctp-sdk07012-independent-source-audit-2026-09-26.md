# CTP SDK 07012 独立源码复验

## 范围与结论

主代理在独立、clean、detached checkout 上复验 SDK commit
`07012dda628c8c0d7fefa6e1b925f7f8b3f8f518`。2026-09-26 本机 Windows、
CPython 3.11 的结果为 **347 passed, 1 deselected, 2 warnings in 57.38s**，
pytest 与审计 runner 均 exit 0。结束后的 Git status 仍 clean。

这是固定源码的 fake API 合同验收，不是 wheel/provenance、原生会话、真实模拟账户或
实盘验收。新开发中的 callback ingress、MD/profile 接线不在此 commit 的结论内。

## 输入与执行

- SDK checkout：`D:/temp/iteration41-root-sdk07012-source-20260926`。
- Base：`D:/temp/bt_api_i9_store_broker_src_20260926/bt_api_base/src`，
  commit `3de0fa4f6cfe8d1973e9f4b9b47b01254259524f`。
- 主仓仅使用现有 `backtrader_runtime.ctp_native_shutdown` consumer。
- 解释器：`C:/anaconda3/python.exe`；禁用第三方 pytest plugin 自动加载、bytecode 写入。
- pytest 参数：`--noconftest -q --tb=short --maxfail=1 -p no:cacheprovider`。
- 排除的唯一测试：`gateway_quote_v2_serialized_payload_reaches_parent_normalizer`，
  它依赖父项目布局；本次 checkout 是独立 SDK 仓。

七个测试文件：

1. `test_ctp_g5_source_unification.py`
2. `test_ctp_native_callback_events.py`
3. `test_ctp_shutdown.py`
4. `test_ctp_feed.py`
5. `test_iter22_contracts.py`
6. `test_ctp_native_query_certificate.py`
7. `test_ctp_trader_login_identity.py`

两个 warning 分别为该解释器的既有 asyncio pytest 配置项不识别，以及审计器主动禁止
可选 CTP 原生扩展导入。fake 测试未依赖原生扩展的空实现来接受真实交易。

## 审计边界

Python audit hook 拒绝外部 socket connect/sendto、外部 DNS、CTP native library 加载和
受保护 runtime 配置/项目 `.env` 打开；meta-path blocker 拒绝 `_ctp`/`ctp_wrap`。
仅允许数值地址 `127.0.0.1` / `::1`，供 Windows asyncio socketpair 使用。
它是测试进程内审计，不是 OS 网络隔离证明。

最终记录：

```json
{
  "pytest_exit": 0,
  "blocked_io": [],
  "loopback_io_count": 113,
  "native_loaded": [],
  "optional_native_imports_blocked": ["bt_api_ctp.ctp._ctp"]
}
```

实际 `bt_api_ctp.ctp.client` 与 `bt_api_ctp` 来源均为上述 frozen SDK checkout；
`bt_api_base` 来源为上述 base checkout，shutdown consumer 来源为主仓。
第一次执行的 harness 误拦了 Windows 本机 socketpair，导致事件循环构造失败；该次结果
属于测试环境失败，没有计作产品回归或验收通过。修正 numeric-loopback guard 后完整重跑，
最终日志为以下成功运行。

## 本机原始证据

| 文件 | SHA256 |
| --- | --- |
| `D:/temp/iteration41-root-sdk07012-audit-20260926.py` | `106c061fa3305b5c87e8ec33a3835d01a9d5828f99afabb71277241c77e618a4` |
| `D:/temp/iteration41-root-sdk07012-audit-20260926.log` | `5e492357f37201238707626d91d4f3681f6b1bebb9ca432c03e31c27efec5045` |

原始文件为本机临时证据，尚非发布制品。原生同步 start/stop 的总时限、账户级 writer
authority、统一制品及真实 provider 接入仍须独立完成；本次没有执行登录、订阅、报单或撤单。
