### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/backtrader_bokeh
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

---

## 一、项目对比分析

### 1.1 backtrader_bokeh 项目核心特性

| 特性 | 描述 |
|------|------|
| **实时绘图** | 基于 Bokeh Server 的实时数据推送和图表更新 |
| **分析器集成** | 将绘图功能作为 `bt.Analyzer` 深度集成 |
| **标签页系统** | 可扩展的标签页架构（Analyzer、Config、Log、Metadata、Source） |
| **导航控制** | 暂停/播放/前进/后退的时间轴导航 |
| **数据过滤** | 按 dataname 或 plotgroup 过滤显示内容 |
| **主题系统** | Blackly（黑）和 Tradimo（白）两种主题 |
| **内存优化** | lookback 参数控制历史数据保留量 |
| **多标签支持** | 可同时查看日志、配置、源码、分析器结果 |

### 1.2 backtrader 现有绘图能力

| 能力 | backtrader | backtrader_bokeh |
|------|-----------|------------------|
| **绘图后端** | matplotlib, Plotly | Bokeh |
| **实时更新** | 不支持 | ✅ WebSocket 支持 |
| **导航控制** | 静态图表 | ✅ 时间轴导航 |
| **标签页** | 无 | ✅ 可扩展标签页 |
| **主题系统** | PlotlyScheme | ✅ 主题配置 |
| **内存优化** | 全量数据 | ✅ lookback 控制 |
| **Web 服务** | 静态 HTML | ✅ Bokeh Server |

### 1.3 差距分析

| 方面 | backtrader_bokeh | backtrader | 差距 |
|------|-----------------|------------|------|
| **实时数据** | WebSocket 推送 | 无 | backtrader 缺少实时更新 |
| **导航控制** | 暂停/前进/后退 | 无交互控制 | backtrader 缺少导航 |
| **标签页系统** | 可扩展架构 | 无 | backtrader 缺少模块化UI |
| **数据过滤** | 动态过滤 | 无 | backtrader 缺少运行时过滤 |
| **内存管理** | lookback 控制 | 全量加载 | backtrader 可优化内存 |

---

## 二、需求规格文档

### 2.1 功能需求

#### FR1: 实时绘图分析器
创建基于 Bokeh 的实时绘图分析器：

- **FR1.1**: 支持 WebSocket 实时数据推送
- **FR1.2**: 支持暂停/继续功能
- **FR1.3**: 支持前进/后退导航
- **FR1.4**: 支持数据 lookback 控制

#### FR2: 标签页系统
可扩展的标签页架构：

- **FR2.1**: 基础标签页类 `BacktraderBokehTab`
- **FR2.2**: 内置标签页：Analyzer、Config、Log、Metadata、Source
- **FR2.3**: 支持用户自定义标签页
- **FR2.4**: 标签页条件显示（is_useable）

#### FR3: 导航控制
时间轴导航控制：

- **FR3.1**: 暂停/播放按钮
- **FR3.2**: 单步前进/后退
- **FR3.3**: 多步前进/后退（如 10 步）
- **FR3.4**: 智能按钮状态（边界禁用）

#### FR4: 数据过滤
运行时数据过滤：

- **FR4.1**: 按 dataname 过滤
- **FR4.2**: 按 plotgroup 过滤
- **FR4.3**: 策略级别过滤
- **FR4.4**: 动态切换无需重启

#### FR5: 主题系统
完整的主题配置：

- **FR5.1**: 黑色主题（Blackly）
- **FR5.2**: 白色主题（Tradimo）
- **FR5.3**: 自定义主题支持
- **FR5.4**: 主题继承机制

### 2.2 非功能需求

- **NFR1**: 性能 - 支持大数据集（10万+点）流畅渲染
- **NFR2**: 内存 - lookback 机制控制内存使用
- **NFR3**: 兼容性 - 与现有 backtrader API 兼容
- **NFR4**: 可扩展性 - 标签页和主题可自定义

### 2.3 用户故事

| ID | 故事描述 | 优先级 |
|----|---------|--------|
| US1 | 作为量化研究员，我想实时监控策略执行，而不需要等待回测完成 | P0 |
| US2 | 作为策略开发者，我想暂停回测查看特定时刻的状态 | P0 |
| US3 | 作为分析师，我想在同一个界面查看日志、配置和分析结果 | P1 |
| US4 | 作为用户，我想自定义主题以符合个人偏好 | P1 |

---

## 三、设计文档

