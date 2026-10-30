# 可选服务读取代理

`ServiceReadProxy` 将 SDK 的账户与行情 facade 接入现有 `BtApiStore`、
`BtApiBroker` 和 `BtApiFeed`。策略进程只使用客户端；账户会话、行情连接和
历史查询由独立 Gateway 服务持有。不配置或不注入代理时沿用现有 Store 路径。

## 使用方式

先按部署配置启动 `ServiceClientRuntime`，构造账户和行情 facade，再显式注入
`BtApiStore(api=proxy)`。账户 facade 必须配置 `require_open_orders=True`，
并绑定明确的账户及资源覆盖范围；每个 feed 使用独立的行情 facade。
当前接入使用 `bt_api_base>=0.15.8` 的合同及 SDK 的
`ServiceAccountClient`、`ServiceMarketClient`；这不是已发布 wheel 的安装声明。
bar 行情授权需包含订阅、快照、重放、head 和 `market.history`。服务端必须提供
实际历史 provider，才能声明和授予历史读取能力。CTP 实时行情可单独使用
`ServiceCtpTickBinding` 订阅 `ctp.quote.v2`；它只向 Feed 交付经验证的原始 tick，
没有 Kline 历史或 tick→bar 投影。

下面假设 `runtime` 已启动，`account_client`、`market_client`、`resource`
已按同一部署图构造；完整可运行的合成服务装配见
`tests/test_service_read_proxy_integration.py`。

```python
import backtrader as bt
from backtrader.stores.btapistore import BtApiStore
from backtrader.stores.service_read_proxy import ServiceFeedBinding, ServiceReadProxy

proxy = ServiceReadProxy(
    account_client,
    {"BTC-USD": ServiceFeedBinding(market_client, resource, "unit", "1m")},
    valuation_currency="USD",
    position_mode="net",
)
store = BtApiStore(api=proxy)
broker = store.getbroker(market_data_only=True, position_mode="net")
cerebro = bt.Cerebro(stdstats=False)
cerebro.setbroker(broker)
cerebro.adddata(store.getdata(
    dataname="BTC-USD", timeframe=bt.TimeFrame.Minutes, compression=1,
    backfill_start=True, dispatch_ticks=False, dispatch_orderbooks=False,
))
cerebro.addstrategy(MyReadOnlyStrategy)
try:
    cerebro.run(runonce=False, preload=False)
finally:
    proxy.close()
    runtime.close()
```

示例的 `unit` 必须与账户 provider 的数量单位一致；需要换算时显式提供
`quantity_multiplier`。`position_mode` 也由部署方明确选择，不根据持仓内容猜测。
现金与净值取自指定币种的 provider valuation，不把不同币种余额直接相加。
账户原生订单与持仓不表示策略分配份额，不赋予订单的策略归属。

## 读取和生命周期约束

- Broker 必须处于 `market_data_only=True`。Store 的提交、撤单及入队入口均拒绝
  写操作；此代理不能用于实盘执行。
- `supports_bar_history(dataname, *, timeframe, compression=1)` 可在 `connect()` 前
  由代理所属线程调用，用于预先检查固定周期的 bar 历史能力。它只检查显式
  `ServiceFeedBinding` 和周期秒数，不调用账户或行情 facade；例如绑定 `60s` 与
  Backtrader 的 1 分钟周期等价。未知 feed、tick/订单簿绑定、无效周期，以及代理
  正在关闭或已关闭时均返回 `False`。该结果只说明配置的周期匹配，不保证服务端
  历史查询一定成功。
- 未成交订单未知和完整空集合有不同含义。订单事实缺失、不完整、单位错误或
  合约未映射时拒绝读取；启动后账户失去有效基线时也会传播错误，不返回旧缓存。
- bar Feed 先建立实时订阅，再分页读取历史。历史和实时重叠的相同闭合 K 线只输出
  一次；内容冲突、乱序、流代次改变或无法恢复的缺口会报错。CTP tick Feed 不读
  history；authenticated wire scope、stream epoch 和 sequence 连续性分别校验。Provider
  connection generation 与 subscription epoch 在绑定期间保持不变；provider `ingest_seq`
  只要求严格递增（不要求连续，因为上游可跨订阅共享游标）。wire 缺口或 source scope
  改变会失败关闭，provider tick 数据字段保持原样。
