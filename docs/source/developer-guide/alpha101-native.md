# 原生 Alpha101 因子

本文说明如何通过 Backtrader 的研究生命周期运行已提升为原生类的 Alpha101 因子。Alpha101 是公式目录，不是交易策略：这里采集的是每个目标资产、每个研究格点上的原始因子值。

> **实现状态（2026-10-22）**：迭代46已完成；101个native类、独立数学参考、完整源码场景、已提交wheel上的6项研究场景及025/026集成验收均通过（AC46-01–06 PASS）。已安装包的 `list_alphas()` 返回1至101。详见[迭代46验收结果](../../_internal/opts/requirements/迭代46-Alpha101原生因子实现/验收结果.md)、[安装验收摘要](../../_internal/opts/requirements/迭代46-Alpha101原生因子实现/evidence/iteration46-installed-20261022/summary.json)及[025/026集成摘要](../../_internal/opts/requirements/迭代46-Alpha101原生因子实现/evidence/iteration46-examples-20261022/summary.json)。后续build前端和全101 native/build对齐分别属于迭代47和48。

本轮直接继承 `FactorIndicator` 的结构重构、模块清理与新验收范围见[重构记录](../../_internal/opts/requirements/迭代46-Alpha101原生因子实现/直接FactorIndicator重构记录.md)。原迭代46安装验收对应其记录的源码版本。

后续无用封装删除、接口迁移以及保留原生 Feed 子指标的反例见[封装清理记录](../../_internal/opts/requirements/迭代46-Alpha101原生因子实现/原生研究封装清理记录.md)。本轮 376 项源码检查和 3 项安装 smoke 通过，完整 installed fincore 矩阵及真实全市场重跑未执行。

## 查找原生因子

`get_alpha()` 返回一个具体的 `FactorIndicator` 子类；将这个类交给 `FactorSpec`，再由 `FactorStrategy` 装配。`list_alphas()` 返回当前已经登记的升序 ID 元组，是检查当前运行环境可用公式的权威接口。注册表只读；ID 必须是普通整数，`bool` 不算整数 ID，未知或尚未登记的 ID 会报错。

```python
from backtrader.research.alpha101 import get_alpha, list_alphas

registered_ids = list_alphas()
alpha003_class = get_alpha(3)

assert 3 in registered_ids
```

写自己的公式时，直接继承 `FactorIndicator` 并声明 `formula_fields`、`lookback_h`、输出线及计算过程。生产库的 101 个类分别位于 `alpha101/alpha001.py` 至 `alpha101/alpha101.py`，全部直接继承 `FactorIndicator`：在普通 `__init__` 中调用 `super().__init__()` 并组合原生子指标，在 `next` 中写入目标资产的输出线。原生因子和自定义因子都用 `FactorSpec` 与 `FactorStrategy` 运行。

Alpha ID、原式、窗口、`alpha101-v1` profile、字段/分类依赖及公式池/PIT 语义直接声明在因子类上。`FactorSpec` 固定一次运行的参数、字段绑定、方向、H 与类源码摘要。重复保存类属性的公式/实现身份对象已经移除；读取原式使用 `get_alpha(id).formula`。改写算法实现不应悄悄改动原式或输入口径。

## 实现结构与模块职责

`alpha101/_helpers.py` 只负责逐资产创建子指标、绑定截面子指标和保留真实中间节点引用。公式运算仍由 Backtrader 的 Indicator/Lines 对象执行，所有节点都由 Cerebro 推进；`_metadata.py` 验证并规范化类声明。原来的 `NativeAlphaBase`、`_make_formula` 钩子和按实施批次组织的公式模块已移除。多个研究组分别构造真实因子实例，诊断时直接读取这些实例的节点。

其余研究模块保留各自实际使用的职责：

| 模块 | 运行职责 |
| --- | --- |
| `factor_indicator.py` | 原生指标生命周期、字段绑定、逐资产输出及可用性状态 |
| `factor_strategy.py` | 装配因子，按格点采集输出并生成研究数据集 |
| `operators.py` | Alpha101 的原生子指标，包括截面秩、行业中性化及固定数值口径的滚动算子 |
| `specs.py`、`inputs.py` | 冻结运行配置、对齐 Feed 和点时输入；025/026/027 均使用这些输入接口 |
| `backtrader/errors.py`、`research/strict.py`、`research/field_validation.py` | 区分计算错误与真实缺失，检查字段来源、数值和时间可用性 |
| `dataset.py` | 保存原始因子面板、缺失原因及输入来源的不可变快照 |
| `storage.py`、`fincore_adapter.py`、`factor_report.py` | 为现有示例提供数据集保存/复评，以及 fincore 的评价和 HTML 报告接口 |

