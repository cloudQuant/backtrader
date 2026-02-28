# CCXT 与 CTP 实盘交易优化清单

> 生成时间：2026-02-25
> 分析范围：`backtrader/brokers/ccxtbroker.py`, `backtrader/stores/ccxtstore.py`, `backtrader/feeds/ccxtfeed.py`, `backtrader/feeds/ccxtfeed_funding.py`, `backtrader/ccxt/*`, `backtrader/brokers/ctpbroker.py`, `backtrader/feeds/ctpdata.py`, `backtrader/stores/ctpstore.py`

- --

## 一、CCXT 模块优化清单

### 🔴 P0 — 严重 Bug / 数据安全

| # | 问题 | 文件 | 说明 | 建议 |

|---|------|------|------|------|

| C1 | **CCXTOrder 未调用父类正确初始化**| `ccxtbroker.py:59-79` | `CCXTOrder.__init__` 先设置属性再调 `super().__init__()`，但 `Order.__init__` 会覆盖/重置部分属性（如 `size`, `price`）。且未传入 `owner`, `data` 等参数给父类。 | 重写为通过 `super().__init__(owner, data, size, price, ...)` 正确初始化，或改用组合模式封装 ccxt_order |

| C2 |**Bracket 模块使用未导入的 `bt`**| `ccxt/orders/bracket.py:130-141` | `_activate_protection()` 中直接使用 `bt.Order.Stop` 和 `bt.Order.Limit`，但文件没有 `import backtrader as bt`。运行时会 NameError。 | 改用已定义的 `_ORDER_LIMIT` 常量，或正确导入 |

| C3 |**CCXTFeed stop() 会关闭共享 WS manager**| `ccxtfeed.py:496-498` | `stop()` 无条件调用 `self._websocket_manager.stop()`。当多个 feed 共享同一个 WS manager 时，第一个 feed 停止会杀掉所有 feed 的 WS。 | 学习 `ccxtfeed_funding.py:637` 的 `_ws_is_shared` 标志做法 |

| C4 |**WebSocket 断线后 REST 回退无限循环**| `ccxtfeed.py:280-306` | WS 断线后 `_ws_connected=False`，进入 REST 轮询，但 `_last_update_bar_time` 可能为 0，导致每次 `_load()` 都触发 `_update_bar(livemode=True)` | 断线时应设置合理的 `_last_update_bar_time` |

| C5 |**getvalue 不计算持仓价值**| `ccxtbroker.py:437-452` | `getvalue()` 只返回 `store._value`（仅账户 USDT 余额），不包含持仓的市值。多币种场景下 value 不准确。 | 遍历 `self.positions` 计算持仓市值，或调用 CCXT 的 `fetch_total_balance()` |

| C6 |**CCXTStore.getdata 类方法被实例方法覆盖**| `ccxtstore.py:93-109` | 先定义 `@classmethod getdata`，随后又定义同名实例方法 `getdata`，Python 中后者覆盖前者。类方法永远不会被调用。 | 删除冗余的类方法定义，或重命名 |

### 🟡 P1 — 功能缺陷 / 健壮性

| # | 问题 | 文件 | 说明 | 建议 |

|---|------|------|------|------|

| C7 |**市价单未正确处理**| `ccxtbroker.py:634-639` 注释 | 注释明确指出"现货不支持市价单"。某些交易所市价单的 amount 字段含义不同（金额 vs 数量）。 | 添加交易所市价单适配层：检测 exchange.has['createMarketBuyOrderRequiresPrice']，自动转换 |

| C8 |**手续费未计入订单执行**| `ccxtbroker.py:396-399,686-700` | `order.execute()` 手续费相关参数全部传 0。策略无法通过 `order.executed.comm` 获取手续费。 | 从 ccxt_order['fee'] 或 trade['fee'] 提取手续费并传入 execute() |

| C9 |**止损单/止损限价单未实现**| `ccxtbroker.py` | `order_types` 映射了 Stop/StopLimit，但 `_submit()` 没有处理止损触发逻辑。与 CTPBroker 不同，CCXT 直接提交到交易所。 | 区分支持原生止损的交易所（binance futures）和不支持的，后者需本地触发 |

| C10 |**OCO/Trailing Stop 参数被丢弃**| `ccxtbroker.py:887-889,926-928` | `buy()/sell()` 直接 `del kwargs["parent"]` 和 `del kwargs["transmit"]`，`oco`, `trailamount`, `trailpercent` 等参数被忽略。 | 将 oco/trailing 参数转发到 ccxt params 或本地管理 |

