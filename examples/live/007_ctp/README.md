# 007 — CTP SimNow 实盘示例（direct 直连）

原 `examples/unified/007_ctp` 的实盘部分，回测部分在
[`examples/backtest/007_ctp`](../../backtest/007_ctp/README.md)。每个策略一个文件夹，里面有
`README.md`、`config.yaml`、`<name>_strategy.py` 和 `run.py`，不依赖其他目录的脚本，可以单独复制使用。
文件夹名以 `_direct` 结尾的是直连版本（迭代 62）；`_gateway` 版本经 Gateway 服务运行，单独提供。

| 文件夹 | 策略 | 合约 |
| --- | --- | --- |
| `sa_dual_ma_direct/` | `DualMAStrategy`：纯碱 1 分钟双均线，只在 `LIVE` 后交易 | SA701（郑商所） |
| `bbroker_5s_single_symbol_direct/` | `SingleSymbolMaStrategy`：tick 输入，策略内聚合 5 秒 bar | rb2701 |
| `bbroker_5s_pair_arbitrage_direct/` | `PairSpreadStrategy`：tick 输入，5 秒价差 | rb2701 / hc2701 |
| `mixbroker_5s_single_symbol_direct/` | `SingleSymbolMaStrategy`：5 秒 bar 输入 | rb2701 |
| `mixbroker_5s_pair_arbitrage_direct/` | `PairSpreadStrategy`：5 秒 bar 输入 | rb2701 / hc2701 |
| `tickbroker_5s_single_symbol_direct/` | `SingleSymbolMaStrategy` | rb2701 |
| `tickbroker_5s_pair_arbitrage_direct/` | `PairSpreadStrategy` | rb2701 / hc2701 |
| `mixbroker_single_symbol_direct/` | `SingleSymbolMixStrategy` | rb2701 |
| `mixbroker_pair_arbitrage_direct/` | `PairMixArbitrageStrategy` | rb2701 / hc2701 |
| `tickbroker_single_symbol_direct/` | `SingleSymbolTickStrategy` | rb2701 |
| `tickbroker_pair_arbitrage_direct/` | `PairTickArbitrageStrategy` | rb2701 / hc2701 |

除 `sa_dual_ma_direct/` 外，各文件夹的 `<name>_strategy.py` 与回测侧同名文件夹中的文件内容相同，修改时请两边同步。
实盘行为由 `config.yaml` 打开：`order_exectype: limit` 改用带价格的可成交限价单，`close_offset: auto`
按可平事实分别提交平今/平昨；回测保持原来的市价单和固定 offset。

## 运行

```bash
# 离线校验配置
python examples/live/007_ctp/sa_dual_ma_direct/run.py --dry-run
# 第一次运行：显式初始化（账户必须完全空仓且没有挂单）
python examples/live/007_ctp/sa_dual_ma_direct/run.py --first-init --env-file /path/to/.env
# 以后的每次运行
python examples/live/007_ctp/sa_dual_ma_direct/run.py --env-file /path/to/.env --run-seconds 600
```

凭据从环境变量 `SIMNOW_USER_ID` / `SIMNOW_PASSWORD`（或小写同名）读取，也可以放在 `--env-file` 指定的文件中；
程序不会打印它们。`config.yaml` 的 `ctp.env_profile` 默认是 SimNow 标准环境，只在交易时段可用；7x24 环境只适合检查连接，
不作为交易验证。真实账户请改用券商前置和 `instrument_environment: production`，代码路径与 SimNow 相同。

## 直连是怎么组成的

`run.py` 只创建 `BtApiStore(provider="ctp", exchange_kwargs=..., write_admission={"CTP___FUTURE": True})`，
没有配置可选的 execution 组件。这时 `store.getbroker()` 返回的 `BtApiBroker` 走直连路径：

- 下单与撤单经 bt_api_py 的 `BtApi.make_order` / `cancel_order`。SDK 先做写入准入，provider 预留 CTP 原生编号，
  本目录 `state/pending.json` 持久写入未决标记之后才真正报单；撤单用原订单的 FrontID/SessionID/OrderRef。
- 回报（委托、成交、报单错误、撤单错误）按原生身份对应到 BT 订单，成交按场所成交号去重。
- 资金每 60 秒刷新一次（D62-06a），持仓每 5 分钟与账户核对一次（D62-06b）；核对不一致时停止该合约的新单并记录。

