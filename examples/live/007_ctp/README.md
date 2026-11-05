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

## 订单规则

- **显式 offset（D62-26）**：每笔 CTP 订单都要写 `offset`：`open`，或场所允许的 `close` / `close_today` /
  `close_yesterday`。缺少或与持仓不符会被本地拒绝。上期所/能源中心的平今与平昨分开下单，框架不会自动拆单；
  示例里 `close_offset: auto` 按 `broker.get_closable(data, side)` 的可平今/可平昨分别提交。
- **平仓与反手同时在途（D62-24）**：平仓单和反向开仓单分别跟踪，可以同时在场所挂着；一笔被拒绝不会覆盖另一笔。
  先前已排队的反向开仓可能先于后来重新提交的平仓发出，是否撤销由策略决定。
- **限价与订单类型（D62-33）**：示例显式给出可成交限价；CTP 只支持限价单，市价单、止损单或无法表示的有效期会被明确拒绝，
  不会被悄悄改成别的类型。`valid` 不填或填 DAY 时按当日有效（GFD）。
- **行情资格（D62-15/21）**：目标合约的 feed 还在历史预热或没有进入 `LIVE` 时，订单在本地被拒绝；
  最新报价超过 2 秒（来源时间到接收、接收到下单两个上限）或时钟未经校验时同样拒绝。
  只检查订单目标合约的行情；参与指标计算的其他合约行情可能较旧，策略需要自己判断。
- **休市待发（D62-30/34/35）**：已完成预热、交易日历可信地确认目标合约正在休市时，`buy/sell/close` 创建本地待发单，
  持久保存在 `state/waiting_orders.json`，到下一个连续交易时段并收到合格行情后按创建顺序发出；集合竞价期间不发。
  待发单不是交易所委托，发出后仍可能被拒绝；目标时段结束仍未发出则过期。跨日后今仓变为昨仓，原来的 `close_today`
  可能被拒绝，策略收到拒绝通知后需要用新的订单显式提交 `close_yesterday`。
- **停止（D62-19）**：正常停止只撤销本策略在场所的挂单并有限等待结果，不自动平仓，不处理别人的订单；
  未发出的待发单保留到下次启动。

## 证据说明

这些示例在 SimNow 上运行的记录见迭代 62 的验收文档；没有实际运行或没有触发交易的示例不能当作已验证。
SimNow 的结果只说明模拟账户上的行为；真实账户使用同一套准入代码路径，但本迭代不提供真实账户证据。