| C11 |**WS order updates 用无界 list 存 fill IDs**| `ccxtbroker.py:78,393` | `executed_fills` 是 list，append 永不清理，长时间运行内存增长。 | 用 set 替代 list（查重 O(1)），或定期清理已完成的订单 |

| C12 |**retry 装饰器在类体内定义**| `ccxtstore.py:212-244` | `retry` 定义为 CCXTStore 内的普通函数（缺少 `@staticmethod`），但作为装饰器使用。虽然能工作但不规范，IDE 和 linter 会报警。 | 改为 `@staticmethod` 或移到模块级 |

| C13 |**get_granularity 使用未导入的 bt**| `ccxtstore.py:204` | `bt.TimeFrame.getname(timeframe)` 但文件未 `import backtrader as bt`，触发 NameError。 | 使用本地常量映射或正确导入 |

| C14 |**WebSocket reconnect 丢失中间数据**| `ccxt/websocket.py:630-661` | 重连成功后恢复订阅，但断线期间的 OHLCV 数据丢失，没有 REST 回补。 | 重连后根据最后收到的 timestamp 做 REST backfill |

| C15 |**ThreadedOrderManager 不处理订单过期**| `ccxt/threading.py:330` | 只 remove closed/canceled/expired/rejected，但不处理长时间 open 且无变化的"僵尸"订单。 | 添加超时清理：超过 N 小时无更新的订单标记为 stale |

### 🟢 P2 — 性能 / 代码质量

| # | 问题 | 文件 | 说明 | 建议 |

|---|------|------|------|------|

| C16 |**REST 轮询间隔硬编码**| `ccxtbroker.py:569` | `3 秒` 硬编码，不同策略/timeframe 需要不同频率。 | 改为可配置参数 `poll_interval` |

| C17 |**open_orders 用 list 遍历查找**| `ccxtbroker.py:371,589-593` | 每次 WS/threaded 更新都遍历 list 找匹配订单，O(n)。 | 改用 dict `{order_id: order}` 实现 O(1) 查找 |

| C18 |**fetch_ohlcv 不支持分页**| `ccxtfeed.py:370-418` | 历史数据回填时限制 `ohlcv_limit` 但没有自动分页。大量历史数据需要手动多次调用。 | 实现自动分页循环直到 fromdate 到 todate 全部获取 |

| C19 |**datetime.utcfromtimestamp 已弃用**| `ccxtfeed.py:476`, `ccxtfeed_funding.py:603` | Python 3.12 中 `datetime.utcfromtimestamp()` 已弃用。 | 改用 `datetime.fromtimestamp(ts, tz=timezone.utc)` |

| C20 |**ExchangeConfig 手续费数据硬编码**| `ccxt/config.py:194-201` | 手续费率硬编码，但实际费率因等级/VIP 不同。 | 优先从 exchange.fetch_trading_fee() 动态获取，硬编码作为 fallback |

| C21 |**RateLimiter 用 list 存时间戳**| `ccxt/ratelimit.py:57` | 每次 acquire 都创建新 list 过滤旧记录，高频调用时 GC 压力大。 | 用 `collections.deque` + 双指针，避免重复创建 list |

| C22 |**ConnectionManager.reconnect 无限循环**| `ccxt/connection.py:100` | `while self._running` 循环，如果 store 被意外 stop，可能卡死。 | 添加最大重连次数限制 |

| C23 |**CCXTFeed 缺少 openinterest line**| `ccxtfeed.py:463-483` | `_load_bar()` 只设置 OHLCV + datetime，没有设置 openinterest。期货交易策略无法获取持仓量。 | 如果 CCXT 返回 OI 数据则填充，否则设 0 |

| C24 |**多交易所同时使用冲突**| `ccxtstore.py:55` | `CCXTStore` 是 `ParameterizedSingletonMixin`，相同参数返回同一实例。但不同交易所需要不同实例。 | 验证 singleton key 是否包含 exchange_id，确保不同交易所不会冲突 |

| C25 |**WS manager 缺少心跳/ping**| `ccxt/websocket.py` | 没有主动 ping 机制检测僵死连接。只靠数据超时判断。 | 添加 ping/pong 心跳或定期 fetch_time() 健康检查 |

- --

## 二、CTP 模块优化清单

### 🔴 P0 — 严重 Bug / 数据安全