## 状态目录与对账

**本示例的对账是直连方式的本地对账，只适用于“一个账户上，一个策略实例独占它所交易的合约”的情况。**
同一账户的这些合约如果还有其他策略或人工交易，本地记录和账户持仓必然对不上，程序会拒绝相关下单；
这时需要先把本地持仓和账户持仓对齐（处理掉他人的持仓/挂单，或者用新的策略目录重新初始化）才能启动。
不在本策略中的合约只报告，不影响启动（D62-17）。

每个策略文件夹就是一个策略实例：

| 路径 | 内容 |
| --- | --- |
| `state/identity.json` | 策略 UUID、主机与目录、账户哈希（不含账号） |
| `state/sequence.json` | 本策略的订单局部序号和 `Order.ref` 高水位（回测与实盘共用，D62-04b） |
| `state/pending.json` | 派发前持久化的未决标记 |
| `state/waiting_orders.json` | 休市期间创建、等待下一交易时段的订单 |
| `state/audit.log` | 身份重绑、人工核验的审计记录 |
| `logs/current_position.yaml` | 对账基线：Broker 在启动、每笔成交和停止时原子写入（多空、今昨仓、当日已应用成交） |
| `logs/<配置名>/<时间戳>/` | TradeLogger 每次运行的可读日志（订单、成交、持仓、资金） |

启动顺序：登录并核验账户与交易日 → 完整查询持仓、委托、当日成交和资金 → 读取本地未决标记，按原生身份核对：
仍在场所挂着的单恢复为 BT 订单，已终结的单补记缺失的成交，当日查不到的单记为未发送 → 比较
`logs/current_position.yaml` 与账户的多空总量及今昨仓（D62-16/22），不一致的合约禁止新单 → 需要时确认当日结算单（D62-20）
→ 策略创建后在 `start()` 中调用 `self.broker.take_over_restored_orders(self)` 接管恢复的订单 → 目标行情合格后才允许下单。

**首次初始化（D62-13）**：没有 `state/` 时必须带 `--first-init`，并且整个账户必须空仓、没有挂单，否则拒绝启动。
请先由有权限的人员处理账户里已有的持仓和挂单，或者换一个干净的账户。

**无法确认的订单（UNKNOWN）**：发出后结果不明、或跨交易日后无法再查询的未决标记会保持 UNKNOWN，并禁止相关合约的新单；
程序不会自动重发或补单。用只读工具查看并在核实后人工处理：

```bash
python -m backtrader.live_state show examples/live/007_ctp/sa_dual_ma_direct
python -m backtrader.live_state resolve examples/live/007_ctp/sa_dual_ma_direct <marker_id> \
    --conclusion terminal_cancelled --operator <你的名字> --evidence "<查询依据>"
```

只有在场所查询或回报能证明真实终态时才这样处理；“已处理”的声明本身不改变账户事实。

## 启动与查询相关配置（2026-11-06 更新）

下列键写在 `config.yaml` 中。22 个示例（11 个 `_direct`、11 个 `_gateway`）的 `ctp.private_topic_mode` 与
`broker.direct_facts_timeout` 取值相同；`broker.direct_permission_*` 没有写进示例配置，使用 Broker 缺省值，
需要调整时加在 `broker:` 下。依据是源码与迭代 62 计划条目（I62-01a、I62-12a、I62-13）；SimNow 上的运行记录见迭代 62
文档，没有真实账户证据，本节不表示任何验收结论。