这些算子不能仅按名称替换成近似指标。例如 Backtrader `PercentRank` 与 Alpha101 的并列秩定义不同，相关系数的常量窗口和数值精度也有固定合同。已有算子本身就是原生 Indicator/FactorIndicator 子类；共享调度、时钟和预热机制继续由 Backtrader 提供。

原来的 20 个诊断因子实现及其测试侧基类、构建钩子已删除。原有数值、时钟、缺失与中间值测试直接运行生产因子，并保留独立的纯 Python 数学参考。论文公式目录位于 `tests/fixtures/research/alpha101_dependencies.json`，供独立参考计算读取，不随运行包安装。具体迁移及验收见[测试清理记录](../../_internal/opts/requirements/迭代46-Alpha101原生因子实现/测试旧实现清理记录.md)。

## 数据与时间网格

调用方必须提供完整、明确的 `ResearchSpec.grid`，不得从各 Feed 日期的交集或普通工作日序列推断交易日历。`grid` 是 DataFrame，索引为严格递增、唯一、带 UTC 时区的 `DatetimeIndex`，索引名为 `close_time`，另有不晚于收盘时刻的 UTC `open_time` 列。网格包含研究开始前的计算预热；如还要评价未来收益，也要包含所需的标签尾部。`start`、`end` 必须是网格上的准确收盘时间。

`targets` 必须明确列出输出资产，`groups` 明确截面排名分组；`formula_universe` 描述公式内部可参与计算的历史成员，`universe` 描述研究窗口中的输出/评价资格，两者语义不同。示例里的“全部为真”只适用于固定、无成员变动的演示数据。真实历史研究应传入逐时点、按当时已知信息生成的成员 Series，不能用今天的成分股回填历史。

`prealign_bars()` 将每个资产的 Pandas OHLCV DataFrame 对齐到完整网格。缺失行保持 NaN 并记录缺失状态；不会前填、压缩时间或通过丢行隐藏缺口。下面示例假定 `bars` 的键是资产名，值是索引带时区的 DataFrame，至少包含标准 `open/high/low/close/volume` 列；示例中的 `grid`、`research_start`、`research_end`、日历和数据版本由调用方提供，并已按真实数据源准备。

## 单因子：原生 Alpha003

Alpha003 先在每个格点对 `open` 与 `volume` 做截面秩，再对每个资产的秩序列计算十格相关并取负。公式需要同一时点的截面，因此应使用能覆盖完整目标集合的同步网格。

```python
import pandas as pd
import backtrader as bt

from backtrader.research import FactorSpec, FactorStrategy, ResearchSpec, prealign_bars
from backtrader.research.alpha101 import get_alpha


def all_membership(times, assets):
    keys = pd.MultiIndex.from_product(
        [times, assets], names=("time", "asset")
    )
    return pd.Series(True, index=keys, dtype=bool)


def run_factor_panel(research, bars, factors, *, data_version, runonce=True):
    cerebro = bt.Cerebro(stdstats=False)
    for asset in research.targets:
        aligned = prealign_bars(
            bars[asset], research, asset, data_version=data_version
        )
        cerebro.adddata(aligned.feed, name=asset)
    cerebro.addstrategy(FactorStrategy, research=research, factors=factors)
    strategy = cerebro.run(runonce=runonce)[0]
    return strategy.get_dataset()


targets = tuple(bars)
formula_times = grid.index[grid.index <= research_end]
study_times = grid.index[
    (grid.index >= research_start) & (grid.index <= research_end)
]

# 以下标识必须来自实际数据快照、价格口径与交易日历，不是默认数据来源。
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
    formula_universe=all_membership(formula_times, targets),
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

dataset = run_factor_panel(
    research,
    bars,
    {"alpha003": alpha003},
    data_version=bars_data_version,
    runonce=True,
)
```

