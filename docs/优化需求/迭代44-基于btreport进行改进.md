### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/btreport
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

---

## 一、项目对比分析

### 1.1 btreport 项目核心特性

| 特性 | 描述 |
|------|------|
| **专业报告生成** | 一键生成包含所有关键指标的PDF报告 |
| **性能指标全面** | 涵盖PnL、交易统计、风险指标（夏普、SQN、回撤） |
| **可视化图表** | 权益曲线图 + 收益率柱状图 + 买入持有对比 |
| **模板化设计** | 使用Jinja2模板，易于自定义 |
| **自动分析器** | 自动添加所有必需的分析器 |
| **SQN人类评级** | 将数值转换为"Average"到"Holy Grail"的7级评级 |
| **智能时间周期** | 自动判断最佳显示周期（分钟→年级） |

### 1.2 backtrader 现有报告能力

| 能力 | 描述 |
|------|------|
| **分析器系统** | 已有 SharpeRatio、DrawDown、TradeAnalyzer、SQN等 |
| **绘图系统** | matplotlib和Plotly两种绘图后端 |
| **观察器系统** | Broker、Trades、BuySell等观察器 |
| **缺少报告生成** | 无一键式报告生成功能 |
| **缺少PDF导出** | 无PDF报告支持 |
| **指标分散** | 需手动从多个分析器提取数据 |

### 1.3 差距分析

1. **报告生成**: backtrader无统一报告输出，需手动提取各分析器结果
2. **用户体验**: btreport的`cerebro.report()`一行代码 vs backtrader需多步操作
3. **可分享性**: btreport生成PDF便于分享，backtrader主要为交互式图表
4. **指标整合**: btreport整合了所有关键指标到一个页面

---

## 二、需求规格文档

### 2.1 功能需求

#### FR1: 报告生成器模块
创建独立的报告生成模块 `backtrader/reports/`，提供：

- **FR1.1**: 支持HTML格式报告生成
- **FR1.2**: 支持PDF格式报告生成
- **FR1.3**: 支持JSON格式报告导出（便于程序化处理）
- **FR1.4**: 报告模板可自定义

#### FR2: 性能指标计算器
统一的性能指标计算类：

- **FR2.1**: 收益指标：总收益、年化收益、累计收益率
- **FR2.2**: 风险指标：最大回撤、夏普比率、SQN、卡玛比率
- **FR2.3**: 交易统计：胜率、盈亏比、平均盈利/亏损、最佳/最差交易
- **FR2.4**: SQN人类评级转换

#### FR3: 可视化图表
报告专用的图表生成：

- **FR3.1**: 权益曲线图（含买入持有对比线）
- **FR3.2**: 收益率柱状图（自动周期判断）
- **FR3.3**: 回撤面积图
- **FR3.4**: 月度/年度收益热力图（可选）

#### FR4: Cerebro集成
在Cerebro类中添加报告方法：

- **FR4.1**: `add_report_analyzers()` - 自动添加报告所需分析器
- **FR4.2**: `generate_report()` - 生成报告文件

### 2.2 非功能需求

- **NFR1**: 性能 - 报告生成应在2秒内完成（正常数据量）
- **NFR2**: 可扩展性 - 支持自定义报告模板
- **NFR3**: 兼容性 - 与现有backtrader API完全兼容
- **NFR4**: 可选依赖 - PDF生成为可选功能（weasyprint）

### 2.3 用户故事

| ID | 故事描述 | 优先级 |
|----|---------|--------|
| US1 | 作为量化研究员，我想一键生成PDF报告，便于与团队分享策略回测结果 | P0 |
| US2 | 作为策略开发者，我想看到所有关键性能指标在一个页面上 | P0 |
| US3 | 作为用户，我想自定义报告模板以符合公司风格 | P1 |
| US4 | 作为开发者，我想导出JSON格式数据以便进一步分析 | P1 |

---

## 三、设计文档

### 3.1 模块结构设计

```
backtrader/
├── reports/                    # 新增报告模块
│   ├── __init__.py            # 模块导出
│   ├── performance.py         # 性能指标计算
│   ├── charts.py              # 报告专用图表
│   ├── template.py            # 模板渲染
│   ├── reporter.py            # 主报告生成器
│   └── templates/             # 报告模板
│       ├── default.html       # 默认HTML模板
│       ├── minimal.html       # 简洁版模板
│       └── dark.html          # 深色主题模板
```

### 3.2 核心类设计

#### 3.2.1 PerformanceCalculator

```python
class PerformanceCalculator:
    """统一的性能指标计算器

    从策略和分析器中提取并计算所有性能指标
    """

    def __init__(self, strategy):
        self.strategy = strategy
        self._analyzers = strategy.analyzers

    def get_all_metrics(self) -> dict:
        """返回所有性能指标的字典"""

    def get_pnl_metrics(self) -> dict:
        """收益相关指标"""

    def get_risk_metrics(self) -> dict:
        """风险相关指标"""

    def get_trade_metrics(self) -> dict:
        """交易统计指标"""

    @staticmethod
    def sqn_to_rating(sqn_score: float) -> str:
        """SQN分数转人类评级"""
```

