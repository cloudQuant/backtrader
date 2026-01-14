### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/backtrader_plotly
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

---

## 一、项目对比分析

### 1.1 backtrader_plotly 项目核心特性

| 特性 | 描述 |
|------|------|
| **独立Plotly实现** | 完全独立的Plotly绘图库，不依赖matplotlib |
| **Tableau配色** | 提供Tableau 10/20专业调色板 |
| **填充区域图** | 支持 `_fill_gt`、`_fill_lt` 等填充功能 |
| **小数位数控制** | `decimal_places` 参数控制价格显示精度 |
| **图例文本换行** | `max_legend_text_width` 防止图例过长 |
| **统一悬停模式** | `hovermode='x unified'` 跨图联动 |
| **成交量叠加** | 支持成交量在主图叠加显示 |
| **多策略支持** | 每个策略独立生成HTML文件 |

### 1.2 backtrader 现有 Plotly 绘图能力

| 能力 | backtrader | backtrader_plotly |
|------|-----------|-------------------|
| **绘图后端** | plot_plotly.py | 独立库 |
| **配色方案** | PlotlyScheme 自定义 | Tableau 10/20 |
| **小数控制** | 无 | ✅ decimal_places |
| **图例换行** | 无 | ✅ max_legend_text_width |
| **填充区域** | 有限 | ✅ 完整实现 |
| **成交量叠加** | ✅ | ✅ |
| **hover模式** | x unified | ✅ x unified |

### 1.3 差距分析

| 方面 | backtrader_plotly | backtrader | 差距 |
|------|-------------------|------------|------|
| **配色系统** | Tableau专业配色 | 自定义颜色列表 | backtrader可借鉴Tableau配色 |
| **精度控制** | decimal_places参数 | 无 | backtrader缺少小数位控制 |
| **图例换行** | 自动换行 | 无 | backtrader缺少图例文本控制 |
| **填充区域** | fill_between完整实现 | 有限 | backtrader可增强填充功能 |
| **代码结构** | 751行简洁实现 | 1000+行 | backtrader可简化代码 |

---

## 二、需求规格文档

### 2.1 功能需求

#### FR1: 增强的样式配置
扩展 PlotlyScheme 的配置选项：

- **FR1.1**: 添加 `decimal_places` 参数控制价格显示精度
- **FR1.2**: 添加 `max_legend_text_width` 参数控制图例文本换行
- **FR1.3**: 添加 Tableau 配色方案选项
- **FR1.4**: 添加 `fillalpha` 参数控制填充区域透明度

#### FR2: 填充区域图增强
完善填充区域图功能：

- **FR2.1**: 支持 `_fill_gt`（大于某值时填充）
- **FR2.2**: 支持 `_fill_lt`（小于某值时填充）
- **FR2.3**: 支持条件填充（where参数）
- **FR2.4**: 支持自定义填充颜色和透明度

#### FR3: 配色系统升级
提供更多专业配色方案：

- **FR3.1**: Tableau 10 配色
- **FR3.2**: Tableau 20 配色
- **FR3.3**: Tableau 10 Light 配色
- **FR3.4**: 自定义配色索引映射

#### FR4: 图例增强
改进图例显示：

- **FR4.1**: 自动文本换行
- **FR4.2**: 图例文本截断保护
- **FR4.3**: 支持HTML格式的图例
- **FR4.4**: 图例分组显示

### 2.2 非功能需求

- **NFR1**: 性能 - 保持现有渲染性能
- **NFR2**: 兼容性 - 与现有 API 完全兼容
- **NFR3**: 可扩展性 - 易于添加新配色方案
- **NFR4**: 代码质量 - 简化代码结构

### 2.3 用户故事

| ID | 故事描述 | 优先级 |
|----|---------|--------|
| US1 | 作为量化研究员，我想控制价格显示的小数位数，便于阅读不同精度的数据 | P0 |
| US2 | 作为策略开发者，我想使用Tableau专业配色，使图表更美观 | P0 |
| US3 | 作为用户，我想图例文本自动换行，避免文本过长被截断 | P1 |
| US4 | 作为分析师，我想绘制填充区域图，直观显示指标差异 | P1 |

---

## 三、设计文档

### 3.1 PlotlyScheme 增强

