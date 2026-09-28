# 评审修订期间的既有代码定向核查

日期：2026-09-21。范围：支持计划修订中“哪些行为已经存在、应在重构中保留”的事实判断。
**不是 AC41 新能力验收，也不是实盘、研究、盈利或 production 准入证据。** 未运行全策略回归或
未来 BM56～59；新增计划用例保持 `NOT_RUN`。

## 环境和范围

- Backtrader commit：`ad2c142b9a8b42cede85886528c681abdfcb8096`；本次只修改计划文档，没有改测试或源码。
- 执行器：`C:/anaconda3/python.exe`，Python 3.11.5；cwd `D:/source_code/backtrader`。
- 实测导入：`D:/source_code/backtrader/backtrader/__init__.py`。
- pytest 8.0.0、pytest-asyncio 0.23.0、pytest-xdist 3.6.1，Windows。
- 已审查测试构造：`tests.fixtures.fake_btapi.FakeBtApiClient`、其 `TypedQueryClient` 子类、
  `_ObservationOnlyStore` 和内存 TradeLogger double；没有使用真实 provider client、账户凭据或
  真实通知渠道。测试自身没有网络交易路径；本次没有新增 OS 网络封锁或外部 wire counter，
  因此不把这组旧单测冒充未来 AC36 的进程树零写强制验收。

## 首次命令与收集错误

下面可复制的 PowerShell 命令所列节点在两次运行保持完全一致：

```powershell
$iteration41Nodes = @(
  'tests/unit/brokers/test_btapibroker.py::test_sell_accepts_close_today_offset_and_passes_it_to_store'
  'tests/unit/brokers/test_ctpoption_comminfo.py::test_option_class_and_metadata_multipliers_reject_nonfinite_or_boolean_values'
  'tests/unit/brokers/test_btapibroker_iteration22.py::test_ctp_shutdown_uses_fresh_opponent_limit_with_one_tick_protection'
  'tests/unit/brokers/test_btapibroker_iteration22.py::test_ctp_shutdown_sends_nothing_when_opponent_quote_is_stale'
  'tests/unit/brokers/test_btapibroker_iteration22.py::test_market_data_only_hydrates_external_state_and_never_mutates_account'
  'tests/unit/brokers/test_btapibroker_iteration22.py::test_unknown_ctp_order_requires_two_complete_identical_reconciliation_rounds'
  'tests/unit/observers/test_trade_logger_monitoring.py'
)
& C:/anaconda3/python.exe -m pytest @iteration41Nodes -n 0 -q --tb=short --junitxml=artifacts/iteration41-review-targeted.xml
```

结果：exit code 1，收集阶段一个错误，未执行测试。pytest-asyncio 的 `pytest_collectstart` 在
`collector.obj` 上触发 `AttributeError: 'Package' object has no attribute 'obj'`。
这是当前 pytest/pytest-asyncio 环境不兼容；完整初次结果保留于
[首次 JUnit](iteration41-review-targeted.xml)，不能覆盖或隐瞒。

## 禁用无关 asyncio 插件后的重跑

所选节点都是同步单测；不需要 asyncio fixture。仅本次命令禁用该插件，不修改环境依赖或仓库配置：

```powershell
& C:/anaconda3/python.exe -m pytest @iteration41Nodes -p no:asyncio -n 0 -q --tb=short --junitxml=artifacts/iteration41-review-targeted-no-asyncio.xml
```

结果：exit code 0，**12 passed，1 warning，pytest 控制台耗时 4.71s**；参数化后含 fresh shutdown
两方向、market_data_only 两模式，以及四个 TradeLogger 节点。JUnit 测试套时间为 4.446s，其与控制台
统计范围不同。警告为 `Unknown config option: asyncio_default_fixture_loop_scope`，未隐去。
成功结果：[重跑 JUnit](iteration41-review-targeted-no-asyncio.xml)。

原始文件也保留在 `D:/source_code/backtrader/artifacts/iteration41-review-targeted.xml` 和
`D:/source_code/backtrader/artifacts/iteration41-review-targeted-no-asyncio.xml`；归档前已阅读，内容仅
测试节点、执行时长、机器名称和依赖栈，不含账户、凭据、approval capability 或交易秘密。

证明的范围：现有 offset 透传、期权非法乘数拒绝、关机新鲜价保护/陈旧价零下单、观测模式只读、
unknown 对账双轮门与 TradeLogger 计数均在本机这组 fake 单测中通过。它们不证明迭代41新插件、
账户 durable authority、跨进程恢复、性能目标、gateway 或 AI 交接已实现。
