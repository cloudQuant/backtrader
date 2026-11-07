# 迭代 62 OKX / Binance demo 实测记录（2026-11-05 23:40 起）

记录者：实施者（Claude）。路由：`OKX___SWAP`（BTC-USDT-SWAP，OKX demo trading）与 `BINANCE___SWAP`
（BTCUSDT，Binance USD-M demo，`demo-fapi.binance.com`）。代码为未提交的迭代 62 工作区：
`bt_api_okx`/`bt_api_binance` 新增 direct 写入 provider（polling 回报），bt_api_py 的 `BtApi.make_order/cancel_order`
direct 分支与写入准入。凭据由会话内的有界读取器按名称模式选取，只输出类别布尔值，运行输出脱敏。
证据等级：DEMO（交易所模拟账户的真实接口行为）。

## 1. SDK 直连（62.04，未经 BT）

脚本：会话临时目录 `scratchpad/crypto62/crypto_direct_probe.py`。
`BtApi(exchange_kwargs={route: {..., "environment": "demo"}}, write_admission={route: True})`，无 execution。

两个 demo 账户均为双向持仓（hedge）模式：不带持仓方向时，OKX 返回 51000（posSide 参数错误），Binance 返回 -4061，
均在发送前后被正确投影为“未发送/拒绝”（sent=False），没有静默改写。带 `position_side="long"`、
`position_mode="dual_side"` 后：

| 步骤 | OKX | Binance |
| --- | --- | --- |
| 账户事实（持仓、活动单、资金） | complete=True，空仓，无活动单，资金存在 | 同左（按合约 scope 查询） |
| 远价限价买开 → Accepted | 0.21 s | 0.24 s |
| 按原身份撤单 → Cancelled | 0.19 s | 0.20 s |
| 可成交限价买开 1 份（OKX 1 张；Binance 0.002 BTC） | 0.30 s FILLED；随后约 2.2 s 收到两笔 TRADE（0.39+0.61 张，含成交号） | 0.31 s FILLED；**未收到 TRADE 事件**（见下） |
| 开仓后账户事实 | long 1 张 | long 0.002 |
| 平多（卖出 close，position_side long） | 0.31 s FILLED，随后收到 TRADE | 0.29 s FILLED，无 TRADE |
| 结束 | 空仓，无活动单 | 空仓，无活动单 |

另：调试 OKX 参数错误时直接经 feed 下过 1 笔远价单（clOrdId `i62dbg66ea63`），随即按 ordId 撤销并核实账户无活动单。

## 2. 发现的问题与处理

- Binance provider 在订单首次轮询即为 FILLED 时没有补发成交（TRADE）事件；BT direct 只按成交事件记账，
  因此 Binance 的 BT 级运行在修复前不可用。已交 provider 修复（附回归测试）。
- OKX/Binance 行情资格需要场所时钟核对：两家没有 CTP 登录时间，SDK 新增基于 REST 服务器时间（epoch ms，
  往返时间的一半计入误差）的核对 `ClockVerifier.check_venue_epoch`，provider 提供 `server_time_observation()`。
- BT direct 侧为非 CTP 路由补齐：按合约元数据的数量单位（OKX 合约张数 `contracts`）、按策略合约 scope 读取账户事实、
  按场所订单号关联成交、单向持仓 `net` 映射到多/空腿；CTP 的 `exchange_id` 只用于 CTP 路由。

## 3. 补充：行情、成交事件与 BT 级运行（2026-11-06 00:12–00:28）

修复后再测（provider 提交 OKX `123926d`、Binance `f9bfe34`，SDK `81a2fa83`）：

- Binance 成交事件：开仓与平仓在 FILLED 之后立即收到 TRADE（成交号 554648119、554648218）。
- SDK 行情流 tick 通道（两家新增）：OKX 20 s 内 108 笔、Binance 87 笔；SDK 时钟资格 VERIFIED/FRESH，首笔为 gap，
  其余可交易；场所服务器时间核对一致（差约 110–120 ms，容差约 2.2 s）。
- 首次接入 BT 时所有 tick 被 Feed 判为数据缺陷（无成交量语义 `VOLUME_SEMANTICS_UNKNOWN`/`DELTA_VOLUME_INVALID`），
  provider 改为如实携带逐笔成交量（Binance aggTrade、OKX trades，~~成交号连续性不足时标记 gap~~（2026-11-06 23:10 更新：OKX/Binance 成交号跳号不再标记 gap，见 §4））后正常。
  OKX demo 报价最小变动为 0.01（如 76214.83），BT 合约元数据按此配置。
