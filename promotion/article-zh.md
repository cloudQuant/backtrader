# 比原版快 46%,C++ 后端加速 128 倍:这个 Backtrader fork 把量化回测带进了 AI 时代

> 发布渠道:CSDN(首发)、知乎(量化交易话题)、掘金
> 建议标题备选:
> - 比原版快 46%:一个仍在活跃维护的 Backtrader 高性能 fork
> - 实测 128 倍加速:Backtrader 高性能 fork + AI 原生策略开发全链路

---

## 为什么要 fork Backtrader

[Backtrader](https://github.com/mementum/backtrader) 是 Python 量化圈最知名的回测框架之一,API 优雅、指标丰富。但原版已经多年缺乏实质维护,性能与生态也停留在十年前的设计。

[cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 是一个**活跃维护的高性能 fork**:保持公共 API 兼容的同时,移除了元类元编程开销、重写了热路径,并围绕它构建了一套 **AI 原生的策略开发工具链**——把"写策略、审策略、跑回测"整条链路交给 AI 编码助手完成。

## 性能:三个维度的实测数据

### 1. 纯 Python 引擎:快 46%

在相同硬件上跑完整 **1,271 个策略回归测试**(8 进程并行):

| 指标 | master(对齐上游) | dev | 提升 |
| --- | --- | --- | --- |
| 总执行时间 | 438.96s | 236.36s | **-46.2%** |
| 加速比 | 1.00x | **1.86x** | ✓ |
| 测试通过率 | 100% | 100% | ✓ |

### 2. C++ / pybind11 后端:数量级加速

通过 [back-trader-cpp](https://pypi.org/project/back-trader-cpp/)(PyPI 一键安装,支持 Python 3.8-3.14、macOS/Windows/Linux):

- 117 个策略基准:**C++ 版 117/117 全部通过,0 指标偏差**
- C++ 总耗时中位数加速:**128.82x**;运行时加速:**235.78x**
- pybind11 总耗时中位数加速:**43.39x**;运行时加速:**57.60x**

### 3. 正确性保障:3,200+ 测试

速度之外,框架还自带 **3,200+ 测试**(其中 1,271 个策略回归测试覆盖 22 个策略类别),master 分支作为正确性基线——**性能优化不允许牺牲结果正确性**。

## 不止快:一个 6 仓库的量化生态

cloudQuant 围绕核心引擎构建了完整生态:

| 仓库 | 一句话介绍 |
| --- | --- |
| [backtrader](https://github.com/cloudQuant/backtrader) | 高性能核心引擎(本仓库),回测 + 实盘,全频段支持 |
| [backtrader-skills](https://github.com/cloudQuant/backtrader-skills) | 面向 AI 编码助手的离线编写/审查/测试 Skills:本地数据登记 → 类型化策略规格 → 静态审查 → 隔离子进程回测 |
| [backtrader-mcp](https://github.com/cloudQuant/backtrader-mcp) | 本地优先的 MCP Server:30 个 typed tools,把 CSV 固化为不可变数据集、策略意图转为私有草稿、审查后受限运行并产出报告 |
| [backtrader-agent](https://github.com/cloudQuant/backtrader-agent) | 离线优先的策略编写 Agent 运行时:哈希绑定审批 + 可恢复会话溯源 |
| [backtrader_web](https://github.com/cloudQuant/backtrader_web) | "AI for Investor" 平台(Vue 3 + FastAPI):研究、AI 策略生成、回测、模拟盘、实盘、数据管理 |
| [fincore](https://github.com/cloudQuant/fincore) | 量化绩效与风险分析库:150+ 指标、组合优化、蒙特卡洛、绩效归因——empyrical/pyfolio/alphalens 的活跃继承者 |

## 一条新路径:让 AI 帮你写策略

传统流程是"人读文档 → 人写策略 → 人调回测"。现在可以直接在 Claude Code / Codex / OpenCode 里对 AI 说:

> "读一下我的 offline CSV,注册成数据集,按多时间框架动量 archetype 生成一个策略,回测给我看报告。"

`backtrader-mcp` 会完成:数据集校验登记 → 策略草稿渲染 → 静态审查(不导入候选代码)→ 人工审批 → 受限子进程回测(runonce/runnext 双模式对拍)→ 输出 11 项规范指标与 JSON/Markdown 报告。

离线、仅回测、审批人机分离——这套设计把"AI 写策略"的风险控制在安全边界内。

## 30 秒上手

```bash
# 纯 Python 版(源码安装)
git clone https://github.com/cloudQuant/backtrader.git
cd backtrader && pip install -U .

# 或 pybind11 加速 wheel
pip install back-trader-cpp
```

```python
import backtrader as bt

class SmaCross(bt.Strategy):
    params = (('fast', 10), ('slow', 30))

    def __init__(self):
        sma_fast = bt.indicators.SMA(period=self.p.fast)
        sma_slow = bt.indicators.SMA(period=self.p.slow)
        self.crossover = bt.indicators.CrossOver(sma_fast, sma_slow)

    def next(self):
        if not self.position and self.crossover > 0:
            self.buy()
        elif self.position and self.crossover < 0:
            self.close()

cerebro = bt.Cerebro()
cerebro.adddata(data)
cerebro.addstrategy(SmaCross)
cerebro.broker.setcash(100000)
results = cerebro.run()
cerebro.plot(backend='plotly')  # 交互式图表
```

## 一起来建设

- ⭐ 觉得有用,给 [6 个仓库](https://github.com/cloudQuant) 都点个 Star
- 🐛 发现问题或指标偏差,直接提 issue——尤其欢迎"dev 与 master 结果不一致"的报告
- 📚 中英文文档齐备:[英文文档](https://backtrader.readthedocs.io/en/latest/) · [中文文档](https://backtrader-zh.readthedocs.io/zh-cn/latest/) · [中文社区站点](https://aifortrader.cn/)

> 风险提示:本项目仅供教育与研究目的,算法交易存在重大亏损风险,历史业绩不代表未来表现。
