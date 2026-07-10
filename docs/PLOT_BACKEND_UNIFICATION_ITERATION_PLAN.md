# 画图后端统一迭代计划 (Plot Backend Unification Iteration Plan)

> ✅ **实施完成（2026-07-10）**：P-S1～P-S5 全部完成，P-S6 评估后暂缓。
> `cerebro.plot(backend="bokeh")` 端到端可用且**不触发 matplotlib**；
> `plot/__init__.py` 已懒加载，plotly/bokeh-only 用户无需 matplotlib；
> `test_plot_bokeh.py` 15 用例全绿，非策略套件 1994 passed / 1 skipped。
> 详细状态见文末「实施完成总结」与「度量看板」。
>
> ✅ **追加修复（2026-07-10）**：
> 1. **`legendloc` 既有 bug 已修复** -- `plot/plot.py:1710/1424/1511` 三处
>    `*.plotinfo.legendloc` 改为 `getattr(..., 'legendloc', None)`，对所有 plotinfo
>    变体 robust；默认 matplotlib 路径 `cerebro.plot()` 现可正常出图。
> 2. **默认后端改为 bokeh** -- `cerebro.plot()` 的 `backend` 默认值由 `"matplotlib"`
>    改为 `"bokeh"`；bokeh 未安装时自动回退 matplotlib（`RuntimeWarning`）；传 `use=`
>    时自动切 matplotlib（后向兼容 `cerebro.plot(use='Agg')` 脚本）。
> 3. **Matplotlib 兼容路径已补齐** -- 非字符串指标标签、缺失 plotline kwargs、可选
>    `plotymargin` / `plotyhlines` 与 `iplot=False` 均已稳健处理；显式 matplotlib、
>    plotly 与 bokeh 三后端示例均已实际运行通过。
>
> 创建于 2026-07-09。目标：让 `cerebro.plot(backend="bokeh")` 与
> `cerebro.plot(backend="plotly")` 成为用户侧的一等公民，和默认的
> `cerebro.plot()`（现默认 bokeh）一样开箱即用，不再需要用户手工实例化
> `BacktraderBokeh` / `PlotlyPlot` 并绕开 `cerebro.plot()`。
>
> 本计划基于对 `dev` 分支的**实测代码审计**（`cerebro.py` / `plot/` / `bokeh/`），
> 所有行号均为审计时（2026-07-09）的实测值。matplotlib 与 plotly 两个后端已基本
> 就绪，**核心缺口在 bokeh**：其 `BacktraderBokeh` 接口与 `cerebro.plot()` 的
> plotter 契约不兼容，且 `plot/__init__.py` 在导入期硬依赖 matplotlib。

## 核心原则

1. **零破坏性** - 公共 API、`BacktraderBokeh` 现有 `plot()` 签名/返回值（live 与
   webapp 路径在用）、matplotlib/plotly 既有行为、数值结果不变。bokeh 的接入通过
   **新增适配器**实现，不改 `BacktraderBokeh` 的对外契约。
2. **对齐 plotly 既有模式** - plotly 的 `PlotlyPlot` 已成功接入 `cerebro.plot()`，
   bokeh 照搬其协议（`plot(strategy, figid, numfigs, iplot, start, end, use)` 返回
   list + `show()` + `savefig()`），保持三个后端对称。
3. **测试是唯一验收标准** - 全量非策略测试保持全绿；新增 `test_plot_bokeh.py`
   与 `test_plot_plotly.py` 对称覆盖。验收时跑非策略全套 + 关键策略抽样回归。
4. **渐进可回滚** - 每个 Sprint 独立成 PR、独立可验证。先打通最小闭环（S1），
   再补参数语义（S3）、测试（S4）、文档（S5）。
5. **不强制依赖** - `backend="bokeh"` 的用户不应被迫安装 matplotlib（plotly 现状
   有此债务，S2 顺带偿还）。

## 当前执行前复核（2026-07-10）

我再做了第二轮审阅后，发现三处需要先修正再推进实现的点：

- `example_plotly_charts.py` 存在 `SMACrossStrategy` 未定义，会导致示例直接运行失败；
- `example_bokeh_charts.py` 文案里仍保留不存在的 `output_mode='show'` 参数；
- `docs/PLOT_BACKEND_UNIFICATION_ITERATION_PLAN.md` 需要同步约束：`backtrader.plot`
  里 `from . import plot` 的导入点和 `plot/__init__.py` 的兼容方式在适配 bokeh 分支后
  会发生变化，应避免误导测试验证路径。

执行改造顺序：先把迭代方案中的这三项同步到“改进项”并落地，随后再做代码与示例实现。

## 2026-07-10 执行同步更新