| 键 | 示例值 / 缺省 | 作用 |
| --- | --- | --- |
| `ctp.private_topic_mode` | 所有示例 `quick`；`run.py` 缺省也是 `quick` | 交易私有流的续传方式。`restart` 为可选配置，见下 |
| `broker.direct_facts_timeout` | 示例 `60`（秒）；Broker 缺省 `10` | 启动时每个账户事实查询（持仓、活动委托、当日成交、资金）各自的超时 |
| `broker.direct_permission_check` | 缺省 `true` | 是否在启动时读取一次 CTP 交易权限事实 |
| `broker.direct_permission_timeout` | 缺省 `5.0`（秒） | 权限事实中每个查询的超时 |
| `broker.direct_permission_max_duration` | 缺省 `60.0`（秒） | 整次权限事实读取的总时限；到时仍未开始的查询对应的事实记为未知 |
| `contracts.<symbol>.exchange` | 如 `CZCE`、`SHFE` | 同时是 CTP 报单的 `ExchangeID`，直到场所自己报告交易所为止（见下） |
| `feed.event_time_max_age` | 示例 `2.0`（秒）；Feed 缺省 `2.0` | 行情来源时间到本机接收的上限（D62-28/37），只能收紧 SDK 的 `max_latency_seconds`，两者同时生效 |
| `feed.receive_time_max_age` | 示例 `2.0`（秒）；Feed 缺省 `2.0` | 本机收到最新一笔合格 tick 之后、下单之前允许停留的时间（D62-28） |
| `feed.incomplete_volume_bars` | 示例 `lines`；Feed 缺省 `lines` | 只缺成交量核算的 bar 进入数据线（`lines`），或只通过 `notify_bar` 通知（`notify_only`），见下 |
| `contracts.<symbol>.event_time_max_age`、`receive_time_max_age`、`incomplete_volume_bars` | 不写则沿用 `feed:` | 按合约覆盖上面三个键 |
| `direct.market_clock_verification` | 示例 `true` | SNTP 证据与场所时间核对；也可以写成映射调整参数，见下 |
| `broker.direct_trade_match_window` | 缺省 `5.0`（秒） | 成交回报先于委托回报到达时，等待重新匹配的时间，见下 |

**私有流模式（I62-01a）**：`quick` 不重放当日私有回报。`restart` 会在登录时重放整个交易日的私有回报；
SimNow 交易时段内，启动查询要排在这次重放之后，等待 20～90 秒以上（迭代 62 SimNow 实测记录，缺陷 14）。
direct 模式的启动恢复不依赖私有流重放：恢复订单来自活动委托查询，已应用成交来自当日成交查询，持仓来自持仓查询，
三者覆盖整个交易日；登录之后到查询快照之间的回报由实时私有流送达并去重；查询覆盖不到的缺口仍按既有规则保持 UNKNOWN。
`quick` 之外 feed 还接受 `resume`，本目录没有使用也没有验证。

**事实查询超时**：整日的委托与成交会随交易时段增长，SimNow 大约每秒返回 14 行，所以示例把每个启动查询的超时设为 60 秒。
超时的查询不会被当作“没有数据”：启动事实不完整时 Broker 有限次重试，仍不完整则拒绝启动（`startup_account_facts_incomplete`）。

**交易权限事实（I62-13）**：启动时直连 Broker 只读一次 CTP 交易权限事实：投资者是否有效、每个合约的交易状态、
每个交易所的投机交易编码、手续费率与保证金率行。查询约每秒一个，例如两个上期所合约共 8 个（1 个投资者、每个合约 3 个、
每个交易所 1 个）。只有事实完整、属于当前会话和交易日，并且明确为否定时，才在本地拒绝该合约的订单，
拒绝原因形如 `trading_permission_denied:<原因>`；未知的事实既不拒绝订单，也不证明有交易权限，场所仍是最终判定方。
读取结果的摘要在运行结束时输出的 JSON 里，位置是 `reconcile.permissions`（不含账号等账户值）。

**交易所（I62-12a）**：报单不再等待合约目录查询来确定交易所。`contracts.<symbol>.exchange` 先作为 `ExchangeID`
使用，场所通过账户持仓事实报告了该合约的交易所之后，以场所报告的为准。配置错误的交易所由场所拒绝，程序不会据此推断别的东西。
全量合约目录查询不在下单路径内执行，细节见 bt_api_ctp 的 `docs/instrument-reference-queries.md`。

**行情时效阈值（D62-28，2026-11-06 起“按场所、策略及合约配置”）**：每个示例只连一个场所，所以 `feed:` 段是这个场所和
策略的缺省值，`contracts.<symbol>` 下的同名键按合约覆盖它（例如冷门合约放宽 `receive_time_max_age`）。`run.py`
在 `--dry-run` 和启动时逐个合约打印生效值（`Feed <合约>: event_time_max_age=… receive_time_max_age=…
incomplete_volume_bars=…`），数值必须是大于 0 的秒数，否则拒绝启动。`event_time_max_age` 与 SDK 的
`max_latency_seconds` 同时生效，所以实际上限取较小者；放宽它不会放宽 SDK 的判断。阈值不证明时钟可信，
也不替代交易时段检查。

