# 原生 Indicator 因子研究

迭代45把因子计算留在 Backtrader，把标签、IC、多因子合成与报告放在 fincore。所有研究因子继承 `FactorIndicator`；`FactorStrategy` 负责装配和采集，作者不用为每个因子重写策略的 `next()`。

重构与性能验收见[45–46优化验收结果](../../_internal/opts/requirements/迭代45-46优化/验收结果.md)。原生101式已实现；迭代47增加公式式 build 和025/026/027双模式，实际验收范围见[47开发与验收记录](../../_internal/opts/requirements/迭代47-因子build简洁模式与算子增强/开发与验收记录.md)。全101式的build伴随实现属于迭代48。

> 迭代45-46优化（2026-10-22）后，研究链路直接产出普通 `FactorPanel`：`ResearchDataset`、`inputs.py`、`dataset.py`、`storage.py`、`field_validation.py`、PIT/as-of 表、`table:` 绑定和 `classification_bindings` 已删除。本文描述的是当前 API；历史快照文件不再保证可读。

迭代47的四公式build、三个500资产示例完整配对和固定wheel验收已通过，见[47验收结果](../../_internal/opts/requirements/迭代47-因子build简洁模式与算子增强/验收结果.md)。全101 build扩展仍在迭代48单独验收。

## 环境与职责

研究入口要求 Python 3.11 及 pandas。普通 Backtrader 核心仍支持其原有 Python 范围；采集和 CSV 交换不需要 fincore。只有评价时才加载包含本轮研究 API 的 fincore 安装产物，不能用同版本号的旧包替代。

- `FactorIndicator`：原生参数、输入、子指标、逐资产输出线和计算过程。
- `ResearchSpec` / `FactorSpec`：日历、研究窗口、目标资产、分组、因子参数及字段绑定。
- `FactorStrategy`：原生指标装配、同步网格采集，把结果写入 `FactorSink`；不提交或撤销订单。
- `FactorPanel`：五类普通帧（factors/grid/prices/universe/groups）加窗口、顺序和方向声明；不是不可变快照，也没有数据身份。
- `MemorySink` / `CsvSink`：采集出口。默认内存面板；`CsvSink` 在结束时写出六个 CSV。
- fincore：未来收益标签、方向和截面变换、固定权重组合、IC/Rank IC/ICIR、分层、覆盖率、分位换手、因子相关性和导出（含 `turnover` 表）。

`ResearchSpec.snapshot_id` 只是调用者的数据版本声明，不校验或生成面板身份；需要将声明用于评价时，须在 `ResearchEvaluationSpec` 中显式传入。

研究异常统一定义在 `backtrader.errors`，直接导入使用 `from backtrader.errors import ResearchError, ResearchConfigError`。`ResearchConfigError` 同时保留 `ValueError` 捕获行为；`backtrader.research.ConfigError` 是同一对象别名。

## 写一个因子

原生写法保留 `__init__`、`super()`、`self.p`、`self.datas` 和 `next()`。每个资产的输出是独立的 Backtrader 数值线，不能把整个截面的字典写进一条 float line。

```python
import math
import backtrader as bt
from backtrader.research import FactorIndicator


class CloseMAFactor(FactorIndicator):
    lines = ("factor",)
    params = (("period", 20),)
    panel_mode = "next"
    formula_fields = ("close",)

    @classmethod
    def lookback_h(cls, period=20):
        return period - 1

    def __init__(self):
        super().__init__()
        self.averages = {
            data: bt.ind.SMA(self.field("close", data), period=self.p.period)
            for data in self.target_datas
        }

    def next(self):
        for data in self.target_datas:
            value = float("nan")
            if len(data) >= self.p.period:
                close, average = self.field("close", data)[0], self.averages[data][0]
                if math.isfinite(close) and math.isfinite(average) and average != 0:
                    value = close / average
            self.outputs[data].factor[0] = value
```

`lookback_h` 表示当前格点之前需要的历史格数，20格均线为19。它不是“已经有足够有效数据”的保证：中间缺格仍会使该格点及其后 `lookback_h` 个格点的因子值记为 NaN。新增因子需要独立已知答案验证其 H 和真实首个有效时点。