- 历史页数、行数和去重状态有上限。仅处理固定时长、UTC 对齐的闭合 K 线；
  bar Feed 不支持 tick、订单簿或带交易日历锚点的周/月/年线。CTP tick binding
  必须显式设置 `backfill_start=False`，因为该来源不提供 K 线历史，且不把 tick 合成为
  K 线历史。它还必须绑定可信 CTP metadata 的 account session generation、
  `clock_domain_id` 和正数 `quote_stream_generation`；新账户 session 不得复用旧 metadata，
  事件必须标识 `source=ctp.native.md` 并与可信来源和 generation 相符。
  未收盘事件会被拒绝，上游 bar 仍应只发布已收盘事件。
- facade 与 runtime 的所有操作应在所属线程执行，并持续维护租约。代理关闭
  自己使用的 facade，调用方负责最后关闭共享 runtime；关闭失败可显式重试。
  成功关闭是终态，重新运行须创建新 facade 和代理，不自动重连或回退到 direct。
- 最终账户值应在策略 `stop()` 或最终 writer 报告中读取。Cerebro 在关闭服务
  facade 前生成最终报告；`run()` 返回后再查询已关闭 Broker 会报错，不返回旧值。
- 若清理抛错，保留对象并处理未关闭资源；不要把抛错当作已完成关闭。示例中的
  顺序确保 facade 关闭成功后才关闭 runtime，完整部署需记录和处理清理失败。

## 第07轮 B 验收记录（2026-10-14）

本轮在 Backtrader 现有 `dev`、基线 `4370013d35a3efef5a26689de1322048121bcd60`
进行。范围为代理、Store/Broker/Feed 接线、两个测试文件、使用记录及 AGENTS 说明，
共8个路径。
前置 Cerebro 收尾修复已单独提交为
`f8f82ae41d09e2ddbbc87d0470b7d3a49193d447`，见
[最终报告生命周期](writer-lifecycle.md)。
本轮接入提交以 `f8f82ae41d09e2ddbbc87d0470b7d3a49193d447` 为直接父提交；
本文件的 Git 历史标识交付提交。SDK 对应 `f85407730606fae93f6c29e4f7b37a99b5b5d76e`，
Gateway 对应 `341c359e93937d0a673ba17b0115a922a36a9227`。

| 检查 | 结果与范围 |
|---|---|
| 代理定向检查 | 20项通过；包括账户完整性、单位/币种、历史分页与实时去重、关闭、周线拒绝及写入口拒绝 |
| 既有接入兼容 | 8项通过；未注入代理的 Store/Broker/Feed 路径及现有 writer 行为 |
| 双服务正常 Cerebro | 1项通过，调用9.76秒，总计13.32秒；真实 Windows spawn、CURVE RPC/PUB/SUB、SDK 与服务宿主 |
| Ruff / Git diff | 本轮 Python 源码和测试 lint、新测试与代理格式、差异空白检查通过 |

集成用例使用实际账户 worker/journal/guard、行情 hub/history、SDK runtime/facade，
仅 provider 数据源与客户端密钥为合成输入。账户连接一次，启动与显式刷新各读一次，
原生开放订单从一项替换为完整空集合。策略收到两根历史 bar 与一根新实时 bar，
重叠 bar 未重复；三个采样的现金、净值、持仓分别为80、105、2.5，最终 writer
真实输出 `End: 105.0`。行情上游启动/关闭各一次，账户会话随服务正常关闭一次；
runtime 清理失败/注销不确定计数均为零，两个子进程正常退出，未使用 terminate/kill。

检查批次各保留1条既有 pytest 配置警告；Windows ZMQ 沿用环境提供的 selector
兼容处理，未改变全局事件循环设置。首次代理用例有一处重复数据夹具内容不一致，
修正后仅重跑失败节点。完整集成先暴露了 Gateway v2 就绪、Cerebro 收尾、账户时钟
三项生产问题，均已分别修复并检查；另修正了未来 K 线及清理计数类型两个测试错误。
失败运行未作为成功证据；通过后未为交付重复检查。

本轮只接受本机合成 provider 的读取接入。真实交易所账户、交易写入、跨账户
订单组、重连完整生命周期、AFI 接入和完整 BT01/BT02 仍需分别验收。
