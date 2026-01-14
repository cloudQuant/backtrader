### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/OmegaUI
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### OmegaUI项目简介
OmegaUI是一个基于Dash框架的量化交易Web UI系统，为backtrader提供可视化的回测界面。项目具有以下核心特点：

**技术栈**：
- **前端框架**: Dash (Plotly) - Python Web应用框架
- **图表库**: Plotly.js - 交互式图表
- **实时通信**: Flask-SocketIO + Redis - WebSocket消息推送
- **样式**: 自定义CSS + Skeleton CSS框架

**核心功能模块**：
- **app.py**: Dash应用主入口，UI布局和回调
- **tearsheet.py**: 回测图表生成（权益曲线、回撤、月度收益热力图）
- **backend.py**: 后端逻辑，策略加载和回测执行
- **socket_logging.py**: WebSocket实时日志推送
- **backtest.py**: 回测基类，可继承实现具体策略

---

## 一、架构对比分析

### 1.1 整体架构对比

| 维度 | Backtrader | OmegaUI |
|------|------------|---------|
| **核心定位** | 量化回测引擎 | 可视化回测UI |
| **UI技术** | 无原生UI（依赖matplotlib/plotly） | Dash Web框架 |
| **数据流向** | 单向执行 | 交互式 + 实时反馈 |
| **策略加载** | 直接import | 动态模块加载 |
| **结果展示** | 静态图表 | 交互式图表 + 统计面板 |
| **日志系统** | 标准logging | Redis + WebSocket实时推送 |
| **参数管理** | params定义 | 动态参数表格（可编辑） |

### 1.2 可视化系统对比

**Backtrader原生可视化**：
```python
# 使用matplotlib
cerebro.plot()

# 或者使用PyFolio
fig, ax = pf.create_full_tear_sheet(returns)
```

**OmegaUI的可视化方案**：
```python
# 使用Plotly创建交互式图表
def create_figure(returns, title):
    # 权益曲线 + 回撤叠加图
    # Underwater plot（水下回撤图）
    # 月度收益热力图
    # 年度收益柱状图
    fig = pto.make_subplots(rows=3, cols=4, specs=[...])
    # ...
    return fig  # 返回Plotly Figure对象
```

**优势对比**：
- **Backtrader**: 简单直接，适合快速查看
- **OmegaUI**: 交互式图表，可缩放、悬停查看数据点

### 1.3 实时日志系统对比

**Backtrader**：
- 使用标准logging模块
- 输出到控制台或文件
- 无实时推送能力

**OmegaUI**：
- Redis Pub/Sub架构
- WebSocket实时推送
- 前端MutationObserver监听DOM变化

**架构图**：
```
回测进程 → Redis Handler → Redis Pub/Sub → SocketIO Server → Browser
```

### 1.4 参数管理对比

**Backtrader**：
```python
class MyStrategy(bt.Strategy):
    params = (
        ('period', 20),
        ('exit_factor', 2.0),
    )
```

**OmegaUI动态参数**：
```python
# 后端动态提取策略参数
def params_list(module_name, strategy_name, symbol):
    params = cash_param()
    module = importlib.import_module(module_name)
    strategy = getattr(module, strategy_name)
    for key, value in backtest.get_parameters(strategy, symbol).items():
        params.append({'Parameter': key, 'Value': value})
    return params  # 返回可编辑表格
```

**优势**：UI中可实时修改参数，无需重启应用

### 1.5 回测基类设计

**OmegaUI的Backtest基类**：
```python
class Backtest(object):
    def get_symbols(self):
        """获取可交易标的列表"""
        pass

    def get_parameters(self, strategy, symbols):
        """获取策略参数（用于UI展示）"""
        pass

    def run(self, symbols, cash, strategy, **params):
        """执行回测"""
        pass

    @staticmethod
    def setup_cerebro(cash):
        """配置Cerebro和Analyzers"""
        cerebro = bt.Cerebro()
        cerebro.broker.setcash(cash)
        cerebro.addanalyzer(bt.analyzers.PyFolio, _name='pyfolio')
        cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        cerebro.addanalyzer(bt.analyzers.SQN, _name='SQN')
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
        return cerebro
```

**设计优势**：
- 抽象出可扩展的基类
- 预配置常用Analyzers
- 参数与策略解耦

---

## 二、需求规格说明书

### 2.1 交互式可视化模块

**需求ID**: REQ-108-01
**优先级**: 高

**功能描述**:
为backtrader提供基于Plotly的交互式可视化组件，替代或补充matplotlib的静态图表。

**详细需求**:

1. **图表组件**
   - 权益曲线图（带回撤叠加）
   - 水下回撤图（Underwater Plot）
   - 月度收益热力图
   - 年度收益柱状图
   - K线图（可选）
   - 成交量图（可选）

2. **交互功能**
   - 缩放、平移
   - 悬停显示数据点
   - 图例切换
   - 导出为PNG/SVG

3. **布局系统**
   - 多子图支持
   - 自适应响应式布局
   - 可配置图表尺寸

**验收标准**:
- [ ] 支持至少5种图表类型
- [ ] 图表响应时间 < 500ms（万根K线）
- [ ] 支持导出为PNG/SVG
- [ ] 移动端适配

### 2.2 实时日志推送系统

**需求ID**: REQ-108-02
**优先级**: 高

**功能描述**:
实现回测过程的实时日志推送，让用户在UI中看到策略执行进度。

**详细需求**:

1. **日志Handler**
   ```python
   class WebSocketLogHandler(logging.Handler):
       """将日志发送到WebSocket"""
       def emit(self, record):
           log_entry = self.format(record)
           # 发送到消息队列
   ```

2. **消息队列**
   - 支持Redis、RabbitMQ、内存队列
   - 发布-订阅模式
   - 按会话隔离

3. **前端显示**
   - 分级显示（DEBUG/INFO/WARNING/ERROR）
   - 自动滚动
   - 可过滤

**验收标准**:
- [ ] 日志延迟 < 100ms
- [ ] 支持1000+并发连接
- [ ] 日志持久化到文件

### 2.3 动态参数管理

**需求ID**: REQ-108-03
**优先级**: 中

**功能描述**:
支持动态修改策略参数并重新运行回测，无需重启应用。

**详细需求**:

1. **参数提取**
   ```python
   def extract_params(strategy_class):
       """从Strategy类提取参数定义"""
       params = []
       for name, default in strategy_class.params._getitems():
           params.append({
               'name': name,
               'value': default,
               'type': type(default).__name__
           })
       return params
   ```

2. **参数验证**
   - 类型检查
   - 范围验证
   - 依赖关系检查

3. **参数持久化**
   - 保存参数配置
   - 加载历史配置
   - 配置对比

**验收标准**:
- [ ] 自动提取90%以上的策略参数
- [ ] 参数修改实时生效
- [ ] 支持配置导入/导出

### 2.4 策略加载器

**需求ID**: REQ-108-04
**优先级**: 中

**功能描述**:
实现动态策略加载，支持从指定模块导入策略类。

**详细需求**:

1. **模块扫描**
   ```python
   def scan_strategies(module_path):
       """扫描模块中的所有Strategy类"""
       module = importlib.import_module(module_path)
       strategies = []
       for name, obj in inspect.getmembers(module):
           if inspect.isclass(obj) and issubclass(obj, bt.Strategy):
               strategies.append({
                   'name': name,
                   'class': obj,
                   'doc': obj.__doc__
               })
       return strategies
   ```

2. **热重载**
   - 代码修改后自动重新加载
   - 不影响正在运行的回测

3. **策略管理**
   - 列出可用策略
   - 策略分类/标签
   - 策略搜索

**验收标准**:
- [ ] 支持从多个目录加载策略
- [ ] 热重载延迟 < 1秒
- [ ] 策略加载错误有明确提示

### 2.5 统计分析面板

**需求ID**: REQ-108-05
**优先级**: 中

**功能描述**:
提供全面的回测统计分析面板，展示关键性能指标。

**详细需求**:

1. **曲线指标**
   - 总收益率
   - 年化收益率(CAGR)
   - 夏普比率
   - 年化波动率
   - SQN
   - R-Squared
   - 最大回撤
   - 最大回撤持续期

2. **交易指标**
   - 胜率
   - 平均盈亏
   - 平均盈利/亏损
   - 最佳/最差交易
   - 平均持仓天数
   - 交易次数

3. **时间维度**
   - 胜月率
   - 平均盈亏月
   - 最佳/最差月份
   - 胜年率
   - 最佳/最差年份

**验收标准**:
- [ ] 支持至少20种统计指标
- [ ] 计算时间 < 100ms
- [ ] 指标说明可展开查看

### 2.6 回测结果对比

**需求ID**: REQ-108-06
**优先级**: 低

**功能描述**:
支持多个回测结果的对比分析。

**详细需求**:

1. **对比功能**
   - 权益曲线对比
   - 指标对比表
   - 参数对比

2. **结果管理**
   - 保存历史结果
   - 结果搜索/过滤
   - 结果导出

**验收标准**:
- [ ] 支持同时对比5个回测
- [ ] 对比图清晰易读
- [ ] 支持导出对比报告

### 2.7 Web API服务

**需求ID**: REQ-108-07
**优先级**: 低

**功能描述**:
提供RESTful API，支持远程调用回测功能。

**详细需求**:

1. **API端点**
   - POST /backtest - 提交回测任务
   - GET /backtest/{id} - 获取回测结果
   - GET /strategies - 列出可用策略
   - GET /analyzers - 列出可用分析器

2. **任务管理**
   - 异步执行
   - 任务队列
   - 进度查询

**验收标准**:
- [ ] API响应时间 < 200ms
- [ ] 支持100并发任务
- [ ] 完整的API文档

---

## 三、设计文档

### 3.1 交互式可视化组件设计

#### 3.1.1 Plotly图表生成器

