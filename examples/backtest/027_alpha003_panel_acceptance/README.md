# Alpha101 #3：原生多资产因子切片

本例用仓库公开的 `FactorIndicator` 和 `FactorStrategy` API，在普通 Backtrader `Cerebro` 中计算：

```text
-correlation(rank(open), rank(volume), 10)
```

公式由 [`alpha003_strategy.py`](alpha003_strategy.py) 中的 `Alpha003Indicator` 手写实现。它是一个真实 Backtrader Indicator：声明 `factor` line，通过 `self.datas` 读取全部资产当格的 `open` 和 `volume`，并把每个资产的结果写入 `self.outputs[data].factor[0]`。默认十行窗口需要 H=9 个历史网格跨度。它没有 `build()` 表达式图，也不使用示例本地的手动 panel engine。

`FactorStrategy` 负责把因子绑定到全部 feeds 并采集结果；公式不在 Strategy 的 `next()` 中。因子在每个网格时点分别对有效资产做平均并列秩，再除以该字段当期有效资产数。Pearson 相关使用最近十个**网格行**，不压缩缺失行；窗口不完整、缺少任一排名值或任一序列为常量时，结果为 NaN，并在诊断中记录原因。

## 运行

本例不下载行情，不读取账户或私有配置。仓库内运行使用当前源码；复制目录后使用环境已安装的 Backtrader 与公开 research API。

```powershell
python examples/backtest/027_alpha003_panel_acceptance/run.py
# 或在本目录内：
python run.py --config config.yaml --output-dir output
```

默认 fixture 是 A/B/C 三资产、十个 UTC 日格。前九格尚无完整十行相关窗口；第十格预期如下：

| 资产 | Alpha#3 负相关 | 精确值 |
|---|---:|---:|
| A | 0.739130435 | 17/23 |
| B | 1.000000000 | 1 |
| C | 0.739130435 | 17/23 |

输出目录会包含三份 CSV 和一份运行摘要：

- `input_bars.csv`：原始合成 OHLCV 输入。
- `node_values.csv`：每个网格时点和资产的 open、volume、两类截面秩、相关、因子、原因，以及该格的回调次数。
- `factor_values.csv`：`FactorStrategy.get_dataset().raw_factors` 返回的 time/asset 因子面板。
- `run_summary.json`：计算状态、因子配置、实际 Backtrader/research 模块来源和每格调用次数。

`main()` 只运行合成计算并导出这些文件，不执行验收断言，也不把结果标记为 formal acceptance。摘要中的 `COMPLETED` 只表示计算和导出完成；`acceptance` 明确保持 `NOT_EVALUATED_BY_EXAMPLE_RUNNER`。数据重排、缺格和非法输入的检查由开发者测试覆盖。修改一个资产的价格可能改变其他资产的当期排名；本例展示这个计算定义，不代表投资收益或完整 Alpha101 复现。

如果已有忽略输出目录中保留着旧版的 `acceptance.json`，它只是旧原型产物；当前入口不会创建或更新该文件。

## 使用逐股真实日线 CSV

**2026-10-22 检查点：日线已提交，完整策略回归 1,286 项通过；真实全市场运行已通过第 1/13 段，全年尚未验收。**
新电脑的环境、运行命令、剩余验收和性能问题见 [HANDOFF.md](HANDOFF.md)。

`run_daily.py` 是本目录的真实日线入口，使用生产库
`backtrader.research.alpha101.get_alpha(3)` 返回的 `Alpha003Native`。
上面的 `run.py` 保留三资产合成示例，便于阅读手写 `Indicator` 的算法。

`tests/datas/a_stocks/` 已包含全部 5,471 只股票的逐股日线，可以直接运行下一步。
日线入口也需要 `pyarrow`，用于 Parquet 缓存和输出。
只有需要重新生成数据时，才在仓库根目录将原始分钟 Parquet 按股票和本地交易日期聚合。
聚合脚本同样需要 `pyarrow`；不会一次读取整个分钟文件，也不修改原文件：

```powershell
python scripts/aggregate_stock_minute_parquet.py --input "D:\股票测试\ChinaStock1MinTradeInfo.1min.20250101_20260101.par" --output-dir tests/datas/a_stocks
```

日线保存为 `tests/datas/a_stocks/<symbol>.csv`，每股一份。
聚合使用首条 open、最高 high、最低 low、末条 close、累计 volume 和 amount；
源分钟按 `Asia/Shanghai` 解释，保留开盘时刻的数据，不做复权、前填或自动去重。
各股票实际首末分钟、分钟数和异常数保留在 CSV 中；
`_metadata/manifest.json` 记录来源、文件哈希和质量统计，
`_metadata/observed_calendar.csv` 记录全文件实际观测到的日期及共同时间网格。
这份网格不冒充独立核验过的交易所交易日历。

然后用全部 CSV 运行 Alpha003：

```powershell
python examples/backtest/027_alpha003_panel_acceptance/run_daily.py --data-dir tests/datas/a_stocks --output-dir examples/backtest/027_alpha003_panel_acceptance/output/daily_a_stocks_2025 --chunk-days 20
```

所有股票位于同一个截面；股票池固定为这份文件中出现的全部股票，
缺失日不前填，也不声称它是经过点时核验的可交易股票池。
计算只按日期分段，每段带入前9个观测交易日预热，保持10日相关窗口，
不会通过分股票运行改变截面排名。输出保留最初9日及缺失/退化窗口的 NaN 和原因。
每个日期、股票的结果都与独立截面排名和滚动相关参考核对；
只有全部分段完成且核对通过，最终摘要才报告完成。
本入口导出因子结果，不执行交易或将因子值当作策略收益。

## 范围

`run.py` 是迭代45的 R0 手写 Indicator 教学示例；`run_daily.py` 使用迭代46的生产版 Alpha003，完成逐股日线加载、全截面计算及独立数值核对。两个入口都通过原生 Cerebro 和 FactorStrategy 运行。真实数据结果用于验证 Alpha003 的计算，不代表其余100个因子均经过这份数据验证，也不包含 IC、组合绩效或策略交易验收。
