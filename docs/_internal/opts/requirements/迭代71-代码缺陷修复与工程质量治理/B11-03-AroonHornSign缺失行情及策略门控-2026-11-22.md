# B11-03 AroonHornSign 缺失行情与策略门控小轮

日期：2026-11-22。状态：**可见 NaN 缺失传播与原策略门控限定修复已提交，独立复审 GO_NARROW_SOURCE_STRATEGY_VISIBLE_NAN**。本记录不代表 B11-03、迭代 71 整期或用户最终验收。

## 范围与版本

仓库 `D:/source_code/backtrader`，分支 `dev`。本轮提交 `b6bbabeca54793b18583e191b96a77d737a7c7e9`，父提交 `c49e79df44a4825f2a684702379ca7afe4f686c6`，提交范围仅以下三个路径：

- `backtrader/indicators/contrib/aroon_horn_sign_indicator.py`：Aroon 回看窗口的 high 或 low 出现可见 NaN 时，两条箭头输出 NaN，不提交本次趋势状态。发生趋势翻转、确实需要计算 ATR 时，所用 high、low 或前收出现 NaN 也输出双 NaN 并保持原趋势；恢复后按有效窗口继续计算。未使用的字段缺失不保证一律屏蔽。
- `tests/functional/strategies/trend_following/test_0252_0894_aroonhornsign.py`：原策略仍先检查止损、止盈；选定信号柱的双箭头均为 NaN 时，跳过本次历史箭头平仓扫描及方向开仓。仅一条箭头为 NaN 时沿用原有处理。该门控会改变缺失柱的历史扫描行为，是本轮明确的策略行为变化。
- `tests/unit/indicators/test_iter71_aroon_horn_missing.py`：新增独立公式、实际策略缺失信号、历史扫描及多空保护性退出测试。

公开隔离复审基线 `889a8ca64276ab4ea3b4b8ebac4a5fcda491d6e1`；该基线与实际父提交之间，指标源码、原策略和公开历史 CSV 无 Git 差异。冻结候选补丁为 `D:/temp/i71_aroon_889a/aroon_missing_candidate_r3.patch`，SHA-256 `fafefa64ee3dd19597cea4386aca4dd89ddd24163987bd2522f8c71c3ceeee5b`。临时补丁只是复审材料，不是运行时依赖。

## 复现与验证

真实 Cerebro 使用完整 base feed 和独立 signal feed；合成行情的 signal feed 在零基第 12 根令 high 为 NaN，`aroon_period=3`、`atr_period=1`。旧版在仍包含该缺失值的窗口产生第 13 根有限卖出箭头 `100.5` 和第 14 根有限买入箭头 `94.5`，原 0252 策略相应调用卖出、平空和买入；候选在两种运行模式下屏蔽这些伪方向信号。复现脚本 `D:/temp/i71_aroon_889a/find_real_false_order.py` SHA-256 `7d54fe008e2a0ae110905a0619a686c3b2c8510e192e45b5f1c065cd29298c24`。

独立复审另用 seed 2 的合成双 feed 样本：signal high 第 19 根缺失，旧版第 21 根产生有限卖出箭头并发卖单；候选第 19–21 根为双 NaN，第 22 根窗口恢复后产生所测真实卖出信号。独立发现的 seed 0 样本还表明，仅修指标时，原策略可在双 NaN 当根通过历史扫描调用卖出平多；策略门控前该项在 next／once 均失败，门控后均通过。