普通 `bt.Indicator` 可以作为因子内部的子指标。配置不接受 `execution`、旧 `line` 或旧 `inputs`。

## 用 build 编写公式

`panel_mode = "expression"` 的类声明一个 `@classmethod build(cls, ctx, **params)`，返回单个表达式；无需编写资产循环或 `next()`。例如生产 Alpha003 的伴随实现为：

```python
class Alpha003Build(FactorIndicator):
    lines = ("factor",)
    panel_mode = "expression"
    formula_fields = ("open", "volume")
    lookback_h = 9

    @classmethod
    def build(cls, ctx, **params):
        return ctx.correlation(ctx.rank(ctx.open), ctx.rank(ctx.volume), 10) * -1.0
```

`ctx.open` 等字段必须已声明并显式绑定。表达式支持四则运算、幂、比较、`ctx.where(condition, yes, no)`。条件表达式不能进入 Python 的 `if`、`and`、`or` 或 `bool()`。H仍由类显式声明或按参数计算，不自动推导。

| 用途 | ctx接口 |
| --- | --- |
| 普通指标 | `sma/roc/highest/lowest(value, period)` |
| 逐点数学 | `abs/sign/log(value)`、`signed_power/minimum/maximum(left, right)` |
| Alpha101滚动算子 | `delay/delta/sum/product/stddev/ts_min/ts_max/ts_rank/ts_argmin/ts_argmax/decay_linear(value, period)` |
| 双输入滚动统计 | `correlation/covariance(left, right, period)` |
| 截面运算 | `rank(value)`、`scale(value, a=1.0)`、`indneutralize(value, groups, level=...)` |
| 条件与显式构图 | `logical_or/less_than/equal_to/subtract(left, right)`、`where(condition, yes, no)` |
| 收益率 | `returns()`，依次构造close的Delay(1)、Subtract和Divide |

Alpha101滚动算子沿用`alpha101-v2`的小数窗口取floor规则；普通SMA等接口仍要求正整数周期，两者的缺失值规则也不互换。分类通过同一ctx的字段表达式传入，例如`ctx.indneutralize(ctx.close, ctx.field("industry"), level="industry")`。`less_than`等显式入口可保留常量在左的比较顺序；纯常量减法用`ctx.subtract(1.0, weight)`才能保留实际节点及reason，Python的`1.0 - weight`会提前计算成一个数。

每个绑定后的因子实例只调用一次build。ctx构造普通Indicator/Line依赖，由Cerebro按原有时钟推进；不同研究组和实例不共享节点。build返回后上下文关闭，不能在运行期间继续构图，也不能混用另一实例的表达式。

`ctx.apply(function, *expressions)` 将无状态逐点函数适配为普通子指标，参数仅为当前各输入的float值。025/026的伴随类用它保留原生比值与KDJ逐点运算的有限值、除零及严格错误行为；SMA、ROC、Highest和Lowest仍是真实子指标。函数不接收历史数组、整个资产面板或调度权。研究四则算子的DOMAIN_ERROR/NaN语义与任意Python算式并非完全相同，迁移已有因子时应验证极端输入和错误行为。

选择生产Alpha实现使用 `get_alpha(id, mode="build")`，1至101均提供同文件伴随类；省略mode等同于native。全量验收状态见[48开发与验收记录](../../_internal/opts/requirements/迭代48-Alpha101-build实现/开发与验收记录.md)。025/026在各自示例文件内提供CloseMA、ROC和KDJ.J伴随类。build/native是公式编写方式，与 `runonce=True/False` 的引擎选择相互独立。

## 装配研究

调用方提供完整 UTC 网格。索引名为 `close_time`，另有 UTC `open_time` 列；每行是一根真实闭合 bar。网格必须包含预热、研究窗口，以及最长标签所需尾部。不要通过多个 Feed 日期的交集来生成研究日历。