```python
import plotly.graph_objs as go
import plotly.tools as pto
import pandas as pd
import numpy as np
import backtrader as bt
from typing import Dict, List, Optional, Tuple


class TearsheetGenerator:
    """回测可视化图表生成器"""

    def __init__(self):
        self.color_scheme = {
            'equity': '#66B266',
            'drawdown': '#FF6A6A',
            'positive': '#0E8245',
            'negative': '#C41E27',
            'heatmap': [
                [0.0, '#C41E27'],
                [0.5, '#FEFFBE'],
                [1.0, '#006837']
            ]
        }

    def create_tearsheet(self, results: bt.strategy.Strategy, title: str = "Backtest Results") -> go.Figure:
        """
        创建完整的Tearsheet图表

        Args:
            results: backtrader回测结果
            title: 图表标题

        Returns:
            Plotly Figure对象
        """
        # 提取收益数据
        returns = self._extract_returns(results)

        # 创建子图布局
        fig = pto.make_subplots(
            rows=3, cols=4,
            specs=[
                [{'colspan': 4}, None, None, None],
                [{'colspan': 4}, None, None, None],
                [{'colspan': 3}, None, None, {}]
            ],
            subplot_titles=('', 'Drawdown (%)', 'Monthly Returns (%)', 'Yearly Returns (%)'),
            horizontal_spacing=0.05,
            vertical_spacing=0.05,
            print_grid=False
        )

        # 添加各子图
        self._add_equity_curve(fig, returns)
        self._add_underwater_plot(fig, returns)
        self._add_monthly_heatmap(fig, returns)
        self._add_yearly_bars(fig, returns)

        # 更新布局
        fig['layout'].update(
            autosize=True,
            showlegend=False,
            title=title,
            hovermode='x unified'
        )

        return fig

    def _extract_returns(self, results: bt.strategy.Strategy) -> pd.Series:
        """从回测结果提取收益率序列"""
        # 从PyFolio analyzer获取数据
        pyfoliozer = results.analyzers.getbyname('pyfolio')
        returns, _, _, _ = pyfoliozer.get_pf_items()
        return returns

    def _add_equity_curve(self, fig: go.Figure, returns: pd.Series):
        """添加权益曲线"""
        cum_returns = (1 + returns).cumprod()

        equity = go.Scatter(
            x=cum_returns.index,
            y=cum_returns.values,
            line=dict(color=self.color_scheme['equity'], width=2),
            name='Equity'
        )
        fig.append_trace(equity, 1, 1)

        fig['layout']['yaxis1']['title'] = 'Portfolio Value'
        fig['layout']['yaxis1']['tickformat'] = '.2f'
        fig['layout']['xaxis1']['tickformat'] = '%Y-%m-%d'

    def _add_underwater_plot(self, fig: go.Figure, returns: pd.Series):
        """添加水下回撤图"""
        cum_returns = (1 + returns).cumprod()
        running_max = np.maximum.accumulate(cum_returns)
        underwater = -100 * ((running_max - cum_returns) / running_max)

        uw = go.Scatter(
            x=underwater.index,
            y=underwater.values,
            fill='tozeroy',
            line=dict(color=self.color_scheme['drawdown'], width=2),
            name='Drawdown',
            fillcolor='rgba(255, 106, 106, 0.3)'
        )
        fig.append_trace(uw, 2, 1)

        fig['layout']['yaxis2']['title'] = 'Drawdown %'
        fig['layout']['yaxis2']['tickformat'] = '.1f'

    def _add_monthly_heatmap(self, fig: go.Figure, returns: pd.Series):
        """添加月度收益热力图"""
        df = returns.to_frame('return')
        df['year'] = df.index.year
        df['month'] = df.index.month

        # 创建透视表
        pivot = pd.pivot_table(
            df,
            index='year',
            columns='month',
            values='return',
            aggfunc=np.sum
        ).fillna(0) * 100

        months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

        # 添加悬停文本
        hover_text = []
        for year in pivot.index:
            row = []
            for month_idx in range(12):
                val = pivot.loc[year, month_idx + 1] if (month_idx + 1) in pivot.columns else 0
                row.append(f'{year} {months[month_idx]}: {val:.2f}%')
            hover_text.append(row)

        heatmap = go.Heatmap(
            z=pivot.values,
            colorscale=self.color_scheme['heatmap'],
            showscale=False,
            x=months,
            y=pivot.index,
            text=hover_text,
            hoverinfo='text'
        )
        fig.append_trace(heatmap, 3, 1)

        # 添加数值标注
        annotations = []
        for n, row in enumerate(pivot.values):
            for m, val in enumerate(row):
                annotations.append(
                    go.layout.Annotation(
                        text=f'{val:.1f}',
                        x=pivot.columns[m] - 1,
                        y=pivot.index[n],
                        xref='x3',
                        yref='y3',
                        font=dict(color='#000'),
                        showarrow=False
                    )
                )
        fig['layout']['annotations'].extend(annotations)

        fig['layout']['yaxis3']['autorange'] = 'reversed'
        fig['layout']['xaxis3']['title'] = 'Monthly Returns %'

    def _add_yearly_bars(self, fig: go.Figure, returns: pd.Series):
        """添加年度收益柱状图"""
        df = returns.to_frame('return')
        df['year'] = df.index.year

        yearly_returns = df.groupby('year')['return'].sum() * 100

        bars = go.Bar(
            x=yearly_returns.index,
            y=yearly_returns.values,
            marker=dict(
                color=[self.color_scheme['positive'] if v > 0 else self.color_scheme['negative']
                       for v in yearly_returns.values]
            ),
            name='Yearly Return'
        )
        fig.append_trace(bars, 3, 4)

        fig['layout']['yaxis4']['title'] = 'Return %'
        fig['layout']['yaxis4']['tickformat'] = '.1f'


class KLneChartGenerator:
    """K线图生成器"""

    def create_candlestick(self, data: pd.DataFrame, volume: bool = True) -> go.Figure:
        """
        创建K线图

        Args:
            data: 包含OHLCV数据的DataFrame
            volume: 是否显示成交量

        Returns:
            Plotly Figure对象
        """
        # 创建子图
        if volume:
            fig = pto.make_subplots(
                rows=2, cols=1, shared_xaxes=True,
                vertical_spacing=0.03,
                row_heights=[0.7, 0.3]
            )
        else:
            fig = go.Figure()

        # K线图
        candlestick = go.Candlestick(
            x=data.index,
            open=data['open'],
            high=data['high'],
            low=data['low'],
            close=data['close'],
            name='OHLC'
        )
        fig.append_trace(candlestick, 1, 1)

        # 成交量
        if volume and 'volume' in data.columns:
            colors = [
                '#FF6A6A' if row['close'] < row['open'] else '#66B266'
                for _, row in data.iterrows()
            ]
            volume_bar = go.Bar(
                x=data.index,
                y=data['volume'],
                marker=dict(color=colors),
                name='Volume'
            )
            fig.append_trace(volume_bar, 2, 1)

        # 布局
        fig.update_layout(
            xaxis_rangeslider_visible=False,
            hovermode='x unified',
            title='Price Chart'
        )

        return fig
```

