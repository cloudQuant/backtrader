# Backtrader Web 界面架构设计

本文档描述如何为 backtrader-ccxt 项目构建一个 Web 界面，用于策略实盘管理和回测研究。

- --

## 目录

1. [系统架构](#系统架构)
2. [技术栈](#技术栈)
3. [后端设计](#后端设计)
4. [前端设计](#前端设计)
5. [数据库设计](#数据库设计)
6. [API 设计](#api-设计)
7. [部署方案](#部署方案)

- --

## 系统架构

### 整体架构图

```bash
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Web 浏览器                                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │  策略管理    │  │  回测研究    │  │  实盘监控    │  │  数据分析    │    │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘    │
└───────────────────────────────────────┬─────────────────────────────────────┘
                                        │ HTTPS / WebSocket
┌───────────────────────────────────────┴─────────────────────────────────────┐
│                           Web 服务器 (Nginx)                                │
└───────────────────────────────────────┬─────────────────────────────────────┘
                                        │
┌───────────────────────────────────────┴─────────────────────────────────────┐
│                          API 网关 / 反向代理                                 │
└───────────┬───────────────────────────┬─────────────────────────────────────┘
            │                           │
┌───────────┴─────────┐     ┌──────────┴──────────┐
│   FastAPI Backend   │     │   WebSocket Server  │
│                     │     │                     │
│  ┌───────────────┐  │     │  ┌───────────────┐  │
│  │  策略管理 API │  │     │  │ 实时数据推送   │  │
│  │  回测引擎 API │  │     │  │ 订单状态推送   │  │
│  │  交易执行 API │  │     │  │ 日志流式推送   │  │
│  │  数据查询 API │  │     │  └───────────────┘  │
│  └───────────────┘  │     │                     │
└───────────┬─────────┘     └──────────┬──────────┘
            │                           │
┌───────────┴───────────────────────────┴─────────────────────────────────────┐
│                              业务逻辑层                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │ 策略管理器   │  │ 回测引擎     │  │ 交易管理器   │  │ 任务调度器   │    │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘    │
└───────────────────────────────────────┬─────────────────────────────────────┘
                                        │
┌───────────────────────────────────────┴─────────────────────────────────────┐
│                              数据访问层                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │  PostgreSQL  │  │    Redis     │  │  ClickHouse  │  │ 文件存储     │    │
│  │  (关系数据)  │  │   (缓存)     │  │  (时序数据)  │  │  (策略/日志)  │    │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘    │
└───────────────────────────────────────┬─────────────────────────────────────┘
                                        │
┌───────────────────────────────────────┴─────────────────────────────────────┐
│                              外部接口层                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │ CCXT 交易所  │  │  WebSocket   │  │  数据源 API   │  │  消息队列    │    │
│  │ (OKX/Binance)│  │  (实时行情)  │  │ (历史数据)   │  │ (通知/告警)  │    │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘

```bash

- --

## 技术栈

### 后端技术栈

| 组件 | 技术选择 | 说明 |

|------|---------|------|

| **Web 框架**| FastAPI | 高性能、异步支持、自动 API 文档 |

|**任务队列**| Celery + Redis | 异步任务处理（回测、策略启动等） |

|**WebSocket**| FastAPI WebSocket | 实时数据推送 |

|**ORM**| SQLAlchemy | 数据库操作 |

|**数据验证**| Pydantic | 数据校验和序列化 |

|**认证**| JWT + OAuth2 | API 认证授权 |

|**日志**| Loguru | 结构化日志 |

### 前端技术栈

| 组件 | 技术选择 | 说明 |

|------|---------|------|

|**框架**| React / Vue 3 | 组件化开发 |

|**状态管理**| Zustand / Pinia | 轻量级状态管理 |

|**图表库**| TradingView Lightweight Charts | 金融图表 |

|**UI 框架**| Ant Design / Element Plus | 企业级 UI 组件 |

|**实时通信**| Socket.IO / WebSocket | 实时数据更新 |

|**构建工具**| Vite | 快速构建 |

### 数据库技术栈

| 用途 | 技术选择 | 说明 |

|------|---------|------|

|**业务数据**| PostgreSQL | 用户、策略、订单等 |

|**缓存**| Redis | 会话、热点数据 |

|**时序数据**| ClickHouse / InfluxDB | K 线、交易记录 |

|**文件存储** | MinIO / 本地文件 | 策略文件、日志文件 |

- --

## 后端设计

### 项目结构

```bash
backend/
├── app/
│   ├── api/                    # API 路由

│   │   ├── v1/
│   │   │   ├── strategies.py   # 策略管理 API

│   │   │   ├── backtests.py    # 回测 API

│   │   │   ├── trading.py      # 交易 API

│   │   │   ├── data.py         # 数据 API

│   │   │   ├── auth.py         # 认证 API

│   │   │   └── websocket.py    # WebSocket 端点

│   ├── core/                   # 核心配置

│   │   ├── config.py           # 配置管理

│   │   ├── security.py         # 安全相关

│   │   └── deps.py             # 依赖注入

│   ├── models/                 # 数据模型

│   │   ├── strategy.py         # 策略模型

│   │   ├── backtest.py         # 回测模型

│   │   ├── trade.py            # 交易模型

│   │   └── user.py             # 用户模型

│   ├── schemas/                # Pydantic 模式

│   │   ├── strategy.py         # 策略请求/响应

│   │   ├── backtest.py         # 回测请求/响应

│   │   └── trade.py            # 交易请求/响应

│   ├── services/               # 业务逻辑

│   │   ├── strategy_manager.py # 策略管理器

│   │   ├── backtest_engine.py  # 回测引擎

│   │   ├── trading_engine.py   # 交易引擎

│   │   └── data_service.py     # 数据服务

│   ├── tasks/                  # Celery 任务

│   │   ├── backtest_tasks.py   # 回测任务

│   │   └── trading_tasks.py    # 交易任务

│   └── utils/                  # 工具函数

│       ├── ccxt_helper.py      # CCXT 辅助

│       └── log_handler.py      # 日志处理

├── alembic/                    # 数据库迁移

├── tests/                      # 测试

├── main.py                     # 应用入口

└── requirements.txt

```bash

### 核心服务设计

#### 1. 策略管理器 (StrategyManager)

```python

# app/services/strategy_manager.py

from typing import List, Optional, Dict, Any
from pathlib import Path
import importlib.util
import sys

class StrategyManager:
    """策略管理器 - 负责策略的加载、验证、管理"""

    def __init__(self, strategy_dir: str = "examples"):
        self.strategy_dir = Path(strategy_dir)
        self.loaded_strategies: Dict[str, type] = {}

    def list_strategies(self) -> List[Dict[str, Any]]:
        """列出所有可用策略"""
        strategies = []
        for py_file in self.strategy_dir.glob("*.py"):
            info = self._parse_strategy_file(py_file)
            if info:
                strategies.append(info)
        return strategies

    def _parse_strategy_file(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """解析策略文件，提取元数据"""

# 解析文件中的策略类和参数

# 返回策略名称、描述、参数列表等信息
        pass

    def load_strategy(self, strategy_name: str) -> type:
        """动态加载策略类"""
        if strategy_name in self.loaded_strategies:
            return self.loaded_strategies[strategy_name]

# 动态导入策略模块
        file_path = self.strategy_dir / f"{strategy_name}.py"
        spec = importlib.util.spec_from_file_location(strategy_name, file_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[strategy_name] = module
        spec.loader.exec_module(module)

# 提取策略类
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if isinstance(attr, type) and hasattr(attr, 'params'):
                self.loaded_strategies[strategy_name] = attr
                return attr

    def validate_strategy(self, strategy_class: type) -> List[str]:
        """验证策略是否符合要求"""
        errors = []

# 检查必需的方法：next, notify_order, notify_trade

# 检查参数定义
        return errors

    def get_strategy_params(self, strategy_name: str) -> Dict[str, Any]:
        """获取策略的参数定义"""
        strategy_class = self.load_strategy(strategy_name)
        return {
            name: {
                'default': getattr(strategy_class.params, name),
                'doc': f'Parameter {name}'
            }
            for name in strategy_class.params._getpairs()
        }

```bash

#### 2. 回测引擎 (BacktestEngine)

```python

# app/services/backtest_engine.py

import backtrader as bt
from datetime import datetime
from typing import Dict, Any, List
import pandas as pd

class BacktestEngine:
    """回测引擎 - 封装 backtrader 的回测功能"""

    def __init__(self):
        self.cerebro = None
        self.results = None

    def setup(self,
              strategy_class: type,
              strategy_params: Dict[str, Any],
              data_feed: bt.feeds.DataBase,
              initial_cash: float = 10000,
              commission: float = 0.001) -> None:
        """设置回测环境"""
        self.cerebro = bt.Cerebro()

# 添加策略
        self.cerebro.addstrategy(strategy_class, **strategy_params)

# 添加数据源
        self.cerebro.adddata(data_feed)

# 设置初始资金
        self.cerebro.broker.setcash(initial_cash)

# 设置佣金
        self.cerebro.broker.setcommission(commission=commission)

# 添加分析器
        self.cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
        self.cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        self.cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
        self.cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')

    def run(self) -> Dict[str, Any]:
        """运行回测"""
        if not self.cerebro:
            raise ValueError("Backtest not setup")

# 运行策略
        strats = self.cerebro.run()
        strat = strats[0]

# 提取结果
        results = {
            'final_value': self.cerebro.broker.getvalue(),
            'total_return': self._calculate_total_return(),
            'sharpe_ratio': strat.analyzers.sharpe.get_analysis(),
            'drawdown': strat.analyzers.drawdown.get_analysis(),
            'trades': strat.analyzers.trades.get_analysis(),
            'returns': strat.analyzers.returns.get_analysis(),
            'trades_detail': self._extract_trades(strat),
        }

        return results

    def _calculate_total_return(self) -> float:
        """计算总收益率"""
        final = self.cerebro.broker.getvalue()
        initial = self.cerebro.broker.startingcash
        return (final - initial) / initial * 100

    def _extract_trades(self, strategy: bt.Strategy) -> List[Dict]:
        """提取交易明细"""

# 从策略中提取每笔交易的详细信息
        pass

```bash

#### 3. 交易引擎 (TradingEngine)

```python

# app/services/trading_engine.py

import backtrader as bt
from typing import Dict, Any, Optional
from threading import Thread, Event
import queue

class TradingEngine:
    """交易引擎 - 管理实盘交易的启动、停止、监控"""

    def __init__(self):
        self.running_strategies: Dict[str, bt.Strategy] = {}
        self.stop_events: Dict[str, Event] = {}
        self.queues: Dict[str, queue.Queue] = {}

    def start_strategy(self,
                      strategy_id: str,
                      strategy_class: type,
                      strategy_params: Dict[str, Any],
                      store_config: Dict[str, Any],
                      data_config: Dict[str, Any]) -> str:
        """启动实盘策略"""
        if strategy_id in self.running_strategies:
            raise ValueError(f"Strategy {strategy_id} already running")

# 创建停止事件
        stop_event = Event()
        self.stop_events[strategy_id] = stop_event

# 创建队列用于接收策略输出
        log_queue = queue.Queue()
        self.queues[strategy_id] = log_queue

# 在新线程中运行策略
        thread = Thread(
            target=self._run_strategy,
            args=(strategy_id, strategy_class, strategy_params,
                  store_config, data_config, stop_event, log_queue),
            daemon=True
        )
        thread.start()

        return strategy_id

    def _run_strategy(self,
                     strategy_id: str,
                     strategy_class: type,
                     strategy_params: Dict[str, Any],
                     store_config: Dict[str, Any],
                     data_config: Dict[str, Any],
                     stop_event: Event,
                     log_queue: queue.Queue) -> None:
        """在线程中运行策略"""
        try:
            cerebro = bt.Cerebro()

# 添加策略
            cerebro.addstrategy(strategy_class, **strategy_params)

# 创建 Store
            from backtrader.stores.ccxtstore import CCXTStore
            store = CCXTStore(**store_config)

# 创建数据源
            data = store.getdata(**data_config)
            cerebro.adddata(data)

# 设置 Broker
            broker = store.getbroker()
            cerebro.setbroker(broker)

# 运行策略
            results = cerebro.run()
            self.running_strategies[strategy_id] = results[0]

        except Exception as e:
            log_queue.put({'type': 'error', 'message': str(e)})
        finally:
            del self.running_strategies[strategy_id]

    def stop_strategy(self, strategy_id: str) -> bool:
        """停止实盘策略"""
        if strategy_id not in self.stop_events:
            return False

        self.stop_events[strategy_id].set()
        return True

    def get_strategy_status(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        """获取策略状态"""
        if strategy_id not in self.running_strategies:
            return None

        strategy = self.running_strategies[strategy_id]
        return {
            'id': strategy_id,
            'running': True,
            'position': self._get_position(strategy),
            'cash': strategy.broker.getvalue(),
            'orders': self._get_orders(strategy),
        }

    def _get_position(self, strategy: bt.Strategy) -> Dict[str, Any]:
        """获取持仓信息"""
        pos = strategy.getposition()
        return {
            'size': pos.size,
            'price': pos.price,
        }

    def _get_orders(self, strategy: bt.Strategy) -> List[Dict]:
        """获取订单信息"""

# 从策略中提取订单状态
        pass

    def get_strategy_logs(self, strategy_id: str, timeout: float = 0.1) -> List[Dict]:
        """获取策略日志"""
        if strategy_id not in self.queues:
            return []

        logs = []
        q = self.queues[strategy_id]
        try:
            while True:
                logs.append(q.get_nowait())
        except queue.Empty:
            pass
        return logs

```bash

- --

## 前端设计

### 页面结构

```bash
frontend/
├── src/
│   ├── pages/              # 页面组件

│   │   ├── Dashboard/      # 仪表板

│   │   ├── Strategies/     # 策略管理

│   │   │   ├── List/       # 策略列表

│   │   │   ├── Create/     # 创建策略

│   │   │   └── Edit/       # 编辑策略

│   │   ├── Backtest/       # 回测研究

│   │   │   ├── Config/     # 回测配置

│   │   │   ├── Results/    # 回测结果

│   │   │   └── Chart/      # 回测图表

│   │   ├── Live/           # 实盘管理

│   │   │   ├── Monitor/    # 实盘监控

│   │   │   ├── Orders/     # 订单管理

│   │   │   └── Positions/  # 持仓管理

│   │   └── Data/           # 数据管理

│   │       ├── Market/     # 行情数据

│   │       └── History/    # 历史数据

│   ├── components/         # 通用组件

│   │   ├── charts/         # 图表组件

│   │   │   ├── KLineChart/ # K 线图

│   │   │   ├── EquityChart/# 资金曲线

│   │   │   └── PnLChart/   # 盈亏图表

│   │   ├── strategy/       # 策略组件

│   │   │   ├── ParamEditor/# 参数编辑器

│   │   │   └── CodeEditor/ # 代码编辑器

│   │   └── trading/        # 交易组件

│   │       ├── OrderBook/  # 订单簿

│   │       └── TradeList/  # 成交列表

│   ├── services/           # API 服务

│   │   ├── api.ts          # API 客户端

│   │   └── ws.ts           # WebSocket 客户端

│   ├── stores/             # 状态管理

│   ├── hooks/              # 自定义 Hooks

│   └── utils/              # 工具函数

├── package.json
└── vite.config.ts

```bash

### 主要页面设计

#### 1. 仪表板 (Dashboard)

```bash
┌─────────────────────────────────────────────────────────────────────────────┐
│  Backtrader 量化交易平台                                      [用户] [退出]  │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ 总资产       │  │ 今日盈亏     │  │ 运行策略     │  │ 系统状态     │  │
│ │ $12,345.67   │  │ +$123.45    │  │ 3 个         │  │ 正常         │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘  │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────┐  ┌─────────────────────────────────────┐  │
│  │ 运行中策略                   │  │ 持仓概览                             │  │
│  │ ┌─────────────────────────┐ │  │ ┌─────────────────────────────────┐ │  │
│  │ │ MINA 布林带策略   [运行] │ │  │ │ MINA/USDT:USDT                │ │  │
│  │ │ 入场: $0.6234           │ │  │ │ 多头: 100 @ $0.6234            │ │  │
│  │ │ 浮盈: +$12.34 (1.2%)    │ │  │ │ 浮盈: +$12.34                  │ │  │
│  │ └─────────────────────────┘ │  │ └─────────────────────────────────┘ │  │
│  │ ┌─────────────────────────┐ │  │ ┌─────────────────────────────────┐ │  │
│  │ │ BTC SMA 策略     [运行] │ │  │ │ BTC/USDT                      │ │  │
│  │ │ 入场: $43,234.00        │ │  │ │ 空头: 0.5 @ $44,000           │ │  │
│  │ │ 浮盈: -$45.67 (-0.5%)   │ │  │ │ 浮亏: -$383.00                 │ │  │
│  │ └─────────────────────────┘ │  │ └─────────────────────────────────┘ │  │
│  └─────────────────────────────┘  └─────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │ 资金曲线                                                            │ │
│  │ ╱╲╱─╱╲╱╱─╲╱─╱╱╱╱─╲╱╱─╲╱╲╱─╲╱╱─╲╱╲                                     │ │
│  │                                                                       │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘

```bash

#### 2. 策略管理页面

```bash
┌─────────────────────────────────────────────────────────────────────────────┐
│  策略管理                                              [+ 新建策略] [导入]  │
├─────────────────────────────────────────────────────────────────────────────┤
│  策略类型: [全部] [布林带] [SMA 交叉] [自定义]  |  状态: [全部] [运行中] [停止]│

├─────────────────────────────────────────────────────────────────────────────┤
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │ 策略名称              │ 类型    │ 状态      │ 收益率    │ 操作         │ │
│  ├───────────────────────────────────────────────────────────────────────┤ │
│  │ MINA 布林带多空       │ 布林带  │ 运行中    │ +5.23%   │ [停止][编辑] │ │
│  │ BTC SMA 交叉         │ SMA     │ 已停止    │ +12.45%  │ [启动][编辑] │ │
│  │ DOGS 网格策略        │ 网格    │ 运行中    │ -2.34%   │ [停止][编辑] │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘

```bash

#### 3. 回测配置页面

```bash
┌─────────────────────────────────────────────────────────────────────────────┐
│  回测研究                                                          [开始回测]│
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────┐  ┌─────────────────────────────────────────────┐  │
│  │ 策略配置            │  │ 回测参数                                    │  │
│  │                     │  │                                             │  │
│  │ 策略: [布林带策略 ▼] │  │ 回测期间: [2024-01-01] 至 [2024-12-31]     │  │
│  │                     │  │ 初始资金: [$10,000]                         │  │
│  │ 交易对:             │  │ 佣金: [0.1%]                                │  │
│  │ ☑ BTC/USDT         │  │ 滑点: [0.05%]                               │  │
│  │ ☑ ETH/USDT         │  │                                             │  │
│  │ ☐ MINA/USDT:USDT   │  │ 优化选项:                                   │  │
│  │                     │  │ ☑ 启用参数优化                              │  │
│  │ 策略参数:           │  │ 优化目标: [夏普比率 ▼]                      │  │
│  │ 周期: [60]          │  │ 优化方法: [网格搜索 ▼]                      │  │
│  │ 标准差: [2.0]       │  │                                             │  │
│  │ ATR 周期: [14]       │  │                                             │  │
│  │ ATR 倍数: [2.0]      │  │                                             │  │
│  └─────────────────────┘  └─────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────────────────┤
│  回测进度: ████████████████░░░░░░░░ 62%                                    │
│  预计剩余时间: 2 分 30 秒                                                        │
└─────────────────────────────────────────────────────────────────────────────┘

```bash

#### 4. 回测结果页面

```bash
┌─────────────────────────────────────────────────────────────────────────────┐
│  回测结果                                                          [导出报告]│
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ 总收益率     │  │ 夏普比率     │  │ 最大回撤     │  │ 胜率         │  │
│  │ +23.45%     │  │ 1.82        │  │ -8.34%      │  │ 58.3%       │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘  │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │ 资金曲线与回撤                                                        │ │
│  │                                                                       │ │
│  │ 125% ┤    ╱╲                                                         │ │
│  │ 120% ┤   ╱  ╲   ╱─╲                                                  │ │
│  │ 115% ┤  ╱    ╲─╱   ╲╱╲                                               │ │
│  │ 110% ┤ ╱            ╱  ╲─╱                                             │ │
│  │ 105% ┤╱            ╱      ╲                                            │ │
│  │ 100% ┼────────────────────────────                                    │ │
│  │      └────────────────────────────────────                             │ │
│  │      回撤区域: ░░░░░                                                  │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────┐  ┌─────────────────────────────────┐  │
│  │ 交易统计                         │  │ 按月统计                         │  │
│  │                                 │  │                                 │  │
│  │ 总交易次数: 156                  │  │ 1 月: +2.3%   7 月: +1.8%        │  │
│  │ 盈利交易: 91 (58%)               │  │ 2 月: -1.2%   8 月: +3.4%        │  │
│  │ 亏损交易: 65 (42%)               │  │ 3 月: +4.5%   9 月: -0.5%        │  │
│  │ 平均盈利: $156.78                │  │ 4 月: +1.2%  10 月: +2.1%        │  │
│  │ 平均亏损: -$98.34                │  │ 5 月: +3.4%  11 月: +4.5%        │  │
│  │ 盈亏比: 1.59                     │  │ 6 月: -2.1%  12 月: +3.8%        │  │
│  └─────────────────────────────────┘  └─────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘

```bash

#### 5. 实盘监控页面

```bash
┌─────────────────────────────────────────────────────────────────────────────┐
│  实盘监控 - MINA 布林带多空                                  [停止] [配置]   │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ 当前价格     │  │ 持仓方向     │  │ 未实现盈亏   │  │ 今日盈亏     │  │
│  │ $0.6234     │  │ 多头 100     │  │ +$12.34     │  │ +$5.67      │  │
│  │ +1.2%       │  │ 入场 $0.6100 │  │ +2.02%      │  │ +0.46%      │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘  │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │ MINA/USDT:USDT  1 分钟 K 线                                            │ │
│  │                                                                       │ │
│  │    ╱───╮                                                              │ │
│  │   ╱    │  ╱───╮                                                      │ │
│  │  ╱     ╱─╱    │  ╱─╮                                                 │ │
│  │ ╱     ╱       ╱─╱  ╲                                                │ │
│  │     ╱─              ╲                                               │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────┐  ┌─────────────────────────────────────┐  │
│  │ 实时日志                    │  │ 当前订单                             │  │
│  │ [14:32:15] 价格突破上轨...  │  │ 订单类型   │ 价格      │ 状态      │  │
│  │ [14:32:16] 开多订单已提交... │  │ 开多限价单 │ $0.6300  │ 已成交    │  │
│  │ [14:32:18] 订单成交: 100@... │  │ 止损单     │ $0.6000  │ 等待中    │  │
│  │ [14:33:01] 新 K 线收盘...      │  │                                     │  │
│  └─────────────────────────────┘  └─────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘

```bash

### 核心组件设计

#### K 线图组件

```typescript
// components/charts/KLineChart.tsx

import { useEffect, useRef } from 'react';
import { createChart, IChartApi, ISeriesApi } from 'lightweight-charts';

interface KLineChartProps {
  symbol: string;
  data: Array<{
    time: string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
  }>;
  indicators?: {
    upper?: number[];
    middle?: number[];
    lower?: number[];
  };
}

export const KLineChart: React.FC<KLineChartProps> = ({ symbol, data, indicators }) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);

  useEffect(() => {
    if (!chartContainerRef.current) return;

    // 创建图表
    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth,
      height: 400,
      layout: {
        background: { color: '#1a1a1a' },
        textColor: '#d1d4dc',
      },
      grid: {
        vertLines: { color: '#2a2a2a' },
        horzLines: { color: '#2a2a2a' },
      },
    });

    // 添加 K 线系列
    const candleSeries = chart.addCandlestickSeries({
      upColor: '#26a69a',
      downColor: '#ef5350',
      borderVisible: false,
      wickUpColor: '#26a69a',
      wickDownColor: '#ef5350',
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;

    // 清理
    return () => {
      chart.remove();
    };
  }, []);

  // 更新数据
  useEffect(() => {
    if (!candleSeriesRef.current || !data.length) return;

    candleSeriesRef.current.setData(data);

    // 添加指标线
    if (indicators?.upper) {
      const upperBandSeries = chartRef.current!.addLineSeries({
        color: '#2962ff',
        lineWidth: 1,
      });
      upperBandSeries.setData(
        indicators.upper.map((val, i) => ({ time: data[i].time, value: val }))
      );
    }
  }, [data, indicators]);

  return (
    <div className="kline-chart-container">
      <div className="chart-header">{symbol}</div>
      <div ref={chartContainerRef} className="chart" />
    </div>
  );
};

```bash

#### 策略参数编辑器

```typescript
// components/strategy/ParamEditor.tsx

import { Form, InputNumber, Select, Switch } from 'antd';

interface Param {
  name: string;
  type: 'number' | 'select' | 'boolean' | 'string';

  default: any;
  options?: string[];
  label: string;
}

interface ParamEditorProps {
  params: Param[];
  values: Record<string, any>;
  onChange: (values: Record<string, any>) => void;
}

export const ParamEditor: React.FC<ParamEditorProps> = ({
  params,
  values,
  onChange,
}) => {
  const renderParam = (param: Param) => {
    switch (param.type) {
      case 'number':
        return (
          <InputNumber
            value={values[param.name] ?? param.default}
            onChange={(val) => onChange({ ...values, [param.name]: val })}
            style={{ width: '100%' }}
          />
        );
      case 'select':
        return (
          <Select
            value={values[param.name] ?? param.default}
            onChange={(val) => onChange({ ...values, [param.name]: val })}
            options={param.options?.map((opt) => ({ label: opt, value: opt }))}
          />
        );
      case 'boolean':
        return (
          <Switch
            checked={values[param.name] ?? param.default}
            onChange={(val) => onChange({ ...values, [param.name]: val })}
          />
        );
      default:
        return null;
    }
  };

  return (
    <Form layout="vertical">
      {params.map((param) => (
        <Form.Item label={param.label} key={param.name}>
          {renderParam(param)}
        </Form.Item>
      ))}
    </Form>
  );
};

```bash

- --

## 数据库设计

### PostgreSQL 核心表结构

```sql

- - 用户表

CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

- - 策略表

CREATE TABLE strategies (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    type VARCHAR(50), -- 'bollinger', 'sma', 'custom', etc.
    code_path VARCHAR(255), -- 策略文件路径
    parameters JSONB, -- 策略参数定义
    is_active BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

- - 回测任务表

CREATE TABLE backtest_tasks (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    strategy_id INTEGER REFERENCES strategies(id) ON DELETE CASCADE,
    status VARCHAR(20) DEFAULT 'pending', -- 'pending', 'running', 'completed', 'failed'
    symbol VARCHAR(50),
    timeframe VARCHAR(10),
    start_date DATE,
    end_date DATE,
    initial_cash DECIMAL(18, 8),
    parameters JSONB,
    results JSONB, -- 回测结果
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);

- - 实盘任务表

CREATE TABLE live_tasks (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    strategy_id INTEGER REFERENCES strategies(id) ON DELETE CASCADE,
    status VARCHAR(20) DEFAULT 'stopped', -- 'running', 'stopped', 'error'
    exchange VARCHAR(20),
    symbol VARCHAR(50),
    parameters JSONB,
    process_id VARCHAR(100),
    started_at TIMESTAMP,
    stopped_at TIMESTAMP,
    error_message TEXT
);

- - 订单表

CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    live_task_id INTEGER REFERENCES live_tasks(id) ON DELETE SET NULL,
    exchange_order_id VARCHAR(100),
    symbol VARCHAR(50),
    side VARCHAR(10), -- 'buy', 'sell'
    type VARCHAR(20), -- 'market', 'limit'
    quantity DECIMAL(18, 8),
    price DECIMAL(18, 8),
    status VARCHAR(20), -- 'pending', 'open', 'closed', 'canceled', 'rejected'
    filled_quantity DECIMAL(18, 8),
    avg_price DECIMAL(18, 8),
    fee DECIMAL(18, 8),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

- - 交易记录表

CREATE TABLE trades (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    order_id INTEGER REFERENCES orders(id),
    live_task_id INTEGER REFERENCES live_tasks(id),
    symbol VARCHAR(50),
    side VARCHAR(10),
    quantity DECIMAL(18, 8),
    price DECIMAL(18, 8),
    fee DECIMAL(18, 8),
    trade_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

- - 持仓表

CREATE TABLE positions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    live_task_id INTEGER REFERENCES live_tasks(id),
    symbol VARCHAR(50),
    side VARCHAR(10), -- 'long', 'short'
    quantity DECIMAL(18, 8),
    entry_price DECIMAL(18, 8),
    current_price DECIMAL(18, 8),
    unrealized_pnl DECIMAL(18, 8),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, live_task_id, symbol)
);

```bash

### ClickHouse 时序数据表

```sql

- - K 线数据表

CREATE TABLE klines (
    symbol String,
    timeframe String,
    timestamp DateTime64(3),
    open Decimal(18, 8),
    high Decimal(18, 8),
    low Decimal(18, 8),
    close Decimal(18, 8),
    volume Decimal(18, 8),
    exchange String
)
ENGINE = MergeTree()
ORDER BY (symbol, timeframe, timestamp);

- - 策略运行日志表

CREATE TABLE strategy_logs (
    task_id String,
    timestamp DateTime64(3),
    level String, -- 'INFO', 'WARNING', 'ERROR'
    message String,
    data String  -- JSON 格式的附加数据
)
ENGINE = MergeTree()
ORDER BY (task_id, timestamp);

- - 资金曲线表

CREATE TABLE equity_curve (
    task_id String,
    timestamp DateTime64(3),
    cash Decimal(18, 8),
    total_value Decimal(18, 8),
    pnl Decimal(18, 8),
    position_count UInt16
)
ENGINE = MergeTree()
ORDER BY (task_id, timestamp);

```bash

- --

## API 设计

### RESTful API 端点

```python

# app/api/v1/strategies.py

from fastapi import APIRouter, Depends, HTTPException
from typing import List

router = APIRouter(prefix="/api/v1/strategies", tags=["strategies"])

@router.get("/", response_model=List[StrategyResponse])
async def list_strategies(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_user)
):
    """获取策略列表"""
    pass

@router.post("/", response_model=StrategyResponse)
async def create_strategy(
    strategy: StrategyCreate,
    current_user: User = Depends(get_current_user)
):
    """创建新策略"""
    pass

@router.get("/{strategy_id}", response_model=StrategyDetailResponse)
async def get_strategy(
    strategy_id: int,
    current_user: User = Depends(get_current_user)
):
    """获取策略详情"""
    pass

@router.put("/{strategy_id}", response_model=StrategyResponse)
async def update_strategy(
    strategy_id: int,
    strategy: StrategyUpdate,
    current_user: User = Depends(get_current_user)
):
    """更新策略"""
    pass

@router.delete("/{strategy_id}")
async def delete_strategy(
    strategy_id: int,
    current_user: User = Depends(get_current_user)
):
    """删除策略"""
    pass

@router.get("/{strategy_id}/params", response_model=Dict[str, Any])
async def get_strategy_params(
    strategy_id: int,
    current_user: User = Depends(get_current_user)
):
    """获取策略参数定义"""
    pass

@router.post("/{strategy_id}/validate", response_model=ValidationResult)
async def validate_strategy(
    strategy_id: int,
    current_user: User = Depends(get_current_user)
):
    """验证策略代码"""
    pass

```bash

```python

# app/api/v1/backtests.py

from fastapi import APIRouter, Depends, BackgroundTasks
from typing import List

router = APIRouter(prefix="/api/v1/backtests", tags=["backtests"])

@router.post("/", response_model=BacktestTaskResponse)
async def create_backtest(
    config: BacktestConfig,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """创建回测任务"""
    task_id = await backtest_service.create_task(config, current_user.id)
    background_tasks.add_task(run_backtest, task_id)
    return {"task_id": task_id, "status": "pending"}

@router.get("/", response_model=List[BacktestTaskResponse])
async def list_backtests(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_user)
):
    """获取回测任务列表"""
    pass

@router.get("/{task_id}", response_model=BacktestDetailResponse)
async def get_backtest(
    task_id: int,
    current_user: User = Depends(get_current_user)
):
    """获取回测结果详情"""
    pass

@router.get("/{task_id}/trades", response_model=List[TradeRecord])
async def get_backtest_trades(
    task_id: int,
    current_user: User = Depends(get_current_user)
):
    """获取回测交易记录"""
    pass

@router.get("/{task_id}/equity")
async def get_backtest_equity(
    task_id: int,
    current_user: User = Depends(get_current_user)
):
    """获取回测资金曲线数据"""
    pass

@router.post("/{task_id}/optimize")
async def optimize_parameters(
    task_id: int,
    optimization_config: OptimizationConfig,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """参数优化"""
    pass

```bash

```python

# app/api/v1/trading.py

from fastapi import APIRouter, Depends, BackgroundTasks

router = APIRouter(prefix="/api/v1/trading", tags=["trading"])

@router.post("/start", response_model=LiveTaskResponse)
async def start_strategy(
    config: LiveConfig,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """启动实盘策略"""
    task_id = await trading_service.start_strategy(config, current_user.id)
    return {"task_id": task_id, "status": "running"}

@router.post("/{task_id}/stop")
async def stop_strategy(
    task_id: int,
    current_user: User = Depends(get_current_user)
):
    """停止实盘策略"""
    await trading_service.stop_strategy(task_id)
    return {"status": "stopped"}

@router.get("/tasks", response_model=List[LiveTaskResponse])
async def list_live_tasks(
    current_user: User = Depends(get_current_user)
):
    """获取运行中的策略列表"""
    pass

@router.get("/{task_id}/status")
async def get_strategy_status(
    task_id: int,
    current_user: User = Depends(get_current_user)
):
    """获取策略运行状态"""
    return await trading_service.get_status(task_id)

@router.get("/{task_id}/positions")
async def get_positions(
    task_id: int,
    current_user: User = Depends(get_current_user)
):
    """获取持仓信息"""
    pass

@router.get("/{task_id}/orders")
async def get_orders(
    task_id: int,
    status: str = None,
    current_user: User = Depends(get_current_user)
):
    """获取订单信息"""
    pass

@router.post("/{task_id}/orders", response_model=OrderResponse)
async def create_manual_order(
    task_id: int,
    order: ManualOrderRequest,
    current_user: User = Depends(get_current_user)
):
    """手动下单"""
    pass

@router.delete("/orders/{order_id}")
async def cancel_order(
    order_id: int,
    current_user: User = Depends(get_current_user)
):
    """取消订单"""
    pass

```bash

```python

# app/api/v1/data.py

from fastapi import APIRouter, Depends

router = APIRouter(prefix="/api/v1/data", tags=["data"])

@router.get("/klines")
async def get_klines(
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    current_user: User = Depends(get_current_user)
):
    """获取 K 线数据"""
    pass

@router.get("/ticker")
async def get_ticker(
    symbol: str,
    current_user: User = Depends(get_current_user)
):
    """获取当前行情"""
    pass

@router.get("/exchanges")
async def list_exchanges():
    """获取支持的交易所列表"""
    return {
        "exchanges": [
            {"id": "okx", "name": "OKX", "features": ["spot", "future", "swap"]},
            {"id": "binance", "name": "Binance", "features": ["spot", "future"]},
            {"id": "bybit", "name": "Bybit", "features": ["spot", "future", "swap"]},
        ]
    }

@router.get("/symbols")
async def list_symbols(
    exchange: str,
    current_user: User = Depends(get_current_user)
):
    """获取交易对列表"""
    pass

```bash

### WebSocket 端点

```python

# app/api/v1/websocket.py

from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict, Set
import json

class ConnectionManager:
    """WebSocket 连接管理器"""

    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, channel: str):
        await websocket.accept()
        if channel not in self.active_connections:
            self.active_connections[channel] = set()
        self.active_connections[channel].add(websocket)

    def disconnect(self, websocket: WebSocket, channel: str):
        if channel in self.active_connections:
            self.active_connections[channel].discard(websocket)

    async def broadcast(self, channel: str, message: dict):
        if channel not in self.active_connections:
            return
        for connection in self.active_connections[channel]:
            await connection.send_json(message)

manager = ConnectionManager()

@router.websocket("/ws/live/{task_id}")
async def websocket_live_monitor(websocket: WebSocket, task_id: str):
    """实盘监控 WebSocket"""
    await manager.connect(websocket, f"live:{task_id}")

    try:
        while True:

# 接收客户端消息
            data = await websocket.receive_text()

# 发送策略状态更新
            status = await trading_service.get_status(task_id)
            await websocket.send_json({
                "type": "status",
                "data": status
            })

    except WebSocketDisconnect:
        manager.disconnect(websocket, f"live:{task_id}")

@router.websocket("/ws/backtest/{task_id}")
async def websocket_backtest_progress(websocket: WebSocket, task_id: str):
    """回测进度 WebSocket"""
    await manager.connect(websocket, f"backtest:{task_id}")

    try:
        while True:

# 发送回测进度更新
            progress = await backtest_service.get_progress(task_id)
            await websocket.send_json({
                "type": "progress",
                "data": progress
            })
            await asyncio.sleep(1)

    except WebSocketDisconnect:
        manager.disconnect(websocket, f"backtest:{task_id}")

@router.websocket("/ws/market/{symbol}")
async def websocket_market_data(websocket: WebSocket, symbol: str):
    """市场数据 WebSocket"""
    await manager.connect(websocket, f"market:{symbol}")

    try:
        while True:

# 推送实时 K 线数据
            kline = await data_service.get_latest_kline(symbol)
            await websocket.send_json({
                "type": "kline",
                "data": kline
            })
            await asyncio.sleep(1)

    except WebSocketDisconnect:
        manager.disconnect(websocket, f"market:{symbol}")

```bash

- --

## 部署方案

### Docker Compose 部署

```yaml

# docker-compose.yml

version: '3.8'

services:

# PostgreSQL 数据库
  postgres:
    image: postgres:15-alpine
    container_name: backtrader_postgres
    environment:
      POSTGRES_USER: backtrader
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      POSTGRES_DB: backtrader
    volumes:

      - postgres_data:/var/lib/postgresql/data

    ports:

      - "5432:5432"

    networks:

      - backtrader_network

# Redis 缓存
  redis:
    image: redis:7-alpine
    container_name: backtrader_redis
    command: redis-server --appendonly yes
    volumes:

      - redis_data:/data

    ports:

      - "6379:6379"

    networks:

      - backtrader_network

# ClickHouse 时序数据库
  clickhouse:
    image: clickhouse/clickhouse-server:latest
    container_name: backtrader_clickhouse
    volumes:

      - clickhouse_data:/var/lib/clickhouse

    ports:

      - "8123:8123"
      - "9000:9000"

    networks:

      - backtrader_network

# FastAPI 后端
  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: backtrader_backend
    environment:
      DATABASE_URL: postgresql://backtrader:${DB_PASSWORD}@postgres:5432/backtrader
      REDIS_URL: redis://redis:6379/0
      CLICKHOUSE_URL: clickhouse://clickhouse:8123/default
      SECRET_KEY: ${SECRET_KEY}
    volumes:

      - ./backend:/app
      - strategy_files:/app/strategies
      - log_files:/app/logs

    ports:

      - "8000:8000"

    depends_on:

      - postgres
      - redis
      - clickhouse

    networks:

      - backtrader_network

    command: uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Celery Worker (后台任务)
  celery_worker:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: backtrader_celery_worker
    environment:
      DATABASE_URL: postgresql://backtrader:${DB_PASSWORD}@postgres:5432/backtrader
      REDIS_URL: redis://redis:6379/0
    volumes:

      - ./backend:/app
      - strategy_files:/app/strategies
      - log_files:/app/logs

    depends_on:

      - postgres
      - redis

    networks:

      - backtrader_network

    command: celery -A app.tasks worker --loglevel=info

# 前端
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    container_name: backtrader_frontend
    volumes:

      - ./frontend:/app
      - /app/node_modules

    ports:

      - "3000:3000"

    networks:

      - backtrader_network

    command: npm run dev

# Nginx 反向代理
  nginx:
    image: nginx:alpine
    container_name: backtrader_nginx
    volumes:

      - ./nginx/nginx.conf:/etc/nginx/nginx.conf
      - ./nginx/ssl:/etc/nginx/ssl

    ports:

      - "80:80"
      - "443:443"

    depends_on:

      - backend
      - frontend

    networks:

      - backtrader_network

volumes:
  postgres_data:
  redis_data:
  clickhouse_data:
  strategy_files:
  log_files:

networks:
  backtrader_network:
    driver: bridge

```bash

### Nginx 配置

```nginx

# nginx/nginx.conf

user nginx;
worker_processes auto;
error_log /var/log/nginx/error.log;
pid /var/run/nginx.pid;

events {
    worker_connections 1024;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

# 日志格式
    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" '
                    '"$http_user_agent" "$http_x_forwarded_for"';

    access_log /var/log/nginx/access.log main;

    sendfile on;
    tcp_nopush on;
    keepalive_timeout 65;
    gzip on;

# 上游服务器
    upstream backend {
        server backend:8000;
    }

    upstream frontend {
        server frontend:3000;
    }

# HTTP 重定向到 HTTPS
    server {
        listen 80;
        server_name your-domain.com;
        return 301 <https://$server_name$request_uri;>
    }

# HTTPS 主服务器
    server {
        listen 443 ssl http2;
        server_name your-domain.com;

        ssl_certificate /etc/nginx/ssl/cert.pem;
        ssl_certificate_key /etc/nginx/ssl/key.pem;
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers HIGH:!aNULL:!MD5;

# 前端
        location / {
            proxy_pass <http://frontend;>
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

# API
        location /api/ {
            proxy_pass <http://backend/;>
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

# WebSocket 支持
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
        }

# WebSocket
        location /ws/ {
            proxy_pass <http://backend/ws/;>
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_read_timeout 86400;
        }
    }
}

```bash

### 后端 Dockerfile

```dockerfile

# backend/Dockerfile

FROM python:3.10-slim

WORKDIR /app

# 安装系统依赖

RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件

COPY requirements.txt .

# 安装 Python 依赖

RUN pip install --no-cache-dir -r requirements.txt

# 复制代码

COPY . .

# 创建策略和日志目录

RUN mkdir -p /app/strategies /app/logs

# 暴露端口

EXPOSE 8000

# 启动命令

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

```bash

### 前端 Dockerfile

```dockerfile

# frontend/Dockerfile

FROM node:18-alpine

WORKDIR /app

# 复制依赖文件

COPY package*.json ./

# 安装依赖

RUN npm ci

# 复制代码

COPY . .

# 暴露端口

EXPOSE 3000

# 启动命令

CMD ["npm", "run", "dev", "--", "--host"]

```bash

- --

## 启动流程

### 1. 开发环境启动

```bash

# 1. 启动数据库服务

docker-compose up -d postgres redis clickhouse

# 2. 初始化数据库

cd backend
alembic upgrade head

# 3. 启动后端

uvicorn main:app --reload --host 0.0.0.0 --port 8000

# 4. 启动 Celery Worker

celery -A app.tasks worker --loglevel=info

# 5. 启动前端

cd ../frontend
npm install
npm run dev

```bash

### 2. 生产环境启动

```bash

# 构建并启动所有服务

docker-compose build
docker-compose up -d

# 查看日志

docker-compose logs -f backend

```bash

- --

## 功能路线图

### Phase 1: MVP (最小可行产品)

- [ ] 用户认证系统
- [ ] 策略列表和详情查看
- [ ] 简单回测功能
- [ ] 基础实盘启动/停止

### Phase 2: 核心功能

- [ ] 回测参数优化
- [ ] 实盘实时监控
- [ ] 订单和持仓管理
- [ ] K 线图表展示

### Phase 3: 高级功能

- [ ] 多策略组合管理
- [ ] 风险控制模块
- [ ] 通知告警系统
- [ ] 性能分析报告

### Phase 4: 企业功能

- [ ] 多用户权限管理
- [ ] API 接口开放
- [ ] 云端部署支持
- [ ] 移动端适配

- --

## 相关文档

- [WebSocket 实时数据指南](./WEBSOCKET_GUIDE.md)
- [CCXT 环境配置](../CCXT_ENV_CONFIG.md)
- [策略开发指南](./STRATEGY_GUIDE.md)