```python
class PlotlyScheme(PlotScheme):
    """增强的 Plotly 样式配置

    参考：backtrader_plotly/scheme.py
    """

    def __init__(self):
        super().__init__()

        # 新增参数
        self.decimal_places = 5          # 价格小数位数
        self.max_legend_text_width = 16  # 图例文本最大宽度

        # 填充配置
        self.fillalpha = 0.20            # 填充透明度

        # 配色方案
        self.color_scheme = 'tableau10'  # tableau10, tableau20, tableau10_light

        # Tableau 配色
        self.tableau10 = [
            'steelblue', 'darkorange', 'green', 'crimson', 'mediumpurple',
            'saddlebrown', 'orchid', 'gray', 'olive', 'mediumturquoise',
        ]

        self.tableau20 = [
            'steelblue', 'lightsteelblue', 'darkorange', 'peachpuff', 'green',
            'lightgreen', 'crimson', 'lightcoral', 'mediumpurple', 'thistle',
            'saddlebrown', 'rosybrown', 'orchid', 'lightpink', 'gray',
            'lightgray', 'olive', 'palegoldenrod', 'mediumturquoise', 'paleturquoise',
        ]

        self.tableau10_light = [
            'lightsteelblue', 'peachpuff', 'lightgreen', 'lightcoral', 'thistle',
            'rosybrown', 'lightpink', 'lightgray', 'palegoldenrod', 'paleturquoise',
        ]

        # 颜色索引映射（优化视觉顺序）
        self.tab10_index = [3, 0, 2, 1, 2, 4, 5, 6, 7, 8, 9]

    def get_colors(self):
        """获取当前配色方案的颜色列表"""
        return getattr(self, f'{self.color_scheme}', self.tableau10)

    def color(self, idx):
        """获取索引对应的颜色

        使用 tab10_index 映射优化视觉顺序
        """
        colors = self.get_colors()
        colidx = self.tab10_index[idx % len(self.tab10_index)]
        return colors[colidx % len(colors)]
```

### 3.2 图例文本处理

```python
def wrap_legend_text(text, max_width=16):
    """包装图例文本，支持自动换行

    参考：backtrader_plotly/plotter.py:695-702

    Args:
        text: 原始文本
        max_width: 最大字符宽度

    Returns:
        处理后的文本，超长部分用 <br> 分隔
    """
    if len(text) <= max_width:
        return text

    # 移除换行符重新处理
    text = text.replace('\n', '')

    # 按最大宽度分割
    return '<br>'.join(
        text[i:i + max_width]
        for i in range(0, len(text), max_width)
    )


# 在 PlotlyPlot 中集成
class PlotlyPlot(ParameterizedBase):
    # ... 现有代码 ...

    def _format_label(self, label):
        """格式化图例标签"""
        max_width = self.p.scheme.max_legend_text_width
        if hasattr(self.p.scheme, 'wrap_legend_text'):
            return self.p.scheme.wrap_legend_text(label, max_width)
        return wrap_legend_text(label, max_width)
```

### 3.3 填充区域图实现

```python
class PlotlyPlot(ParameterizedBase):
    # ... 现有代码 ...

    def fill_between(self, row, x, y1, y2, secondary_y=False,
                     color=None, opacity=0.2, name='', where=None):
        """绘制填充区域图

        参考：backtrader_plotly/plotter.py:718-750

        Args:
            row: 子图行号
            x: x轴数据
            y1: 上边界数据
            y2: 下边界数据
            secondary_y: 是否使用右侧y轴
            color: 填充颜色
            opacity: 透明度
            name: 图例名称
            where: 条件掩码（可选）
        """
        import numpy as np
        import plotly.graph_objects as go

        x = np.array(x)
        y1 = np.array(y1)
        y2 = np.array(y2)

        # 应用条件过滤
        if where is not None:
            y2 = np.where(where, y2, y1)

        # 转换颜色为RGBA
        if color and not color.startswith('rgba'):
            color = self._to_rgba(color, opacity)

        legendgroup = f'fill_{name}_{row}'

        # 添加上边界线
        self.fig.add_trace(
            go.Scatter(
                x=x, y=y2,
                name=name,
                legendgroup=legendgroup,
                showlegend=False,
                line=dict(color=color),
            ),
            row=row, col=1, secondary_y=secondary_y
        )

        # 添加填充区域
        self.fig.add_trace(
            go.Scatter(
                x=x, y=y1,
                name=name,
                legendgroup=legendgroup,
                fill='tonexty',
                fillcolor=color,
                line=dict(color=color),
            ),
            row=row, col=1, secondary_y=secondary_y
        )

    def _to_rgba(self, color, opacity):
        """转换颜色为RGBA格式

        Args:
            color: 颜色（支持 RGB 字符串、颜色名称等）
            opacity: 透明度 (0-1)

        Returns:
            rgba(r, g, b, a) 格式字符串
        """
        # 颜色映射字典
        color_map = {
            'red': 'rgb(255, 0, 0)',
            'green': 'rgb(0, 128, 0)',
            'blue': 'rgb(0, 0, 255)',
            # ... 更多颜色映射
        }

        # 获取RGB值
        if color in color_map:
            rgb = color_map[color]
        else:
            rgb = color  # 假设已经是 rgb() 格式

        # 提取RGB数值
        import re
        match = re.match(r'rgb\((\d+),\s*(\d+),\s*(\d+)\)', rgb)
        if match:
            r, g, b = match.groups()
            return f'rgba({r}, {g}, {b}, {opacity})'

        return color
```

### 3.4 小数位数控制