```python
import backtrader as bt
from backtrader.research import FactorStrategy, MemorySink, ResearchSpec, align_to_grid

research = ResearchSpec(
    grid=grid,
    start=research_start,
    end=research_end,
    targets=("A", "B", "C"),
    source_timezone="Asia/Shanghai",
    calendar_id="declared-session-calendar-v1",
    frequency="1session",
    feed_time_kind="close_time",
    snapshot_id="local-snapshot-v1",
    price_basis="CNY_unadjusted_cash_equity",
)
cerebro = bt.Cerebro(stdstats=False)
for asset, frame in bars.items():
    aligned = align_to_grid(frame, research, asset)
    cerebro.adddata(aligned.feed, name=asset)
cerebro.addstrategy(
    FactorStrategy,
    research=research,
    factors={
        "close_ma": {
            "indicator": CloseMAFactor,
            "params": {"period": 20},
            "panel_line": "factor",
            "field_bindings": {"close": "feed:target:close"},
            "direction": 1,
        }
    },
    sink=MemorySink(),
)
strategy = cerebro.run()[0]
panel = strategy.get_panel()
```

`align_to_grid` 每个资产只做一次 `reindex`：返回截止研究 `end` 的 PandasData feed、计算网格的真实 bar 布尔标记，以及覆盖完整网格（含标签尾段）的 open/close 向量。它不维护 `available_at` 或 PIT as-of 选择。

输入缺格保持 NaN，不前填，也不删除后压缩时间。不同研究组分别进行公式截面计算；额外基准必须显式绑定，不自动变成输出资产。研究只处理同频、闭合的历史 bar，不支持 live、replay、tick 或混合频率。

研究输入使用可检查原始表格的 `PandasData`（或 `align_to_grid` 返回的 feed）。CSV 数据先读为 DataFrame，再明确时间和列映射；直接传入 `GenericCSVData` 会得到 `ResearchConfigError(code='UNSUPPORTED_SOURCE')`。

## 面板、CSV 与复评

`panel.factors` 是 `(time, asset)` 唯一 UTC MultiIndex 的 float64 宽表，只覆盖 `start` 至 `end` 的研究窗口；`panel.grid` 是完整网格，`panel.prices_open/close` 覆盖完整网格（可到标签尾段），`panel.universe` 是研究窗口的布尔宽表，`panel.groups` 是资产到研究分组的映射。

```python
panel.to_csv("research-panel")          # factors/grid/prices_open/prices_close/universe/groups

from backtrader.research import FactorPanel
restored = FactorPanel.from_csv(
    "research-panel",
    start=research.start,
    end=research.end,
    directions={"close_ma": 1},
    target_order=research.targets,
    factor_order=["close_ma"],
)
```

`from_csv` 必须显式获得 start/end、方向、目标顺序和因子顺序；它不从首末非空值推断区间，也不猜 long CSV 的列顺序。缺行、重复键、无穷值和缺文件都会报错；NaN 单元仍有实际行。CSV 是交换格式，没有 manifest、dataset ID 或内容哈希；需要校验的调用方自行计算文件哈希。

## 横截面与多个因子

Alpha003 的计算顺序为：同一时刻对 open 排名、对 volume 排名，然后按资产对两条排名历史做10格相关，最后取负。截面算子的默认成员是“该格点存在真实 bar”的资产；缺 bar 补出的网格行不进入 rank/scale。

同时研究三个因子时，在 `factors` 中配置三个类。它们各自产生原始输出，再由 fincore 按名称、方向、变换及权重组合。不能先对不同量纲的 raw 值直接相加，再把结果当作“各因子排名后的等权合成”。

```python
result = strategy.evaluate(
    periods=(1, 5, 20),
    label="next_open_to_open",
    preprocess="cross_section_rank",
    combinations={"equal_weight": {"close_ma": 1, "roc": 1, "kdj": 1}},
    quantiles=5,
    min_assets=10,
)
result.export("research-report", charts=True)
```

`FactorStrategy.evaluate(...)` 只是 `evaluate_frames(panel, spec)` 的便捷入口。组合成员缺失时不填零、不动态重分权重；显式零权重成员仍是声明的必需成员。

## 标签与结果解释

