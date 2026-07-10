# 绘图后端能力说明（Plotting Backends）

更新时间：2026-07-10
适用范围：开发版 `backtrader`（`dev`）

## 1. 后端入口（统一入口）

同一个调用点支持三种主流后端：

- `bokeh`（默认）：`cerebro.plot()` -- 交互式 HTML Tabs，需可选依赖 `bokeh`
- `matplotlib`：`cerebro.plot(backend='matplotlib')` -- 传统静态图
- `plotly`：`cerebro.plot(backend='plotly')` -- 交互式 HTML 图

注意：默认后端为 `bokeh`。若未安装 `bokeh`，`cerebro.plot()` 会自动回退到
`matplotlib` 并发出 `RuntimeWarning`。传 `use=`（matplotlib 专属参数）也会自动切到
`matplotlib`，以兼容 `cerebro.plot(use='Agg')` 类脚本。此处入口仅在 `backtrader`
内部创建对应 plotter 适配器，不要求用户手工实例化 `BacktraderBokeh` / `PlotlyPlot`。

## 2. 能力矩阵

| 维度 | matplotlib | plotly | bokeh |
| --- | --- | --- | --- |
| 调用路径 | `cerebro.plot(backend='matplotlib')` | `cerebro.plot(backend='plotly')` | `cerebro.plot()` 默认路径，或 `cerebro.plot(backend='bokeh')` |
| 输出形态 | GUI/图片 | 交互式 HTML 图 | 交互式 HTML Tabs |
| 主要参数 | `use`（matplotlib backend 选择） | `style`、`decimal_places`（通过 `PlotlyScheme`） | `style`、`scheme`、`use_default_tabs`、`filter` |
| `start/end` | 支持 | 支持 | 支持（通过适配器切片） |
| `iplot` | Notebook inline 可选 | 对应 `show()` 语义 | 检测 `ipykernel` 时开启 notebook 渲染 |
| 依赖 | matplotlib（已可选） | plotly | bokeh |
| `figsize`/`width`/`height` | 原生生效 | 文件保存/显示时间接控制 | 保存为 `.html` 时通过浏览器尺寸显示 |

## 3. 参数与输出

- 统一约定：`cerebro.plot()` 会通过 plotter 契约执行 `plotter.plot(...) -> plotter.show() -> plotter.savefig(...)`。
- `cerebro.plot(backend='bokeh', filename='...')` 会在后端内部自动落盘；`iplot=False`
  可避免 notebook/display 以外的即时弹窗。
- `cerebro.plot(backend='plotly', filename='...')` 若需无界面保存，建议使用 `PlotlyPlot` 手工构造：

```python
from backtrader.plot.plot_plotly import PlotlyPlot

plotter = PlotlyPlot(style='candle')
figs = plotter.plot(results[0])
figs[0].write_html('result.html')
```

## 4. 推荐用法（同一策略同一入口）

```python
# 默认（Bokeh）
cerebro.plot()

# plotly
cerebro.plot(backend='plotly')

# bokeh（推荐开启文件输出，避免交互环境差异）
cerebro.plot(backend='bokeh', filename='backtest_bokeh.html', iplot=False, style='candle')
```

## 5. 已知限制（当前实现）

- bokeh 在策略级数据源层面仍使用 `strategy.datas[0]` 渲染主图，当前不支持完整多数据并排显示；
  如需多数据对比请优先使用 matplotlib 或 plotly。
- bokeh 的 `BacktraderBokeh` 与 `cerebro.plot()` 的契约通过适配器 `BokehPlot` 对齐；
  适配器保留了 `BacktraderBokeh` 原始 `plot()` 行为。
- 在无图形前端环境执行时，建议使用文件输出路径替代 `show()`。

## 6. 相关示例

- `examples/example_plotly_charts.py`
- `examples/example_bokeh_charts.py`

两者都包含后端切换说明，便于用户对比三后端。