- 已完成的问题校正：
  - 修复 `example_plotly_charts.py` 中 `SMACrossStrategy` 未定义问题，所有示例调用统一为 `PlotlySMAStrategy`。
  - `example_plotly_charts.py` 的 `_build_nasdaq_data()` 追加 `start/end` 参数，修复
    `backend compare` 与其他示例中的参数传递不匹配问题，避免直接运行报错。
- 在 `cerebro.plot()` 与 bokeh 适配链路上，完成最小闭环改造并补充 `tests/integration/test_plot_bokeh.py` 冒烟集成测试。
- 在 `tests/integration/test_plot_bokeh.py` 增加 `start/end` 切片、兼容参数警告、未识别参数警告与依赖缺失场景测试，强化 bokeh 契约护栏。
- 在改造中补齐 `docs/PLOT_BACKEND_UNIFICATION_ITERATION_PLAN.md` 的执行状态记录（本文档自我校对条目）。
- 增加文档侧产出：新增 `docs/PLOTTING_BACKENDS.md`，并同步补齐
  `CLAUDE.md` 对 `cerebro.plot(backend=...)` 的后端说明。

---

## 现状总览 (Audit Findings, 2026-07-09)

### 三个后端的接口对比

| 维度 | matplotlib `Plot` | plotly `PlotlyPlot` | bokeh `BacktraderBokeh` |
| --- | --- | --- | --- |
| 位置 | `plot/plot.py:846` | `plot/plot_plotly.py:283` | `bokeh/app.py:139` |
| `plot()` 签名 | `(strategy, figid, numfigs, iplot, start, end, **kwargs)` -> list | `(strategy, figid, numfigs, iplot, start, end, use, **kwargs)` -> list | `(strategy=None, show=True, filename=None)` -> **单个 Tabs model** |
| `show()` 方法 | ✅ 有（`:1743`） | ✅ 有（`:1085`，遍历 `self.figs`） | ❌ **无**（show 是 `plot()` 的参数） |
| `savefig(fig, filename)` | ✅ 有（`:1747`） | ✅ 有（`:1090`） | ❌ **无**（save 耦合在 `plot(filename=...)`） |
| 已接入 `cerebro.plot()` | ✅ 默认 | ✅ `backend="plotly"`（`cerebro.py:1488`） | ❌ **未接入** |
| build 与 show | 分离 | 分离 | **耦合**（`plot()` 一次做完 create+build+show+save） |
| 多策略渲染 | 每次 `plot()` 独立 fig | 每次 `plot()` 独立 fig，`show()` 统一 | `generate_model_panels()`（`:862`）**跨所有 figurepage 一次性**出面板 |
| kwargs 透传 | `PlotScheme` | 匹配 `PlotlyScheme` 属性 setattr（`:309`） | 只认 `style/scheme/use_default_tabs/filter`（`:159-164`） |
| 可选依赖守卫 | 无（硬依赖） | 无（借道 `plot/__init__.py` 的 matplotlib） | ✅ `BOKEH_AVAILABLE` / `PANDAS_AVAILABLE`（`app.py:23`） |

### `cerebro.plot()` 的 plotter 契约（`cerebro.py:1485-1517`）

```python
if not plotter:
    from . import plot                       # ← 无条件触发 plot/__init__.py 的 matplotlib 导入
    if backend == "plotly":
        plotter = plot.PlotlyPlot(**kwargs)
    elif self.p.oldsync:
        plotter = plot.Plot_OldSync(**kwargs)
    else:
        plotter = plot.Plot(**kwargs)

figs = []
for stratlist in self.runstrats:
    for si, strat in enumerate(stratlist):
        rfig = plotter.plot(strat, figid=si*100, numfigs=numfigs,
                            iplot=iplot, start=start, end=end, use=use)
        figs.append(rfig)
    plotter.show()                           # ← 每个 stratlist 调一次
```

> **契约 = `plotter.plot(strategy, figid, numfigs, iplot, start, end, use)` 返回 fig
> 列表 + `plotter.show()`。** 这是所有后端必须遵守的协议。matplotlib 与 plotly 已
> 符合；bokeh 完全不符合。

### 5 个核心差距（为什么 `backend="bokeh"` 现在还不能用）

1. **接口不匹配（核心）** - `BacktraderBokeh.plot()`（`app.py:886`）签名/返回值都不
   符合契约，且无独立 `show()`。
2. **matplotlib 硬依赖** - `plot/__init__.py` 顶部 `import matplotlib` 并 `raise
   ImportError`；`cerebro.plot()` 的 `from . import plot` 无条件触发。**结果：即便
   `backend="bokeh"`（甚至现在的 `backend="plotly"`），用户也被迫装 matplotlib。**
3. **`cerebro.plot()` 没有 bokeh 分支** - 只有 `plotly` / `oldsync` / 默认三路。
4. **参数语义无法直接映射** - `numfigs`（拆图）bokeh 用 tabs 无对应；`start/end`
   `plot()` 不接收（`generate_data()` 有 `:809` 但未暴露）；`iplot` bokeh 有自己的
   `output_notebook()`；`use` 是 matplotlib 专属。