#### 3.1.2 使用示例

```python
import backtrader as bt
from omegaui.visualization import TearsheetGenerator, KLneChartGenerator

# 运行回测
cerebro = bt.Cerebro()
cerebro.addstrategy(MyStrategy)
results = cerebro.run()

# 生成Tearsheet
generator = TearsheetGenerator()
fig = generator.create_tearsheet(results[0], title="My Strategy")

# 在Jupyter中显示
fig.show()

# 或者保存为HTML
fig.write_html("backtest_results.html")

# 生成K线图
kline_gen = KLneChartGenerator()
kline_fig = kline_gen.create_candlestick(data_df, volume=True)
```

### 3.2 实时日志系统设计

#### 3.2.1 日志Handler实现

```python
import logging
import json
import threading
import queue
from typing import Optional
from abc import ABC, abstractmethod


class LogPublisher(ABC):
    """日志发布器抽象接口"""

    @abstractmethod
    def publish(self, channel: str, message: dict):
        """发布日志消息"""
        pass


class RedisLogPublisher(LogPublisher):
    """Redis日志发布器"""

    def __init__(self, host='localhost', port=6379, db=0):
        import redis
        self.redis_client = redis.StrictRedis(host=host, port=port, db=db)

    def publish(self, channel: str, message: dict):
        self.redis_client.publish(channel, json.dumps(message))


class QueueLogPublisher(LogPublisher):
    """内存队列发布器（用于单机测试）"""

    def __init__(self):
        self.queues: dict = {}
        self.lock = threading.Lock()

    def get_queue(self, channel: str) -> queue.Queue:
        with self.lock:
            if channel not in self.queues:
                self.queues[channel] = queue.Queue()
            return self.queues[channel]

    def publish(self, channel: str, message: dict):
        q = self.get_queue(channel)
        q.put(message)


class WebSocketLogHandler(logging.Handler):
    """WebSocket日志Handler"""

    def __init__(self, channel: str, publisher: LogPublisher):
        super().__init__()
        self.channel = channel
        self.publisher = publisher

    def emit(self, record: logging.LogRecord):
        """发送日志记录"""
        try:
            message = {
                'name': record.name,
                'levelname': record.levelname,
                'message': self.format(record),
                'timestamp': self.formatTime(record),
                'pathname': record.pathname,
                'lineno': record.lineno
            }
            self.publisher.publish(self.channel, message)
        except Exception:
            self.handleError(record)


class BacktestLogger:
    """回测日志管理器"""

    def __init__(self, session_id: str, publisher: Optional[LogPublisher] = None):
        self.session_id = session_id
        self.channel = f'logs:{session_id}'
        self.publisher = publisher or QueueLogPublisher()
        self.logger = logging.getLogger(f'backtest.{session_id}')
        self._setup_handlers()

    def _setup_handlers(self):
        """设置日志Handler"""
        # 清除现有handlers
        self.logger.handlers.clear()

        # WebSocket Handler
        ws_handler = WebSocketLogHandler(self.channel, self.publisher)
        ws_formatter = logging.Formatter('%(message)s')
        ws_handler.setFormatter(ws_formatter)
        self.logger.addHandler(ws_handler)

        # 文件Handler（可选）
        # file_handler = logging.FileHandler(f'backtest_{self.session_id}.log')
        # self.logger.addHandler(file_handler)

        self.logger.setLevel(logging.DEBUG)

    def get_logger(self) -> logging.Logger:
        """获取logger实例"""
        return self.logger


# 使用示例
def run_backtest_with_logging(session_id: str, strategy_class, **kwargs):
    """带日志的回测执行"""

    # 创建日志管理器
    log_manager = BacktestLogger(session_id)
    logger = log_manager.get_logger()

    logger.info("Starting backtest...")

    try:
        cerebro = bt.Cerebro()
        logger.info(f"Adding strategy: {strategy_class.__name__}")
        cerebro.addstrategy(strategy_class, **kwargs)

        logger.info("Running cerebro...")
        results = cerebro.run()

        logger.info("Backtest completed successfully")
        return results

    except Exception as e:
        logger.error(f"Backtest failed: {str(e)}")
        raise
```

#### 3.2.2 WebSocket服务端

