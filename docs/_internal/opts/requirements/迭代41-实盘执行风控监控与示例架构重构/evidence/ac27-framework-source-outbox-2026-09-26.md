# AC41-27：不可变源事件恢复与精确增量投影

日期：2026-09-26。裁决：`LOCAL_PROJECTION_SLICE_PASS / NO_WRITE / LIVE_NO_GO`。

这次验收覆盖真实本地 SQLite execution journal、Framework projection journal、
Bridge、BtApiStore/BtApiBroker 和 fake provider。它不代表完整 AC41-27、统一安装
制品或真实账户验收；多数据部分成交的 runonce/runnext 组合正在另外验证。

## 实现与发现的缺陷

SDK 已提交、Framework 尚未 claim 的事件通过主动 source-outbox 恢复，按不可变
事件中的经济字段恢复，不能用当前订单最新行替换历史事件。拒绝、阻断、撤单与
费用未知状态都有独立事件语义。重复事件不再次记账或调用 provider。

独立 QA 先发现合法浮点结果被精确 Decimal 比较误判；小范围 ULP 校验修复后，
又发现直接相减累计浮点数会导致实质错误：

| 不可变源事实 | 原错误增量 | 修复后的增量 |
| --- | --- | --- |
| 数量 `1e15 → 1e15+1`，VWAP `1 → 1.0000000000000001` | 价格 `1` | 价格 `1.1` |
| 累计费用 `1e12 → 1e12+0.0001` | 费用 `0.0001220703125` | 费用 `0.0001` |

两条错误曾推进 cursor 且没有 fence，因此此前 57 项通过的冻结点被撤回。
最终实现用 `Fraction(Decimal)` 精确计算相邻源事件的增量价格和费用，再各自转换
一次 float。原始累计字段保持 claim 绑定；Broker 使用明确增量，避免重新做累计
浮点差分。数量仍走现有 Broker 接口，必须通过精确源增量与实际 float 差分的
相邻 ULP 校验，并超过其 `1e-12` 应用下限。非有限值、非零增量下溢和不可表示
数量在 claim 前拒绝。实际 execution bits、累计数量/VWAP/费用和终态经核对后
才能完成 claim；未支持的同数量经济修正继续拒绝，不默默丢弃。

## 冻结源与测试

| 文件 | SHA-256 |
| --- | --- |
| `backtrader_runtime/managed_execution.py` | `3353051390b28e869749cd7c0a9e38e741b63ef1f536831555bbb6e4b5a67362` |
| `backtrader_runtime/framework_projection.py` | `b3fbeaeea8665fea84bcb3ad46366b3a12285fcf6f5f6f7c37470aaefe85bbb0` |
| `backtrader/brokers/btapibroker.py` | `538f7ddeb2d1c2ab52f43ec6ffe20981488f901b1b92bddc05f47d5cb75a159c` |
| `backtrader/stores/btapistore.py` | `dba2989252db76fe010fbee7caacdcdba34a9b951e3702724156482b67fae826` |
| `tests/unit/brokers/test_btapibroker_managed_execution_projection.py` | `2719d831a8ad545d47a4bcd271a28d8c89bb4aaf7e235a5c64c19ae43eb2ab5d` |
| `tests/unit/runtime/test_framework_projection_source_events.py` | `c0ee3aa177b6308500f0720f8ab2883ed701a11196d68f6268c216cc627ee543` |
| `tests/integration/test_iteration41_framework_projection_recovery.py` | `ae7deb4b8b0de01e927a082e8b1fbc31edf8001fdb8d7d1e0eb1634d0682feda` |

作者焦点：**64 passed / 4.75s**；独立审阅者同三个测试文件复跑：
**64 passed / 4.60s，exit 0**。使用 Python 3.11.5 与 pytest 8.2.2 的兼容 venv，
execution candidate、clean base `3de0fa4`、本仓按次序位于 `PYTHONPATH`。
这是显式源码集成测试，不是 installed-wheel 验收。Ruff、格式和 scoped diff 检查通过。

独立额外实测确认两条舍入误判、两条大数相消反例均实际记账、完成 cursor、没有
UNKNOWN 或账本失配，后续新订单可接受。真实 facade 的 reject/block 不触达
provider 并正常消费事件。新 session 从历史 partial、后续费用证据和 cancel
恢复，不使用故意冲突的最新行，不重新派发恢复中的订单。

四项故障注入通过：read/claim 失败在 Framework mutation 前 fence；complete 失败
保留已经发生的 fill 并标 UNKNOWN/账本失配；活动事件身份/内容冲突不重复入账。
临时故障测试首次因 pytest 自动发现上级目录的 Windows 权限失败；显式限定
`--rootdir/--confcutdir/--noconftest` 后实际四项通过，该环境失败不计为测试通过。

最终源码另用真实 CPython **3.8.20** 直接验证 Fraction/ULP helpers，以及默认
runtime registry 构造（16 registrations），两个进程均 exit 0，未加载 execution
SDK。这次精度修复没有修改 `backtrader/` 核心文件，因此不改变另外保存的
[1,286 项核心策略回归](f10-core-strategies-2026-09-26.md)源清单。

独立 QA 随后保存回执的复跑为 **64 passed / 4.69s**；首次回执捕获命令参数有误、
未执行测试，该记录与修正后的完整运行分别保留。[JSON 清单](ac27-framework-source-outbox-2026-09-26.json)、
[JUnit](ac27-framework-source-outbox-2026-09-26.junit.xml)、[stdout](ac27-framework-source-outbox-2026-09-26.log)
及[探针/环境/依赖源清单归档](ac27-framework-source-outbox-2026-09-26-probes.zip)可复核。
另一个实际 Broker 探针依次完成买开、卖平多、卖开空、买平空，保留 SELL 负数量、
负手续费与正确仓位，cursor 到 7、全部 Completed、无 fence；这项临时证据正转为持久测试。

## 仍需完成

- 多数据、部分成交、费用通知及 TradeLogger 的双引擎模式组合验收。
- 最新 execution/SDK/parent 的完整集成与统一安装制品验证。
- 完整账户经济事实、真实模拟/生产会话及其各自准入条件。

没有读取私有账户配置、发起 native/provider 会话、真实报单或撤单。
