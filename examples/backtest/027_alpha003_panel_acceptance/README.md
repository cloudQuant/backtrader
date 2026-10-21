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
- `factor_values.csv`：`FactorStrategy.get_dataset()` 返回的 time/asset 因子面板。
- `run_summary.json`：计算状态、因子配置、实际 Backtrader/research 模块来源和每格调用次数。

`main()` 只运行合成计算并导出这些文件，不执行验收断言，也不把结果标记为 formal acceptance。摘要中的 `COMPLETED` 只表示计算和导出完成；`acceptance` 明确保持 `NOT_EVALUATED_BY_EXAMPLE_RUNNER`。数据重排、缺格和非法输入的检查由开发者测试覆盖。修改一个资产的价格可能改变其他资产的当期排名；本例展示这个计算定义，不代表投资收益或完整 Alpha101 复现。

如果已有忽略输出目录中保留着旧版的 `acceptance.json`，它只是旧原型产物；当前入口不会创建或更新该文件。

## 范围

这是迭代45的 R0 原生 Indicator/Cerebro 切片，用来展示多 feed 计算和数据采集接口。它不代表迭代45全部能力或任一正式验收项通过。示例旧的本地 prototype 不再是运行依赖；其历史版本保留在 Git 中。本轮没有实现全部 Alpha101 算子、动态资产池、研究评价工作流或策略下单逻辑。