这个例子为 `formula_universe` 和 `universe` 都显式传入了固定成员集合，适用于稳定的合成数据。实际股票池、行业池或可交易资格会随历史变化时，应由可信的点时数据源生成相同索引形状的布尔 Series。`runonce=False` 可用于事件驱动模式对照；两种模式都由 Cerebro 推进，调用者不能手动执行因子的 `next()`、`once()` 或 `advance()`。

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

Alpha005 的 VWAP 不是 Backtrader 标准 OHLCV 行。将其作为显式 `ResearchSpec.formula_fields` 表输入时，表索引为唯一的 `(time, asset)` MultiIndex，列至少有 `value`、`available_at`、`data_version`；`time` 和 `available_at` 必须是可转换为 UTC 的真实时点。表的 `attrs["source_metadata"]` 应保留实际来源、字段单位和价格口径。不要用 `(high + low + close) / 3` 冒充 VWAP。

```python
import pandas as pd

from backtrader.research import FactorSpec, ResearchSpec
from backtrader.research.alpha101 import get_alpha, list_alphas


def make_vwap_table(bars, grid, targets, *, source_metadata):
    """Convert source VWAP rows to the formula_fields PIT-table schema."""
    records = []
    for asset in targets:
        frame = bars[asset]
        required_columns = {"vwap", "vwap_available_at", "vwap_data_version"}
        if not required_columns.issubset(frame.columns):
            raise ValueError("VWAP needs value, actual availability time, and version")
        for timestamp, row in frame.iterrows():
            time = pd.Timestamp(timestamp)
            available_at = pd.Timestamp(row["vwap_available_at"])
            if time.tz is None or available_at.tz is None:
                raise ValueError("VWAP source times must be timezone-aware")
            time = time.tz_convert("UTC")
            available_at = available_at.tz_convert("UTC")
            if time not in grid.index:
                raise ValueError("VWAP row falls outside the declared grid")
            if pd.isna(row["vwap"]):
                continue
            records.append(
                (
                    time,
                    asset,
                    float(row["vwap"]),
                    available_at,
                    str(row["vwap_data_version"]),
                )
            )
    table = pd.DataFrame(
        records,
        columns=("time", "asset", "value", "available_at", "data_version"),
    ).set_index(["time", "asset"])
    table.attrs["source_metadata"] = dict(source_metadata)
    return table


def alpha_5_6_101_specs():
    required = (5, 6, 101)
    missing = sorted(set(required) - set(list_alphas()))
    if missing:
        raise RuntimeError(
            "Alpha IDs are not yet registered and accepted: %s" % missing
        )

    specs = {}
    for alpha_id in required:
        indicator = get_alpha(alpha_id)
        bindings = {
            field: "feed:target:%s" % field
            for field in indicator.formula_fields
        }
        if "vwap" in indicator.formula_fields:
            bindings["vwap"] = "table:pit_vwap"
        name = "alpha%03d" % alpha_id
        specs[name] = FactorSpec(
            name=name,
            indicator=indicator,
            panel_line="factor",
            field_bindings=bindings,
            direction=1,
        )
    return specs


# 仅在 get_alpha(5) 和 get_alpha(6) 已被正式登记后执行：
factors = alpha_5_6_101_specs()
vwap_table = make_vwap_table(
    bars,
    grid,
    targets,
    source_metadata=actual_vwap_source_metadata,
)
research_with_vwap = ResearchSpec(
    grid=grid,
    start=research_start,
    end=research_end,
    targets=targets,
    source_timezone="UTC",
    snapshot_id=snapshot_id,
    price_basis=price_basis,
    calendar_id=calendar_id,
    frequency=frequency,
    feed_time_kind="close_time",
    groups={asset: "equity-universe" for asset in targets},
    universe=all_membership(study_times, targets),
    formula_universe=all_membership(formula_times, targets),
    formula_fields={"pit_vwap": vwap_table},
)
# 各目标 Feed 仍通过 prealign_bars 加入同一个 Cerebro。
dataset = run_factor_panel(
    research_with_vwap,
    bars,
    factors,
    data_version=bars_data_version,
    runonce=True,
)
```

如今也可以组合只依赖标准 OHLCV Feed 的 Alpha003、Alpha009 和 Alpha101：