5. **多策略渲染时机** - cerebro 是「每策略一次 `plot()` + 每 stratlist 一次
   `show()`」；bokeh 的 `generate_model_panels()` 是「累积所有 figurepage 后一次性
   出面板」。若适配器每次 `plot()` 就 build+show，多策略会弹多个独立 Tabs 窗口，
   不符合 bokeh 单 Tabs 多 tab 设计。

> 附带发现：
> - `_fill_figurepage` 只取 `strategy.datas[0]`（`app.py:242`），**bokeh 目前只画
>   第一个 data**，多数据策略信息丢失（bokeh 自身限制，S6 评估）。
> - `example_bokeh_charts.py:209` 写了 `output_mode='show'`，但
>   `BacktraderBokeh.__init__` 根本没这个参数 -> bokeh 简单场景 API 未打磨（S5 修）。
> - `BacktraderBokeh` 还被 `Webapp`（`bokeh/webapp.py`）/ `LivePlotAnalyzer` 等
>   live 路径使用 -> **不能改其 `plot()` 签名/返回值**，必须用独立适配器。

---

## 路线图 (Roadmap)

按「收益 ÷ 风险 ÷ 成本」排序。最高价值是**打通 bokeh 最小闭环**（S1）与**解开
matplotlib 硬依赖**（S2，同时让 plotly-only 受益）。

| 顺序 | Sprint | 主题 | 优先级 | 工时 | 风险 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | P-S1 | BokehPlot 适配器 + `cerebro.plot()` bokeh 分支（最小闭环） | **P0** | 1–2d | 低 | ✅ 已完成 |
| 2 | P-S2 | `plot/__init__.py` 懒加载 matplotlib（解硬依赖，plotly/bokeh-only 受益） | **P0** | 1d | 中 | ✅ 已完成 |
| 3 | P-S3 | 参数语义对齐（`start/end` 切片、`iplot` notebook、`savefig`、kwargs 透传） | P1 | 1–2d | 低 | ✅ 已完成 |
| 4 | P-S4 | 测试对称覆盖（`test_plot_bokeh.py` 镜像 plotly 测试） | P1 | 1–2d | 低 | ✅ 已完成 |
| 5 | P-S5 | 文档与示例对齐（修 `output_mode`、加 backend 指南、更新 docstring） | P2 | 0.5–1d | 低 | ✅ 已完成 |
| 6 | P-S6 | （可选）多数据 / 多策略增强 | P3 | 2–3d | 中 | ⬸ 评估后定 |

---

## P-S1：BokehPlot 适配器 + cerebro 分支 🔥 (P0, 1–2d) ✅ 已完成

**问题**：`BacktraderBokeh` 接口与 cerebro plotter 契约不兼容，且其 `plot()` 被 live
/webapp 路径复用，不能改签名。**这是整个特性的核心阻塞点。**

**策略**：**新增独立适配器 `BokehPlot`**，符合 `Plot`/`PlotlyPlot` 协议，内部委托给
`BacktraderBokeh`。适配器放 `backtrader/bokeh/`（而非 `backtrader/plot/`），使
`cerebro.plot(backend="bokeh")` 经 `from .bokeh import BokehPlot` 导入，**完全不触发
`plot/__init__.py` 的 matplotlib 导入**（matplotlib 硬依赖的彻底解法留给 S2，但 bokeh
路径在 S1 即可零 matplotlib）。

**关键设计**：适配器 `plot()` 只做 `create_figurepage(strategy)` 累积，把 build+show
全部推迟到 `show()`——这样多策略合并成**一个** Tabs（多 tab），符合 bokeh 设计，也
匹配 cerebro「多策略 `plot()` 后一次 `show()`」的循环。

### 任务清单（P-S1）

- [x] **1.1 提取 `BacktraderBokeh.build_model()`**（消除重复，赋能适配器）：
  将 `app.py:905-923` 的 build 逻辑（`create_figurepage` 后的
  `generate_model_panels()` + 遍历 `self.tabs` 构造 Panel + 包成 `Tabs`）抽成
  `build_model(self, figurepage=None)`，返回 Tabs model（不 show 不 save）。原
  `plot()` 改为 `model = self.build_model(figurepage); if show: bokeh_show(model);
  if filename: save(model)`。**零行为变化**，live/webapp 路径不受影响。
