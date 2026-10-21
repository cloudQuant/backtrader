# Alpha101 #3：横截面因子验收原型

这个示例回答：**因子需要多个资产时，怎样仍然只写一个 Indicator 类，而不重写 Strategy.next？**

公式来自 [101 Formulaic Alphas，Appendix A，Alpha#3](https://arxiv.org/pdf/1601.00991)：

```text
-correlation(rank(open), rank(volume), 10)
```

`rank` 对同一天的多个资产排序；`correlation` 对每个资产最近10个网格时点的两条排名序列计算 Pearson 相关。这里的相关不是评价因子收益预测能力的 IC。

## 1. 因子作者实际写什么

[alpha003_strategy.py](alpha003_strategy.py) 中的完整声明如下：

```python
from factor_strategy import PanelFactorIndicator


class Alpha003Indicator(PanelFactorIndicator):
    @classmethod
    def build(cls, ctx):
        return -ctx.correlation(ctx.rank(ctx.open), ctx.rank(ctx.volume), 10)
```

`PanelFactorIndicator` 继承 `bt.Indicator`，但在这一方案中它是**图声明容器**。模板调用 `build()` 一次，不构造逐资产 Indicator 实例、不将它放进普通指标调度树，也不提供普通 `lines[0]`。`ctx.open` 表示整个资产池当前的开盘价向量，而不是某一个资产的价格。

用户不用在因子中实现 `next()`。本目录公共 [factor_strategy.py](factor_strategy.py) 负责逐格推进，核心计算链是：

```text
当日 A/B/C 的 open   → 截面 rank → 每资产保存10格历史 ─┐
当日 A/B/C 的 volume → 截面 rank → 每资产保存10格历史 ─┤
                                                     ↓
                                  每资产 Pearson correlation → 取负
```

因此，B 的开盘价改变，可能改变 A 当日的截面排名，进而改变 A 的因子值；不需要修改 A 自身的价格。

## 2. Cerebro 怎样使用

[run.py](run.py) 的 `run_experiment()` 展示了实际接入方式，下面是相同的配置结构：

```python
from factor_strategy import FactorStrategy
from alpha003_strategy import Alpha003Indicator

# cerebro.adddata(feed_a, name="A")
# cerebro.adddata(feed_b, name="B")
# cerebro.adddata(feed_c, name="C")
cerebro.addstrategy(
    FactorStrategy,
    grid=grid,  # 调用方提供、严格递增的 UTC 闭合 bar 时点
    factors={
        "alpha003": {
            "indicator": Alpha003Indicator,
            "execution": "panel",
            "operator_profile": "alpha101-v1",
            "field_bindings": {
                "open": "feedline:open", "volume": "feedline:volume",
            },
        },
    },
)
strategy = cerebro.run(runonce=False)[0]
factor_values = strategy.get_dataset()
```

`factor_values` 是以 `(time, asset)` 为索引、以因子名称为列的 DataFrame。使用已经支持的算子增加另一个因子时，新增声明类并加入 `factors`，公共模板的 `next()` 不变；相同表达式节点共享计算。

## 3. 运行与结果

需要本仓库的 Backtrader，以及 pandas、PyYAML。仓库内运行会加载当前源码；整个目录复制出去时使用环境已安装的 Backtrader，并在结果中记录实际导入路径。本示例自带确定性数据生成器，不下载行情。

```powershell
python examples/backtest/027_alpha003_panel_acceptance/run.py
# 或在该目录内：
python run.py --config config.yaml --output-dir output
```

成功退出0并打印 `PASS: LOCAL_ALPHA003_PROTOTYPE_ONLY`。配置/计算/断言失败退出1；明确缺文件或运行期缺依赖退出2；argparse参数错误也退出2。本例没有实盘或未知执行结果路径。

默认包含 A/B/C 三资产、10个合成日格。前9格尚无完整相关窗口；第10格：

| 资产 | 独立手算值 | 近似值 |
|---|---|---:|
| A | 17/23 | 0.739130435 |
| B | 1 | 1.000000000 |
| C | 17/23 | 0.739130435 |

只把第10格 B 的 open 从12改为9.5，其他输入不变，A 的输出应变成 `sqrt(20/23)`，约0.932504808。这是验收中的跨资产影响用例。

输出到本目录已忽略的 `output/`：

- `input_bars.csv`：原始合成OHLCV。
- `node_values.csv`：每格、每资产的字段值、截面排名、相关值、负号结果及原因。
- `factor_values.csv`：最终因子面板。
- `acceptance.json`：本次检查结果、公式/profile、Backtrader版本/来源及共享节点执行次数。

平均秩除以当期有效资产数是 `alpha101-v1` 的明确工程约定。缺bar不沿用前值、不压缩窗口；常数排名序列的相关无效。两种 Cerebro 模式均在逐事件回调中推进同一个面板引擎，不读取未来预加载数组。

资产资格池固定，但每个排名节点只使用当期该字段有限的资产；某资产缺bar会影响其他资产当期的排名分母，该缺失资产自身的相关窗口无效。全池缺格和网格尾部没有bar的格子仍输出缺失行，不制造行情或有效信号。`node_values.csv`保留这种缺失的中间状态。

## 4. 验收范围

[acceptance.py](acceptance.py) 用独立的 Fraction 标量参考计算排名和相关，没有调用候选引擎的算子。验收检查手算值、完整面板、两种运行模式、资产加载顺序、跨资产影响、未来扰动、缺bar/全池缺格、并列排名、零方差、共享节点和错误输入拒绝；同时检查没有注册普通 Indicator 实例、没有下单。

这是用户授权提前查看写法的**独立原型**，新编号027不替代计划中的025单因子和026多因子正式示例。公共模板和引擎暂时放在本例目录，后续正式实现再迁入库并稳定API。

本例仅支持固定资产池、显式网格、open/volume、rank、整数窗口相关和负号。历史行业分类、动态公式池、全部Alpha101算子、完整数据集持久化、fincore的IC/绩效分析都尚未实现。结果只证明本原型的合成数据计算；不将迭代45的AC45-28/29或全迭代标为PASS，不宣称投资收益或完整Alpha101复现。