**时钟核验参数（`direct.market_clock_verification`）**：写 `true` 时使用 SDK 缺省值。写成映射时，与 `true` 一样开启核验，
并可调整这些键（模板里有注释示例，缺省值如下）：`max_latency_seconds`（2.0，来源到接收的 SDK 上限）、
`max_error_bound_ms`（500，可接受的 SNTP 误差上界）、`validity_seconds`（900，一次 SNTP 测量的有效期）、
`refresh_interval_seconds`（300，后台刷新间隔）、`timeout_seconds`（2.0，单次查询超时）、`servers`（NTP 服务器列表，
缺省 `time.apple.com`、`cn.pool.ntp.org`、`ntp.aliyun.com`）。前两个由 BtApi 取出，其余交给 SDK 的 `ClockVerifier`；
写入未知键时启动失败（当前为 `TypeError`，不是有限错误码）。缺省仍为 `true`。

**行情状态与下单资格（D62-38，2026-11-06）**：feed 的 LIVE/DELAYED 与下单资格只看价格时效、当前连接没有已知的本地丢消息、
报价有效性和交易时段。订阅、重连或换交易日后的首笔（成交量基线）、成交号跳号、累计量下降、涨跌停时一侧为空的盘口
（另一侧恰好等于该快照的涨跌停价）、锁盘和零深度都不会让 feed 离开 LIVE；提供方报告的 `gap`、更早连接代际的 tick、
无效或交叉的报价仍会使 feed 进入 DELAYED。交易所时间倒退的单笔 tick 被丢弃并计数（`tick_ingest_error_counts()` 中的
`OUT_OF_ORDER_EVENT_TIME`），不降级；连续 3 笔倒退（`event_time_regression_limit`）才按原规则降级。

**成交量不完整的 bar（2026-11-06 决定）**：只因成交量核算不完整（成交号跳号、订阅或重连后的基线、累计量下降、
被丢弃的倒退 tick）而不完整的 bar，缺省（`incomplete_volume_bars: lines`）照常进入策略数据线，不再留空洞；
`notify_only` 恢复以前只走 `notify_bar` 的做法。两种方式下这根 bar 的 `notify_bar` 事件都带 `complete=False`、
`volume_complete=False` 和 `quality_flags`（如 `VOLUME_INCOMPLETE`、`VOLUME_BASELINE`），策略在 `next()` 里可用
`data.line_bar_quality()` 读取当前 bar 的同样信息。依赖成交量的策略应检查这些标记。价格或时间有问题的 bar 仍不进入数据线。

**拒单原因（2026-11-06 决定）**：目标行情不合格时，`order.info["error_code"]` 是 `target_data_not_tradable:<主因>`，
完整原因列表在 `order.info["refusal_reasons"]` 和错误信息里，并按主因节流写一次日志。主因按以下顺序取第一个：
阈值或时钟域无效 → 没有可用的实时 tick → 时钟未经核验 → 接收后停留超时（`RECEIVE_TIME_STALE`）→ 来源到接收超时
（`EVENT_TIME_STALE`、`FRESHNESS_STALE`）→ SDK 判定不可执行（`UPSTREAM_EXECUTION_INELIGIBLE`）。feed 不是 LIVE 时仍是
`target_feed_not_live`，同样带完整列表。

**先到的成交回报（2026-11-06 决定）**：CTP 成交回报靠委托回报里的 `OrderSysID` 关联到本策略订单。成交回报先到时，
Broker 先保留它 `broker.direct_trade_match_window` 秒（缺省 5 秒），每次轮询回报后重新匹配，匹配上就照常计入且只计一次；
到期仍未匹配、缓冲区满（256 笔）或停止时，按以前的规则视为别人的成交，不计入，并在运行结束的 JSON 汇总
`reconcile.unmatched_trade_returns` 中计数（`trade_match_buffer` 有缓冲统计）。停止后不再计入任何保留的成交，
下次启动由当日成交查询对账。

## 订单规则

- **显式 offset（D62-26）**：每笔 CTP 订单都要写 `offset`：`open`，或场所允许的 `close` / `close_today` /
  `close_yesterday`。缺少或与持仓不符会被本地拒绝。上期所/能源中心的平今与平昨分开下单，框架不会自动拆单；
  示例里 `close_offset: auto` 按 `broker.get_closable(data, side)` 的可平今/可平昨分别提交。
- **平仓与反手同时在途（D62-24）**：平仓单和反向开仓单分别跟踪，可以同时在场所挂着；一笔被拒绝不会覆盖另一笔。
  先前已排队的反向开仓可能先于后来重新提交的平仓发出，是否撤销由策略决定。