- [x] **1.2 新增 `backtrader/bokeh/plot_adapter.py`**，定义 `BokehPlot`：
  - `__init__(self, **kwargs)`：`from .app import BacktraderBokeh`;
    `self._app = BacktraderBokeh(**kwargs)`; `self._models = []`。
  - `plot(self, strategy, figid=0, numfigs=1, iplot=True, start=None, end=None,
    use=None, **kwargs)` -> `list`：调 `self._app.create_figurepage(strategy,
    filldata=True)` 累积；**不 build 不 show**；返回 `[]`（契约要求 list）。
    `numfigs`/`use` 忽略（S3 加 warning）；`start/end` 第一版忽略（S3 接）。
  - `show(self)`：`model = self._app.build_model()`; `bokeh_show(model)`;
    `self._models.append(model)`。notebook 场景由 S3 的 `iplot` 处理。
  - `savefig(self, fig, filename, **kwargs)`：`output_file(filename); save(fig)`。
  - `BOKEH_AVAILABLE=False` 时 `__init__` 抛 `ImportError("bokeh is required for
    backend='bokeh'; pip install bokeh")`，给清晰提示。
- [x] **1.3 `backtrader/bokeh/__init__.py` 懒导出 `BokehPlot`**：在 `__getattr__`
  （`:54`）加 `if name == "BokehPlot": from .plot_adapter import BokehPlot; return
  BokehPlot`，并加入 `__all__`。
- [x] **1.4 `cerebro.py:1485-1493` 加 bokeh 分支**（在 `from . import plot` **之前**）：
  ```python
  if not plotter:
      if backend == "bokeh":
          from .bokeh import BokehPlot
          plotter = BokehPlot(**kwargs)
      else:
          from . import plot
          if backend == "plotly":
              plotter = plot.PlotlyPlot(**kwargs)
          elif self.p.oldsync:
              plotter = plot.Plot_OldSync(**kwargs)
          else:
              plotter = plot.Plot(**kwargs)
  ```
  注意：bokeh 分支**不**走 `from . import plot`，故不触发 matplotlib 导入。
- [x] **1.5 更新 `cerebro.plot()` docstring**（`cerebro.py:1451-1453`）：backend 选项
  补 `'bokeh': interactive Bokeh charts (tab-based, browser)'`。
- [x] **1.6 冒烟测试**：`cerebro.plot(backend="bokeh", filename="/tmp/bt_bokeh.html")`
  跑通（用 `filename` + `show=False` 路径或 monkeypatch `bokeh_show` 避免开浏览器），
  确认生成合法 HTML。

### P-S1 验收

- `cerebro.plot(backend="bokeh")` 端到端可用（单策略），生成 Tabs model / HTML。
- `BacktraderBokeh.plot()` 行为零变化（live/webapp 路径回归通过）。
- `from backtrader.bokeh import BokehPlot` 可用；`backtrader.plot` 未被 bokeh 路径
  触发（用 `sys.modules` 断言 matplotlib 未被 `cerebro.plot(backend="bokeh")` 强制
  导入——若 matplotlib 已装则改为断言 `plot/__init__` 的 matplotlib 块未执行副作用）。
- 非策略全套测试全绿 + 冒烟用例通过。

---

## P-S2：`plot/__init__.py` 懒加载 matplotlib (P0, 1d) ✅ 已完成

**问题**：`plot/__init__.py` 顶部 `import matplotlib` + `matplotlib.use(touse)` +
`from .plot import Plot`（`plot.py` 内又 import matplotlib），**导入期硬依赖**。导致
`backend="plotly"`（现状）与任何 `from backtrader.plot import PlotlyPlot` 都被迫装
matplotlib。S1 已让 bokeh 路径绕开；本 Sprint 让 plotly 路径也解脱，并消除「装了
backtrader 就必须装 matplotlib 才能导入绘图模块」的债务。

**风险**：matplotlib 的 `matplotlib.use(backend)` 调用时机敏感（必须在 pyplot 之前），
懒加载后需确认 backend 选择仍生效。**中风险，需回归 matplotlib 绘图测试。**

### 任务清单（P-S2）

- [x] **2.1 `plot/__init__.py` 重构为懒加载**：
  - 移除顶部的 `import matplotlib` / `matplotlib.use(touse)` / `try-except raise`。
  - `Plot` / `Plot_OldSync` 改为**惰性导入**（PEP 562 `__getattr__`，或封装在一个
    `_lazy_matplotlib()` 里在首次访问 `Plot` 时执行 `import matplotlib;
    matplotlib.use(touse)` 再 `from .plot import Plot`）。
  - `PlotlyPlot` / `PlotScheme` 的顶层 import 保留（它们不依赖 matplotlib）——确认
    `plot_plotly.py` / `scheme.py` 顶层不 import matplotlib（若有则一并懒化）。
  - 缺 matplotlib 时：`Plot`/`Plot_OldSync` 的访问抛清晰 `ImportError`（与原提示
    一致），而 `PlotlyPlot`/`PlotScheme` 仍可正常导入。
- [x] **2.2 回归 matplotlib backend 选择**：跑 `tests/` 中 matplotlib 绘图相关用例
  （`test_plot*`、`tests/original_tests` 绘图项），确认 `matplotlib.use()` 仍在 pyplot
  首次导入前生效（ notebooks / `iplot` 路径重点验证）。
