# 原生 Alpha101 因子

本文说明如何通过 Backtrader 的研究生命周期运行已提升为原生类的 Alpha101 因子。Alpha101 是公式目录，不是交易策略：这里采集的是每个目标资产、每个研究格点上的原始因子值。

> **实现状态（2026-10-22）**：迭代46已完成；101个native类、独立数学参考、完整源码场景、已提交wheel上的6项研究场景及025/026集成验收均通过（AC46-01–06 PASS）。已安装包的 `list_alphas()` 返回1至101。详见[迭代46验收结果](../../_internal/opts/requirements/迭代46-Alpha101原生因子实现/验收结果.md)、[安装验收摘要](../../_internal/opts/requirements/迭代46-Alpha101原生因子实现/evidence/iteration46-installed-20261022/summary.json)及[025/026集成摘要](../../_internal/opts/requirements/迭代46-Alpha101原生因子实现/evidence/iteration46-examples-20261022/summary.json)。后续build前端和全101 native/build对齐分别属于迭代47和48。

**历史验收（2026-10-23，单类重构之前）**：45–46优化、47和48均完成本地验收。47的四公式build、三个500资产quick完整配对及固定wheel上的132项检查见[47验收结果](../../_internal/opts/requirements/迭代47-因子build简洁模式与算子增强/验收结果.md)。48全部101个build伴随类通过T320/T640/T1280四路源码矩阵、下游12表及101对实际报告、新wheel149项检查，详见[48验收结果](../../_internal/opts/requirements/迭代48-Alpha101-build实现/验收结果.md)。固定fixture中的14式不可三分位原因保留；完整配对PASS不表示每式都有可用IC。

本轮直接继承 `FactorIndicator` 的结构重构、模块清理与新验收范围见[重构记录](../../_internal/opts/requirements/迭代46-Alpha101原生因子实现/直接FactorIndicator重构记录.md)。原迭代46安装验收对应其记录的源码版本。

此前无用封装删除、接口迁移以及保留原生 Feed 子指标的反例见[封装清理记录](../../_internal/opts/requirements/迭代46-Alpha101原生因子实现/原生研究封装清理记录.md)。该历史检查点为376项源码检查及3项安装smoke，未执行当时的完整installed fincore矩阵；旧双类版本的源码与安装状态以上述48验收结果为准；当前单类重构见[49记录](../../_internal/opts/requirements/迭代49-因子单类双模式重构/实施与验收.md)。真实全市场吞吐仍未验收。

**当前单类版本**：49已完成本地源码和固定wheel验收，101个原类均包含native与build方法；725项单测、三种历史长度四路矩阵、完整下游比较以及159项安装测试通过。用法和精确证据见[49记录](../../_internal/opts/requirements/迭代49-因子单类双模式重构/实施与验收.md)。

## 查找原生因子

`get_alpha()` 返回一个具体的 `FactorIndicator` 子类；将这个类交给 `FactorSpec`，再由 `FactorStrategy` 装配。`list_alphas()` 返回当前已经登记的升序 ID 元组，是检查当前运行环境可用公式的权威接口。注册表只读；ID 必须是普通整数，`bool` 不算整数 ID，未知或尚未登记的 ID 会报错。

```python
from backtrader.research.alpha101 import get_alpha, list_alphas

registered_ids = list_alphas()
alpha003_class = get_alpha(3)
alpha101_class = get_alpha(101)

assert 3 in registered_ids
```

每个ID只返回原来的一个类，保留`Alpha003Native`等类名与只读注册表。两种实现合并在该类中，通过`FactorSpec(..., mode="native")`或`FactorSpec(..., mode="build")`选择；直接绑定使用`alpha003_class.bind(*datas, mode="build")`。生产类省略mode默认native。`get_alpha`不再接受mode，旧双类调用须迁移到绑定配置。具体验收状态见[单类双模式记录](../../_internal/opts/requirements/迭代49-因子单类双模式重构/实施与验收.md)和[逐式台账](../../_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/Alpha101覆盖清单.md)。