```python
class PlotlyPlot(ParameterizedBase):
    # ... 现有代码 ...

    def _format_value(self, value):
        """格式化数值显示

        使用 scheme.decimal_places 控制小数位数
        """
        decimal_places = getattr(self.p.scheme, 'decimal_places', 5)
        return f'{value:.{decimal_places}f}'

    def _get_tick_format(self):
        """获取坐标轴刻度格式"""
        decimal_places = getattr(self.p.scheme, 'decimal_places', 5)
        return f'.{decimal_places}f'

    def _update_layout(self):
        """更新图表布局"""
        # ... 现有代码 ...

        # 应用小数位数格式
        tick_format = self._get_tick_format()
        for i in range(1, self.pinf.nrows + 1):
            self.fig.update_yaxes(tickformat=tick_format, row=i)
```

### 3.5 API 设计

```python
import backtrader as bt

# 1. 使用增强的 PlotlyScheme
scheme = bt.plot.PlotlyScheme()
scheme.decimal_places = 2           # 控制小数位数
scheme.max_legend_text_width = 20   # 控制图例换行
scheme.color_scheme = 'tableau20'   # 使用 Tableau 20 配色
scheme.fillalpha = 0.30             # 填充透明度

# 2. 创建绘图器
plotter = bt.plot.PlotlyPlot(scheme=scheme)

# 3. 绘图
cerebro.plot(plotter)

# 4. 或者使用 Cerebro 简化接口
cerebro.plot(
    style='candle',
    scheme='tableau20',      # 使用预设配色
    decimal_places=2,       # 小数位数
    max_legend_width=20,    # 图例宽度
)
```

### 3.6 配色方案对比

| 配色方案 | 颜色数量 | 适用场景 |
|---------|---------|---------|
| tableau10 | 10 | 少量指标，高对比度 |
| tableau20 | 20 | 中等指标，配对配色 |
| tableau10_light | 10 | 浅色背景，柔和色调 |

### 3.7 代码结构优化

```
plot/
├── plot_plotly.py              # 主绘图模块
│   ├── PlotlyScheme            # 样式配置（增强）
│   │   ├── decimal_places      # 新增
│   │   ├── max_legend_text_width  # 新增
│   │   ├── color_scheme        # 新增
│   │   └── fillalpha           # 新增
│   └── PlotlyPlot
│       ├── wrap_legend_text()  # 新增
│       ├── fill_between()      # 增强
│       ├── _format_value()     # 新增
│       └── _get_tick_format()  # 新增
└── scheme.py                   # 配色方案模块（新增）
    ├── TABLEAU10               # Tableau 10 配色
    ├── TABLEAU20               # Tableau 20 配色
    ├── TABLEAU10_LIGHT         # Tableau 10 Light 配色
    └── get_color_scheme()      # 获取配色方案函数
```

---

## 四、实施计划

### 4.1 实施阶段

| 阶段 | 任务 | 预计工作量 |
|------|------|-----------|
| Phase 1 | 扩展 PlotlyScheme 添加新参数 | 0.5天 |
| Phase 2 | 实现 Tableau 配色系统 | 0.5天 |
| Phase 3 | 实现图例文本换行功能 | 0.5天 |
| Phase 4 | 实现小数位数控制 | 0.5天 |
| Phase 5 | 增强填充区域图功能 | 1天 |
| Phase 6 | 测试和文档 | 0.5天 |

### 4.2 优先级

1. **P0**: 小数位数控制（decimal_places）
2. **P0**: Tableau 配色系统
3. **P1**: 图例文本换行
4. **P1**: 填充区域图增强
5. **P2**: 自定义配色方案

---

## 五、参考资料

### 5.1 关键参考代码

- backtrader_plotly/plotter.py:1-751 - 核心绘图实现
- backtrader_plotly/plotter.py:53-172 - PlotScheme 配置
- backtrader_plotly/plotter.py:695-702 - 图例文本换行
- backtrader_plotly/plotter.py:718-750 - 填充区域图
- backtrader_plotly/scheme.py:1-172 - 主题和配色
- backtrader_plotly/main.py - 使用示例

### 5.2 关键特性实现

1. **Tableau 配色** (scheme.py:1-50)
   ```python
   tableau20 = ['steelblue', 'lightsteelblue', 'darkorange', ...]
   tab10_index = [3, 0, 2, 1, 2, 4, 5, 6, 7, 8, 9]
   ```

2. **图例换行** (plotter.py:695)
   ```python
   def wrap_legend_text(self, s):
       max_length = self.pinf.sch.max_legend_text_width
       if n > max_length:
           return '<br>'.join(s[i:i+max_length] for i in range(0, n, max_width))
   ```

3. **小数控制** (plotter.py:315, 549)
   ```python
   label += f' {lplot[-1]:.{self.pinf.sch.decimal_places}f}'
   self.fig['layout'][f'yaxis{2 * ax}']['tickformat'] = f'.{self.pinf.sch.decimal_places}f'
   ```

4. **填充区域** (plotter.py:718)
   ```python
   def fill_between(self, ax, x, y1, y2, secondary_y=False, **kwargs):
       # 使用两个 Scatter trace，设置 fill='tonexty'
   ```

### 5.3 backtrader 可复用组件

- `backtrader/plot/plot_plotly.py` - 现有 Plotly 实现
- `backtrader/plot/scheme.py` - 现有样式基类