```python
def native_factor_spec(alpha_id):
    indicator = get_alpha(alpha_id)
    name = "alpha%03d" % alpha_id
    return FactorSpec(
        name=name,
        indicator=indicator,
        panel_line="factor",
        field_bindings={
            field: "feed:target:%s" % field
            for field in indicator.formula_fields
        },
        direction=1,
    )


factors = {
    "alpha003": native_factor_spec(3),
    "alpha009": native_factor_spec(9),
    "alpha101": native_factor_spec(101),
}
dataset = run_factor_panel(
    research,
    bars,
    factors,
    data_version=bars_data_version,
    runonce=True,
)
```

无论组合哪些公式，每个因子都要独立配置 `FactorSpec`；不要把不同量纲的原始值先相加冒充截面秩变换或等权合成。方向、预处理、共同评价池、标签和组合权重属于后续评价配置，不改变 Alpha 原始公式。

## 字段绑定、ADV 与点时分类

`FactorSpec.field_bindings` 的键必须来自该类声明的 `formula_fields`。来源需明确使用 `feed:<name>:<line>` 或 `table:<name>`；`feed:target:<line>` 表示同名目标 Feed 行。若字段不属于 OHLCV 标准行（例如 VWAP、直接 ADV），可以在 Feed 上显式提供对应行，或以 `ResearchSpec.formula_fields` 表为来源。字段列名本身不证明单位、复权方式或来源。数据集会保存实际绑定值及其可用时点、版本和来源元数据。

Alpha048 需要 251 格历史跨度以及点时行业去均值。它必须绑定确切层级为 `subindustry` 的 PIT 表，不能从 Feed 的普通字符串列读取“当前行业”，也不能把今天的行业成员回填到历史。

```python
from backtrader.research import FactorSpec
from backtrader.research.alpha101 import get_alpha


alpha048 = FactorSpec(
    name="alpha048",
    indicator=get_alpha(48),
    panel_line="factor",
    field_bindings={"close": "feed:target:close"},
    classification_bindings={"subindustry": "table:pit_subindustry"},
    direction=1,
)

# 将 pit_subindustry 传入 ResearchSpec(classifications=...)。
# 表索引为 (time, asset)，至少含：
# level, category, effective_at, available_at, taxonomy_version。
```

分类表的 `available_at` 表示信息何时可知，`effective_at` 表示分类何时生效；两者不能互换。`taxonomy_version` 和 `level` 必须明确，分类缺失会保留未知原因，不会被当作一个普通行业类别。

依赖 ADV 的公式还需声明美元日成交额的真实来源。通常可以直接绑定带完整窗口、窗口长度和来源版本声明的 `advN` 字段；也可以显式选择引擎支持的派生方式：从 `dollar_volume` 对 `N` 个历史格点取均值，或从单位一致、复权口径一致的 VWAP 与 volume 相乘得到 `dollar_volume`。这两种派生都支持 PIT 表输入，并保持各目标资产的面板归属；Alpha081 专项测试覆盖了 PIT 与直接绑定、两种执行模式及独立首个截面秩参考的逐格比较。不要把 volume 本身当 ADV，也不要同时提供互相冲突的直接值和派生定义。详细字段来源/PIT 合同见[研究指南中的 Alpha101 数据边界](factor-research.md)、[派生 PIT 面板时钟测试](../../../tests/unit/test_alpha101_pit_derived_clock.py)及[迭代45 Alpha101 覆盖清单](../../_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/Alpha101覆盖清单.md)。

直接 ADV 表应提供 `value`、`available_at`、`data_version`，并在 `attrs["source_metadata"]` 中声明 `name="adv20"`、`semantic="average_daily_dollar_volume"`、USD 单位与币种、`statistic="mean"`、`window=20`、`complete_window=True`、来源版本，以及 `provenance_source_lookback_grid_bars=19`。例如，Alpha007 可将直接 ADV 表与美元成交额表明确绑定：

```python
alpha007 = get_alpha(7)
alpha007_spec = FactorSpec(
    name="alpha007",
    indicator=alpha007,
    panel_line="factor",
    field_bindings={
        "close": "feed:target:close",
        "volume": "feed:target:volume",
        "dollar_volume": "table:pit_dollar_volume",
        "adv20": "table:pit_adv20",
    },
    direction=1,
)

# 两张表均按 (time, asset) 索引并包含 PIT 可用时点和数据版本。
# pit_adv20.attrs["source_metadata"] 声明完整窗口及其来源元数据。
research_with_adv = ResearchSpec(
    grid=grid,
    start=research_start,
    end=research_end,
    targets=targets,
    source_timezone="UTC",
    snapshot_id=snapshot_id,
    price_basis=price_basis,
    calendar_id=calendar_id,
    frequency=frequency,
    feed_time_kind="close_time",
    groups={asset: "equity-universe" for asset in targets},
    universe=all_membership(study_times, targets),
    formula_universe=all_membership(formula_times, targets),
    formula_fields={
        "pit_adv20": pit_adv20,
        "pit_dollar_volume": pit_dollar_volume,
    },
)
dataset = run_factor_panel(
    research_with_adv,
    bars,
    {"alpha007": alpha007_spec},
    data_version=bars_data_version,
    runonce=True,
)
```