| # | 问题 | 文件 | 说明 | 建议 |

|---|------|------|------|------|

| T1 |**CTPBroker.next() 每次调 get_balance()**| `ctpbroker.py:556` | `next()` 每个 tick/bar 都调用 `self.o.get_balance()`，即使有 2 秒 rate limit，高频策略仍会产生大量无用查询。 | 降低频率：只在有成交或每 N 秒查询一次 |

| T2 |**平仓量超过持仓时逻辑错误**| `ctpbroker.py:266-274` | `_determine_close_offset` 当 today_vol < volume 且 yd_vol < volume 时，如果 today_vol > 0 返回 CloseToday，但实际需要拆单（today+yesterday）。 | 实现拆单逻辑：先平今 today_vol 手，再平昨 (volume - today_vol) 手 |

| T3 |**Stop 订单本地触发无滑点控制**| `ctpbroker.py:489-552` | `_check_stop_triggers()` 用 `close[0]` 判断触发，然后以市价单发出。但实际成交价可能与触发价差距很大。 | 添加最大滑点参数；Stop 触发后用限价单（stop_price ± slippage）而非市价单 |

| T4 |**Trade 事件可能重复处理**| `ctpbroker.py:388-487` | `_process_trade_events()` 没有 trade_id 去重。CTP 偶尔会重发 OnRtnTrade。 | 用 set 记录已处理的 trade_id |

### 🟡 P1 — 功能缺陷 / 健壮性

| # | 问题 | 文件 | 说明 | 建议 |

|---|------|------|------|------|

| T5 |**CTPStore 登录失败无重试**| `ctpstore.py:676-698` | 登录等待 15 秒超时后就放弃，但 CTP 网络抖动常见。 | 添加登录重试机制（注意 CTP error 75 限制，间隔不少于 30 秒） |

| T6 |**OnFrontDisconnected 不通知 broker**| `ctpstore.py:150-157` | 断线后只打日志，不通知 broker/strategy。策略不知道已断线，继续发单会失败。 | 添加 disconnect 回调通知链，让 broker 暂停发单 |

| T7 |**avg_price 计算错误** | `ctpstore.py:318` | `OpenCost / max(Position, 1)` — OpenCost 是总开仓成本（含合约乘数），直接除以手数不一定是正确的平均价格。 | 使用 `PositionCost / (Position * 合约乘数)` 或 `OpenPrice` 字段 |

| T8 | **akshare 回补数据精度问题**| `ctpdata.py:102-169` | 使用 `futures_zh_minute_sina` 回补，但 sina 数据源精度有限（延迟高、偶有缺失）。且硬编码列名映射。 | 支持多数据源回补：优先 tqsdk/vnpy 本地数据，fallback 到 akshare |

| T9 |**tick 聚合的增量成交量可能不准**| `ctpdata.py:238-242` | `delta_vol = tick_volume - self._last_tick_volume`，但换交易日或合约切换时 tick_volume 会重置为 0，产生负值（虽有保护但丢了一个 tick 的真实量）。 | 检测交易日切换，重置 `_last_tick_volume` |

| T10 |**交易时段硬编码**| `ctpdata.py:306-312` | `_TRADING_SESSIONS` 硬编码了固定时段，但不同品种（股指期货、商品期货、夜盘品种）时段不同。 | 从 CTP 合约信息获取交易时段，或按品种分类配置 |

| T11 |**CTPStore singleton 可能导致多策略冲突**| `ctpstore.py:576` | `ParameterizedSingletonMixin` 意味着相同参数返回同一实例。多策略用相同账户但不同配置时可能冲突。 | 明确 singleton key 规则，或提供 non-singleton 选项 |

| T12 |**cancel_order 缺少 exchange_id**| `ctpbroker.py:225-232` | `cancel()` 只传 symbol 和 order_ref，但 CTP 撤单需要 ExchangeID。从 symbol 解析的 exchange_id 可能不准（如果 symbol 不含交易所后缀）。 | 在 Order 上保存完整的 CTP 订单信息（front_id, session_id, exchange_id） |

| T13 |**position detail 跨日不重置**| `ctpbroker.py:132-134` | `_pos_detail` 中的 today/yd 分类在跨日后不重置。隔日后所有 today 应变为 yd。 | 监听交易日切换事件，重置 _pos_detail |

### 🟢 P2 — 性能 / 代码质量

| # | 问题 | 文件 | 说明 | 建议 |

|---|------|------|------|------|