### 3.1 模块结构设计

```
backtrader/
├── bokeh/                      # 新增 Bokeh 模块
│   ├── __init__.py             # 模块初始化
│   ├── app.py                  # 核心应用类
│   ├── scheme.py               # 主题基类
│   ├── schemes/                # 主题实现
│   │   ├── __init__.py
│   │   ├── blackly.py          # 黑色主题
│   │   └── tradimo.py          # 白色主题
│   ├── analyzers/              # 分析器
│   │   ├── __init__.py
│   │   └── live_plot.py        # 实时绘图分析器
│   ├── tabs/                   # 标签页
│   │   ├── __init__.py
│   │   ├── base.py             # 标签页基类
│   │   ├── analyzer.py         # 分析器标签页
│   │   ├── config.py           # 配置标签页
│   │   ├── log.py              # 日志标签页
│   │   ├── metadata.py         # 元数据标签页
│   │   └── source.py           # 源码标签页
│   ├── live/                   # 实时功能
│   │   ├── __init__.py
│   │   ├── client.py           # 实时客户端
│   │   └── datahandler.py      # 数据处理器
│   └── utils/                  # 工具函数
│       ├── __init__.py
│       └── helpers.py          # 辅助函数
```

### 3.2 核心类设计

#### 3.2.1 主题系统

```python
class BokehScheme:
    """Bokeh 绘图主题基类

    定义所有绘图相关的样式参数
    参考：backtrader_bokeh/schemes/blackly.py
    """

    def __init__(self):
        self._set_params()

    def _set_params(self):
        """设置默认参数"""
        # 颜色配置
        self.barup = '#ff9896'           # 上涨颜色
        self.bardown = '#98df8a'         # 下跌颜色
        self.volup = '#ff9896'           # 上涨成交量
        self.voldown = '#98df8a'         # 下跌成交量

        # 背景配置
        self.background_fill = '#222222'
        self.body_background_color = '#2B2B2B'

        # 网格配置
        self.grid_line_color = '#444444'

        # 文字配置
        self.axis_text_color = 'lightgrey'

        # 十字准线
        self.crosshair_line_color = '#999999'


class BlacklyScheme(BokehScheme):
    """黑色主题

    参考：backtrader_bokeh/schemes/blackly.py
    """

    def _set_params(self):
        super()._set_params()
        # 覆盖特定样式
        self.barup = '#ff9896'
        self.bardown = '#98df8a'
        self.background_fill = '#222222'


class TradimoScheme(BokehScheme):
    """白色主题"""
    def _set_params(self):
        super()._set_params()
        # 白色主题样式
        self.barup = '#ff0000'
        self.bardown = '#00ff00'
        self.background_fill = '#ffffff'
```

#### 3.2.2 标签页系统

```python
class BokehTab:
    """标签页基类

    参考：backtrader_bokeh/tab.py
    """

    def __init__(self, app, figurepage, client=None):
        self._app = app
        self._figurepage = figurepage
        self._client = client
        self._panel = None

    def _is_useable(self):
        """判断标签页是否可用

        子类必须实现此方法
        """
        raise NotImplementedError()

    def _get_panel(self):
        """获取标签页内容

        返回: (child_widget, title)
        子类必须实现此方法
        """
        raise NotImplementedError()

    def is_useable(self):
        """公共接口：判断是否可用"""
        return self._is_useable()

    def get_panel(self):
        """公共接口：获取面板"""
        child, title = self._get_panel()
        from bokeh.models.widgets import Panel
        self._panel = Panel(child=child, title=title)
        return self._panel


class AnalyzerTab(BokehTab):
    """分析器标签页

    显示所有分析器的结果
    """

    def _is_useable(self):
        # 有分析器时可用
        return len(self._strategy.analyzers) > 0

    def _get_panel(self):
        # 创建分析器结果表格
        from bokeh.models import DataTable
        table = self._create_analyzer_table()
        return table, 'Analyzers'


class LogTab(BokehTab):
    """日志标签页"""

    def __init__(self, app, figurepage, client=None, cols=None):
        super().__init__(app, figurepage, client)
        self.cols = cols or ['Date', 'Message']

    def _is_useable(self):
        return True

    def _get_panel(self):
        # 创建日志表格
        table = self._create_log_table()
        return table, 'Log'
```

#### 3.2.3 实时绘图分析器