- 在公开隔离候选，Python 3.11.5 与 3.14.2 各 **23 passed、1 条既有 Quandl 弃用警告**，包括 22 项新增专项和原历史策略 1 项。指标／新测试 Ruff 通过；原策略文件基线和候选各有 59 条既有 Ruff 诊断，不能声称三个文件全部 lint 通过。
- 提交后的共享 checkout，两种 Python 各运行新增专项 **22 passed、1 条既有 Quandl 弃用警告**。这些是相同专项在不同验证位置的结果，不能将测试数相加作为独立案例总数。
- 独立复审对固定 R3 在 Python 3.11 和 3.14 下各验证作者 22 项及独立策略 12 项，均通过；独立检查覆盖 seed 0 历史平仓、`signal_bar=1/2`、单条有效箭头和两种模式；其中单条有效箭头的 4 项通过手工写指标线构造策略输入。独立策略测试 `D:/temp/i71_aroon_independent_889a8ca6/test_aroon_strategy_gate_independent.py` SHA-256 `fc3295747bd97c161a9cf75ccdca763e9ad2d634418004497a45f8ee9a1bb95c`，依赖同目录 `independent_real_strategy.py` SHA-256 `dae408940b9f6b6bae42855480e553e9f6177d3bb94b6bc0631671f513df9381`。新增可提交用例分别验证多头／空头的止损／止盈各两模式：缺失箭头当根的保护性退出仍先执行。策略执行止盈止损本身仍可能在缺失行情期间发单。
- 独立复审在真实 `FactorIndicator`／`FactorStrategy` 中另检查两模式：high 第 19 根缺失时，选用的 bear 因子第 19–21 根为 NaN、第 22 根恢复有限；不覆盖 bull 线或 strict 溢出／Inf。测试 `D:/temp/i71_aroon_independent_889a8ca6/test_aroon_factor_strict.py` SHA-256 `b8591661b8a90e68b172d3cc78f8439987d49e2111020a8b066e37e1ea115c7f`。该结果不构成 strict 全数值域验收。

## 公开历史与 replay

使用公开 `tests/datas/XAUUSD_M15.csv` 和原 0252 策略，基线与候选分别执行 next／once。**每种模式内部**新旧各有 405 个信号线槽、204 条订单通知、68 条交易通知，期末资产均为 `999124.4999999997`；两条线、所记事件及 metrics 的对应模式摘要相同。订单字段包括数据长度、状态、方向、创建数量和价格、成交数量、价格、金额、佣金及 PnL；交易字段包括数据长度、开平状态、方向、数量、价格、PnL 和净 PnL，不代表未记录字段。

上述历史中，两模式之间存在既有差异：next 与 once 的 bear、bull 线各有 17 个槽不同，而所记 272 条订单／交易通知和 metrics 相同。本轮新旧同模式结果相同，不能据此称两模式指标线完全一致。对照脚本 `D:/temp/i71_aroon_889a/history_compare.py` SHA-256 `46e21a626f482bf38471d09e92af1fb0d99d124b06a86b47fa4610fd4332dff1`；next 和 once 对应摘要分别为 `e5972350cf69cf982a0460fd4eb33ccfac8ea0e90d053fccc8d4f207e9195a88`、`c60d1be18daefd0c9bd8b13fca5b8679793400a40ef650f6d8a001bdd10dcb55`。

独立复审在 Python 3.11 的单源有限行情 replay 对照使用 8 个种子、1,272 次可见修订，所记 OHLC 和双箭头旧版与候选逐项一致；脚本 `D:/temp/i71_aroon_independent_889a8ca6/finite_replay_compatibility.py` SHA-256 `aad8ae04f2f27f7c7ac9d898cb94c0cb507378456bd47f64b02c78e46f748e87`，结果 JSON SHA-256 `5289261e816cfca4331f266142cf5bc635cb58402bb8c5fca1efdeb59286678b`；这只是有限数据兼容性证据，不证明 replay 同一 bar 多次修订的状态重算完全正确，也不证明批量 replay。

## 开放边界

- 已知真实历史两模式的指标线槽差异仍 OPEN；本轮不修复通用多 feed 时钟或相关生命周期。
- 复杂多 feed／replay、同 bar 状态回滚、上游聚合可能掩盖 NaN 的情况，以及写入失败和重试的完整状态语义未全面验证。
- Inf、有限数中间溢出、strict 全域和动态参数／数值对象未全面覆盖。所测 `FactorStrategy` 可见 NaN 不等于这些边界已通过。
- 仅双 NaN 的当前信号被策略门控；保护性止盈止损保持优先，其他条件下的历史扫描沿用既有行为。合成和公开历史回测不证明真实账户或生产能力。