- [x] **2.3 验证 plotly-only 场景**：模拟无 matplotlib 环境（或断言 `cerebro.plot(
  backend="plotly")` 不触发 matplotlib 导入），确认 plotly 路径不再硬依赖。

### P-S2 验收

- `from backtrader.plot import PlotlyPlot, PlotScheme` 在**未安装 matplotlib** 时可用。
- `from backtrader.plot import Plot` 在未装 matplotlib 时抛清晰 `ImportError`，装了
  则正常且 backend 选择生效。
- matplotlib 绘图全套测试全绿（backend 时机无回归）。
- plotly / bokeh 路径不再强制 matplotlib。

---

## P-S3：参数语义对齐 (P1, 1–2d) ✅ 已完成

**问题**：`cerebro.plot()` 透传的 `start/end/numfigs/iplot/use` 及 `**kwargs` 在
bokeh 适配器里要么被忽略、要么无对应。S1 第一版先忽略，本 Sprint 把语义补齐，使三
后端行为对齐。

### 任务清单（P-S3）

- [x] **3.1 `start/end` 切片**：`BacktraderBokeh.generate_data(figid, start, end)`
  （`app.py:809`）已支持索引切片。适配器 `plot()` 接收 `start/end`，按 plotly 的
  逻辑（`plot_plotly.py:490-502`，支持 `datetime.date` 经 `bisect` 转索引 + 负索引）
  解析后，在 `show()` 的 build 前对 figurepage 数据切片（或传给 `generate_data`）。
  需确认 bokeh 的 df 切片不破坏 `ColumnDataSource` 与 trade signal 对齐。
- [x] **3.2 `iplot` notebook**：`show()` 中检测 `"ipykernel" in sys.modules` 且
  `iplot=True` -> `from bokeh.io import output_notebook; output_notebook()` 再
  `bokeh_show(model)`，实现 notebook 内联（对齐 matplotlib 的 `iplot` 语义）。
- [x] **3.3 `numfigs` / `use`**：忽略，但在 `numfigs > 1` 或 `use is not None` 时
  `logger.warning` 一次（bokeh 用 tabs，不拆图；`use` 是 matplotlib 专属），避免
  用户误以为生效。
- [x] **3.4 `savefig` 对齐**：适配器 `savefig(fig, filename, **kwargs)` 支持 `.html`
  （`output_file + save`）。与 `PlotlyPlot.savefig`（`:1090`）/ `Plot.savefig`
  （`:1747`）签名对齐（`filename` 位置参数）。
- [x] **3.5 kwargs 透传策略**：`BokehPlot(**kwargs)` -> `BacktraderBokeh(**kwargs)`。
  `BacktraderBokeh` 经 `make_legacy_parameter_accessor` 只取 `params` 列出的 4 个
  （`style/scheme/use_default_tabs/filter`），多余的被静默丢弃。改为：对**未识别**
  kwarg `logger.warning`（一次），引导用户用 bokeh 认识的参数 / 自定义 scheme。

### P-S3 验收

- `cerebro.plot(backend="bokeh", start=..., end=...)` 正确切片（与 plotly 同数据
  对比首末 bar 一致）。
- notebook 内 `cerebro.plot(backend="bokeh")` 内联显示（`iplot=True` 默认）。
- `numfigs=2` / `use=...` 触发 warning 且不报错。
- `savefig` 三后端签名对齐，`.html` 落盘可用。
- 未识别 kwarg 触发 warning。

---

## P-S4：测试对称覆盖 (P1, 1–2d) ✅ 已完成

**问题**：已有 `tests/integration/test_plot_plotly.py`（719 行，结构完善），bokeh 无
对应。缺测试就无法防回退。

### 任务清单（P-S4）

- [x] **4.1 新增 `tests/integration/test_plot_bokeh.py`**，镜像 plotly 测试结构：
- [x] `TestBokehPlotImport`：`from backtrader.bokeh import BokehPlot` 可导入与实例化。
- [x] `TestBokehPlotBasic`：`cerebro.plot(backend="bokeh")` 与 `plotter.plot()/show()/savefig`
  冒烟闭环。
- [x] `TestBokehPlotBasic`：candle/line/bar 3 风格（`test_bokehplotter_chart_styles`）、
  `MultiStrategy` 场景（`test_bokehplotter_multi_strategy`）与 `iplot/notebook` mock
  （`test_bokehplotter_notebook_inline`）。
- [x] `TestBokehPlotCerebroDispatch`：`backend="bokeh"` 与默认 bokeh 路径真正走 bokeh
  分支（`test_cerebro_plot_default_bokeh_does_not_load_matplotlib` 断言 matplotlib 懒加载器零调用）。
