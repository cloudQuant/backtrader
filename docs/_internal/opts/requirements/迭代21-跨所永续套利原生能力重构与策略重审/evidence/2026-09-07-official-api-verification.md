# 迭代 21 官方 API 复核记录

> 复核时间：2026-09-07（Asia/Shanghai）
> 状态：`PASS_WITH_LIVE_ENDPOINT_CHECK_PENDING`
> 范围：只读官方文档；没有使用凭据或发出交易请求。

## OKX

官方来源：

- https://www.okx.com/docs-v5/
- https://app.okx.com/docs-v5/trick_en/

复核结论：

1. Demo REST 仍使用 `https://openapi.okx.com`，请求必须带
   `x-simulated-trading: 1`；demo public/private/business WebSocket 使用
   `wss://wspap.okx.com:8443/ws/v5/{public,private,business}`。
2. `GET /api/v5/account/config` 返回 `posMode`；永续和期货的双向模式是
   `long_short_mode`，`net_mode` 不满足本迭代要求。
3. `POST /api/v5/account/set-position-mode` 需要交易权限。迭代 21 runner 只核验模式，
   不自动修改用户账户模式。
4. `GET /api/v5/public/instruments` 是合约规则来源。`books` 是 100 ms 增量簿；
   `books-l2-tbt`/`books50-l2-tbt` 是 10 ms 增量簿且有登录/VIP 限制。因此普通 demo
   账号不能假定拥有 10 ms L2 通道，能力不可用时必须显式降级并影响 HFT 名称门。
5. 账户实际费率和 funding 必须由账户/公共接口返回；缺失时报告 unavailable，不能用
   固定默认值声明净收益。

## Binance USD-M Futures

官方来源：

- https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/account
- https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/Live-Subscribing-Unsubscribing-to-streams
- https://github.com/binance/binance-connector-python/tree/master/clients/derivatives_trading_usds_futures
- https://github.com/binance/binance-signature-examples/blob/master/python/futures/um_futures.py

复核结论：

1. `GET /fapi/v1/positionSide/dual` 是账户 Hedge/One-way 模式的权威查询，
   `dualSidePosition=true` 才满足本迭代双向持仓要求。
2. Hedge Mode 下订单必须显式发送 `positionSide=LONG|SHORT`，不能使用 `BOTH`。
   官方订单合同说明 Hedge Mode 不接受 `reduceOnly` 字段；SDK 必须把统一 close intent
   映射为正确方向和 `positionSide`，而不是原样发送不合法组合。
3. `/fapi/v1/exchangeInfo` 和 symbol filters 是 tick/step/min/notional 的规则来源；
   `canTrade`、账户信息、用户费率和 funding 分别独立获取，不能互相推断。
4. 官方连接器把 Futures Testnet 作为独立 base path；历史官方签名示例使用
   `https://testnet.binancefuture.com`。候选 SDK 当前解析出的 REST/WS/account-stream
   endpoint 必须在 G4/G5A 再做实时 identity 检查，不能仅凭历史 URL 通过。
5. market stream 的订阅 ACK 只证明请求被接收；本地 order book 仍需 snapshot、连续
   update-id、重复/乱序/gap 恢复。private stream 与 REST 查询共同用于订单和持仓收敛。

## 对实现与验收的约束

- 所有 vendor header、host、`positionSide`/`posSide`、listen-key 和规则字段只存在于
  `bt_api_py` 及其 venue 插件；Backtrader Core 和 examples 只消费标准合同。
- G1 合同 fixture 必须绑定本记录的字段语义；G4/G5A 仍需记录运行时 endpoint identity、
  交易所响应时间、position mode 和权限结果。
- 本记录不证明网络可达、账号权限、行情连续性、订单成交或策略收益；对应状态仍为
  `NOT_RUN`，直到候选 wheel 上执行相应 Gate。
