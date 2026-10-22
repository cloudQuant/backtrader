# 原生 Indicator 因子研究

迭代45把因子计算留在 Backtrader，把标签、IC、多因子合成与报告放在 fincore。所有研究因子继承 `FactorIndicator`；`FactorStrategy` 负责装配和采集，作者不用为每个因子重写策略的 `next()`。

逐项验收状态见[迭代45验收结果](../../_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/验收结果.md)，分轮提交与检查记录见[迭代45开发记录](../../_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/开发与验收记录.md)。后续 build 简洁写法属于迭代47，完整101个生产因子属于迭代46/48。

## 环境与职责

研究入口要求 Python 3.11 及 pandas。普通 Backtrader 核心仍支持其原有 Python 范围；采集、保存、加载原始数据集不需要 fincore。只有评价时才加载包含本轮研究 API 的 fincore 安装产物，不能用同版本号的旧包替代。

- `FactorIndicator`：原生参数、输入、子指标、逐资产输出线和计算过程。
- `ResearchSpec` / `FactorSpec`：日历、研究窗口、输入来源、目标资产、分组、因子参数及绑定。
- `FactorStrategy`：原生指标装配、同步网格采集和可用性诊断；不提交或撤销订单。
- `ResearchDataset`：不可变快照、保存/加载及离线复评。
- fincore：未来收益标签、方向和截面变换、固定权重组合、共同池/消融、IC/Rank IC/ICIR、分层、覆盖、换手、相关性和导出。

研究异常统一定义在 `backtrader.errors`，直接导入使用 `from backtrader.errors import ResearchError, ResearchConfigError`。`ResearchError` 继承 `BacktraderError`，因此可以按研究领域或整个框架捕获异常；研究异常继续提供 `code` 和只读 `report`。`ResearchConfigError` 同时保留 `ValueError` 捕获行为，与框架通用的 `ConfigError` 分开。`backtrader.research.ConfigError` 是 `ResearchConfigError` 的同一对象别名；原 `backtrader.research.errors` 模块已移除。

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

`lookback_h` 表示当前格点之前需要的历史格数，20格均线为19。它不是“已经有足够有效数据”的保证：中间缺格仍可能使窗口不可用。新增因子需要独立已知答案验证其 H 和真实首个有效时点。

普通 `bt.Indicator` 可以作为因子内部的子指标。研究入口本身统一为 `FactorIndicator`，配置不接受 `execution`、旧 `line` 或旧 `inputs`。

## 装配研究

调用方提供完整 UTC 网格。索引名为 `close_time`，另有 UTC `open_time` 列；每行是一根真实闭合 bar。网格必须包含预热、研究窗口，以及最长标签所需尾部。不要通过多个 Feed 日期的交集来生成研究日历。

```python
from backtrader.research import FactorStrategy, ResearchSpec, prealign_bars

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
    aligned = prealign_bars(frame, research, asset)
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
)
strategy = cerebro.run()[0]
dataset = strategy.get_dataset()
dataset.save("research-data")
```

输入缺格保持 NaN，不前填，也不删除后压缩时间。不同研究组分别进行公式截面计算；额外基准必须显式绑定，不自动变成输出资产。初版研究只处理同频、闭合的历史 bar，不支持 live、replay、tick 或混合频率。

研究输入使用可检查原始表格的 `PandasData` 或 `prealign_bars`。CSV 数据先读为 DataFrame，再明确时间和列映射；直接传入 `GenericCSVData` 会得到 `ResearchConfigError(code='UNSUPPORTED_SOURCE')`。这样可以在旧 Feed 加载逻辑处理数值前发现源数据中的无穷值，避免把它误当成合法的零。

## 横截面与多个因子

Alpha003 的计算顺序为：同一时刻对 open 排名、对 volume 排名，然后按资产对两条排名历史做10格相关，最后取负。因子仍在自己的 `next()` 中写算法；公共策略不需要知道排名和相关的细节。027 示例保留输入、中间排名和最终值，便于阅读计算过程。

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

这个调用要求采集时已配置 `close_ma`、`roc`、`kdj`。组合成员缺失时不填零、不动态重分权重；显式零权重成员仍是声明的必需成员。公平比较和消融固定共同样本池，并在池内重新计算评价变换。评价池不能反过来改变 Alpha 公式内部的历史截面排名。

## 标签与结果解释

默认 next-open 标签为 `open[t+1+h] / open[t+1] - 1`，h 是网格 bar 数。h=20 至少需要21根尾部 bar。close-to-close 是统计标签，不表示收盘信号可以在相同收盘价成交。分期边界按入场和退出所属 bar 判断，不把跨期收益归给单个分期。

Pearson IC 衡量数值关系，Rank IC 对两边取秩后衡量排序关系；ICIR 使用有限 IC 序列的样本标准差（ddof=1），不年化。常数、小截面、重复分位边界、零 IC 标准差和缺标签应保留明确原因。分箱失败不应删除仍然可计算的 IC。

默认损失上限为0.35。分母包含研究窗口内全部 eligible 候选；共同池形成损失也必须计入。超过任一请求序列的上限会抛出带诊断的质量异常，不能靠先删除缺失资产改善覆盖率。重叠的5/20-bar分层收益不直接复利成成交净值。

## 保存后复评

```python
from backtrader.research import load_dataset, evaluate_dataset

saved = load_dataset("research-data")
result = evaluate_dataset(saved, periods=(1, 10))
result.export("research-report-1-10", charts=False)
```

此过程不执行 Cerebro 或原始因子类。使用相同评价配置时，保存前后的评价 ID 和导出表应完全一致；时间索引的可推导频率及截窗留下的未使用索引项不改变评价身份。更改方向、权重、标签周期等评价参数产生新的评价身份；更改公式、历史资产池、输入绑定或原始数据需要重新采集。加载会验证 schema、文件摘要和完成标记，不反序列化可执行 Python 对象。

## Alpha101 的数据边界

`alpha101-v1` 冻结平均秩/n、完整窗口、总体方差/协方差、行业去均值、幂和三值布尔等工程语义。VWAP 必须是明确来源字段，不能用 OHLC 均价偷偷替代；ADV 的直接字段与显式派生路径互斥。市值、行业层级、分类体系版本和 available_at/effective_at 必须具有明确语义。

特殊字段的来源声明放在表格 `attrs['source_metadata']`；一个 Feed 包含多个特殊字段时，用 `{'fields': {字段名: 声明}}`。直接 ADV 要声明日均美元成交额、完整窗口、窗口长度和来源版本；VWAP 与成交量派生需要价格单位、数量单位和一致的复权口径。只提供列名不能证明这些含义。数据集保存显式绑定字段的值、可用时刻、版本和来源声明；缺少独立数据版本时会明确记录使用了调用方的 `snapshot_id`。

滚动协方差对实际输入的 binary64 数值精确累计，最后一次舍入到浮点输出，保留近零结果的符号。截面排序不以容差把不同值合并为并列。

formula_universe 覆盖预热历史并保留当时成员；评价 universe 只定义研究窗口的统计资格。未知成员不能默认为不在池中，行业分类不能用今天的分类回填历史。

框架可以处理多种资产，但股票市值和行业字段不适用于所有市场。负价期货、连续合约换月、乘数或资金费相关收益需要有明确定义的预计算标签。公式数值复现不等于复现论文使用的专有数据、收益或交易成本。

正式例子为 `examples/backtest/025_factor_single` 和 `026_factor_multi`；两者使用相同的20资产确定性输入、260个研究 bar、20格预热和21格尾部，并固定前160/后100格分期。它们演示 API 和可复现研究，不证明因子具有投资价值。
