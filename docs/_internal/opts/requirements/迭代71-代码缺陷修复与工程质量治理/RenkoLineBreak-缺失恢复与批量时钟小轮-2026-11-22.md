# RenkoLineBreak：缺失恢复与批量时钟小轮

日期：2026-11-22。状态：**限定源码与回测样本已完成本轮检查；不代表 B11-03 全项或所有运行场景完成。**

本轮在 Backtrader 现有 dev 提交 `0927242f741a60a54087360bbc7a91a1dd65ca50`，父提交为 `62ce2865026687dff9bafc2b5b5fdcef6c9309e5`。范围只有 `backtrader/indicators/contrib/renko_line_break.py` 与新增 `tests/unit/indicators/test_iter71_renko_line_break_missing.py`；未更改交易模块。提交的 Git blob SHA-256 分别为 `78c8b077c85e005f8d6c98afa61ce2c4555a796bd3d035a3fff047583c347dc8`、`9613958b924dbdf5cc6c623330b87315694509e9cd94e05b3e25ee67fc38741e`。独立复审所固定的源码 checkout 字节 SHA-256 为 `7d9f5c6c745fbbd2d8f51acc8edd4488b0b3eefee95b9408b0f2dd6f4c64974a`；与 Git blob 的换行表示不同，不能把两种原始字节哈希混同。

## 复现与修改

公开基线 `889a8ca64276ab4ea3b4b8ebac4a5fcda491d6e1` 的真实 Cerebro 中，首个 close 为 NaN 时旧实现将其保存为种子，下一根有效价格可被误判成下降盒；已有种子但尚未形成趋势时遇到 NaN，也会错误地产生负盒数。已有趋势时缺失价格则会保留有限盒数，可能被消费方当作当前趋势。嵌套输入指标的批量执行另有真实时钟缺口：旧 once_via_next 可持续读取源索引 -1，既造成逐值偏差，也可能漏掉严格因子上下文中的原始 Inf。

本轮让缺失 close 对应三条公开线均输出 NaN，状态不随该缺失值推进，后续有效柱从上一次有效状态继续；同一 replay 柱修订从柱前状态计算。原生 RenkoLineBreak 在批量模式按源的绝对索引递推；子类或覆写 next 的情况沿用 once_via_next，不能把本轮原生路径证据推广到自定义回调。单源 replay 的有效输入可能因此不同于旧有同柱重复推进结果；正常历史样本的有限数据对照见下文。

## 检查与独立证据

共享 checkout 的 Python 3.11 和 3.14 各完成新增专项 **25 项通过**，各有一条既有 Quandl 弃用警告；Ruff 与 diff 检查通过。专项包括首次和后续缺失、有效值恢复、逐根与批量模式、exactbars=1、异步第二 Feed、嵌套源、子类和实例 next 覆写，以及真实 FactorStrategy 中人工写入源线的正负 Inf 严格失败。独立复审将相同测试放回公开基线得到 21 失败、4 通过，候选为 25 通过；这些是受控源和本地回测证据。

独立复审以 SMA(3) 为嵌套输入，逐根与批量各检查 13 点，包括缺失窗口和恢复；另一组真实 FactorStrategy 注入普通 NaN，两模式各 10 点不误抛，缺失柱为 NaN，随后恢复。正负 Inf 严格用例通过人工向 Raw 指标的底层源线注入并由 boxes 消费，不能表述为普通 Feed 的 Inf 端到端验证。

单源 replay 使用 21 个一分钟合成 close 聚合到三分钟，exactbars=0/1 与 runonce=False/True 四组各 21 次回调，共 84 次；每次依据当时可见柱的 close 独立重算，包含同柱 NaN 修订与恢复。replay 的 runonce=True 实际按逐根执行；该样本不证明异步多源 replay 或上游表达式的更新正确。

历史对照使用原 RenkoLineBreakVsRsiStrategy 与公开 XAUUSD_M15.csv（SHA-256 `d364dea806a6ef634277184d1edc71fb90216fadacf673f70ea9706c55a1f51f`）。公开基线与候选分别以逐根及批量运行，四组各记录策略 next 期间 6125 条指标行、414 条订单通知和 138 条交易通知，期末 cash/value 均为 1002111.999999999；所测规范序列 SHA-256 均为 `a11759f6916beca3934cb9950739d5efef9927fd3c27b24a795b97cfea6505d2`。指标字段为数据长度及 upper/lower/boxes；订单字段为数据长度、状态、买卖方向、成交数量、价格、价值和佣金；交易字段为数据长度、状态、数量、价格、pnl 和 pnlcomm。未比较其他通知字段或策略 next 前的指标行。

独立公开探针为 `D:/temp/i71_renko_independent_889a/probe.py`，SHA-256 `3a03a2bd4e17ee188e9d8270c107da066bbc6d7e1e82d3b4eb2f943fc974d1b6`；临时路径不保证长期保存。

## 未覆盖边界

普通数据线读取原始 Inf 的现有投影仍可能得到零，本轮未改变该框架合同。缺失后的下一根有效柱仍可能满足原策略趋势与 RSI 条件，既有挂起订单也可能执行；本轮不证明缺失期间完全不交易。复杂多源 replay、自定义子类的批量时钟与上游表达式修订仍需分别验证；源码和回测样本不构成实盘或账户能力验收。