- **限价与订单类型（D62-33）**：示例显式给出可成交限价；CTP 只支持限价单，市价单、止损单或无法表示的有效期会被明确拒绝，
  不会被悄悄改成别的类型。`valid` 不填或填 DAY 时按当日有效（GFD）。
- **限价取价（2026-11-06 更新）**：除 `sa_dual_ma_*` 外的示例策略，限价以最后价格加减 `slippage_ticks` 个最小变动价位：
  最后价格依次取策略记录的该合约最新 tick 价格、`close[0]`、`close[-1]`，取第一个有限的正数；
  都没有有效价格时这次信号被跳过并写日志（`no valid price for ...`），不发送订单。tick 回调可能发生在 feed 装载下一行时，
  那一行的 `close[0]` 还没写入（读到 0），所以不能只用 `close[0]`。`sa_dual_ma_*` 仍直接用 1 分钟 bar 的 `close[0]`。
- **拒绝后退避（`reject_backoff_seconds`，2026-11-06 更新）**：策略参数（写在 `strategy_params:` 下），缺省 `3.0` 秒，
  `sa_dual_ma_*` 没有这个参数。某合约的订单被拒绝（`Rejected`）后，该合约的新订单在这段时间内不再提交，
  被跳过的信号写日志（`refusal backoff for ...`），避免行情数据暂时不合格时每个 tick 都重复提交。
- **行情资格（D62-15/21）**：目标合约的 feed 还在历史预热或没有进入 `LIVE` 时，订单在本地被拒绝；
  最新报价超过时效上限（来源时间到接收、接收到下单两个上限，缺省各 2 秒，可按合约配置，见上）或时钟未经校验时同样拒绝，
  拒绝原因的主因与完整列表见上文“拒单原因”。
  只检查订单目标合约的行情；参与指标计算的其他合约行情可能较旧，策略需要自己判断。
- **休市待发（D62-30/34/35）**：已完成预热、交易日历可信地确认目标合约正在休市时，`buy/sell/close` 创建本地待发单，
  持久保存在 `state/waiting_orders.json`，到下一个连续交易时段并收到合格行情后按创建顺序发出；集合竞价期间不发。
  待发单不是交易所委托，发出后仍可能被拒绝；目标时段结束仍未发出则过期。跨日后今仓变为昨仓，原来的 `close_today`
  可能被拒绝，策略收到拒绝通知后需要用新的订单显式提交 `close_yesterday`。
- **停止（D62-19）**：正常停止只撤销本策略在场所的挂单并有限等待结果，不自动平仓，不处理别人的订单；
  未发出的待发单保留到下次启动。
- **SIGTERM 走优雅停止（S-23，2026-11-06）**：`cerebro.run()` 运行期间，`run.py` 把 SIGTERM（Windows 上另加 SIGBREAK）
  转成与 `run_timeout_seconds` 到时相同的 `cerebro.runstop()`（`backtrader.live_trading.stop_on_terminate`），
  所以操作系统或进程管理器发出的 SIGTERM 也会走上面的停止流程：撤本策略挂单、等待在途写入
  （`direct_stop_write_timeout`）、写最终快照、释放运行锁，最后照常输出 JSON 汇总，其中 `stop_signal` 记录收到的信号。
  运行开始前收到的 SIGTERM 会在运行一开始就生效；停止过程中再收到 SIGTERM 只重复请求，不会中断停止，
  确需立即结束用 SIGKILL（不撤单、不写快照，下次启动按对账恢复）。运行结束后恢复原来的信号处理；
  Ctrl+C（SIGINT）行为不变。Windows 的 `TerminateProcess`（包括 `os.kill(pid, signal.SIGTERM)`）无法被捕获，
  需要优雅停止时向进程组发送 `CTRL_BREAK_EVENT`。`_gateway` 版本的 `gateway_host.py` 子进程仍由 `run.py`
  结束时停止；如果 SIGTERM 发给整个进程组，它会立即退出（本次未改），之后的撤单仍走 SDK direct。
  证据：UNIT/FAKE（子进程 + 假 Feed/Broker），没有在 SimNow 上发送过 SIGTERM。

## 证据说明

