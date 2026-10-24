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