```python
from flask import Flask
from flask_socketio import SocketIO, emit
import threading


class BacktestWebSocketServer:
    """回测WebSocket服务"""

    def __init__(self, host='0.0.0.0', port=5000):
        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = 'backtest-secret'
        self.socketio = SocketIO(self.app, cors_allowed_origins="*")
        self.publisher = QueueLogPublisher()
        self._setup_routes()

    def _setup_routes(self):
        """设置路由和事件"""

        @self.socketio.on('connect')
        def handle_connect():
            print(f"Client connected: {request.sid}")
            emit('connected', {'status': 'ok'})

        @self.socketio.on('subscribe_logs')
        def handle_subscribe(data):
            """订阅日志"""
            session_id = data.get('session_id')
            if not session_id:
                return

            channel = f'logs:{session_id}'

            # 启动日志转发线程
            def forward_logs():
                q = self.publisher.get_queue(channel)
                while True:
                    try:
                        msg = q.get(timeout=1)
                        emit('log_message', msg)
                    except queue.Empty:
                        continue

            thread = threading.Thread(target=forward_logs, daemon=True)
            thread.start()

        @self.socketio.on('disconnect')
        def handle_disconnect():
            print(f"Client disconnected: {request.sid}")

    def run(self):
        """启动服务"""
        self.socketio.run(self.app, host='0.0.0.0', port=5000)


# 启动服务
if __name__ == '__main__':
    server = BacktestWebSocketServer()
    server.run()
```

### 3.3 动态参数管理系统

```python
import inspect
import importlib
from typing import Dict, Any, List
from dataclasses import dataclass


@dataclass
class ParameterInfo:
    """参数信息"""
    name: str
    value: Any
    type: str
    default: Any
    description: str = ""


class ParameterExtractor:
    """策略参数提取器"""

    @staticmethod
    def extract_params(strategy_class) -> List[ParameterInfo]:
        """
        从策略类提取参数定义

        Args:
            strategy_class: backtrader Strategy类

        Returns:
            参数信息列表
        """
        params = []

        # 获取params定义
        if hasattr(strategy_class, 'params'):
            for name, value in strategy_class.params._getitems():
                param = ParameterInfo(
                    name=name,
                    value=value,
                    type=type(value).__name__,
                    default=value,
                    description=ParameterExtractor._get_param_doc(
                        strategy_class, name
                    )
                )
                params.append(param)

        return params

    @staticmethod
    def _get_param_doc(strategy_class, param_name: str) -> str:
        """从docstring提取参数说明"""
        docstring = strategy_class.__doc__ or ""
        # 简化实现，实际可以使用更复杂的docstring解析
        lines = docstring.split('\n')
        for line in lines:
            if param_name in line:
                return line.strip()
        return ""

    @staticmethod
    def validate_params(strategy_class, params: Dict[str, Any]) -> List[str]:
        """
        验证参数值

        Returns:
            错误信息列表
        """
        errors = []
        param_infos = {p.name: p for p in ParameterExtractor.extract_params(strategy_class)}

        for name, value in params.items():
            if name not in param_infos:
                errors.append(f"Unknown parameter: {name}")
                continue

            param_info = param_infos[name]

            # 类型检查
            expected_type = param_info.type
            actual_type = type(value).__name__

            if expected_type != actual_type:
                try:
                    # 尝试类型转换
                    if expected_type == 'int':
                        params[name] = int(value)
                    elif expected_type == 'float':
                        params[name] = float(value)
                    elif expected_type == 'bool':
                        if isinstance(value, str):
                            params[name] = value.lower() in ('true', '1', 'yes')
                except (ValueError, TypeError):
                    errors.append(
                        f"Parameter '{name}': expected {expected_type}, got {actual_type}"
                    )

        return errors


class StrategyLoader:
    """策略加载器"""

    def __init__(self):
        self._strategy_cache = {}

    def load_strategy(self, module_path: str, class_name: str):
        """加载策略类"""
        cache_key = f"{module_path}.{class_name}"

        if cache_key in self._strategy_cache:
            return self._strategy_cache[cache_key]

        try:
            module = importlib.import_module(module_path)
            importlib.reload(module)  # 热重载
            strategy_class = getattr(module, class_name)

            # 验证是Strategy子类
            import backtrader as bt
            if not issubclass(strategy_class, bt.Strategy):
                raise ValueError(f"{class_name} is not a Strategy subclass")

            self._strategy_cache[cache_key] = strategy_class
            return strategy_class

        except (ImportError, AttributeError) as e:
            raise ValueError(f"Failed to load strategy: {e}")

    def list_strategies(self, module_path: str) -> List[Dict]:
        """列出模块中的所有策略"""
        try:
            module = importlib.import_module(module_path)
            importlib.reload(module)

            strategies = []
            for name, obj in inspect.getmembers(module):
                if inspect.isclass(obj):
                    # 检查是否是Strategy子类
                    import backtrader as bt
                    try:
                        if issubclass(obj, bt.Strategy) and obj != bt.Strategy:
                            strategies.append({
                                'name': name,
                                'module': module_path,
                                'doc': obj.__doc__ or "",
                                'params': [
                                    p.name for p in ParameterExtractor.extract_params(obj)
                                ]
                            })
                    except TypeError:
                        pass

            return strategies

        except ImportError as e:
            return []


# 使用示例
loader = StrategyLoader()

# 列出策略
strategies = loader.list_strategies('my_strategies')
for s in strategies:
    print(f"{s['name']}: {s['doc']}")

# 加载策略
MyStrategy = loader.load_strategy('my_strategies', 'TestStrategy')

# 提取参数
params = ParameterExtractor.extract_params(MyStrategy)
for p in params:
    print(f"{p.name}: {p.value} (type: {p.type})")

# 验证并修改参数
user_params = {'period': 25, 'printlog': True}
errors = ParameterExtractor.validate_params(MyStrategy, user_params)
if not errors:
    # 使用参数运行回测
    cerebro = bt.Cerebro()
    cerebro.addstrategy(MyStrategy, **user_params)
```

### 3.4 统计分析模块

