# Backtrader 中英文术语对照表

## 核心概念 Core Concepts

| English | 中文 | 说明 |

|---------|------|------|

| Backtrader | Backtrader | 框架名称，不翻译 |

| Cerebro | Cerebro | 核心引擎类名，不翻译 |

| Strategy | 策略 | 交易策略 |

| Indicator | 指标 | 技术指标 |

| Analyzer | 分析器 | 性能分析器 |

| Observer | 观察器 | 数据观察器 |

| Data Feed | 数据源 | 数据馈送 |

| Broker | 经纪人/交易商 | 模拟或实盘交易接口 |

| Order | 订单 | 交易订单 |

| Position | 持仓 | 仓位 |

| Trade | 交易 | 已完成的买卖对 |

| Portfolio | 投资组合 | 账户组合 |

| Cash | 现金 | 可用资金 |

| Value | 价值 | 账户总价值 |

## 技术指标 Technical Indicators

| English | 中文 | 说明 |

|---------|------|------|

| Simple Moving Average (SMA) | 简单移动平均线 | 简称：均线 |

| Exponential Moving Average (EMA) | 指数移动平均线 | 指数加权均线 |

| Relative Strength Index (RSI) | 相对强弱指标 | RSI 指标 |

| Moving Average Convergence Divergence (MACD) | 移动平均收敛发散指标 | MACD 指标 |

| Bollinger Bands | 布林带 | 布林通道 |

| Stochastic Oscillator | 随机振荡器 | KD 指标 |

| Average True Range (ATR) | 平均真实波幅 | ATR 指标 |

| Volume | 成交量 | 交易量 |

| Crossover | 交叉 | 指标交叉 |

## 回测相关 Backtesting

| English | 中文 | 说明 |

|---------|------|------|

| Backtest | 回测 | 历史数据测试 |

| Optimization | 优化 | 参数优化 |

| Walk-Forward Analysis | 滚动优化分析 | 前进分析 |

| In-Sample | 样本内 | 训练集 |

| Out-of-Sample | 样本外 | 测试集 |

| Overfitting | 过拟合 | 过度优化 |

| Commission | 手续费/佣金 | 交易成本 |

| Slippage | 滑点 | 价格滑移 |

| Fill | 成交 | 订单执行 |

| Execution | 执行 | 订单执行 |

## 性能指标 Performance Metrics

| English | 中文 | 说明 |

|---------|------|------|

| Return | 收益/回报 | 投资回报 |

| Total Return | 总收益 | 累计收益率 |

| Annual Return | 年化收益 | 年度收益率 |

| Sharpe Ratio | 夏普比率 | 风险调整收益 |

| Sortino Ratio | 索提诺比率 | 下行风险调整收益 |

| Maximum Drawdown | 最大回撤 | 最大跌幅 |

| Drawdown | 回撤 | 资金回撤 |

| Win Rate | 胜率 | 盈利交易占比 |

| Profit Factor | 盈利因子 | 盈亏比 |

| Calmar Ratio | 卡玛比率 | 收益回撤比 |

## 订单类型 Order Types

| English | 中文 | 说明 |

|---------|------|------|

| Market Order | 市价单 | 按市场价成交 |

| Limit Order | 限价单 | 指定价格成交 |

| Stop Order | 止损单 | 触发价止损 |

| Stop-Limit Order | 止损限价单 | 组合订单 |

| Buy | 买入 | 做多 |

| Sell | 卖出 | 做空/平仓 |

| Long | 多头 | 买入持仓 |

| Short | 空头 | 卖出持仓 |

| Close | 平仓 | 关闭仓位 |

## 数据相关 Data

| English | 中文 | 说明 |

|---------|------|------|

| OHLC | 开高低收 | Open/High/Low/Close |

| Open | 开盘价 | 开盘 |

| High | 最高价 | 最高 |

| Low | 最低价 | 最低 |

| Close | 收盘价 | 收盘 |

| Volume | 成交量 | 交易量 |

| Timeframe | 时间周期 | 时间框架 |

| Bar | K 线/柱 | 价格柱 |

| Tick | 分笔/Tick | 最小价格变动 |

| Candle | 蜡烛图 | K 线图 |

## 实盘交易 Live Trading

| English | 中文 | 说明 |

|---------|------|------|

| Live Trading | 实盘交易 | 真实交易 |

| Paper Trading | 模拟交易 | 虚拟交易 |

| Exchange | 交易所 | 市场 |

| API | API 接口 | 应用程序接口 |

| WebSocket | WebSocket | 实时数据推送 |

| REST API | REST 接口 | HTTP 接口 |

| Authentication | 认证 | 身份验证 |

| API Key | API 密钥 | 访问密钥 |

| Secret Key | 密钥 | 私钥 |

## 架构相关 Architecture

| English | 中文 | 说明 |

|---------|------|------|

| Line System | Line 系统 | 数据序列系统 |

| LineBuffer | 行缓冲 | 数据缓冲 |

| LineIterator | 行迭代器 | 序列迭代器 |

| LineSeries | 行序列 | 数据序列 |

| MetaClass | 元类 | Python 元类 |

| Parameters | 参数 | 配置参数 |

| Next | Next 方法 | 逐步执行 |

| Once | Once 方法 | 批量执行 |

| Prenext | Prenext 方法 | 预热阶段 |

| Nextstart | Nextstart 方法 | 启动阶段 |

## 常用动词 Common Verbs

| English | 中文 | 说明 |

|---------|------|------|

| Add | 添加 | 增加 |

| Remove | 移除 | 删除 |

| Run | 运行 | 执行 |

| Plot | 绘图 | 可视化 |

| Optimize | 优化 | 参数寻优 |

| Analyze | 分析 | 性能分析 |

| Execute | 执行 | 运行 |

| Initialize | 初始化 | 初始设置 |

| Update | 更新 | 刷新 |

| Calculate | 计算 | 运算 |

## 翻译规范 Translation Guidelines

### 1. 专有名词

- 类名、方法名保持英文：`Cerebro`, `Strategy`, `next()`
- 技术术语首次出现时使用"中文（English）"格式

### 2. 代码示例

- 代码中的变量名、注释保持英文
- 代码说明使用中文

### 3. 一致性原则

- 同一术语在全文档中保持统一翻译
- 参考本对照表进行翻译

### 4. 可读性优先

- 优先使用通俗易懂的中文表达
- 避免生硬的直译

### 5. 技术准确性

- 保持技术概念的准确性
- 必要时保留英文原文

## 更新记录

- 2026-03-01: 初始版本创建
- 包含 200+常用术语对照

## 贡献指南

如需添加新术语或修改翻译，请：

1. 确保术语在金融/交易领域的准确性
2. 保持与现有翻译风格一致
3. 提供使用场景说明