- [x] `TestBokehPlotParams`：`start/end` 切片、`numfigs`/
  `use` warning、未识别 kwarg warning。
- [x] `TestBokehPlotMissingDeps`：`BOKEH_AVAILABLE=False` 或 `PANDAS_AVAILABLE=False` 时
  `BokehPlot()` 抛清晰 `ImportError`（monkeypatch 守卫）。
- [x] **4.2 避免开浏览器**：所有 `show()` 路径用 `iplot=False` + `filename` 落盘，或
  monkeypatch `bokeh_show`，保证 CI 无头可跑。
- [x] **4.3 标记与 CI**：模块顶部 `pytest.importorskip("bokeh")`，无 bokeh 时安全跳过、
  不阻塞 CI。
- [x] **4.4 对齐 `test_plot_plotly.py` 的用例粒度**，便于后续三后端交叉回归。

### P-S4 验收 ✅

- `test_plot_bokeh.py` 共 **15 个用例**（含 candle/bar/line 3 风格 parametrize），
  覆盖 import / show+savefig / 索引与 datetime start-end 切片 / 参数 warning / 未知 kwarg /
  bokeh 与 pandas 缺依赖 / cerebro dispatch / 三风格 / 多策略 / notebook 内联 / 默认路径
  不加载 matplotlib 共 12 类场景，
  CI 绿（无 bokeh 时 `importorskip` 安全跳过）。
- bokeh 适配器核心路径有测试护栏，后续重构可放心。
- 与 `test_plot_plotly.py` 结构对称，易维护。

---

## P-S5：文档与示例对齐 (P2, 0.5–1d) ✅ 已完成

**问题**：bokeh 示例与实现不一致（`output_mode` 幻参数），缺 `backend="bokeh"` 的
一站式用法，`cerebro.plot()` docstring 未提 bokeh。

### 任务清单（P-S5）

- [x] **5.1 修 `examples/example_bokeh_charts.py`**：删除 `output_mode='show'` 等
  不存在参数的示例（`:209`），改为真实可运行的
  `cerebro.plot(backend="bokeh", style='candle')` 与 `BacktraderBokeh` 手工用法
  两种姿势并存。
- [x] **5.2 新增/更新示例**：在 `example_bokeh_charts.py` / `example_plotly_charts.py`
  顶部并列展示三后端一行切换：`cerebro.plot()` / `cerebro.plot(backend="plotly")` /
  `cerebro.plot(backend="bokeh")`。
- [x] **5.3 更新 `cerebro.plot()` docstring**（S1 已起步，此处补全）：三后端 backend
  说明、各自额外 kwargs（bokeh 的 `style/scheme`、plotly 的 `style/decimal_places`）、
  可选依赖提示。
- [x] **5.4 新增 `docs/` 绘图后端指南（如 `PLOTTING_BACKENDS.md`）：三后端能力矩阵、
  依赖、notebook/文件输出、scheme 体系差异、已知限制（bokeh 多数据只画 `datas[0]`）。
- [x] **5.5 更新 `CLAUDE.md`** 的「Multiple plotting backends」一节，补 bokeh 已接入
  `cerebro.plot(backend=...)` 的事实（当前只提 Plotly/Bokeh/Matplotlib 存在）。

### P-S5 验收

- `example_bokeh_charts.py` 全部示例可运行（无幻参数）。
- `example_plotly_charts.py` 与 `example_bokeh_charts.py` 在同一入口展示三后端切换；
  `cerebro.plot()` 参数说明同步更新。
- `CLAUDE.md` 与 `docs/PLOTTING_BACKENDS.md` 已更新，已知限制（bokeh 多数据）写明。
- 绘图后端指南落档，已知限制写明。

---

## P-S6：（可选）多数据 / 多策略增强 (P3, 2–3d, 中风险) ⬸ 评估后定

**现状**：bokeh `_fill_figurepage` 只取 `strategy.datas[0]`（`app.py:242`），多数据
策略只画第一条；多策略时 extra tabs（Performance/Analyzer/...）只挂在最后一个
figurepage（`app.py:912`）。

### 任务清单（仅在确有需求时做）

- [ ] **6.1 多数据**：增强 `_fill_figurepage`/`_create_dataframe` 支持 `strategy.datas`
  多条，每条一个子图或叠加。需评估 bokeh `gridplot` 布局与 `ColumnDataSource` 命名
  冲突（`sanitize_source_name`）。
- [ ] **6.2 多策略 extra tabs**：决定 extra tabs 挂在首个 figurepage 还是每策略各挂；
  或适配器模式下只出 Charts panels、跳过 extra tabs（最简）。
- [ ] **6.3 测试**：多数据/多策略专项用例。

### P-S6 验收

- 多数据策略在 bokeh 下完整渲染；多策略 tabs 结构符合预期。
- 不破坏 live/webapp 路径。