```python
import pandas as pd
import numpy as np
import backtrader as bt
from typing import Dict, Any
from dataclasses import dataclass


@dataclass
class BacktestStats:
    """回测统计结果"""
    # 曲线指标
    total_return: float
    cagr: float
    sharpe_ratio: float
    annual_volatility: float
    sqn: float
    r_squared: float
    max_drawdown: float
    max_drawdown_duration: int

    # 交易指标
    win_rate: float
    avg_trade: float
    avg_win: float
    avg_loss: float
    best_trade: float
    worst_trade: float
    avg_trade_duration: float
    total_trades: int

    # 时间维度
    win_month_pct: float
    avg_win_month: float
    avg_loss_month: float
    best_month: float
    worst_month: float
    win_year_pct: float
    best_year: float
    worst_year: float


class StatisticsCalculator:
    """回测统计计算器"""

    @staticmethod
    def calculate(results: bt.strategy.Strategy) -> BacktestStats:
        """计算完整的回测统计"""

        # 获取analyzer结果
        pyfoliozer = results.analyzers.getbyname('pyfolio')
        returns, _, _, _ = pyfoliozer.get_pf_items()

        drawdown_analysis = results.analyzers.drawdown.get_analysis()
        sqn_analysis = results.analyzers.SQN.get_analysis()
        trades_analysis = results.analyzers.trades.get_analysis()

        # 曲线指标
        total_return = StatisticsCalculator._total_return(returns)
        cagr = StatisticsCalculator._cagr(returns)
        sharpe = StatisticsCalculator._sharpe_ratio(returns)
        volatility = StatisticsCalculator._annual_volatility(returns)

        # 交易指标
        win_rate, avg_win, avg_loss = StatisticsCalculator._trade_stats(trades_analysis)

        # 时间维度
        monthly_stats = StatisticsCalculator._monthly_stats(returns)
        yearly_stats = StatisticsCalculator._yearly_stats(returns)

        return BacktestStats(
            total_return=total_return,
            cagr=cagr,
            sharpe_ratio=sharpe,
            annual_volatility=volatility,
            sqn=sqn_analysis.get('sqn', 0),
            r_squared=StatisticsCalculator._r_squared(returns),
            max_drawdown=drawdown_analysis['max']['drawdown'],
            max_drawdown_duration=drawdown_analysis['max']['len'],
            win_rate=win_rate,
            avg_trade=trades_analysis.get('pnl', {}).get('net', {}).get('average', 0),
            avg_win=avg_win,
            avg_loss=avg_loss,
            best_trade=trades_analysis.get('won', {}).get('pnl', {}).get('max', 0),
            worst_trade=trades_analysis.get('lost', {}).get('pnl', {}).get('max', 0),
            avg_trade_duration=trades_analysis.get('len', {}).get('average', 0),
            total_trades=trades_analysis.get('total', {}).get('total', 0),
            win_month_pct=monthly_stats['win_pct'],
            avg_win_month=monthly_stats['avg_win'],
            avg_loss_month=monthly_stats['avg_loss'],
            best_month=monthly_stats['best'],
            worst_month=monthly_stats['worst'],
            win_year_pct=yearly_stats['win_pct'],
            best_year=yearly_stats['best'],
            worst_year=yearly_stats['worst']
        )

    @staticmethod
    def _total_return(returns: pd.Series) -> float:
        """总收益率"""
        return round((1 + returns).prod() - 1, 4)

    @staticmethod
    def _cagr(returns: pd.Series) -> float:
        """年化收益率"""
        try:
            import empyrical as ep
            return round(ep.cagr(returns), 4)
        except ImportError:
            # 简化计算
            total_days = (returns.index[-1] - returns.index[0]).days
            years = total_days / 365.25
            total_return = (1 + returns).prod()
            return round(total_return ** (1 / years) - 1, 4)

    @staticmethod
    def _sharpe_ratio(returns: pd.Series, risk_free_rate: float = 0.0) -> float:
        """夏普比率"""
        try:
            import empyrical as ep
            return round(ep.sharpe_ratio(returns, risk_free_rate=risk_free_rate), 4)
        except ImportError:
            # 简化计算
            return round(returns.mean() / returns.std() * np.sqrt(252), 4)

    @staticmethod
    def _annual_volatility(returns: pd.Series) -> float:
        """年化波动率"""
        return round(returns.std() * np.sqrt(252), 4)

    @staticmethod
    def _r_squared(returns: pd.Series) -> float:
        """R-Squared（时间序列稳定性）"""
        try:
            import empyrical as ep
            return round(ep.stability_of_timeseries(returns), 4)
        except ImportError:
            # 简化：返回收益与时间的线性相关系数
            x = np.arange(len(returns))
            cumulative = (1 + returns).cumprod()
            return round(np.corrcoef(x, cumulative)[0, 1] ** 2, 4)

    @staticmethod
    def _trade_stats(trades_analysis: dict) -> tuple:
        """交易统计"""
        total = trades_analysis.get('total', {}).get('total', 0)
        won = trades_analysis.get('won', {}).get('total', 0)

        win_rate = round(won / total * 100, 2) if total > 0 else 0

        avg_win = trades_analysis.get('won', {}).get('pnl', {}).get('average', 0)
        avg_loss = trades_analysis.get('lost', {}).get('pnl', {}).get('average', 0)

        return win_rate, round(avg_win, 2), round(avg_loss, 2)

    @staticmethod
    def _monthly_stats(returns: pd.Series) -> dict:
        """月度统计"""
        df = returns.to_frame('return')
        df['year'] = df.index.year
        df['month'] = df.index.month

        monthly_returns = df.groupby(['year', 'month'])['return'].sum()

        win_months = (monthly_returns > 0).sum()
        total_months = len(monthly_returns)

        win_pct = round(win_months / total_months * 100, 2) if total_months > 0 else 0
        avg_win = round(monthly_returns[monthly_returns > 0].mean(), 4) if win_months > 0 else 0
        avg_loss = round(monthly_returns[monthly_returns < 0].mean(), 4) if win_months < total_months else 0
        best = round(monthly_returns.max(), 4)
        worst = round(monthly_returns.min(), 4)

        return {
            'win_pct': win_pct,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'best': best,
            'worst': worst
        }

    @staticmethod
    def _yearly_stats(returns: pd.Series) -> dict:
        """年度统计"""
        df = returns.to_frame('return')
        df['year'] = df.index.year

        yearly_returns = df.groupby('year')['return'].sum()

        win_years = (yearly_returns > 0).sum()
        total_years = len(yearly_returns)

        win_pct = round(win_years / total_years * 100, 2) if total_years > 0 else 0
        best = round(yearly_returns.max(), 4)
        worst = round(yearly_returns.min(), 4)

        return {
            'win_pct': win_pct,
            'best': best,
            'worst': worst
        }


# 格式化输出
class StatsFormatter:
    """统计结果格式化器"""

    @staticmethod
    def to_dict(stats: BacktestStats) -> Dict[str, Dict[str, Any]]:
        """转换为嵌套字典格式"""
        return {
            'Curve': {
                'Total Return': f"{stats.total_return * 100:.2f}%",
                'CAGR': f"{stats.cagr * 100:.2f}%",
                'Sharpe Ratio': f"{stats.sharpe_ratio:.2f}",
                'Annual Volatility': f"{stats.annual_volatility * 100:.2f}%",
                'SQN': f"{stats.sqn:.2f}",
                'R-Squared': f"{stats.r_squared:.2f}",
                'Max Drawdown': f"{stats.max_drawdown:.2f}%",
                'Max DD Duration': f"{stats.max_drawdown_duration} days"
            },
            'Trade': {
                'Win Rate': f"{stats.win_rate:.2f}%",
                'Average Trade': f"{stats.avg_trade:.2f}",
                'Average Win': f"{stats.avg_win:.2f}",
                'Average Loss': f"{stats.avg_loss:.2f}",
                'Best Trade': f"{stats.best_trade:.2f}",
                'Worst Trade': f"{stats.worst_trade:.2f}",
                'Avg Duration': f"{stats.avg_trade_duration:.1f} days",
                'Total Trades': stats.total_trades
            },
            'Time': {
                'Win Months %': f"{stats.win_month_pct:.2f}%",
                'Avg Win Month': f"{stats.avg_win_month * 100:.2f}%",
                'Avg Loss Month': f"{stats.avg_loss_month * 100:.2f}%",
                'Best Month': f"{stats.best_month * 100:.2f}%",
                'Worst Month': f"{stats.worst_month * 100:.2f}%",
                'Win Years %': f"{stats.win_year_pct:.2f}%",
                'Best Year': f"{stats.best_year * 100:.2f}%",
                'Worst Year': f"{stats.worst_year * 100:.2f}%"
            }
        }
```