```python
class LivePlotAnalyzer(bt.Analyzer):
    """实时绘图分析器

    参考：backtrader_bokeh/analyzers/plot.py
    """

    params = (
        ('scheme', None),           # 主题
        ('style', 'bar'),           # 图表样式
        ('lookback', 100),          # 历史数据保留量
        ('address', 'localhost'),   # 服务器地址
        ('port', 8999),             # 服务器端口
        ('title', None),            # 标题
        ('autostart', True),        # 自动启动
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._scheme = self.p.scheme or TradimoScheme()
        self._lock = threading.Lock()
        self._clients = {}
        self._webapp = None

    def start(self):
        """从 backtrader 启动

        启动 Bokeh Server
        """
        self._start_server()

    def stop(self):
        """从 backtrader 停止"""
        with self._lock:
            for client in self._clients.values():
                client.stop()

    def next(self):
        """从 backtrader 接收新数据

        更新所有连接的客户端
        """
        with self._lock:
            for client in self._clients.values():
                client.next()
```

#### 3.2.4 实时客户端

```python
class LiveClient:
    """实时客户端

    管理 Bokeh 文档和用户交互
    参考：backtrader_bokeh/live/client.py
    """

    def __init__(self, doc, app, strategy, lookback):
        self.doc = doc              # Bokeh 文档
        self._app = app
        self._strategy = strategy
        self.lookback = lookback
        self._paused = False
        self._filter = ''
        self._datahandler = None

    def _create_navigation(self):
        """创建导航控制

        包括：暂停/播放、前进/后退按钮
        """
        from bokeh.models import Button

        # 控制按钮
        btn_prev = Button(label='❮', width=38)
        btn_prev.on_click(self._on_prev)

        btn_action = Button(label='❙❙', width=38)
        btn_action.on_click(self._on_action)

        btn_next = Button(label='❯', width=38)
        btn_next.on_click(self._on_next)

        return [btn_prev, btn_action, btn_next]

    def _on_action(self):
        """暂停/播放切换"""
        if self._paused:
            self._resume()
        else:
            self._pause()

    def _on_prev(self):
        """后退一步"""
        self._pause()
        self._set_data_by_idx(self._datahandler.get_last_idx() - 1)

    def _on_next(self):
        """前进一步"""
        self._pause()
        self._set_data_by_idx(self._datahandler.get_last_idx() + 1)

    def next(self):
        """接收新数据并更新"""
        if not self._paused:
            self._datahandler.update()
```

### 3.3 API 设计

```python
import backtrader as bt

# 1. 使用实时绘图
cerebro = bt.Cerebro()
cerebro.adddata(data)
cerebro.addstrategy(MyStrategy)

# 添加实时绘图分析器
cerebro.addanalyzer(bt.bokeh.LivePlotAnalyzer,
                   scheme=bt.bokeh.schemes.Blackly(),
                   lookback=100,
                   autostart=True)

strats = cerebro.run()

# 2. 静态绘图（使用 Bokeh）
from backtrader.bokeh import BokehPlot

plotter = BokehPlot(style='candle',
                    scheme=bt.bokeh.schemes.Blackly())
cerebro.plot(plotter)

# 3. 自定义标签页
class MyCustomTab(bt.bokeh.BokehTab):
    def _is_useable(self):
        return True

    def _get_panel(self):
        from bokeh.models import Div
        div = Div(text='<h1>My Custom Content</h1>')
        return div, 'Custom'

# 注册自定义标签页
bt.bokeh.register_tab(MyCustomTab)
```

### 3.4 组件化架构

