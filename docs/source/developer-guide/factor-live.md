# 实时因子与普通 Strategy

`LiveFactorSet` 把已有 `FactorSpec` 绑定到普通 Backtrader feed lines；它复用
`FactorIndicator` 的 native/build 图和 Cerebro 生命周期，不创建第二个指标调度器。
策略仍由用户的 `bt.Strategy` 持有，照常从 `next()` 读取结果并执行自己的策略逻辑。

```python
import backtrader as bt
from backtrader.research import (
    FactorHistoryContract, FactorIndicator, LiveFactorSet,
    LiveFactorReadiness, LiveFactorOutputStatus,
)

class AlphaStrategy(bt.Strategy):
    params = (("plan", None), ("cohort", None))

    def __init__(self):
        feeds = {data._name: data for data in self.datas}
        self.live_factors = LiveFactorSet.bind(
            self.p.plan, feeds, cohort=self.p.cohort
        )

    def next(self):
        snapshot = self.live_factors.snapshot()
        if snapshot.readiness is not LiveFactorReadiness.LIVE_READY:
            return
        value = snapshot.factors["alpha003"].values["rb"]
        if value.status is not LiveFactorOutputStatus.OUTPUT_AVAILABLE:
            return
        # 在这里继续执行独立的策略、持仓、风险和执行准入检查。
```

`plan` 是 `LiveFactorPlan`，其中每个因子可用同一个 `FactorSpec` 显式选择
`mode="native"` 或 `mode="build"`；省略模式时按该因子已实现的模式解析。计划的
目标名称必须在 Strategy 的具名 feeds 中存在；传入的 feeds 必须覆盖 cohort 全部成员，
也可包含通过字段绑定引用的基准成员。绑定只接受由 Cerebro 为该
`LiveBarCohort` 激活的精确 `BtApiFeed`，并校验字段绑定、日历、频率、窗口和调度时钟。

策略入口还需在 `Cerebro` 上配置同一个 cohort；`clock` 提供 `utc_now()`、
`monotonic_ns()` 和 `wait(timeout)`：

```python
cerebro.add_live_bar_cohort(cohort, clock=clock)
```

日历是有限且明确的计划网格。Cerebro 按正常 feed 生命周期
调度各成员；cohort 先验证来源事件，再等当前计划格的所有成员到齐并且可用，最后
原子发布完整 batch。未齐的成员留在有界 pending 窗口内等待；超时或缺格保留为显式
状态，不压缩时间轴；缺格也不能绕过严格输入语义而获得 `LIVE_READY`。`max_pending_slots`、`wait_timeout_ns` 和
`max_window_bars` 是 cohort 与 plan 必须一致的容量边界。引擎使用只读等待建议
`next_wait_timeout()`，并把 Broker 自己的下次轮询期限纳入等待；应用不应自行推进
feed 或指标来“补齐”截面。

`snapshot.readiness` 描述计算输入和图状态：`INITIALIZING`、`WARMUP`、
`CATCHING_UP`、`LIVE_READY` 或 `DEGRADED`。单个值另有
`OUTPUT_AVAILABLE` / `OUTPUT_UNAVAILABLE` 状态。`LIVE_READY` 只说明本批计算满足
已声明的输入、窗口、cutover 与新鲜度合同；它不表示有交易信号，也不授予下单权。
Strategy 必须另外检查业务成员、direction、账户和持仓、在途订单、风险预算、执行
报价及写权限，随后才可调用现有 Broker 的 `buy`、`sell` 或 `cancel`。历史预热格
不能直接变成订单信号。

自定义因子必须在具体类上诚实声明如何从有限来源历史重建状态。有限图声明覆盖图所需的实际
bar 数，且不能短于执行图跨度：

```python
class BoundedFactor(FactorIndicator):
    # 放在实际声明 lines、formula_fields、lookback_h 和 next/build 的因子类上
    history_contract = FactorHistoryContract.finite_window(span_bars=32)
```

需要递归状态的因子须从适配器证明的来源起点连续重放；仅声明 H 或 `lookback_h`
不构成递归状态恢复证明：

```python
class RecursiveFactor(FactorIndicator):
    # 因子仍需实现 next() 或 classmethod build()
    history_contract = FactorHistoryContract.replay_from_source_origin()
```

这项声明也不是恢复凭证。绑定还要求当前 cohort 能证明同一成员、来源和 epoch 的
起点、连续历史前缀及其与 live 的交接。来源起点缺失、历史被截断、冲突或断档时，
快照保留诊断输出但不会因此成为 `LIVE_READY`，readiness 会保持 `WARMUP` 或退化；
不能用长度 H、截断的递归值或 pickle 状态代替来源证明。

## 字段点时能力与边界

`FactorSpec.field_policies` 为公式输入声明单位和最大观测年龄；它不会替数据源补造
时间戳或解释字段含义。每个输入还需要由精确 cohort member 声明
`LiveFieldContract(source_ref, unit, delivery_mode)`。独立更新的字段必须随事件提供
`LiveFieldObservation(source_ref, unit, effective_at, available_at, revision, valid_until)`；
这些时刻必须是带时区的 UTC，来源和单位必须与 member contract 一致，`available_at`
不能晚于调度器评估时刻，且观测未过期、年龄不超过因子政策。修订号不能为空。
只有 adapter 明确声明 `delivery_mode="co_delivered"` 和有限
`validity_seconds` 时，cohort 才能从同一精确来源事件派生该字段的观测；生产者不能延长
adapter 声明的有效期。

