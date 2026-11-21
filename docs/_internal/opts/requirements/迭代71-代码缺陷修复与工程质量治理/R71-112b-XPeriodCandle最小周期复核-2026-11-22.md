# R71-112b XPeriodCandleColor 最小周期小轮复核（2026-11-22）

状态：限定最小周期修复已在 Backtrader `dev` 提交，独立复审为 **GO_NARROW_MINPERIOD**；不代表 R71-112b 或迭代 71 整体验收。提交为 `4433b1535dcfb1ec4afb0a41f64ac2ae7a63267b`，实际父提交为 `f5c6f0bc5c1fb3e9d813f51f68008a2ef910e7ae`。独立对照使用公开基线 `535eaa80e9aa5b4a8002855f4f3b61da8e585e28`；基线与父提交的相关指标源码及两份历史策略文件相同。

## 修复范围

对于 `ma_length` 和 `cperiod` 均为精确内置整数的情况，`XPeriodCandleColor` 从四条平滑子指标的最大最小周期累计完整 candle 窗口，而不是直接将两个本地参数相加。普通数据源、`ma_length=3`、`cperiod=5` 时，第一根完整结果从第 8 根提前到第 7 根；上游 OHLC 四线已有各 3 根预热时，应从第 9 根就绪。非精确内置整数参数保留旧的参数相加路径，不声称其最小周期均已修正。

本轮修改 `backtrader/indicators/contrib/shared_strategy_indicators.py`，新增 `tests/unit/indicators/test_iter71_xperiod_minperiod.py`，并仅更新两个真实使用该指标的历史策略中的 `bar_num` 断言。提交后的源码 Git blob SHA-256 为 `38860d2c0871e8b1d1502be341f6c3d806316495bc01f8bc4fbc07f7aa798c91`，新单测 blob SHA-256 为 `5eb7c1096ab545c583c778929456100cb3c84eab9fe119d79695e39458cd5bbe`。当前 Windows checkout 对应原始 SHA-256 为 `13ed195bb91a227e91f46023d50fb72e54b82869f70eaa1dd80dc10cd0302099` 和 `46fe9b6f2145191a58f2600c128b8fcf8d9b7155b3f30c58c0894d78b64ce675`；CRLF 规范化为 LF 后与 blob 一致。

## 检查与参数边界

公开隔离候选的 30 项专项及两份历史策略测试在 Python 3.11.5 和 Python 3.14.2 下各 **32 passed**，各有一条既有 Quandl 废弃警告。专项覆盖不同正整数周期、非正 `cperiod` 的现有一根 lookback、短历史、下游 SMA 和快慢 Feed；源码及新单测的仓库 Ruff 检查通过。

独立复审在 Python 3.11.5 另运行 **16 项**真实 Cerebro 上下游测试，覆盖上游三期平滑、内部 `ma_length=1`、OHLC 上游周期不等及下游 SMA。逐根模式成熟值与独立公式比较；批量模式仅核最小周期、回调时机和预热期不提前输出伪颜色，不将成熟值当作通过。独立测试 `test_xperiod_r2_independent.py` 的 SHA-256 为 `b00dfcc593ada970ddc1e7336975e569ee1f510c7672024a8eef7f562ce34c25`。

真实 Cerebro 参数对照中，`cperiod=5.5`、字符串 `"5"` 和实现 `__radd__`/`__int__` 的自定义对象，其所测结果、异常及调用顺序与基线一致；仅据这些样例说明兼容。构造后动态增加周期和 `ma_length<=0` 的既有行为未获本轮验收。

补充：`dev` 提交 `2d36fd1c5` 新增上游与下游预热回归，覆盖 `ma_length=1` 和不同 OHLC 来源周期；固定修前版本 4 项失败，修后 4 项通过。批量模式只检查预热边界，成熟值的既有问题仍开放。

## 两份历史策略

公开 `tests/datas/XAUUSD_M15.csv` 的 SHA-256 为 `d364dea806a6ef634277184d1edc71fb90216fadacf673f70ea9706c55a1f51f`。基线和候选分别以 `runonce`、`runnext` 比较，所得计数、权益及所记事件如下：

| 策略 | `bar_num` 基线 → 候选 | 订单 / 交易通知数 | 最终资产 |
| --- | ---: | ---: | ---: |
| `0002_0343_exp_xperiodcandle_x2` | 1360 → 1383 | 498 / 166 | 998519.4 |
| `0003_0344_exp_xperiodcandle` | 6016 → 6032 | 276 / 92 | 998414.6999999993 |

提前就绪使策略 `next` 回调计数变化。两策略的基线与候选在两模式下，订单通知中所记数据长度、时间、状态、买卖方向、创建数量及价格、成交数量、价格、金额、佣金和 PnL 一致；交易通知中所记数据长度、时间、开平状态、方向、数量、价格、PnL 和净 PnL 一致。这里只比较列出的字段，不称所有内部对象或其他策略一致。候选的 `runonce` 与 `runnext` 所记结果也一致。

## 开放事项

- 输入为上游 Indicator 时，既有 `once_via_next` 游标可停在 `-1`：即使成熟期的源数组和子 SMA 数组已有效，批量输出的 `xopen` 仍为 NaN、颜色可为 `2`。本轮修复累计的最小周期，未修复该批量数值路径，也不宣称所有数据源的两模式数值一致。
- 现有颜色判断对缺失值可能产生有限颜色；缺失数据传播、上游聚合和恢复语义未在本轮解决。
- replay 同 bar 修订、完整 strict 数值与异常路径、非普通整数参数的最小周期，以及构造后的周期变更仍待单独验证。公开合成与历史回测不证明实盘或账户能力。