### 3.5 Dash应用集成

```python
import dash
from dash import dcc, html, dash_table
import dash.dependencies as dd
from dash.exceptions import PreventUpdate
import plotly.graph_objs as go


class BacktestApp:
    """Backtrader Dash应用"""

    def __init__(self):
        self.app = dash.Dash(__name__)
        self.strategy_loader = StrategyLoader()
        self.backtest_results = {}
        self._setup_layout()
        self._setup_callbacks()

    def _setup_layout(self):
        """设置UI布局"""
        self.app.layout = html.Div([
            # 标题
            html.H1('Backtrader Dashboard', className='mb-4'),

            # 控制面板
            html.Div([
                html.Div([
                    html.Label('Module:'),
                    dcc.Dropdown(id='module-dropdown', options=[], value=None)
                ], className='col-md-4'),

                html.Div([
                    html.Label('Strategy:'),
                    dcc.Dropdown(id='strategy-dropdown', options=[], value=None)
                ], className='col-md-4'),

                html.Div([
                    html.Label('Cash:'),
                    dcc.Input(id='cash-input', type='number', value=10000, className='form-control')
                ], className='col-md-4')
            ], className='row mb-3'),

            # 参数表格
            html.Div(id='params-container', className='mb-3'),

            # 运行按钮
            html.Button('Run Backtest', id='run-btn', n_clicks=0, className='btn btn-primary mb-3'),

            # 结果区域
            html.Div(id='results-container', style={'display': 'none'}, children=[
                # 图表
                dcc.Graph(id='tearsheet-chart'),

                # 统计指标
                html.Div(id='stats-display', className='mt-4')
            ])
        ])

    def _setup_callbacks(self):
        """设置回调函数"""

        @self.app.callback(
            dd.Output('module-dropdown', 'options'),
            [dd.Input('module-dropdown', 'search_value')]
        )
        def update_modules(search_value):
            # 列出可用模块
            modules = ['my_strategies', 'strategies.another']
            return [{'label': m, 'value': m} for m in modules]

        @self.app.callback(
            dd.Output('strategy-dropdown', 'options'),
            [dd.Input('module-dropdown', 'value')]
        )
        def update_strategies(module_name):
            if not module_name:
                return []
            strategies = self.strategy_loader.list_strategies(module_name)
            return [{'label': s['name'], 'value': s['name']} for s in strategies]

        @self.app.callback(
            dd.Output('params-container', 'children'),
            [dd.Input('strategy-dropdown', 'value')],
            [dd.State('module-dropdown', 'value')]
        )
        def update_params(strategy_name, module_name):
            if not strategy_name or not module_name:
                return []

            strategy_class = self.strategy_loader.load_strategy(module_name, strategy_name)
            params = ParameterExtractor.extract_params(strategy_class)

            data = [{'Parameter': p.name, 'Value': p.value, 'Type': p.type} for p in params]

            return dash_table.DataTable(
                id='params-table',
                columns=[
                    {'name': 'Parameter', 'id': 'Parameter'},
                    {'name': 'Value', 'id': 'Value', 'editable': True},
                    {'name': 'Type', 'id': 'Type'}
                ],
                data=data,
                editable=True
            )

        @self.app.callback(
            [dd.Output('results-container', 'style'),
             dd.Output('results-container', 'children')],
            [dd.Input('run-btn', 'n_clicks')],
            [dd.State('module-dropdown', 'value'),
             dd.State('strategy-dropdown', 'value'),
             dd.State('cash-input', 'value'),
             dd.State('params-table', 'data')]
        )
        def run_backtest(n_clicks, module_name, strategy_name, cash, params_data):
            if n_clicks == 0:
                raise PreventUpdate

            # 执行回测
            results = self._execute_backtest(
                module_name, strategy_name, cash, params_data
            )

            # 生成图表
            generator = TearsheetGenerator()
            fig = generator.create_tearsheet(results, title=f"{strategy_name} Results")

            # 计算统计
            stats = StatisticsCalculator.calculate(results)
            stats_dict = StatsFormatter.to_dict(stats)

            # 统计显示
            stats_html = self._format_stats(stats_dict)

            return {'display': 'block'}, [
                dcc.Graph(figure=fig),
                stats_html
            ]

    def _execute_backtest(self, module_name, strategy_name, cash, params_data):
        """执行回测"""
        import backtrader as bt

        strategy_class = self.strategy_loader.load_strategy(module_name, strategy_name)

        cerebro = bt.Cerebro()
        cerebro.broker.setcash(cash)
        cerebro.addstrategy(strategy_class)

        # 添加数据（示例）
        # data = bt.feeds.PandasData(dataname=...)
        # cerebro.adddata(data)

        results = cerebro.run()
        return results[0]

    def _format_stats(self, stats_dict: dict) -> html.Div:
        """格式化统计显示"""
        rows = []

        for section, metrics in stats_dict.items():
            rows.append(html.H4(section))
            for metric, value in metrics.items():
                rows.append(html.Div([
                    html.Span(metric, className='font-weight-bold'),
                    html.Span(value, className='float-right')
                ], className='row mb-1'))

        return html.Div(rows, className='container mt-4')

    def run(self, debug=True):
        """运行应用"""
        self.app.run_server(debug=debug)


# 启动应用
if __name__ == '__main__':
    app = BacktestApp()
    app.run()
```

