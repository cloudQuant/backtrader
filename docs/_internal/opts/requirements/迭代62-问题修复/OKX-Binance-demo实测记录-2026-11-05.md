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
  provider 改为如实携带逐笔成交量（Binance aggTrade、OKX trades，成交号连续性不足时标记 gap）后正常。
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

## 4. 未覆盖（NOT_RUN / GAP）

- 单向持仓（net）账户、多币种保证金、OKX 两小时后历史订单不可查等场景未在 demo 上验证。
- 成交号连续性：OKX 将 `tradeId == 上一笔 + count` 视为连续，否则按缺口处理（fail closed），导致 Feed 偶发短暂 DELAYED；若 OKX 成交号并非逐笔无缺口，需要用户决定是否改为“连接未中断即连续”。
- 带挂单（未成交委托）的重启恢复未在 demo 上验证（CTP 已在 SimNow 验证）。