这些示例在 SimNow 上运行的记录见迭代 62 的验收文档；没有实际运行或没有触发交易的示例不能当作已验证。
SimNow 的结果只说明模拟账户上的行为；真实账户使用同一套准入代码路径，但本迭代不提供真实账户证据。

## Gateway 版本（`_gateway`，迭代 62.08）

每个 `_direct` 文件夹都有一个同名的 `_gateway` 文件夹（共 11 个），里面是相同的策略文件、`config.yaml`、
BT 入口 `run.py` 和 Gateway 进程 `gateway_host.py`，同样自包含。

**当前可运行的组合**：行情来自 Gateway CTP MarketHub，下单走 SDK 直连写入准入（`gateway.orders: direct`，默认）。
`run.py` 先以子进程启动本目录的 `gateway_host.py`，经进程间管道取得本次运行生成的 CURVE 连接，再运行 Cerebro。
**订单经 Gateway 托管执行运行时（`gateway.orders: managed`）目前不可用**：`run.py` 在读取凭据前输出
`BLOCKED`（`managed_gateway_execution_unavailable`）并以退出码 2 结束。

```bash
python examples/live/007_ctp/sa_dual_ma_gateway/run.py --dry-run
python examples/live/007_ctp/sa_dual_ma_gateway/gateway_host.py --env-file /path/to/.env --check-seconds 60
python examples/live/007_ctp/sa_dual_ma_gateway/run.py --first-init --env-file /path/to/.env
python examples/live/007_ctp/sa_dual_ma_gateway/run.py --env-file /path/to/.env --run-seconds 600
python examples/live/007_ctp/sa_dual_ma_gateway/gateway_host.py --env-file /path/to/.env --managed-boot-check
```

### 组成

| 进程 | 组件与配置 |
| --- | --- |
| Gateway（`gateway_host.py`） | SDK `ctp_gateway_composition.build_ctp_gateway_market_host`：Gateway 组件角色 `market_hub`、端口 `service.market_source`，SimNow 档案取 `gateway.ctp_profile`；订阅频道 `tick`、合约键环境 `demo`，载荷为中立的 `sdk.market.tick`；行情凭据只在此进程读取 |
| BT 策略（`run.py`） | SDK `create_gateway_market_runtime` 建立 CURVE 客户端；`BtApiStore(provider="ctp", exchange_kwargs=..., write_admission={"CTP___FUTURE": True}, market_runtime_factory=...)`：SDK facade 的行情订阅全部由 Gateway 提供，不再打开进程内 CTP 行情会话；`store.getbroker(strategy_dir=...)` 走直连 Broker（本目录 `state/`、`logs/current_position.yaml`） |
| 托管执行（`--managed-boot-check`） | SDK `ctp_gateway_execution.build_ctp_gateway_execution`：托管 CTP 运行时以 bt_api_py 写入准入代替 SimNow 审批白名单（登录、结算单回读/确认、按合约 arm），只做启动核验，不下单 |

### 缺口（托管下单）

- **BT 启动证明**：非直连的 SDK Store 的 `get_reconcile_snapshot()` 恒为不完整，托管路径的 Broker 无法证明首次空仓，任何真实 Store 都不能启动托管会话。
- **CTP OrderRef 切换依据**：托管运行时第一次预留 OrderRef 需要 `CtpOrderRefSeedProof`，目前没有生产签发方（测试中只有合成种子）。
- **托管撤单恢复**：运行时的撤单恢复绑定仍依赖 SimNow 凭据绑定，SDK 写入准入下无法配置。
- **单合约**：托管运行时一个账户只服务一个合约，配对策略（`*_pair_*`）无法经托管路径下单。
- **启动恢复依据**：带持仓或挂单重启时，没有能证明持仓安全、接管挂单的已验证依据。

### 与直连版本的区别

- 行情：Gateway 进程独占 CTP 行情会话，策略进程通过 CURVE 订阅；tick 保留来源时间和 Gateway 接收时间，
  本进程按直连同样的 SDK 规则判定时钟资格，无法核验的 tick 不作为下单依据。
- 凭据：`run.py`（直连交易会话）和 Gateway 子进程（行情会话）各自读取，都不打印。
- 状态：下单仍是直连，所以对账与恢复规则同直连，但状态属于 `_gateway` 文件夹自己；不要与 `_direct` 文件夹同时交易同一账户的同一合约。
- 证据：Gateway 路径只有本地模拟（INTEGRATION_SIM）结果，尚无 SimNow 运行记录。