#### 3.2.2 ReportChart

```python
class ReportChart:
    """报告专用图表生成器

    生成报告所需的静态图表，区别于交互式绘图
    """

    def plot_equity_curve(self, equity_data, benchmark_data=None):
        """绘制权益曲线图"""

    def plot_return_bars(self, returns_data, period='auto'):
        """绘制收益率柱状图"""

    def plot_drawdown(self, drawdown_data):
        """绘制回撤面积图"""

    def save_to_file(self, filename, format='png'):
        """保存图表到文件"""
```

#### 3.2.3 ReportGenerator

```python
class ReportGenerator:
    """主报告生成器"""

    def __init__(self, strategy, template='default'):
        self.strategy = strategy
        self.calculator = PerformanceCalculator(strategy)
        self.charts = ReportChart()
        self.template = template

    def generate_html(self, output_path: str):
        """生成HTML报告"""

    def generate_pdf(self, output_path: str):
        """生成PDF报告"""

    def generate_json(self, output_path: str):
        """生成JSON报告"""
```

#### 3.2.4 Cerebro扩展

```python
# 在 cerebro.py 中添加

class Cerebro:
    # ... 现有代码 ...

    def add_report_analyzers(self, riskfree_rate: float = 0.01):
        """自动添加报告所需的分析器"""

    def generate_report(self, output_path: str, format: str = 'html',
                       template: str = 'default', **kwargs):
        """生成回测报告

        Args:
            output_path: 输出文件路径
            format: 报告格式 ('html', 'pdf', 'json')
            template: 模板名称
            **kwargs: 额外参数（用户名、备注等）
        """
```

### 3.3 模板设计

#### 3.3.1 默认模板结构

```html
<!DOCTYPE html>
<html>
<head>
    <style>
        /* 报告样式 */
    </style>
</head>
<body>
    <!-- 页眉区域：策略信息、数据信息、用户信息 -->
    <header>...</header>

    <!-- 图表区域：权益曲线、收益率柱状图 -->
    <section class="charts">...</section>

    <!-- 指标表格区域：分PnL、交易、KPI三个表 -->
    <section class="metrics">...</section>
</body>
</html>
```

### 3.4 数据流设计

```
Cerebro.run()
    ↓
Strategy (带分析器)
    ↓
ReportGenerator
    ├── PerformanceCalculator → 指标数据
    ├── ReportChart → 图表文件
    └── Template → 渲染报告
    ↓
输出文件 (HTML/PDF/JSON)
```

### 3.5 依赖管理

| 依赖 | 类型 | 说明 |
|------|------|------|
| jinja2 | 必需 | HTML模板渲染 |
| matplotlib | 必需 | 图表生成 |
| weasyprint | 可选 | PDF生成（使用try-except处理） |
| pandas | 必需 | 数据处理 |

### 3.6 API设计示例

```python
import backtrader as bt

# 使用方式1：基本用法
cerebro = bt.Cerebro()
cerebro.add_strategy(MyStrategy)
cerebro.adddata(data)
cerebro.run()
cerebro.generate_report('report.html')

# 使用方式2：PDF报告
cerebro.generate_report('report.pdf', format='pdf')

# 使用方式3：自定义信息
cerebro.generate_report(
    'report.pdf',
    user='Trading John',
    memo='Golden Cross Strategy Test',
    template='minimal'
)

# 使用方式4：单独使用计算器
strat = cerebro.run()[0]
calc = bt.reports.PerformanceCalculator(strat)
metrics = calc.get_all_metrics()
print(metrics['sharpe_ratio'])
```

---

## 四、实施计划

### 4.1 实施阶段

| 阶段 | 任务 | 预计工作量 |
|------|------|-----------|
| Phase 1 | 创建 reports 目录结构和基础类 | 2天 |
| Phase 2 | 实现 PerformanceCalculator | 2天 |
| Phase 3 | 实现 ReportChart 图表生成 | 2天 |
| Phase 4 | 实现报告模板和 Reporter | 2天 |
| Phase 5 | Cerebro集成和API设计 | 1天 |
| Phase 6 | 测试和文档 | 1天 |

### 4.2 优先级

1. **P0**: HTML报告生成（核心功能）
2. **P0**: PerformanceCalculator指标计算
3. **P1**: PDF报告生成
4. **P1**: Cerebro集成
5. **P2**: JSON导出
6. **P2**: 自定义模板支持

---

## 五、参考资料

### 5.1 关键参考代码

- btreport/report.py:38-78 - `get_performance_stats()` 方法
- btreport/report.py:80-87 - `get_equity_curve()` 方法
- btreport/report.py:89-106 - `_sqn2rating()` 评级转换
- btreport/report.py:138-151 - `plot_equity_curve()` 图表生成
- btreport/report.py:153-174 - `_get_periodicity()` 智能周期判断
- btreport/templates/template.html - HTML模板结构

### 5.2 可复用的backtrader组件

- `backtrader/analyzers/` - 所有现有分析器
- `backtrader/observers/` - 数据观察器
- `backtrader/plot/` - 图表绘制逻辑