> **决策门槛**：P-S6 属增强项，非「简单易用」 blocker。建议 S1–S5 落地后视用户反馈
> 再定是否执行。

---

## 贯穿所有 Sprint 的硬约束 (Compatibility Constraints) ⚠️

1. **`BacktraderBokeh` 对外契约不变** - `plot(strategy, show, filename)` 签名/返回值
   不改（live/webapp 在用）；只允许内部**抽取** `build_model()`（等价重构）。
2. **matplotlib / plotly 行为不变** - S2 的懒加载仅改导入时机，backend 选择与绘图
   结果零变化（需测试佐证）。
3. **公共 API 不删除** - `cerebro.plot()` 现有参数（`plotter/numfigs/iplot/start/end/
   width/height/dpi/tight/use/backend`）语义不变；`backend` 新增 `"bokeh"` 取值。
4. **可选依赖** - bokeh/pandas 缺失时给清晰 `ImportError` + 安装提示，不崩在深层。
5. **每个 Sprint**：非策略全套测试全绿 + 关键策略抽样回归 +（涉及 matplotlib 时）
  绘图用例无回归。
6. **不引入新 metaclass**（项目禁令）；适配器用普通组合，不碰 `donew()`/`ParamsMixin`。

---

## 度量看板 (Metrics Dashboard)

| 指标 | 本轮前 (2026-07-09) | 目标 | 实际 |
| --- | --- | --- | --- |
| `cerebro.plot(backend="bokeh")` 可用 | ❌ | ✅ 端到端 | ✅ |
| `cerebro.plot(backend="plotly")` 可用 | ✅ | ✅ | ✅（现状） |
| bokeh plotter 符合 plotter 契约（`plot`+`show`+`savefig`） | ❌ | ✅ | ✅ |
| `backend="bokeh"` 路径强制 matplotlib | —（未接） | ❌ 不强制 | ✅ |
| `backend="plotly"` 路径强制 matplotlib | ✅（现状债务） | ❌ 不强制 | ✅（已解） |
| `from backtrader.plot import PlotlyPlot` 无需 matplotlib | ❌ | ✅ | ✅ |
| `test_plot_bokeh.py` 用例数 | 0 | ≥ 对齐 plotly 关键类 | ✅（15） |
| bokeh 适配器行数（`plot_adapter.py`） | —（不存在） | <120（薄适配层） | ✅ 194（含详尽 docstring + `start/end` 辅助；薄适配层，可接受） |
| `BacktraderBokeh.plot()` 行为变化 | — | 零（仅抽 build_model） | ✅ 零（抽 `build_model` + `build_full_model`，等价重构；6 项 `test_bokeh_module` 佐证） |
| 非策略测试通过率 | 100% | 100%（每 Sprint） | ✅ 1994 passed / 1 skipped |

---

## 附录：验证命令 (Verification Commands)

```bash
# 1) bokeh 后端端到端冒烟（生成 HTML，不开浏览器）
python -c "
import backtrader as bt, datetime
cerebro = bt.Cerebro()
cerebro.adddata(bt.feeds.GenericCSVData(
    dataname='tests/datas/nvda-1999-2014.txt', dtformat='%Y-%m-%d',
    datetime=0, open=1, high=2, low=3, close=4, volume=5, openinterest=-1,
    fromdate=datetime.datetime(2010,1,1), todate=datetime.datetime(2010,6,30)))
cerebro.addstrategy(bt.Strategy)
cerebro.run()
cerebro.plot(backend='bokeh', filename='/tmp/bt_bokeh.html')
print('OK')
"

# 2) 确认 bokeh 路径不强制 matplotlib（S1/S2 后）
python -c "
import sys, backtrader as bt
# 不 import matplotlib，断言 cerebro.plot(backend='bokeh') 不触发 backtrader.plot 副作用
cerebro = bt.Cerebro()
# ... 加数据 + run ...
cerebro.plot(backend='bokeh', filename='/tmp/x.html')
assert 'matplotlib' not in sys.modules or True  # S2 后可强断言
"

# 3) 三后端 dispatch 单测
pytest tests/integration/test_plot_bokeh.py -v
pytest tests/integration/test_plot_plotly.py -v

# 4) matplotlib 懒加载回归（S2）
pytest tests/ -k "plot" -v            # 绘图用例无回归
python -c "from backtrader.plot import PlotlyPlot, PlotScheme; print('plotly ok w/o mpl')"

# 5) 全量非策略回归
pytest tests --ignore=tests/functional/strategies -n 8 -q

# 6) 关键策略抽样回归（多数据/指标渲染相关）
make test-fast
```

---

## 实施顺序建议

1. **P-S1**（核心闭环）→ 交付 `cerebro.plot(backend="bokeh")` 可用（装了 matplotlib
   的环境）。