写自己的公式时，直接继承 `FactorIndicator` 并声明 `formula_fields`、`lookback_h`、输出线及计算过程。生产库的 101 个类分别位于 `alpha101/alpha001.py` 至 `alpha101/alpha101.py`，全部直接继承 `FactorIndicator`：在普通 `__init__` 中调用 `super().__init__()` 并组合原生子指标，在 `next` 中写入目标资产的输出线。原生因子和自定义因子都用 `FactorSpec` 与 `FactorStrategy` 运行。

每个原类现在也定义`@classmethod build`。选择build时只构造表达式子图，跳过原生初始化、next和自定义once阶段；选择native时不调用build。自定义因子允许只实现其中一种，省略mode时按类能力选择。显式H、字段和原式共用同一份声明。表达式接口和窗口规则见[build指南](factor-research.md#用-build-编写公式)。

Alpha ID、原式、窗口、`alpha101-v2` profile、字段依赖（含行业编码字段）直接声明在因子类上。`FactorSpec` 固定一次运行的参数、字段绑定、方向、H 与类源码摘要。重复保存类属性的公式/实现身份对象已经移除；读取原式使用 `get_alpha(id).formula`。改写算法实现不应悄悄改动原式或输入口径。

## 实现结构与模块职责

`research/_helpers.py` 只负责逐资产创建子指标、绑定截面子指标和保留真实中间节点引用。公式运算仍由 Backtrader 的 Indicator/Lines 对象执行，所有节点都由 Cerebro 推进；`_metadata.py` 验证并规范化类声明。原来的 `NativeAlphaBase`、`_make_formula` 钩子和按实施批次组织的公式模块已移除。多个研究组分别构造真实因子实例，诊断时直接读取这些实例的节点。

其余研究模块保留各自实际使用的职责：

| 模块 | 运行职责 |
| --- | --- |
| `factor_indicator.py` | 原生指标生命周期、字段绑定、逐资产输出；截面成员只按真实 bar 判定 |
| `_expression.py` | 将build表达式适配为现有Indicator/Line依赖；不另行计算或调度 |
| `factor_strategy.py` | 装配因子，按格点采集输出到 `FactorSink` 并产出 `FactorPanel` |
| `operators.py` | Alpha101 的原生子指标，包括截面秩、行业中性化及 float64 滚动算子 |
| `specs.py` | 冻结运行配置和 `feed:<name>:<line>` 字段绑定 |
| `align.py` | 每资产一次 `reindex` 的轻量网格对齐与真实 bar 标记 |
| `panel.py`、`sink.py` | 五类普通帧容器、CSV 往返与内存/CSV 采集出口 |
| `backtrader/errors.py`、`research/strict.py` | 区分计算错误与真实缺失并向上传播 |
| `fincore_adapter.py`、`factor_report.py` | 薄适配 `evaluate_frames(panel, spec)` 与 fincore HTML 报告 |

这些算子不能仅按名称替换成近似指标。例如 Backtrader `PercentRank` 与 Alpha101 的并列秩定义不同，相关系数的常量窗口和数值精度也有固定合同。已有算子本身就是原生 Indicator/FactorIndicator 子类；共享调度、时钟和预热机制继续由 Backtrader 提供。

原来的 20 个诊断因子实现及其测试侧基类、构建钩子已删除。原有数值、时钟、缺失与中间值测试直接运行生产因子，并保留独立的纯 Python 数学参考。论文公式目录位于 `tests/fixtures/research/alpha101_dependencies.json`，供独立参考计算读取，不随运行包安装。具体迁移及验收见[测试清理记录](../../_internal/opts/requirements/迭代46-Alpha101原生因子实现/测试旧实现清理记录.md)。

## 数据与时间网格

调用方必须提供完整、明确的 `ResearchSpec.grid`，不得从各 Feed 日期的交集或普通工作日序列推断交易日历。`grid` 是 DataFrame，索引为严格递增、唯一、带 UTC 时区的 `DatetimeIndex`，索引名为 `close_time`，另有不晚于收盘时刻的 UTC `open_time` 列。网格包含研究开始前的计算预热；如还要评价未来收益，也要包含所需的标签尾部。`start`、`end` 必须是网格上的准确收盘时间。

`targets` 必须明确列出输出资产，`groups` 明确截面排名分组。`universe` 只描述研究窗口中每个格点的评价资格，不改变已计算的公式值；公式的截面成员由“该格点是否存在真实 bar”决定，缺 bar 补出的网格行不进入 rank/scale。动态公式池/PIT 成员接口已移除：需要限制历史成员时，由调用者在普通 feed 中提供已对齐的数值/布尔字段并显式绑定。

`align_to_grid()` 将每个资产的 Pandas OHLCV DataFrame 对齐到完整网格，只做一次 `reindex`，返回 feed、真实 bar 布尔标记和完整网格的 open/close 向量。缺失行保持 NaN；不会前填、压缩时间或通过丢行隐藏缺口。下面示例假定 `bars` 的键是资产名，值是索引带时区的 DataFrame，至少包含标准 `open/high/low/close/volume` 列；示例中的 `grid`、`research_start`、`research_end`、日历和数据版本由调用方提供，并已按真实数据源准备。

## 单因子：原生 Alpha003

Alpha003 先在每个格点对 `open` 与 `volume` 做截面秩，再对每个资产的秩序列计算十格相关并取负。公式需要同一时点的截面，因此应使用能覆盖完整目标集合的同步网格。

```python
import pandas as pd
import backtrader as bt

from backtrader.research import (
    FactorSpec,
    FactorStrategy,
    MemorySink,
    ResearchSpec,
    align_to_grid,
)
from backtrader.research.alpha101 import get_alpha


def all_membership(times, assets):
    keys = pd.MultiIndex.from_product([times, assets], names=("time", "asset"))
    return pd.Series(True, index=keys, dtype=bool)


def run_factor_panel(research, bars, factors, *, data_version, runonce=True):
    cerebro = bt.Cerebro(stdstats=False)
    for asset in research.targets:
        aligned = align_to_grid(bars[asset], research, asset, data_version=data_version)
        cerebro.adddata(aligned.feed, name=asset)
    cerebro.addstrategy(FactorStrategy, research=research, factors=factors, sink=MemorySink())
    strategy = cerebro.run(runonce=runonce)[0]
    return strategy.get_panel()


targets = tuple(bars)
study_times = grid.index[(grid.index >= research_start) & (grid.index <= research_end)]

# 以下标识由调用者按实际数据版本、价格口径与日历填写。
# snapshot_id 仅作版本声明，研究层不生成或验证数据快照身份。
research = ResearchSpec(
    grid=grid,
    start=research_start,
    end=research_end,
    targets=targets,
    source_timezone="UTC",  # bars 的索引已经标准化为 UTC
    snapshot_id=snapshot_id,
    price_basis=price_basis,
    calendar_id=calendar_id,
    frequency=frequency,
    feed_time_kind="close_time",
    groups={asset: "equity-universe" for asset in targets},
    universe=all_membership(study_times, targets),
)

alpha003 = FactorSpec(
    name="alpha003",
    indicator=get_alpha(3),
    panel_line="factor",
    field_bindings={
        "open": "feed:target:open",
        "volume": "feed:target:volume",
    },
    direction=1,
)

panel = run_factor_panel(
    research,
    bars,
    {"alpha003": alpha003},
    data_version=bars_data_version,
    runonce=True,
)
```

这里只显式传入了研究窗口的 `universe`；公式的截面成员由真实 bar 决定，适用于稳定的合成数据。实际股票池、行业池或可交易资格会随历史变化时，应由可信的数据源生成已对齐的普通 feed 字段。`runonce=False` 可用于事件驱动模式对照；两种模式都由 Cerebro 推进，调用者不能手动执行因子的 `next()`、`once()` 或 `advance()`。

纯时序的 Alpha009 也通过同一入口运行，不需要为了时序公式添加截面步骤：

```python
alpha009_class = get_alpha(9)
alpha009 = FactorSpec(
    name="alpha009",
    indicator=alpha009_class,
    panel_line="factor",
    field_bindings={
        field: "feed:target:%s" % field
        for field in alpha009_class.formula_fields
    },
    direction=1,
)
```

## 多因子：Alpha005、Alpha006 与 Alpha101

这组因子演示共享一个网格和一组 Feed 的多因子采集：Alpha005 使用 `open/vwap/close`，Alpha006 使用 `open/volume`，Alpha101 使用 OHLC。构造器先检查当前运行时登记表；使用较早版本或未包含某个批次的环境会明确报出缺失 ID，不会替未登记公式创建占位实现。

Alpha005 的 VWAP 不是 Backtrader 标准 OHLCV 行，需要由调用者在 feed 上显式提供同名列（例如 `class VwapPandasData(bt.feeds.PandasData): lines = ("vwap",)`），并在 `FactorSpec.field_bindings` 中写 `"vwap": "feed:target:vwap"`。不要用 `(high + low + close) / 3` 冒充 VWAP。

```python
from backtrader.research import FactorSpec
from backtrader.research.alpha101 import get_alpha


alpha005 = get_alpha(5)
alpha006 = get_alpha(6)
alpha101 = get_alpha(101)

factors = {
    "alpha005": FactorSpec(
        name="alpha005",
        indicator=alpha005,
        panel_line="factor",
        field_bindings={field: "feed:target:" + field for field in alpha005.formula_fields},
        direction=1,
    ),
    "alpha006": FactorSpec(
        name="alpha006",
        indicator=alpha006,
        panel_line="factor",
        field_bindings={field: "feed:target:" + field for field in alpha006.formula_fields},
        direction=1,
    ),
    "alpha101": FactorSpec(
        name="alpha101",
        indicator=alpha101,
        panel_line="factor",
        field_bindings={field: "feed:target:" + field for field in alpha101.formula_fields},
        direction=1,
    ),
}

# 各目标 Feed 仍通过 align_to_grid 加入同一个 Cerebro；VWAP 列随 bars 一起对齐。
panel = run_factor_panel(
    research,
    bars,
    factors,
    data_version=bars_data_version,
    runonce=True,
)
```

需要美元成交额或 ADV 的公式在 `formula_fields` 中声明 `dollar_volume`/`advN`，同样绑定普通 feed 行，或用 `{"derive": "vwap_volume", "vwap": "vwap", "volume": "volume"}` / `{"derive": "adv", "source": "dollar_volume", "window": 20}` 显式派生。字段列名本身不证明单位、复权方式或来源，这些由调用者负责。

无论组合哪些公式，每个因子都要独立配置 `FactorSpec`；不要把不同量纲的原始值先相加冒充截面秩变换或等权合成。方向、预处理、共同评价池、标签和组合权重属于后续评价配置，不改变 Alpha 原始公式。

## 字段绑定、ADV 与行业编码

`FactorSpec.field_bindings` 的键必须来自该类声明的 `formula_fields`，来源统一使用 `feed:<name>:<line>`；`feed:target:<line>` 表示同名目标 Feed 行。PIT 表、`table:` 绑定、`classification_bindings` 和逐格可用时点记录已从研究层删除。

非 OHLCV 字段（VWAP、直接 ADV、行业/板块/子行业编码、市值等）由调用者在 feed 上显式提供对应行。例如：

```python
import backtrader as bt


class ClassifiedPandasData(bt.feeds.PandasData):
    lines = ("subindustry",)  # industry / sector 使用各自同名数值列
    params = (("subindustry", "subindustry"),)


alpha048 = FactorSpec(
    name="alpha048",
    indicator=get_alpha(48),
    panel_line="factor",
    field_bindings={
        "close": "feed:target:close",
        "subindustry": "feed:target:subindustry",
    },
    direction=1,
)
```

Alpha048 需要 251 格历史跨度以及按子行业去均值。它现在读取调用者提供的 `subindustry` 数值编码线；未知编码为 NaN，不会被当作一个普通行业类别，也不会用今天的分类回填历史。时间变化的编码由调用者逐 grid 预先提供，研究层不维护分类历史。

当前 18 个公式需要行业编码：`industry` 为 059/063/069/070/080/087/089/091/093/097，`sector` 为 058/067/076/079/082，`subindustry` 为 048/067/090/100（067 同时跨两个层级）。这些字段已并入 `formula_fields` 和普通 `feed:<name>:<line>` 路径；缺必需输入时装配即失败，不填默认行业。

依赖 ADV 的公式可以直接绑定调用者提供的 `advN` 行，或显式选择引擎支持的派生方式：从 `dollar_volume` 对 `N` 个历史格点取均值，或从单位一致、复权口径一致的 VWAP 与 volume 相乘得到 `dollar_volume`。VWAP 必须是明确来源字段，不能用 OHLC 均价偷偷替代；不要把 volume 本身当 ADV，也不要同时提供互相冲突的直接值和派生定义。详细合同见[研究指南中的 Alpha101 数据边界](factor-research.md)。

数值口径（`alpha101-v2`）：相关/协方差分别中心化并缩放偏差，使用 `math.fsum` 累加；协方差通过指数安全乘法恢复尺度，避免中间溢出或下溢。常量窗口按原始值判定（协方差 0，相关为 DOMAIN_ERROR）。合法的近零或近 ±1 相关值不作吸附，只有计算舍入导致的极窄越界允许裁回数学边界。rank 始终按实际 float64 精确相等分组。此前按最终值多重集、资产列置换或固定行数偏差预算进行的验收不足以排除接线和排序错误，已在本轮续验中撤回；全 101 验收采用独立公式表达式与逐节点数值检查，结果以本轮验收记录为准。

行业/市值/ADV 的发布时间、单位、复权和数据版本由调用者负责；研究层只做一次形状、索引、字段和配置检查，不再逐格构造来源/可用性对象。

## H、预热与标签

`lookback_h` 是因子当前格点之前需要的历史网格跨度，不是“此时一定有有效值”的承诺。H=251 的因子需要当前点以及之前251个网格间隔，即完整输入至少跨252个格点；缺 bar、字段迟到或普通 feed 分类编码缺失可能使输出继续为 NaN。预热长度应按公式的嵌套窗口和真实源数据共同核对，不能只按自然日估算。

因子输出与未来收益标签是两类数据。若公式身份注明 `paper_signal_delay=0`，它描述该公式在当前格点生成信号的时序约定；它既不是 forward-return label，也不表示可以在同一收盘价成交。评价标签由单独的评估 API 生成，例如 next-open 标签 `open[t+1+h] / open[t+1] - 1`，需要额外的尾部 bar。`FactorSpec.direction` 影响下游评价方向，不改写原生公式已定义的正负号。

采集因子值、构建 FactorPanel 和保存 CSV 面板不依赖 fincore；`strategy.evaluate(...)` 才会按需要加载 fincore 的研究 API。IC、Rank IC、分层统计和组合结果是研究统计，不是含交易费用、滑点、成交约束和资金管理的策略收益。公式数值复现也不代表复现论文专有数据、股票池或论文收益。

## 示例与进一步阅读

- [025：单因子 FactorIndicator/FactorStrategy 示例](../../../examples/backtest/025_factor_single/README.md)及其[因子源码](../../../examples/backtest/025_factor_single/close_ma_factor_strategy.py)。
- [026：多因子采集和离线组合示例](../../../examples/backtest/026_factor_multi/README.md)及其[因子源码](../../../examples/backtest/026_factor_multi/multi_factor_strategy.py)。
- [027：Alpha003 的真实日线示例](../../../examples/backtest/027_alpha003_panel_acceptance/README.md)及其[入口源码](../../../examples/backtest/027_alpha003_panel_acceptance/run.py)。两种模式均使用生产库的`Alpha003Native`，`--factor-mode build`选择该类的build方法；quick和daily均支持模式选择。这个单式示例不代表全库验收。
- [迭代45原生因子研究指南](factor-research.md)：统一 API、面板/CSV 复评和字段来源。
- [迭代45设计文档](../../_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/设计文档.md)：`alpha101-v1` 历史语义、字段血缘、ADV、美元成交额与 VWAP；PIT 部分仅作历史说明。
- [迭代45代表公式与验收材料](../../_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/Alpha101代表验收案例.md)：代表公式及其独立参考背景。
- [迭代46计划](../../_internal/opts/requirements/迭代46-Alpha101原生因子实现/迭代计划.md)：101式逐批范围、H/PIT/边界验收门槛和当前状态。