```
┌────────────────────────────────────────────────────────────┐
│                    Backtrader Bokeh Components              │
├────────────────────────────────────────────────────────────┤
│  Layer: Application                                         │
│  ┌──────────────────────────────────────────────────────┐ │
│  │  BokehApp (app.py)                                   │ │
│  │  - create_figurepage()                              │ │
│  │  - generate_model_panels()                          │ │
│  │  - update_figurepage()                              │ │
│  └──────────────────────────────────────────────────────┘ │
├────────────────────────────────────────────────────────────┤
│  Layer: Analyzer                                           │
│  ┌──────────────────────────────────────────────────────┐ │
│  │  LivePlotAnalyzer                                    │ │
│  │  - start() / stop() / next()                        │ │
│  │  - 管理 WebSocket 服务器                             │ │
│  └──────────────────────────────────────────────────────┘ │
├────────────────────────────────────────────────────────────┤
│  Layer: Client & Navigation                                │
│  ┌──────────────────┐  ┌────────────────────────────────┐ │
│  │  LiveClient      │  │  Navigation Controls           │ │
│  │  - pause/resume  │  │  - ❙❙ (暂停/播放)              │ │
│  │  - prev/next     │  │  - ❮ ❯ (单步)                 │ │
│  │  - datahandler   │  │  - ❮❮ ❯❯ (多步)               │ │
│  └──────────────────┘  └────────────────────────────────┘ │
├────────────────────────────────────────────────────────────┤
│  Layer: Tabs                                                │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐     │
│  │ Analyzer │ │  Config  │ │   Log    │ │ Metadata │     │
│  │   Tab    │ │   Tab    │ │   Tab    │ │   Tab    │     │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘     │
│  ┌──────────┐ ┌──────────────────────────────────────┐  │
│  │  Source  │ │        Custom Tabs (User-defined)   │  │
│  │   Tab    │ │                                        │  │
│  └──────────┘ └──────────────────────────────────────┘  │
├────────────────────────────────────────────────────────────┤
│  Layer: Scheme                                              │
│  ┌──────────────────┐  ┌──────────────────┐              │
│  │  BlacklyScheme   │  │  TradimoScheme   │              │
│  │  (Dark Theme)    │  │  (Light Theme)   │              │
│  └──────────────────┘  └──────────────────┘              │
└────────────────────────────────────────────────────────────┘
```

### 3.5 数据流设计

```
Backtrader Cerebro.run()
    │
    ├─→ Strategy.next()
    │
    ├─→ LivePlotAnalyzer.next()
    │       │
    │       └─→ LiveClient.next()
    │               │
    │               └─→ LiveDataHandler.update()
    │                       │
    │                       └─→ Bokeh Document.patch()
    │                               │
    │                               └─→ WebSocket 推送
    │                                       │
    └──────────────────────────────────────→ 浏览器更新
```

### 3.6 与 Plotly 的关系

| 特性 | Plotly | Bokeh | 建议 |
|------|--------|-------|------|
| 静态图表 | ✅ | ✅ | Plotly 更简单 |
| 实时更新 | ❌ | ✅ | Bokeh 用于实时 |
| 交互性 | ✅ | ✅ | 两者都很好 |
| 服务器 | 无需 | 需要 | Plotly 更轻量 |
| 导航控制 | 有限 | ✅ | Bokeh 更强 |

**建议**: 将 Bokeh 作为可选的实时绘图后端，与 Plotly 共存。

---

## 四、实施计划

### 4.1 实施阶段

| 阶段 | 任务 | 预计工作量 |
|------|------|-----------|
| Phase 1 | 创建 bokeh 目录结构和基础类 | 2天 |
| Phase 2 | 实现主题系统（Scheme） | 1天 |
| Phase 3 | 实现标签页基类和内置标签页 | 3天 |
| Phase 4 | 实现 LiveClient 和数据处理器 | 3天 |
| Phase 5 | 实现 LivePlotAnalyzer | 2天 |
| Phase 6 | Bokeh Server 集成 | 2天 |
| Phase 7 | 测试和文档 | 2天 |

### 4.2 优先级

1. **P0**: 主题系统和基础架构
2. **P0**: LiveClient 和导航控制
3. **P0**: LivePlotAnalyzer 基本功能
4. **P1**: 内置标签页实现
5. **P1**: 数据过滤功能
6. **P2**: 自定义标签页支持
7. **P2**: 高级主题定制

---

## 五、参考资料

### 5.1 关键参考代码

- backtrader_bokeh/__init__.py - 模块初始化和集成方式
- backtrader_bokeh/analyzers/plot.py - LivePlotAnalyzer 实现
- backtrader_bokeh/live/client.py - LiveClient 和导航控制
- backtrader_bokeh/tab.py - 标签页基类
- backtrader_bokeh/schemes/blackly.py - 主题实现
- backtrader_bokeh/tabs/ - 各类内置标签页

### 5.2 技术参考

- **Bokeh Server**: 用于实时数据推送
- **Bokeh Models**: ColumnDataSource、图、布局
- **Tornado**: Bokeh Server 依赖的异步框架
- **WebSocket**: 实时通信协议

### 5.3 backtrader 可复用组件

- `backtrader/analyzer.py` - 分析器基类
- `backtrader/plot/plot_plotly.py` - 现有绘图实现（可参考结构）
- `backtrader/observers/` - 数据观察器
- `backtrader/lineseries.py` - 数据访问接口