默认 next-open 标签为 `open[t+1+h] / open[t+1] - 1`，h 是网格 bar 数。h=20 至少需要21根尾部 bar。close-to-close 是统计标签，不表示收盘信号可以在相同收盘价成交。

Pearson IC 衡量数值关系，Rank IC 对两边取秩后衡量排序关系；ICIR 使用有限 IC 序列的样本标准差（ddof=1），不年化。常数、小截面、重复分位边界、零 IC 标准差和缺标签应保留明确原因。

默认损失上限为0.35。分母包含研究窗口内全部 eligible 候选；共同池形成损失也必须计入。重叠的5/20-bar分层收益不直接复利成成交净值。

## Alpha101 的数据边界

`alpha101-v2` 冻结平均秩/n、完整窗口、总体方差/协方差、行业去均值、幂和三值布尔等工程语义。运行时统一 float64：相关/协方差用中心化、缩放和 `math.fsum` 的稳定核；完整常量窗口的协方差和标准差为 0，而常量输入的相关系数为 NaN+DOMAIN_ERROR；单值总体协方差为 0。rank 按实际 float64 精确相等分组，不引入 epsilon。

VWAP 必须是明确来源字段，不能用 OHLC 均价偷偷替代；ADV 的直接字段与显式派生路径互斥。行业/板块/子行业编码是普通 feed 数值线：18 个需要分类的公式把它们声明在 `formula_fields` 中，并要求 `feed:<name>:<line>` 绑定；未知编码为 NaN，不填默认行业。时间变化的编码由调用者逐 grid 预先提供，研究层不维护分类历史。

框架可以处理多种资产，但股票市值和行业字段不适用于所有市场。负价期货、连续合约换月、乘数或资金费相关收益需要有明确定义的预计算标签。公式数值复现不等于复现论文使用的专有数据、收益或交易成本。

正式例子为 `examples/backtest/025_factor_single`、`026_factor_multi` 和 `027_alpha003_panel_acceptance`；三个 quick `run.py` 入口使用 `tests/datas/a_stocks` 的逐股真实日线，默认从 manifest 均匀抽样500只股票，可用 `--max-symbols 0` 使用全部股票，日历取源文件观测到的交易日并集。它们演示 API 和可复现研究，不证明因子具有投资价值。025/026 两个入口先完成原生采集并写出 `factor_values.csv`，可用 `--save-panel` 保存 CSV 面板、`--panel` 跳过 Cerebro 直接复评；只有评价阶段需要含研究 API 的 fincore，该 API 缺失时会跳过评价并以 `PANEL_ONLY` 正常退出。

三个quick入口均可传 `--factor-mode native|build`，优先级为CLI、config.yaml的factor_mode、native默认值。026整体切换三个因子，列顺序仍为close_ma、kdj_j、roc。025/026的 `--panel` 只复评已有面板，不能同时显式传 `--factor-mode`；摘要记录 `factor_mode="NOT_APPLICABLE"`、`factor_calculation="NOT_RUN"`。

027 的 `run_daily.py` 是独立的全市场分块/续跑入口，`--chunk-days` 控制分块；它不使用quick YAML、500只默认值或 `--report` 参数。daily也支持 `--factor-mode native|build`，默认native。模式进入运行指纹并传至实际worker，同一输出目录不能跨模式续跑；为另一模式选择新目录。47的daily验收使用小型多分段真实子进程，不代表5,471只全年验收完成。

需要专业因子图表时，三个 quick `run.py` 入口都支持 `--report`（`--report-language zh|en` 选择默认语言），生成自包含的 `factor_report_<factor>.html`。报告实现位于 fincore 的 `fincore.report.factor.write_factor_report(factor, prices, path, ...)`；Backtrader 的 `write_factor_report(panel, factor_name, path)` 会应用该因子的显式方向，并按 `label` 传入原始价格。默认 `next_open_to_open` 使用开盘价与 `next_open=True`，`close_to_close` 使用收盘价与 `next_open=False`；标签只由 fincore 计算一次。025/026 的报告采用与研究评价相同的配置标签，027 保持默认 next-open。评价和报告不修改传入面板的帧、索引或属性。