- BT 级（`BtApiStore` direct 模式、`BtApiBroker` dual_side、5 秒 bar；脚本 `scratchpad/crypto62/bt_crypto_direct.py`）：

| 步骤 | OKX BTC-USDT-SWAP | Binance BTCUSDT |
| --- | --- | --- |
| 首次初始化（全账户空仓） | 通过 | 通过 |
| Feed LIVE、bar 生成 | 是（成交号缺口时短暂 DELAYED 后恢复） | 同左 |
| 远价限价买开 → Accepted → 撤单 → Canceled | 是 | 是 |
| 可成交限价买开 → Completed | 1 张 @ 76783.14 | 0.002 @ 76854.5 |
| 卖出平多 → Completed | 1 张 @ 76708.0 | 0.002 @ 76806.7 |
| 停止后账户 / 未决标记 | 空仓、无挂单；标记全部 TERMINAL（2 成交、1 撤单、1 撤单标记） | 同左 |

- 带持仓重启（00:30–00:33）：首次运行开多后停止并保留持仓，再次启动对账、平仓。Binance 首次尝试发现缺陷：
  快照按整数存数量，0.002 BTC 被舍入为 0，重启时对账（正确地）报告差异并禁止该合约写入；修复为保留场所的小数数量后，
  Binance（0.002）与 OKX（1 张）均为：重启对账无差异 → 平多成交 → 账户空仓、无挂单。差异出现时的账户由 SDK 直接平仓清理。

- 带挂单崩溃重启（2026-11-06 03:46–03:48，脚本模式 `far-crash` / `far-restore`）：首次初始化后远价限价买开，
  Accepted 后进程立即退出（不停止、不撤单），场所剩 1 笔挂单；重启后对账报告 `restored_orders=1`，该挂单在 Feed 第一根 bar
  后交给策略（`restored=True`），策略撤单 → Canceled，停止 STOPPED，场所无挂单、空仓。两家结果相同。
  OKX 一轮发现恢复订单缺少 `position_side`（dual_side 下为 None）：成交投影按方向与开平推导持仓腿，不受影响，
  但 hedge 模式策略看不到所属腿；已改为按同一规则推导并写入订单 info，Binance 一轮验证为 `long`。

## 4. 未覆盖（NOT_RUN / GAP）

- 单向持仓（net）账户、多币种保证金、OKX 两小时后历史订单不可查等场景未在 demo 上验证。
- ~~成交号连续性：OKX 将 `tradeId == 上一笔 + count` 视为连续，否则按缺口处理（fail closed），导致 Feed 偶发短暂 DELAYED；若 OKX 成交号并非逐笔无缺口，需要用户决定是否改为“连接未中断即连续”。~~（2026-11-06 23:10 更新：该开放项已由用户 2026-11-06 的决定关闭。OKX 在连接未中断时成交号跳号不再使 tick 成为连续性缺口，只影响该笔成交量（`volume_complete=False`）；首笔、丢帧或畸形帧与恢复路径仍为缺口。Binance 与 OKX 一致（D62-38 第 3 点）。提交：bt_api_okx `6bd5958`、bt_api_binance `2034334`、backtrader `74c48c7e3`。证据：UNIT/FAKE（假 WSS 帧）；成交号规则改动后的 demo 复跑 NOT_RUN。本记录 §1～§3 的 demo 实测是改动前的冻结证据，不改。）

## 5. 2026-11-08 复跑（最终代码，用户 2026-11-08 决定）

证据等级：DEMO。凭据仍由有界读取器按名称模式选取，只输出类别布尔值（5 类均存在且为 demo 标签），运行输出脱敏。BT 级脚本同 §3
（`bt_crypto_direct.py`，场景 full、open-hold + close-held、far-crash + far-restore），新增 `--cross`（可成交限价的偏离比例）与 `--size`。

**第一轮（00:49–00:55，代码为 2026-11-07 推送后的 dev）**