---

## 四、实施路线图

### 阶段一：核心可视化（1-2个月）

**目标**: 实现基于Plotly的交互式图表

1. **Tearsheet生成器**（3周）
   - Week 1: 实现权益曲线和回撤图
   - Week 2: 实现月度热力图和年度柱状图
   - Week 3: 布局优化和样式调整

2. **K线图生成器**（2周）
   - Week 1: 基础K线图
   - Week 2: 成交量和指标叠加

3. **统计分析**（1周）
   - 提取analyzer数据
   - 计算各项指标

### 阶段二：实时系统（1-2个月）

**目标**: 实现日志推送和参数管理

1. **实时日志系统**（3周）
   - Week 1: WebSocket Handler实现
   - Week 2: Redis集成
   - Week 3: 前端展示和过滤

2. **参数管理**（2周）
   - Week 1: 参数提取和验证
   - Week 2: UI编辑和持久化

3. **策略加载器**（1周）
   - 动态加载和热重载

### 阶段三：Web应用（1-2个月）

**目标**: 构建完整的Dash应用

1. **Dash框架搭建**（2周）
   - 布局设计
   - 回调函数实现

2. **API服务**（2周）
   - RESTful接口
   - 任务队列

3. **结果对比**（1周）
   - 多结果对比功能

### 阶段四：测试和文档（1个月）

**目标**: 完善测试和文档

1. **测试覆盖**（2周）
2. **文档编写**（1周）
3. **示例代码**（1周）

### 总时间估算：4-7个月

---

## 五、总结

### 5.1 OmegaUI的核心优势

1. **Plotly交互图表**: 比matplotlib更适合Web展示
2. **实时日志推送**: Redis + WebSocket架构可扩展
3. **动态参数管理**: 无需重启即可调整参数
4. **模块化设计**: Backtest基类易于扩展
5. **Dash框架**: 快速构建分析型Web应用

### 5.2 对Backtrader的借鉴价值

1. **可视化增强**: Plotly Tearsheet可补充backtrader的可视化能力
2. **实时反馈**: 适合长时间运行的回测任务
3. **Web化**: 便于远程使用和团队协作
4. **参数优化**: 支持参数调优工作流

### 5.3 实施建议

1. **优先级**: 可视化 > 实时日志 > 参数管理 > API服务
2. **技术选择**: Plotly（图表）、Dash（框架）、Redis（消息）
3. **兼容性**: 保持与现有backtrader API兼容
4. **渐进式**: 可作为独立包逐步集成