| T14 |**CTP 查询请求无节流**| `ctpstore.py:279-322` | `query_account()` 和 `query_positions()` 没有检查上次查询时间。CTP 对查询有 1 秒限流。 | 添加查询间隔检查（类似 get_balance 的 2 秒间隔） |

| T15 |**tick queue 无上限警告**| `ctpstore.py:556` | tick_queues maxsize=10000，满了就丢弃旧 tick，但没有日志警告。策略不知道丢了数据。 | 添加丢弃计数器和警告日志 |

| T16 |**CTPBroker 缺少 order valid 支持**| `ctpbroker.py:276-354` | `_submit_order()` 忽略了 `valid` 参数（GTC/GTD 有效期）。CTP 支持 GFD 和 IOC。 | 根据 valid 参数设置 CTP 的 TimeCondition |

| T17 |**手续费计算不精确** | `ctpbroker.py:419` | `comm_rate * fill_size` 只支持按手数固定费率。中国期货实际有按成交金额比例和按手数两种模式。 | 支持两种模式：固定费率和比例费率，从合约信息自动判断 |

| T18 | **CTPData 缺少日线以外的回补**| `ctpdata.py:117-126` | 只支持分钟线和日线回补。周线、小时线等不支持。 | 扩展回补支持，或用分钟线自行聚合 |

| T19 |**bar 时间对齐不处理跨夜盘**| `ctpdata.py:314-342` | `_align_bar_time()` 的 `session_ends` 用 `tick_dt.replace()`，跨午夜的夜盘（23:00→02:30）会产生错误的对齐。 | 正确处理跨午夜的时段边界 |

- --

## 三、CCXT 和 CTP 共性问题

| # | 问题 | 说明 | 建议 |

|---|------|------|------|

| G1 |**LiveBrokerBase 未被继承**| `livebroker.py` 定义了抽象基类，但 CCXTBroker 和 CTPBroker 都没有继承它。 | 让两者继承 LiveBrokerBase，统一接口 |

| G2 |**缺少统一的日志框架**| CCXT 用 `print()`，CTP 用 `logging`。实盘交易应有统一的日志级别和格式。 | 统一使用 `logging` 模块，并支持文件输出 |

| G3 |**缺少订单持久化**| 两个 broker 的订单状态只在内存中。程序重启后所有未完成订单信息丢失。 | 实现订单持久化到文件/SQLite，启动时恢复 |

| G4 |**缺少风控模块**| 没有统一的风控检查：最大持仓、最大单笔下单量、每日最大亏损等。 | 添加 RiskManager 组件，在 submit 前检查 |

| G5 |**缺少交易记录导出**| 没有统一的方式导出实盘交易记录为 CSV/JSON。 | 添加 TradeLogger 观察者或分析器 |

| G6 |**缺少模拟盘/沙盒统一接口**| CCXT 有 sandbox 参数，CTP 有 SimNow，但没有统一的"切换到模拟"接口。 | 在 Store 层提供 `sandbox=True` 统一参数 |

| G7 |**缺少多账户支持**| 两个模块都是单账户设计。无法同一策略对接多个账户。 | 在 Store 层支持多账户管理，Broker 通过 account_id 区分 |

- --

## 四、优先级排序建议

### 第一优先（影响正确性）

1.**C1**— CCXTOrder 初始化问题（可能导致订单属性丢失）
2.**C2**— Bracket 模块 NameError
3.**T2**— SHFE/INE 拆单逻辑（平仓失败）
4.**T4**— Trade 事件去重（重复成交通知）
5.**C5**— getvalue 不含持仓市值
6.**C3**— 共享 WS 被误关闭

### 第二优先（影响可靠性）

7.**C13**— get_granularity NameError
8.**T6**— 断线不通知策略
9.**T1**— 过度查询余额
10.**T13**— position detail 跨日不重置
11.**C14**— WS 重连后数据缺口
12.**T3**— Stop 订单无滑点控制

### 第三优先（功能增强）

13.**G2**— 统一日志
14.**G3**— 订单持久化
15.**G4**— 风控模块
16.**C8**— 手续费计入
17.**C7**— 市价单适配
18.**T10**— 交易时段配置化
19.**T17**— 双模式手续费

### 第四优先（代码质量）

20.**C17**— open_orders 用 dict
21.**C19**— 弃用 API 替换
22.**C21**— RateLimiter 优化
23.**G1** — 继承 LiveBrokerBase