当前支持的绑定形态如下：

| 输入 | 配置与单位 | 点时要求和限制 |
| --- | --- | --- |
| 直接数值字段，例如交易额 `dollar_volume` | `field_bindings={"dollar_volume": "feed:target:dollar_volume"}`，并为该 alias 声明 `FieldPITPolicy(unit="USD", max_age_seconds=60)` | 每个 member 的字段 contract 与 observation 必须使用同一单位；允许独立 observation，或 adapter 明确声明的 co-delivery。 |
| 由 VWAP 与成交量推导交易额 | 显式绑定 `vwap`、`volume`，再声明 `dollar_volume` 的 `vwap_volume` 派生；VWAP 用 `USD/share`，数量用 `share`，产物为 `USD` | 当前只接受明确登记的价格×数量单位组合；不从 OHLC 近似 VWAP，也不把美元成交额再次乘成交量。派生来源各自带 PIT policy。 |
| ADV 窗口 | `advN` 绑定为 `{"derive": "adv", "source": "dollar_volume", "window": N}`；`advN` 与交易额均声明相同货币单位 | `N` 必须与别名一致。计算和 PIT qualification 都覆盖完整 N 格窗口；窗口内 stale、expired 或 missing 样本让整个固定截面不可用，直到干净窗口重新形成。 |
| 基准或其他辅助 feed | 例如 `{"benchmark_close": "feed:benchmark:close"}`，并为该字段声明与基准 contract 一致的单位和年龄 | 辅助 feed 必须是 Strategy / cohort 中的精确成员。它只作为因子输入；`LiveFactorPlan.targets`、因子输出键和截面成员仍由 targets 决定，不能因加入 benchmark 扩大公式目标池。 |
| 市值或分类字段 | `cap` 可声明数据源实际使用的货币单位（例如 `USD`）；数值编码的 `industry` 可声明版本化单位名，例如 `industry-code:taxonomy-v1` | `cap`、`industry`、`sector` 和 `subindustry` 沿用相同的 contract、观测时点、年龄和有效期检查。库只比较声明单位与来源单位；它不解释分类码含义、分类版本迁移或市值口径。 |

直接输入示例：

```python
from backtrader.research import FieldPITPolicy, FactorSpec

FactorSpec(
    name="turnover",
    indicator=TurnoverFactor,
    panel_line="factor",
    field_bindings={"dollar_volume": "feed:target:dollar_volume"},
    field_policies={"dollar_volume": FieldPITPolicy(unit="USD", max_age_seconds=60)},
)
```

缺少 policy 的数值字段仍可按已有图计算，但结果明确标记
`pit_policy_complete=False`、`pit_qualified=False`，不能作为通过 PIT 验证的输入。
过期、超龄或明确缺失的受管字段保留在原 cohort batch 和固定目标集合内，输入 line
投影为不可用值，因子输出不能用于新风险决策；不会静默缩小截面排名成员。缺失或 stale
样本仍在因子依赖窗口时 readiness 保持 `WARMUP`，直到完整干净窗口恢复。没有明确 PIT
政策的普通 cohort 缺格仍按既有严格 gap 语义处理，不会借字段 policy 一概放行。

当前实际测试覆盖直接字段、独立 observation 与显式 co-delivery、VWAP×成交量→交易额、
ADV3 窗口、missing/stale 窗口恢复、无 policy 的 UNQUALIFIED 输出，以及辅助 benchmark
不改变 target pool 的未来值因果性。新增的小型实际 cohort 组合也覆盖 benchmark close、
`cap` 和数值编码 `industry` 的显式单位、来源 observation、effective/available 时间、
expiry 与干净依赖窗口恢复；它只验证通用 PIT 机械，不验证市值口径、行业分类经济含义或
taxonomy 迁移。具体 adapter/factor 仍须为每个来源声明正确单位和时间事实，不能据此声称
所有市场数据源都已 PIT 合格。

离线 `FactorStrategy` / `ResearchSpec` 研究入口处理的是同频、闭合历史 bar；它拒绝
live、replay、tick 和混合频率输入。实时计算应使用普通 Strategy、Cerebro cohort
和 `LiveFactorSet`，不要把离线研究策略当作 live runner。

当前实时因子、cohort、feed 绑定及部分普通 Strategy 组合已有 SOURCE / COMPOSITION
级局部验收；这不等于完整 Iteration 50/51 交付。安装 wheel / 隔离消费者、完整
028 live 组合、完整主力与会话覆盖，以及真实 SimNow 行情、订单和恢复验收仍未完成。
不要把组件测试或示例源码当成真实账户通过证明。

后续实施状态见[迭代50实施与验收记录](../../_internal/opts/requirements/迭代50-因子实盘运行与交易接入/实施与验收.md)。
唯一示例入口[028 Alpha003 SimNow minute（实施中）](../../../examples/unified/028_alpha003_simnow_minute/README.md)
描述了继续集成的目标；其完整 live 路径与运行说明仍在验收中，不是已接受的安装或账户操作手册。