- Binance：全部场景 PASS（远价挂单→撤单、0.002 开平、带持仓重启后平仓、崩溃后恢复挂单并撤单），停止均为 STOPPED。
- OKX：远价挂单、崩溃恢复 PASS；两张可成交限价单（bar 收盘价 × 1.003）在 BT 中一直停在 Submitted，未决标记 DISPATCHED，停止时报
  `STOPPED_WITH_WORKING_ORDERS`。OKX 当日完整委托列表中没有这两个客户端订单号，即订单从未在场所建立。只用 SDK 的探针（00:56，价格 ask × 1.002 + 1 跳）
  全部正常（成交与成交回报均关联），排除了 SDK 关联与去重改动。
- 缺陷 26（编号接 SimNow 记录 §4 的缺陷 25）：OKX 在价格限制外拒单（demo 的价格带约为最新价 ±0.34%，公共接口 `price-limit`；拒单代码推断为 51006，
  当时未被记录），HTTP 200、`code` 为 "1"，SDK 的 feed 将其作为错误抛出；但 51006 不在“确定拒单”的代码表里，provider 判为结果不明，按 `clOrdId`
  轮询到运行结束，BT 因此一直以为订单在途。撤单路径对 51400 有同样问题。修复：bt_api_okx `081be5b`（51006 与撤单拒绝 51400/51401/51402 列为确定拒单；
  对抛出的错误和 200 响应体中被拒的单笔订单行用同一规则判定；51410、51412 仍为结果不明），bt_api_py gitlink `d9ad56bd`。49 个测试，21 个在旧代码上失败，
  13 处变异全部检出。SDK 执行日志的恢复读取同一代码表，所以过去以 51006 结束为“结果不明”的记录，在启动时会被判为拒单（正确）。Binance 的拒单是 HTTP 4xx 加负数代码，没有同样问题。
- 价格带内复跑（01:03，× 1.001）：OKX 可成交单成交，但成交被拆成多笔小数张（0.13、0.01 ……），最后一笔后订单仍为 Partial，没有变为 Completed，
  停止时同样报未解决的在途订单，持仓留在场所，下一次首次初始化因账户非空仓而拒绝启动。
- 缺陷 27：BT direct 用二进制浮点逐笔扣减剩余数量，小数成交累加后留下约 1e-16 的余量，订单永远不算完成；全部平仓后还会留下约 1e-16 的反向幽灵持仓腿。
  CTP 为整数手不受影响，Binance 本次成交未拆分。修复：backtrader `37a1e2bf9`（direct 模式中的成交与持仓数量按十进制累加，与订单数量相差在 1e-9（大于 1 时为相对值）
  以内视为完成；今昨拆分、净持仓、可平视图、重启基数、恢复订单数量与成交缺口报告同样改为精确值；backtrader 核心 `Order`/`BackBroker`/`Position` 不变，回测不受影响）。
  20 个测试，19 个在旧代码上失败，20 处变异全部检出。

**修复后复跑（01:20–01:39，bt_api_okx `081be5b`、bt_api_py gitlink `d9ad56bd`、backtrader `37a1e2bf9`）**

- 价格带外的 OKX 订单（+1%，77226.1 对买入上限 76552.95）立即 Rejected（`not_sent:okx_order_rejected`），未决标记 TERMINAL `not_sent`，停止 STOPPED、无在途订单。
- 两家全部场景 PASS，停止均为 STOPPED、无未解决订单、对账无差异，结束时场所空仓无挂单。OKX full 场景中的可成交单（× 1.001，76595.7）再次落在价格带外被拒，
  并如实报告为 Rejected；open-hold 与 close-held 成交并平仓。
- 小数成交：OKX 12 张平仓单拆成 7 笔成交（7.77、0.39、0.01、0.40、1.30、0.86、1.27），订单 Completed、成交量恰为 −12.0，持仓清零，停止 STOPPED。
- 回归（合并后，2026-11-08 01:39–01:48）：BT fast 5661 passed、18 skipped，只有基线既有的 3 个失败，无新增；SDK 全量失败与错误 id 与上一次相同（320 个，无新增）；bt_api_okx 486 passed、bt_api_binance 560 passed（均不含网络测试）；22 个示例 `--dry-run` 22/22。

**仍开放**

- 拒单的场所代码（如 51006）没有写入 BT 的订单信息与未决标记（只有 `okx_order_rejected`），排查时只能推断；可诊断性缺口，记录待处理。
- 验收工具的可成交价偏离（× 1.003）可能超出 OKX demo 的价格带；工具已改为可配置（`--cross`），交付示例不受影响。