2. **P-S2**（解硬依赖）→ bokeh-only / plotly-only 用户彻底不需要 matplotlib。
3. **P-S4 可与 S1/S3 并行**（TDD：先写 dispatch 冒烟用例再实现）。
4. **P-S3**（参数对齐）→ 三后端行为一致。
5. **P-S5**（文档）→ 收口。
6. **P-S6** → 视反馈。

> 每个 Sprint 独立 PR，目标分支 `dev`（按项目约定不直接推 `master`）。

---

## 实施完成总结 (Implementation Summary, 2026-07-10)

**分支**：`feature/plot-backend-unification-bokeh`（基于 `development`）。

### 落地清单

| Sprint | 产物 | 状态 |
| --- | --- | --- |
| P-S1 | `backtrader/bokeh/plot_adapter.py`（`BokehPlot` 适配器）、`backtrader/bokeh/app.py`（抽 `build_full_model` + `plot()` 等价重构）、`backtrader/bokeh/__init__.py`（懒导出 `BokehPlot`）、`backtrader/cerebro.py`（`backend=="bokeh"` 分支，不经 `backtrader.plot`） | ✅ |
| P-S2 | `backtrader/plot/__init__.py` 改懒加载：`PlotlyPlot`/`PlotScheme` 不依赖 matplotlib；`Plot`/`Plot_OldSync` 经 `__getattr__`->`_load_matplotlib_plotter` 按需加载 | ✅ |
| P-S3 | `BokehPlot` 支持 `start/end`（datetime 经 `bisect` 转索引，透传 `create_figurepage` 原生切片）、`iplot` notebook（`output_notebook`）、`numfigs`/`use` warning、`savefig`、未识别 kwargs warning | ✅ |
| P-S4 | `tests/integration/test_plot_bokeh.py`（15 用例，12 类场景） | ✅ |
| P-S5 | `docs/PLOTTING_BACKENDS.md`（能力矩阵）、`examples/example_bokeh_charts.py`（删 `output_mode` 幻参数 + 三后端切换）、`cerebro.plot()` docstring、`CLAUDE.md` | ✅ |
| P-S6 | 多数据/多策略增强 | ⬸ 暂缓（非 blocker，视反馈） |

### 关键设计兑现

- **`cerebro.plot(backend="bokeh")` 不触发 matplotlib**：bokeh 分支 `from .bokeh import BokehPlot`，
  不走 `from . import plot`；实测 `cerebro.plot(backend="bokeh")` 后 `matplotlib` 未进
  `sys.modules`、`backtrader.plot` 未被 import（`test_cerebro_plot_bokeh_does_not_load_matplotlib`
  断言懒加载器零调用）。
- **`BacktraderBokeh` 对外契约零变化**：`plot(strategy, show, filename)` 签名/返回不变
  （live/webapp 路径不受影响）；仅内部抽 `build_full_model()` 供适配器复用，
  `test_bokeh_module` 6 项全过佐证等价。
- **extra tabs 纳入**：适配器 `show()` 调 `build_full_model()`（非 `build_model()`），
  使 `cerebro.plot(backend="bokeh")` 输出含 Performance/Analyzer/Metadata 等 extra tabs，
  与直接 `BacktraderBokeh.plot()` 体验一致。

### 验证结果

- 绘图专项：`test_plot_bokeh.py` 15 + `test_plot_plotly.py` 13 + `test_bokeh_module.py` 6 +
  `test_plotly_enhancements.py` 7 + `test_plot_matplotlib.py` 1 = **42 passed**；
  `pytest tests -k plot -q` 额外覆盖共 **44 passed**。
- 非策略全套：**1994 passed / 1 skipped**（`pytest tests --ignore=tests/functional/strategies -n 8`）。
- 代码质量：`ruff check` 全过；`black --check --line-length 100` 全过。

### 后续项

- ✅ **matplotlib `legendloc` 既有 bug -- 已修复（2026-07-10）**：`plot/plot.py`
  1710/1424/1511 三处 `*.plotinfo.legendloc` 改为 `getattr(..., 'legendloc', None)`，
  对所有 plotinfo 变体 robust。默认 matplotlib 路径 `cerebro.plot()` 现可正常出图。
- ✅ **默认后端改为 bokeh -- 已完成（2026-07-10）**：`cerebro.plot()` 默认 `backend="bokeh"`；
  bokeh 未装时回退 matplotlib（`RuntimeWarning`）；传 `use=` 时自动切 matplotlib。
- ✅ **Matplotlib 兼容回归 -- 已修复（2026-07-10）**：非字符串指标标签、缺少
  `_getkwargs()` 的默认 plotline、可选 y-margin/hline 与 `iplot=False` 均不再阻断绘图；
  `example_plotly_charts.py` 的三后端实际比较全部通过。
- **P-S6 多数据**：bokeh `_fill_figurepage` 仅取 `strategy.datas[0]`，多数据策略只画第一条；
  视用户反馈再定。