指南中的公开合成数据 smoke 实际执行了单因子 Alpha003、多因子 Alpha003/009/101 的 `runonce=False/True`、Alpha005/006/101 的 VWAP PIT 绑定、Alpha007 的直接 ADV PIT 绑定，以及 Alpha048 的 subindustry PIT 分类。测试在六个合成资产、260 格网格上检查了研究窗口内的有限输出，5 项通过；其中事件模式和批量模式各运行一次。该检查只验证 API 装配，不代表真实市场数据、101 式完整验收或投资收益。复现命令和 fixture 见[原生 Alpha101 指南 smoke](../../../tests/unit/test_alpha101_guide_examples.py)。

在仓库根目录可用以下命令重跑该 API smoke：

```powershell
& C:/anaconda3/python.exe -m pytest -p no:asyncio -o filterwarnings=default tests/unit/test_alpha101_guide_examples.py -q
```

记录结果为 `5 passed`、2 条现存环境 warning（未知的 pytest asyncio 配置项及 Quandl 弃用提示）；这不是生产公式矩阵或整库测试。

## H、预热与标签

`lookback_h` 是因子当前格点之前需要的历史网格跨度，不是“此时一定有有效值”的承诺。H=251 的因子需要当前点以及之前251个网格间隔，即完整输入至少跨252个格点；缺 bar、字段迟到或 PIT 分类未知可能使输出继续为 NaN。预热长度应按公式的嵌套窗口和真实源数据共同核对，不能只按自然日估算。

因子输出与未来收益标签是两类数据。若公式身份注明 `paper_signal_delay=0`，它描述该公式在当前格点生成信号的时序约定；它既不是 forward-return label，也不表示可以在同一收盘价成交。评价标签由单独的评估 API 生成，例如 next-open 标签 `open[t+1+h] / open[t+1] - 1`，需要额外的尾部 bar。`FactorSpec.direction` 影响下游评价方向，不改写原生公式已定义的正负号。

采集和保存原始数据集不依赖 fincore；`strategy.evaluate(...)` 才会按需要加载 fincore 的研究 API。IC、Rank IC、分层统计和组合结果是研究统计，不是含交易费用、滑点、成交约束和资金管理的策略收益。公式数值复现也不代表复现论文专有数据、股票池或论文收益。

## 示例与进一步阅读

- [025：单因子 FactorIndicator/FactorStrategy 示例](../../../examples/backtest/025_factor_single/README.md)及其[因子源码](../../../examples/backtest/025_factor_single/close_ma_factor_strategy.py)。
- [026：多因子采集和离线组合示例](../../../examples/backtest/026_factor_multi/README.md)及其[因子源码](../../../examples/backtest/026_factor_multi/multi_factor_strategy.py)。
- [027：Alpha003 的真实日线示例](../../../examples/backtest/027_alpha003_panel_acceptance/README.md)及其[入口源码](../../../examples/backtest/027_alpha003_panel_acceptance/run.py)。该示例使用生产库 `get_alpha(3)` 返回的 `Alpha003Native`，不是独立实现或全库验收报告。
- [迭代45原生因子研究指南](factor-research.md)：统一 API、保存/复评、字段来源和 PIT 语义。
- [迭代45设计文档](../../_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/设计文档.md)：`alpha101-v1`、字段血缘、ADV、美元成交额、VWAP 与 PIT 的共享语义。
- [迭代45代表公式与验收材料](../../_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/Alpha101代表验收案例.md)：代表公式及其独立参考背景。
- [迭代46计划](../../_internal/opts/requirements/迭代46-Alpha101原生因子实现/迭代计划.md)：101式逐批范围、H/PIT/边界验收门槛和当前状态。
