# Backtrader Web 平台开发计划

本文档详细描述 Backtrader Web 平台的开发方案，用于所有 backtrader 策略的实盘交易管理和研究回测。

- --

## 目录

1. [项目概述](#项目概述)
2. [技术栈](#技术栈)
3. [系统架构](#系统架构)
4. [目录结构](#目录结构)
5. [数据库设计](#数据库设计)
6. [API 设计](#api-设计)
7. [前端设计](#前端设计)
8. [开发任务清单](#开发任务清单)
9. [开发步骤](#开发步骤)

- --

## 项目概述

### 目标

构建一个统一的 Web 平台，支持：

1. **实盘交易管理**：启动、停止、监控所有 backtrader 策略的实盘运行
2. **策略研究回测**：配置参数、运行回测、分析结果
3. **数据管理**：历史数据查询、实时行情展示
4. **账户管理**：多交易所账户、资金统计

### 核心功能

| 功能模块 | 描述 |

|---------|------|

| **策略管理**| 上传、编辑、验证 Python 策略文件 |

|**参数配置**| 可视化编辑策略参数 |

|**回测研究**| 选择数据源、配置参数、运行回测、查看结果 |

|**实盘运行**| 选择交易所和账户、启动策略、实时监控 |

|**订单管理**| 查看订单状态、手动下单、取消订单 |

|**持仓监控**| 实时持仓、盈亏统计、风险提示 |

|**日志追踪**| 实时日志、历史查询、错误告警 |

|**数据分析** | K 线图表、资金曲线、交易统计 |

- --

## 技术栈

### 后端

```bash
FastAPI          # Web 框架

MySQL            # 数据库

SQLAlchemy       # ORM

Pydantic         # 数据验证

Celery + Redis   # 异步任务（回测、策略运行）

WebSocket        # 实时通信

Loguru           # 日志

```bash

### 前端

```bash
Vue 3 + Vite     # 前端框架

TypeScript       # 类型安全

Element Plus     # UI 组件库

Pinia            # 状态管理

Vue Router       # 路由

Axios            # HTTP 客户端

ECharts          # 图表库（K 线、资金曲线等）

vue-echarts      # ECharts Vue 3 封装

Day.js           # 日期处理

Monaco Editor    # 代码编辑器（可选）

```bash

- --

## 系统架构

```bash
┌─────────────────────────────────────────────────────────────────────────────┐
│                              浏览器                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │  策略研究    │  │  回测分析    │  │  实盘交易    │  │  监控面板    │    │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘    │
└───────────────────────────────────────┬─────────────────────────────────────┘
                                        │ HTTP/WebSocket
┌───────────────────────────────────────┴─────────────────────────────────────┐
│                           FastAPI 后端                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │  API 路由    │  │  业务逻辑    │  │  任务调度    │  │  WebSocket   │    │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘    │
└───────────────────────────────────────┬─────────────────────────────────────┘
                                        │
┌───────────────────────────────────────┴─────────────────────────────────────┐
│                              数据层                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │   MySQL      │  │   Redis     │  │ 文件存储     │  │ Backtrader   │    │
│  │  (业务数据)  │  │  (缓存/队列) │  │ (策略/日志)  │  │  (执行引擎)  │    │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘    │
└───────────────────────────────────────┬─────────────────────────────────────┘
                                        │
┌───────────────────────────────────────┴─────────────────────────────────────┐
│                              外部接口                                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                       │
│  │ CCXT 交易所  │  │ WebSocket API │  │ REST API     │                       │
│  │ (交易执行)   │  │ (实时行情)    │  │ (历史数据)   │                       │
│  └──────────────┘  └──────────────┘  └──────────────┘                       │
└─────────────────────────────────────────────────────────────────────────────┘

```bash

- --

## 目录结构

```bash
backtrader/
├── backtrader/                   # 核心库

│   └── ...
│
├── examples/                     # 策略示例

│   ├── sample.py
│   ├── backtrader_ccxt_okx_mina_futures_long_short.py
│   └── ...
│
├── web/                          # Web 平台根目录

│   │
│   ├── backend/                  # 后端

│   │   ├── main.py              # FastAPI 应用入口

│   │   ├── config.py            # 配置文件

│   │   │
│   │   ├── app/
│   │   │   ├── api/             # API 路由

│   │   │   │   ├── __init__.py
│   │   │   │   ├── auth.py          # 认证 API

│   │   │   │   ├── strategies.py    # 策略管理 API

│   │   │   │   ├── backtests.py     # 回测 API

│   │   │   │   ├── live.py          # 实盘 API

│   │   │   │   ├── data.py          # 数据 API

│   │   │   │   ├── accounts.py      # 账户 API

│   │   │   │   └── websocket.py     # WebSocket

│   │   │   │
│   │   │   ├── models/           # SQLAlchemy 模型

│   │   │   │   ├── __init__.py
│   │   │   │   ├── base.py          # 基类

│   │   │   │   ├── user.py          # 用户

│   │   │   │   ├── strategy.py      # 策略

│   │   │   │   ├── backtest.py      # 回测

│   │   │   │   ├── live_task.py     # 实盘任务

│   │   │   │   ├── order.py         # 订单

│   │   │   │   ├── trade.py         # 交易

│   │   │   │   └── account.py       # 账户

│   │   │   │
│   │   │   ├── schemas/           # Pydantic 模式

│   │   │   │   ├── __init__.py
│   │   │   │   ├── user.py
│   │   │   │   ├── strategy.py
│   │   │   │   ├── backtest.py
│   │   │   │   ├── live.py
│   │   │   │   └── data.py
│   │   │   │
│   │   │   ├── services/          # 业务逻辑

│   │   │   │   ├── __init__.py
│   │   │   │   ├── strategy_service.py    # 策略服务

│   │   │   │   ├── backtest_service.py   # 回测服务

│   │   │   │   ├── live_service.py        # 实盘服务

│   │   │   │   ├── data_service.py        # 数据服务

│   │   │   │   └── ccxt_service.py        # CCXT 服务

│   │   │   │
│   │   │   ├── tasks/             # Celery 任务

│   │   │   │   ├── __init__.py
│   │   │   │   ├── celery_app.py    # Celery 应用

│   │   │   │   ├── backtest_tasks.py
│   │   │   │   └── live_tasks.py
│   │   │   │
│   │   │   ├── core/              # 核心功能

│   │   │   │   ├── __init__.py
│   │   │   │   ├── auth.py           # 认证

│   │   │   │   ├── security.py       # 安全

│   │   │   │   └── deps.py           # 依赖注入

│   │   │   │
│   │   │   └── utils/             # 工具函数

│   │   │       ├── __init__.py
│   │   │       ├── logger.py         # 日志

│   │   │       ├── strategy_parser.py # 策略解析

│   │   │       └── date_helper.py    # 日期工具

│   │   │
│   │   ├── database/              # 数据库

│   │   │   ├── __init__.py
│   │   │   ├── session.py         # DB Session

│   │   │   └── migrations/        # Alembic 迁移

│   │   │       └── versions/
│   │   │
│   │   ├── storage/               # 文件存储

│   │   │   ├── strategies/        # 策略文件

│   │   │   ├── backtests/         # 回测结果

│   │   │   └── logs/              # 日志文件

│   │   │
│   │   ├── requirements.txt
│   │   └── .env.example
│   │
│   └── frontend/                 # 前端 (Vue 3)

│       ├── index.html
│       ├── package.json
│       ├── vite.config.ts
│       ├── tsconfig.json
│       ├── tsconfig.node.json
│       │
│       ├── src/
│       │   ├── main.ts            # 入口

│       │   ├── App.vue            # 根组件

│       │   │
│       │   ├── views/             # 页面视图

│       │   │   ├── Dashboard.vue
│       │   │   ├── Login.vue
│       │   │   ├── strategies/
│       │   │   │   ├── StrategyList.vue
│       │   │   │   ├── StrategyCreate.vue
│       │   │   │   ├── StrategyEdit.vue
│       │   │   │   └── StrategyDetail.vue
│       │   │   ├── backtests/
│       │   │   │   ├── BacktestList.vue
│       │   │   │   ├── BacktestNew.vue
│       │   │   │   └── BacktestResult.vue
│       │   │   ├── live/
│       │   │   │   ├── LiveList.vue
│       │   │   │   └── LiveMonitor.vue
│       │   │   ├── data/
│       │   │   │   └── DataMarket.vue
│       │   │   └── settings/
│       │   │       ├── SettingsIndex.vue
│       │   │       └── SettingsAccounts.vue
│       │   │
│       │   ├── components/        # 组件

│       │   │   ├── layout/
│       │   │   │   ├── MainLayout.vue
│       │   │   │   ├── AppHeader.vue
│       │   │   │   ├── AppSidebar.vue
│       │   │   │   └── AppBreadcrumb.vue
│       │   │   │
│       │   │   ├── charts/        # 图表组件

│       │   │   │   ├── KLineChart.vue       # K 线图

│       │   │   │   ├── EquityCurve.vue      # 资金曲线

│       │   │   │   ├── DrawdownChart.vue    # 回撤图

│       │   │   │   ├── PnLChart.vue         # 盈亏图

│       │   │   │   └── TradeChart.vue       # 交易分布图

│       │   │   │
│       │   │   ├── strategy/      # 策略组件

│       │   │   │   ├── StrategyCard.vue     # 策略卡片

│       │   │   │   ├── ParamEditor.vue      # 参数编辑器

│       │   │   │   ├── CodeEditor.vue       # 代码编辑器

│       │   │   │   └── TemplateSelector.vue # 模板选择器

│       │   │   │
│       │   │   ├── trading/       # 交易组件

│       │   │   │   ├── PositionList.vue     # 持仓列表

│       │   │   │   ├── OrderList.vue        # 订单列表

│       │   │   │   ├── TradeList.vue        # 成交列表

│       │   │   │   └── OrderForm.vue        # 下单表单

│       │   │   │
│       │   │   └── common/        # 通用组件

│       │   │       ├── DataTable.vue        # 数据表格

│       │   │       ├── StatusTag.vue        # 状态标签

│       │   │       ├── DateTimePicker.vue   # 日期选择器

│       │   │       ├── SymbolSelector.vue   # 交易对选择器

│       │   │       └── LogViewer.vue        # 日志查看器

│       │   │
│       │   ├── stores/            # Pinia 状态

│       │   │   ├── index.ts
│       │   │   ├── useUserStore.ts
│       │   │   ├── useStrategyStore.ts
│       │   │   ├── useBacktestStore.ts
│       │   │   ├── useLiveStore.ts
│       │   │   └── useAppStore.ts
│       │   │
│       │   ├── composables/       # Composables

│       │   │   ├── useWebSocket.ts
│       │   │   ├── useApi.ts
│       │   │   └── useECharts.ts
│       │   │
│       │   ├── api/               # API 服务

│       │   │   ├── index.ts
│       │   │   ├── request.ts            # Axios 封装

│       │   │   ├── auth.ts               # 认证 API

│       │   │   ├── strategy.ts           # 策略 API

│       │   │   ├── backtest.ts           # 回测 API

│       │   │   ├── live.ts               # 实盘 API

│       │   │   ├── data.ts               # 数据 API

│       │   │   └── account.ts            # 账户 API

│       │   │
│       │   ├── types/             # TypeScript 类型

│       │   │   ├── index.ts
│       │   │   ├── user.ts
│       │   │   ├── strategy.ts
│       │   │   ├── backtest.ts
│       │   │   ├── live.ts
│       │   │   └── common.ts
│       │   │
│       │   ├── utils/             # 工具函数

│       │   │   ├── format.ts             # 格式化

│       │   │   ├── validate.ts           # 验证

│       │   │   ├── storage.ts            # 本地存储

│       │   │   └── constants.ts          # 常量

│       │   │
│       │   ├── router/            # 路由

│       │   │   ├── index.ts
│       │   │   └── routes.ts
│       │   │
│       │   ├── assets/            # 静态资源

│       │   │   ├── styles/
│       │   │   │   ├── main.scss
│       │   │   │   ├── variables.scss
│       │   │   │   └── element.scss
│       │   │   ├── images/
│       │   │   └── icons/
│       │   │
│       │   └── locales/           # 国际化

│       │       ├── zh-CN.ts
│       │       └── en-US.ts
│       │
│       └── public/
│           └── favicon.ico
│
├── docs/                         # 文档

│   ├── WEB_DEVELOPMENT_PLAN.md
│   ├── WEBSOCKET_GUIDE.md
│   └── ...
│
├── .env.example
├── pyproject.toml
└── README.md

```bash

- --

## 数据库设计

### MySQL 表结构

```sql

- - ============================================================
- - 用户相关表
- - ============================================================

- - 用户表

CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    is_admin BOOLEAN DEFAULT FALSE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_username (username),
    INDEX idx_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

- - ============================================================
- - 交易所账户表
- - ============================================================

- - 交易所账户表（存储多个交易所的 API 密钥，加密存储）

CREATE TABLE exchange_accounts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    exchange VARCHAR(20) NOT NULL COMMENT '交易所名称: okx, binance, bybit 等',
    account_name VARCHAR(100) NOT NULL COMMENT '账户名称',
    api_key_encrypted TEXT NOT NULL COMMENT '加密的 API Key',
    api_secret_encrypted TEXT NOT NULL COMMENT '加密的 API Secret',
    api_password_encrypted TEXT COMMENT '加密的 API Password (OKX 需要)',
    is_sandbox BOOLEAN DEFAULT FALSE COMMENT '是否沙盒环境',
    is_tested BOOLEAN DEFAULT FALSE COMMENT '是否已测试连接',
    is_active BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_exchange (user_id, exchange),
    UNIQUE KEY uk_user_account_name (user_id, account_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

- - 交易所账户余额表（缓存当前余额）

CREATE TABLE account_balances (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    currency VARCHAR(20) NOT NULL COMMENT '币种: USDT, BTC 等',
    total_balance DECIMAL(18, 8) NOT NULL COMMENT '总余额',
    available_balance DECIMAL(18, 8) NOT NULL COMMENT '可用余额',
    frozen_balance DECIMAL(18, 8) DEFAULT 0 COMMENT '冻结余额',
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (account_id) REFERENCES exchange_accounts(id) ON DELETE CASCADE,
    INDEX idx_account_currency (account_id, currency),
    UNIQUE KEY uk_account_currency (account_id, currency)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

- - ============================================================
- - 策略相关表
- - ============================================================

- - 策略表（存储策略的元数据）

CREATE TABLE strategies (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    name VARCHAR(100) NOT NULL,
    description TEXT COMMENT '策略描述',
    strategy_type VARCHAR(50) COMMENT '策略类型: custom, bollinger, sma 等',
    file_path VARCHAR(500) COMMENT '策略文件路径',
    class_name VARCHAR(100) COMMENT '策略类名',
    parameters JSON COMMENT '策略参数定义 [{"name":"period","type":"int","default":20}]',
    code_content TEXT COMMENT '策略代码内容',
    is_valid BOOLEAN DEFAULT FALSE COMMENT '代码是否通过验证',
    tags JSON COMMENT '标签 ["趋势", "突破"]',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_id (user_id),
    INDEX idx_type (strategy_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

- - 策略模板表（系统预置的策略模板）

CREATE TABLE strategy_templates (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    strategy_type VARCHAR(50),
    template_code TEXT NOT NULL COMMENT '模板代码',
    parameters JSON COMMENT '参数定义',
    is_public BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

- - ============================================================
- - 回测相关表
- - ============================================================

- - 回测任务表

CREATE TABLE backtest_tasks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    strategy_id INT NOT NULL,
    name VARCHAR(200) COMMENT '回测名称',
    status ENUM('pending', 'running', 'completed', 'failed', 'cancelled') DEFAULT 'pending',
    progress INT DEFAULT 0 COMMENT '进度 0-100',

    - - 数据配置

    exchange VARCHAR(20) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    timeframe VARCHAR(10) NOT NULL COMMENT '1m, 5m, 1h, 1d 等',
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,

    - - 回测参数

    initial_cash DECIMAL(18, 8) DEFAULT 10000,
    commission DECIMAL(6, 5) DEFAULT 0.001 COMMENT '佣金率',
    slippage DECIMAL(6, 5) DEFAULT 0.0005 COMMENT '滑点率',
    parameters JSON COMMENT '策略运行参数',

    - - 结果数据

    results JSON COMMENT '回测结果摘要',
    error_message TEXT,

    - - 时间记录

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    started_at DATETIME,
    completed_at DATETIME,

    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (strategy_id) REFERENCES strategies(id) ON DELETE CASCADE,
    INDEX idx_user_status (user_id, status),
    INDEX idx_strategy_id (strategy_id),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

- - 回测交易记录表

CREATE TABLE backtest_trades (
    id INT AUTO_INCREMENT PRIMARY KEY,
    backtest_id INT NOT NULL,
    trade_number INT NOT NULL COMMENT '交易序号',

    entry_time DATETIME NOT NULL,
    exit_time DATETIME,
    symbol VARCHAR(50) NOT NULL,
    side ENUM('long', 'short') NOT NULL,

    entry_price DECIMAL(18, 8) NOT NULL,
    exit_price DECIMAL(18, 8),
    quantity DECIMAL(18, 8) NOT NULL,

    pnl DECIMAL(18, 8) COMMENT '盈亏',
    pnl_percent DECIMAL(10, 4) COMMENT '盈亏百分比',
    commission DECIMAL(18, 8) COMMENT '手续费',

    exit_reason VARCHAR(50) COMMENT '退出原因: signal, stop_loss, take_profit',

    FOREIGN KEY (backtest_id) REFERENCES backtest_tasks(id) ON DELETE CASCADE,
    INDEX idx_backtest_id (backtest_id),
    INDEX idx_entry_time (entry_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

- - 回测资金曲线表（存储每天的权益数据）

CREATE TABLE backtest_equity_curve (
    id INT AUTO_INCREMENT PRIMARY KEY,
    backtest_id INT NOT NULL,
    date DATE NOT NULL,
    equity DECIMAL(18, 8) NOT NULL COMMENT '权益',
    drawdown DECIMAL(10, 4) COMMENT '回撤百分比',
    trades_count INT DEFAULT 0 COMMENT '当日交易次数',
    FOREIGN KEY (backtest_id) REFERENCES backtest_tasks(id) ON DELETE CASCADE,
    UNIQUE KEY uk_backtest_date (backtest_id, date),
    INDEX idx_backtest_id (backtest_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

- - ============================================================
- - 实盘相关表
- - ============================================================

- - 实盘任务表

CREATE TABLE live_tasks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    strategy_id INT NOT NULL,
    account_id INT NOT NULL,

    name VARCHAR(200) NOT NULL COMMENT '任务名称',
    status ENUM('stopped', 'running', 'error', 'stopping') DEFAULT 'stopped',

    - - 交易配置

    exchange VARCHAR(20) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,

    - - 策略参数

    parameters JSON COMMENT '策略运行参数',

    - - 进程信息

    process_id VARCHAR(100) COMMENT '进程 ID',
    log_file_path VARCHAR(500) COMMENT '日志文件路径',

    - - 错误信息

    last_error TEXT COMMENT '最后一次错误',
    error_count INT DEFAULT 0 COMMENT '错误次数',

    - - 时间记录

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    started_at DATETIME,
    stopped_at DATETIME,

    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (strategy_id) REFERENCES strategies(id) ON DELETE CASCADE,
    FOREIGN KEY (account_id) REFERENCES exchange_accounts(id) ON DELETE CASCADE,
    INDEX idx_user_status (user_id, status),
    INDEX idx_account_id (account_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

- - 实盘订单表

CREATE TABLE live_orders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    live_task_id INT NOT NULL,
    user_id INT NOT NULL,

    - - 订单信息

    exchange_order_id VARCHAR(100) COMMENT '交易所订单 ID',
    client_order_id VARCHAR(100) COMMENT '客户端订单 ID',

    symbol VARCHAR(50) NOT NULL,
    side ENUM('buy', 'sell') NOT NULL,
    type ENUM('market', 'limit', 'stop', 'stop_limit') NOT NULL,

    quantity DECIMAL(18, 8) NOT NULL,
    price DECIMAL(18, 8) COMMENT '限价单价格',
    stop_price DECIMAL(18, 8) COMMENT '止损价格',

    - - 状态

    status ENUM('pending', 'open', 'closed', 'canceled', 'rejected', 'expired') DEFAULT 'pending',

    - - 成交信息

    filled_quantity DECIMAL(18, 8) DEFAULT 0,
    avg_price DECIMAL(18, 8) COMMENT '平均成交价',
    fee DECIMAL(18, 8) DEFAULT 0 COMMENT '手续费',
    fee_currency VARCHAR(20) COMMENT '手续费币种',

    - - 订单元数据

    meta JSON COMMENT '额外信息，如订单标签等',

    - - 时间记录

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    filled_at DATETIME COMMENT '成交时间',

    FOREIGN KEY (live_task_id) REFERENCES live_tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_task_id (live_task_id),
    INDEX idx_status (status),
    INDEX idx_exchange_order_id (exchange_order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

- - 实盘成交记录表

CREATE TABLE live_trades (
    id INT AUTO_INCREMENT PRIMARY KEY,
    live_task_id INT NOT NULL,
    order_id INT NOT NULL,
    user_id INT NOT NULL,

    exchange_trade_id VARCHAR(100) COMMENT '交易所成交 ID',
    symbol VARCHAR(50) NOT NULL,
    side ENUM('buy', 'sell') NOT NULL,

    quantity DECIMAL(18, 8) NOT NULL,
    price DECIMAL(18, 8) NOT NULL,
    fee DECIMAL(18, 8) DEFAULT 0,
    fee_currency VARCHAR(20),

    trade_time DATETIME NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (live_task_id) REFERENCES live_tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (order_id) REFERENCES live_orders(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_task_id (live_task_id),
    INDEX idx_trade_time (trade_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

- - 实盘持仓表

CREATE TABLE live_positions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    live_task_id INT NOT NULL,
    user_id INT NOT NULL,

    symbol VARCHAR(50) NOT NULL,
    side ENUM('long', 'short') NOT NULL,

    quantity DECIMAL(18, 8) NOT NULL COMMENT '持仓数量（正数为多，负数为空）',
    entry_price DECIMAL(18, 8) NOT NULL COMMENT '平均入场价',

    - - 盈亏信息（实时更新）

    current_price DECIMAL(18, 8) COMMENT '当前价格',
    unrealized_pnl DECIMAL(18, 8) COMMENT '未实现盈亏',
    realized_pnl DECIMAL(18, 8) DEFAULT 0 COMMENT '已实现盈亏',

    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (live_task_id) REFERENCES live_tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE KEY uk_task_symbol (live_task_id, symbol),
    INDEX idx_user_id (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

- - ============================================================
- - 数据相关表
- - ============================================================

- - K 线数据表（可选，用于缓存常用数据）

CREATE TABLE kline_data (
    id INT AUTO_INCREMENT PRIMARY KEY,
    exchange VARCHAR(20) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,

    timestamp BIGINT NOT NULL COMMENT '时间戳（毫秒）',
    open DECIMAL(18, 8) NOT NULL,
    high DECIMAL(18, 8) NOT NULL,
    low DECIMAL(18, 8) NOT NULL,
    close DECIMAL(18, 8) NOT NULL,
    volume DECIMAL(18, 8) NOT NULL,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uk_data (exchange, symbol, timeframe, timestamp),
    INDEX idx_symbol_time (symbol, timeframe, timestamp),
    INDEX idx_timestamp (timestamp)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

- - ============================================================
- - 系统日志表
- - ============================================================

- - 策略运行日志表

CREATE TABLE strategy_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    task_type ENUM('backtest', 'live') NOT NULL,
    task_id INT NOT NULL,

    level ENUM('DEBUG', 'INFO', 'WARNING', 'ERROR') DEFAULT 'INFO',
    message TEXT NOT NULL,
    extra JSON COMMENT '额外数据',

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_task (task_type, task_id),
    INDEX idx_level (level),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

- - 系统事件表（用于记录重要事件）

CREATE TABLE system_events (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id INT,
    event_type VARCHAR(50) NOT NULL COMMENT 'strategy_started, order_filled, error 等',
    event_type_level ENUM('info', 'warning', 'error', 'critical') DEFAULT 'info',
    title VARCHAR(200) NOT NULL,
    message TEXT,
    data JSON COMMENT '事件相关数据',
    is_read BOOLEAN DEFAULT FALSE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_unread (user_id, is_read),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

```bash

- --

## API 设计

### API 端点列表

#### 1. 认证相关 (`/api/v1/auth`)

| 方法 | 端点 | 描述 |

|------|------|------|

| POST | `/register` | 用户注册 |

| POST | `/login` | 用户登录 |

| POST | `/logout` | 用户登出 |

| GET | `/me` | 获取当前用户信息 |

#### 2. 策略管理 (`/api/v1/strategies`)

| 方法 | 端点 | 描述 |

|------|------|------|

| GET | `/` | 获取策略列表 |

| POST | `/` | 创建新策略 |

| GET | `/{id}` | 获取策略详情 |

| PUT | `/{id}` | 更新策略 |

| DELETE | `/{id}` | 删除策略 |

| POST | `/{id}/validate` | 验证策略代码 |

| GET | `/{id}/params` | 获取策略参数定义 |

| GET | `/templates` | 获取策略模板列表 |

#### 3. 回测管理 (`/api/v1/backtests`)

| 方法 | 端点 | 描述 |

|------|------|------|

| GET | `/` | 获取回测任务列表 |

| POST | `/` | 创建回测任务 |

| GET | `/{id}` | 获取回测详情 |

| DELETE | `/{id}` | 删除回测任务 |

| POST | `/{id}/cancel` | 取消回测任务 |

| GET | `/{id}/trades` | 获取交易记录 |

| GET | `/{id}/equity` | 获取资金曲线 |

#### 4. 实盘管理 (`/api/v1/live`)

| 方法 | 端点 | 描述 |

|------|------|------|

| GET | `/tasks` | 获取实盘任务列表 |

| POST | `/tasks` | 创建实盘任务 |

| GET | `/tasks/{id}` | 获取任务详情 |

| POST | `/tasks/{id}/start` | 启动策略 |

| POST | `/tasks/{id}/stop` | 停止策略 |

| GET | `/tasks/{id}/status` | 获取运行状态 |

| GET | `/tasks/{id}/positions` | 获取持仓 |

| GET | `/tasks/{id}/orders` | 获取订单 |

| GET | `/tasks/{id}/logs` | 获取日志 |

#### 5. 账户管理 (`/api/v1/accounts`)

| 方法 | 端点 | 描述 |

|------|------|------|

| GET | `/` | 获取账户列表 |

| POST | `/` | 添加交易所账户 |

| GET | `/{id}` | 获取账户详情 |

| PUT | `/{id}` | 更新账户信息 |

| DELETE | `/{id}` | 删除账户 |

| POST | `/{id}/test` | 测试连接 |

| GET | `/{id}/balance` | 获取账户余额 |

#### 6. 数据接口 (`/api/v1/data`)

| 方法 | 端点 | 描述 |

|------|------|------|

| GET | `/exchanges` | 获取支持的交易所 |

| GET | `/symbols` | 获取交易对列表 |

| GET | `/klines` | 获取 K 线数据 |

| GET | `/ticker` | 获取当前行情 |

#### 7. WebSocket 端点

| 端点 | 描述 |

|------|------|

| `/ws/live/{task_id}` | 实盘任务实时数据推送 |

| `/ws/backtest/{task_id}` | 回测进度推送 |

| `/ws/market/{symbol}` | 市场数据推送 |

| `/ws/notifications` | 系统通知推送 |

- --

## 前端设计

### Vue 3 技术栈详情

```json
{
  "dependencies": {
    "vue": "^3.4.0",
    "vue-router": "^4.2.5",
    "pinia": "^2.1.7",
    "element-plus": "^2.4.4",
    "@element-plus/icons-vue": "^2.3.1",
    "echarts": "^5.4.3",
    "vue-echarts": "^6.6.5",
    "axios": "^1.6.2",
    "dayjs": "^1.11.10",
    "@vueuse/core": "^10.7.0",
    "monaco-editor": "^0.45.0",
    "@codemirror/lang-python": "^6.0.0"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.0.0",
    "typescript": "^5.3.0",
    "vite": "^5.0.0",
    "sass": "^1.69.5",
    "unplugin-auto-import": "^0.17.2",
    "unplugin-vue-components": "^0.26.0"
  }
}

```bash

### Vue Router 配置

```typescript
// src/router/index.ts
import { createRouter, createWebHistory, RouteRecordRaw } from 'vue-router';
import { useUserStore } from '@/stores/useUserStore';
import Layout from '@/components/layout/MainLayout.vue';

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/',
    component: Layout,
    meta: { requiresAuth: true },
    children: [
      {
        path: '',
        name: 'Dashboard',
        component: () => import('@/views/Dashboard.vue'),
        meta: { title: '仪表板', icon: 'Odometer' }
      },
      {
        path: 'strategies',
        name: 'Strategies',
        component: () => import('@/views/strategies/StrategyList.vue'),
        meta: { title: '策略管理', icon: 'Document' }
      },
      {
        path: 'strategies/create',
        name: 'StrategyCreate',
        component: () => import('@/views/strategies/StrategyCreate.vue'),
        meta: { title: '创建策略', icon: 'Plus' }
      },
      {
        path: 'strategies/:id/edit',
        name: 'StrategyEdit',
        component: () => import('@/views/strategies/StrategyEdit.vue'),
        meta: { title: '编辑策略' }
      },
      {
        path: 'backtests',
        name: 'Backtests',
        component: () => import('@/views/backtests/BacktestList.vue'),
        meta: { title: '回测研究', icon: 'DataAnalysis' }
      },
      {
        path: 'backtests/new',
        name: 'BacktestNew',
        component: () => import('@/views/backtests/BacktestNew.vue'),
        meta: { title: '新建回测', icon: 'Plus' }
      },
      {
        path: 'backtests/:id',
        name: 'BacktestResult',
        component: () => import('@/views/backtests/BacktestResult.vue'),
        meta: { title: '回测结果' }
      },
      {
        path: 'live',
        name: 'Live',
        component: () => import('@/views/live/LiveList.vue'),
        meta: { title: '实盘交易', icon: 'TrendCharts' }
      },
      {
        path: 'live/:id/monitor',
        name: 'LiveMonitor',
        component: () => import('@/views/live/LiveMonitor.vue'),
        meta: { title: '实盘监控' }
      },
      {
        path: 'data',
        name: 'Data',
        component: () => import('@/views/data/DataMarket.vue'),
        meta: { title: '数据管理', icon: 'DataLine' }
      },
      {
        path: 'settings',
        name: 'Settings',
        redirect: '/settings/accounts',
        meta: { title: '设置', icon: 'Setting' }
      },
      {
        path: 'settings/accounts',
        name: 'SettingsAccounts',
        component: () => import('@/views/settings/SettingsAccounts.vue'),
        meta: { title: '账户设置' }
      }
    ]
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: () => import('@/views/NotFound.vue')
  }
];

const router = createRouter({
  history: createWebHistory(),
  routes
});

// 路由守卫
router.beforeEach((to, from, next) => {
  const userStore = useUserStore();
  const requiresAuth = to.matched.some(record => record.meta.requiresAuth !== false);

  if (requiresAuth && !userStore.isLoggedIn) {
    next({ name: 'Login', query: { redirect: to.fullPath } });
  } else {
    next();
  }
});

export default router;

```bash

### Pinia 状态管理

```typescript
// src/stores/useUserStore.ts
import { defineStore } from 'pinia';
import { login, logout, getUserInfo } from '@/api/auth';
import { setToken, getToken, removeToken } from '@/utils/storage';

interface User {
  id: number;
  username: string;
  email: string;
  is_admin: boolean;
}

export const useUserStore = defineStore('user', {
  state: () => ({
    user: null as User | null,

    token: getToken() || '',

    isLoggedIn: !!getToken()
  }),

  getters: {
    isAdmin: (state) => state.user?.is_admin || false

  },

  actions: {
    async login(username: string, password: string) {
      const data = await login(username, password);
      this.token = data.access_token;
      setToken(data.access_token);
      this.isLoggedIn = true;
      await this.fetchUserInfo();
    },

    async fetchUserInfo() {
      const data = await getUserInfo();
      this.user = data;
    },

    async logout() {
      await logout();
      this.token = '';
      this.user = null;
      this.isLoggedIn = false;
      removeToken();
    }
  }
});

```bash

### ECharts K 线图组件

```vue
<!-- src/components/charts/KLineChart.vue -->
<template>
  <div ref="chartRef" class="kline-chart" :style="{ height: height, width: width }"></div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue';
import *as echarts from 'echarts';
import { use } from 'echarts/core';
import { CandlestickChart, BarChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, TitleComponent, DataZoomComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

use([
  CandlestickChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  TitleComponent,
  DataZoomComponent,
  CanvasRenderer
]);

interface KLineData {
  timestamp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface Props {
  data: KLineData[];
  height?: string;
  width?: string;
  title?: string;
  indicators?: {
    upper?: number[];
    middle?: number[];
    lower?: number[];
  };
}

const props = withDefaults(defineProps<Props>(), {
  height: '400px',
  width: '100%',
  title: ''
});

const chartRef = ref<HTMLElement>();
let chart: echarts.ECharts | null = null;

const initChart = () => {
  if (!chartRef.value) return;

  chart = echarts.init(chartRef.value);
  updateChart();
};

const updateChart = () => {
  if (!chart || !props.data.length) return;

  const dates = props.data.map(item => new Date(item.timestamp).toLocaleString());
  const candleData = props.data.map(item => [item.open, item.close, item.low, item.high]);
  const volumes = props.data.map((item, index) => [index, item.volume, item.open > item.close ? -1 : 1]);

  const option: echarts.EChartsOption = {
    title: {
      text: props.title,
      left: 'center'
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: {
        type: 'cross'
      }
    },
    legend: {
      data: ['K 线', '成交量'],
      top: 30
    },
    grid: [
      {
        left: '10%',
        right: '10%',
        top: '15%',
        height: '50%'
      },
      {
        left: '10%',
        right: '10%',
        top: '70%',
        height: '15%'
      }
    ],
    xAxis: [
      {
        type: 'category',
        data: dates,
        scale: true,
        boundaryGap: false,
        axisLine: { onZero: false },
        splitLine: { show: false },
        min: 'dataMin',
        max: 'dataMax'
      },
      {
        type: 'category',
        gridIndex: 1,
        data: dates,
        scale: true,
        boundaryGap: false,
        axisLine: { onZero: false },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: { show: false },
        min: 'dataMin',
        max: 'dataMax'
      }
    ],
    yAxis: [
      {
        scale: true,
        splitArea: {
          show: true
        }
      },
      {
        scale: true,
        gridIndex: 1,
        splitNumber: 2,
        axisLabel: { show: false },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { show: false }
      }
    ],
    dataZoom: [
      {
        type: 'inside',
        xAxisIndex: [0, 1],
        start: 70,
        end: 100
      },
      {
        show: true,
        xAxisIndex: [0, 1],
        type: 'slider',
        top: '90%',
        start: 70,
        end: 100
      }
    ],
    series: [
      {
        name: 'K 线',
        type: 'candlestick',
        data: candleData,
        itemStyle: {
          color: '#26a69a',      // 阳线颜色
          color0: '#ef5350',     // 阴线颜色
          borderColor: '#26a69a',
          borderColor0: '#ef5350'
        }
      },
      {
        name: '成交量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: volumes,
        itemStyle: {
          color: (params: any) => {
            return params[2] > 0 ? '#26a69a' : '#ef5350';
          }
        }
      }
    ]
  };

  // 添加指标线
  if (props.indicators?.upper) {
    option.series.push({
      name: '上轨',
      type: 'line',
      data: props.indicators.upper,
      lineStyle: { color: '#2962ff', width: 1 },
      showSymbol: false
    } as any);
  }

  chart.setOption(option, true);
};

onMounted(() => {
  initChart();
  window.addEventListener('resize', () => chart?.resize());
});

onUnmounted(() => {
  window.removeEventListener('resize', () => chart?.resize());
  chart?.dispose();
});

watch(() => props.data, () => {
  updateChart();
}, { deep: true });
</script>

<style scoped lang="scss">
.kline-chart {
  min-height: 400px;
}
</style>

```bash

### 资金曲线图组件

```vue
<!-- src/components/charts/EquityCurve.vue -->
<template>
  <div ref="chartRef" class="equity-chart" :style="{ height: height, width: width }"></div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue';
import*as echarts from 'echarts';
import { LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, TitleComponent, LegendComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

use([LineChart, GridComponent, TooltipComponent, TitleComponent, LegendComponent, CanvasRenderer]);

interface EquityData {
  date: string;
  equity: number;
  drawdown?: number;
}

interface Props {
  data: EquityData[];
  height?: string;
  width?: string;
  title?: string;
  showDrawdown?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  height: '350px',
  width: '100%',
  title: '资金曲线',
  showDrawdown: true
});

const chartRef = ref<HTMLElement>();
let chart: echarts.ECharts | null = null;

const initChart = () => {
  if (!chartRef.value) return;
  chart = echarts.init(chartRef.value);
  updateChart();
};

const updateChart = () => {
  if (!chart || !props.data.length) return;

  const dates = props.data.map(item => item.date);
  const equity = props.data.map(item => item.equity);
  const drawdown = props.data.map(item => item.drawdown || 0);

  const series: any[] = [
    {
      name: '权益',
      type: 'line',
      data: equity,
      smooth: true,
      lineStyle: { color: '#26a69a', width: 2 },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(38, 166, 154, 0.3)' },
          { offset: 1, color: 'rgba(38, 166, 154, 0.05)' }
          ])
      }
    }
  ];

  if (props.showDrawdown) {
    series.push({
      name: '回撤',
      type: 'line',
      data: drawdown,
      smooth: true,
      lineStyle: { color: '#ef5350', width: 1, type: 'dashed' },
      showSymbol: false
    });
  }

  const option: echarts.EChartsOption = {
    title: {
      text: props.title,
      left: 'center'
    },
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        let result = params[0].axisValue + '<br/>';
        params.forEach((param: any) => {
          result += `${param.marker} ${param.seriesName}: ${param.value.toFixed(2)}<br/>`;
        });
        return result;
      }
    },
    legend: {
      data: props.showDrawdown ? ['权益', '回撤'] : ['权益'],
      top: 30
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '3%',
      containLabel: true
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: dates
    },
    yAxis: {
      type: 'value'
    },
    series
  };

  chart.setOption(option, true);
};

onMounted(() => {
  initChart();
  window.addEventListener('resize', () => chart?.resize());
});

onUnmounted(() => {
  window.removeEventListener('resize', () => chart?.resize());
  chart?.dispose();
});

watch(() => props.data, () => {
  updateChart();
}, { deep: true });
</script>

<style scoped lang="scss">
.equity-chart {
  min-height: 300px;
}
</style>

```bash

### 参数编辑器组件

```vue
<!-- src/components/strategy/ParamEditor.vue -->
<template>
  <el-form :model="formData" label-width="120px">
    <el-form-item
      v-for="param in params"
      :key="param.name"
      :label="param.label || param.name"

      :required="param.required"
    >
      <!-- 数字输入 -->
    <el-input-number
      v-if="param.type === 'number'"
      v-model="formData[param.name]"
      :min="param.min"
      :max="param.max"
      :step="param.step || 1"

      :precision="param.precision || 2"

      :placeholder="`请输入 ${param.label || param.name}`"

      style="width: 100%"
    />

    <!-- 下拉选择 -->
    <el-select
      v-else-if="param.type === 'select'"
      v-model="formData[param.name]"
      :placeholder="`请选择 ${param.label || param.name}`"

      style="width: 100%"
    >
      <el-option
        v-for="opt in param.options"
        :key="opt.value"
        :label="opt.label"
        :value="opt.value"
      />
    </el-select>

    <!-- 开关 -->
    <el-switch
      v-else-if="param.type === 'boolean'"
      v-model="formData[param.name]"
      :active-text="param.activeText || '开'"

      :inactive-text="param.inactiveText || '关'"

    />

    <!-- 文本输入 -->
    <el-input
      v-else
      v-model="formData[param.name]"
      :type="param.inputType || 'text'"

      :placeholder="`请输入 ${param.label || param.name}`"

    />

    <!-- 描述信息 -->
    <template v-if="param.description">
      <div class="param-description">{{ param.description }}</div>
    </template>
    </el-form-item>
  </el-form>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';

interface Param {
  name: string;
  label?: string;
  type: 'number' | 'select' | 'boolean' | 'string';

  default?: any;
  required?: boolean;
  min?: number;
  max?: number;
  step?: number;
  precision?: number;
  options?: Array<{ label: string; value: any }>;
  activeText?: string;
  inactiveText?: string;
  inputType?: string;
  description?: string;
}

interface Props {
  params: Param[];
  modelValue: Record<string, any>;
}

const props = defineProps<Props>();
const emit = defineEmits<{
  'update:modelValue': [value: Record<string, any>]
}>();

const formData = ref<Record<string, any>>({});

// 初始化表单数据
const initForm = () => {
  formData.value = {};
  props.params.forEach(param => {
    formData.value[param.name] = props.modelValue[param.name] ?? param.default ?? '';
  });
};

initForm();

// 监听变化并同步
watch(formData, (newVal) => {
  emit('update:modelValue', { ...props.modelValue, ...newVal });
}, { deep: true });

// 监听外部变化
watch(() => props.modelValue, (newVal) => {
  Object.keys(newVal).forEach(key => {
    if (formData.value[key] !== newVal[key]) {
      formData.value[key] = newVal[key];
    }
  });
}, { deep: true });
</script>

<style scoped lang="scss">
.param-description {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
}
</style>

```bash

### 代码编辑器组件 (Monaco Editor)

```vue
<!-- src/components/strategy/CodeEditor.vue -->
<template>
  <div ref="editorRef" class="monaco-editor" :style="{ height: height }"></div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue';
import* as monaco from 'monaco-editor';

interface Props {
  modelValue: string;
  language?: string;
  height?: string;
  readOnly?: boolean;
  theme?: 'vs' | 'vs-dark';

}

const props = withDefaults(defineProps<Props>(), {
  language: 'python',
  height: '500px',
  readOnly: false,
  theme: 'vs-dark'
});

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>();

const editorRef = ref<HTMLElement>();
let editor: monaco.editor.IStandaloneCodeEditor | null = null;

onMounted(() => {
  if (!editorRef.value) return;

  editor = monaco.editor.create(editorRef.value, {
    value: props.modelValue,
    language: props.language,
    theme: props.theme,
    automaticLayout: true,
    readOnly: props.readOnly,
    minimap: { enabled: true },
    scrollBeyondLastLine: false,
    fontSize: 14,
    lineNumbers: 'on',
    roundedSelection: true,
    scrollbar: {
      useShadows: false,
      verticalScrollbarSize: 10,
      horizontalScrollbarSize: 10
    },
    python: {
      indent: 4
    }
  });

  editor.onDidChangeModelContent(() => {
    if (editor) {
      emit('update:modelValue', editor.getValue());
    }
  });
});

watch(() => props.modelValue, (newValue) => {
    if (editor && editor.getValue() !== newValue) {
      editor.setValue(newValue);
    }
});
</script>

<style scoped lang="scss">
.monaco-editor {
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  overflow: hidden;
}
</style>

```bash

- --

## 开发任务清单

### Phase 1: 项目初始化 (1-2 天)

- [ ] **后端初始化**
  - [ ] 创建 `web/backend` 目录结构
  - [ ] 配置 FastAPI 项目 (`main.py`, `config.py`)
  - [ ] 配置 SQLAlchemy 和 MySQL 连接
  - [ ] 配置 Alembic 数据库迁移
  - [ ] 创建基础模型 (User, Strategy)
  - [ ] 编写 `.env.example` 和 `requirements.txt`

- [ ] **前端初始化**
  - [ ] 使用 Vite 创建 Vue 3 + TypeScript 项目
  - [ ] 安装 Element Plus 和依赖包
  - [ ] 配置 Vue Router
  - [ ] 配置 Pinia 状态管理
  - [ ] 配置 ECharts 和 vue-echarts
  - [ ] 配置自动导入插件
  - [ ] 创建基础布局组件

- [ ] **数据库**
  - [ ] 安装 MySQL 8.0
  - [ ] 创建数据库 `backtrader_web`
  - [ ] 执行初始迁移创建表结构
  - [ ] 创建测试数据

### Phase 2: 用户系统 (2-3 天)

- [ ] **后端 - 认证**
  - [ ] 实现用户注册 API
  - [ ] 实现用户登录 API (JWT)
  - [ ] 实现密码加密 (bcrypt)
  - [ ] 实现权限验证中间件
  - [ ] 实现用户信息获取/更新 API

- [ ] **前端 - 认证**
  - [ ] 登录页面 (`/login`)
  - [ ] 注册页面 (`/register`)
  - [ ] 用户状态管理
  - [ ] 路由守卫（未登录跳转）
  - [ ] Token 自动刷新

### Phase 3: 交易所账户管理 (2-3 天)

- [ ] **后端**
  - [ ] 创建 ExchangeAccount 模型
  - [ ] 实现账户 CRUD API
  - [ ] 实现账户连接测试 API
  - [ ] 实现账户余额查询 API
  - [ ] API 密钥加密存储

- [ ] **前端**
  - [ ] 账户管理页面 (`/settings/accounts`)
  - [ ] 添加账户表单
  - [ ] 账户列表展示
  - [ ] 连接测试功能

### Phase 4: 策略管理 (3-4 天)

- [ ] **后端 - 策略解析**
  - [ ] 策略文件上传 API
  - [ ] 策略代码解析器
    - [ ] 提取策略类名
    - [ ] 提取 params 定义
    - [ ] 提取 docstring 描述
  - [ ] 策略验证 API (语法检查)
  - [ ] 策略 CRUD API

- [ ] **后端 - 策略模板**
  - [ ] 内置策略模板数据
  - [ ] 模板查询 API
  - [ ] 从模板创建策略 API

- [ ] **前端**
  - [ ] 策略列表页面 (`/strategies`)
  - [ ] 创建策略页面 (`/strategies/create`)
  - [ ] Monaco 代码编辑器组件
  - [ ] 参数编辑器组件
  - [ ] 策略详情/编辑页面

### Phase 5: 回测系统 (4-5 天)

- [ ] **后端 - 回测引擎**
  - [ ] Celery 任务配置
  - [ ] 回测任务创建 API
  - [ ] 回测执行任务
    - [ ] 加载策略
    - [ ] 加载数据
    - [ ] 运行 Cerebro
    - [ ] 收集结果
  - [ ] 回测进度推送 (WebSocket)
  - [ ] 回测结果存储
  - [ ] 回测记录查询 API

- [ ] **前端**
  - [ ] 回测列表页面 (`/backtests`)
  - [ ] 创建回测页面
    - [ ] 策略选择器
    - [ ] 数据源选择器
    - [ ] 参数配置面板
    - [ ] 日期范围选择
  - [ ] 回测结果页面
    - [ ] 结果汇总卡片
    - [ ] 资金曲线图表 (ECharts)
    - [ ] 回撤图表
    - [ ] 交易列表
    - [ ] 统计数据

### Phase 6: 实盘交易系统 (5-7 天)

- [ ] **后端 - 实盘引擎**
  - [ ] 实盘任务创建 API
  - [ ] 策略进程管理
    - [ ] 启动策略 (子进程)
    - [ ] 停止策略
    - [ ] 进程状态监控
  - [ ] 实时数据收集
  - [ ] 订单同步 (CCXT → DB)
  - [ ] 持仓同步
  - [ ] 日志收集
  - [ ] WebSocket 状态推送

- [ ] **前端**
  - [ ] 实盘列表页面 (`/live`)
  - [ ] 实盘监控页面 (`/live/:id/monitor`)
    - [ ] 状态面板
    - [ ] K 线图表
    - [ ] 持仓列表
    - [ ] 订单列表
    - [ ] 实时日志
    - [ ] 快捷操作 (启动/停止/手动下单)

### Phase 7: 数据管理 (2-3 天)

- [ ] **后端**
  - [ ] 交易所列表 API
  - [ ] 交易对查询 API
  - [ ] K 线数据查询 API
  - [ ] 实时行情 API (WebSocket)
  - [ ] 历史数据下载任务

- [ ] **前端**
  - [ ] 数据管理页面 (`/data`)
  - [ ] 交易对选择组件
  - [ ] K 线图表展示
  - [ ] 数据导出功能

### Phase 8: 完善与优化 (3-5 天)

- [ ] **通知系统**
  - [ ] 系统事件表
  - [ ] 订单成交通知
  - [ ] 错误告警通知
  - [ ] Element Plus Notification 封装

- [ ] **日志系统**
  - [ ] 策略日志查询 API
  - [ ] 日志过滤和搜索
  - [ ] 日志下载

- [ ] **性能优化**
  - [ ] 数据库查询优化
  - [ ] API 响应缓存 (Redis)
  - [ ] 前端懒加载
  - [ ] ECharts 按需加载

- [ ] **安全加固**
  - [ ] API 访问频率限制
  - [ ] SQL 注入防护
  - [ ] XSS 防护
  - [ ] CORS 配置

- --

## 开发步骤

### Step 1: 环境准备

```bash

# 1. 安装 MySQL 8.0

# Windows: 下载安装包

# Linux: sudo apt install mysql-server

# Mac: brew install mysql

# 2. 创建数据库

mysql -u root -p
CREATE DATABASE backtrader_web CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'backtrader'@'localhost' IDENTIFIED BY 'your_password';
GRANT ALL PRIVILEGES ON backtrader_web.* TO 'backtrader'@'localhost';
FLUSH PRIVILEGES;

# 3. 安装 Redis (用于 Celery)

# Windows: 下载 Redis for Windows

# Linux: sudo apt install redis-server

# Mac: brew install redis

# 4. 启动 Redis

redis-server

```bash

### Step 2: 后端项目初始化

```bash

# 1. 创建目录

cd backtrader
mkdir -p web/backend

# 2. 创建虚拟环境

cd web/backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. 安装依赖

cat > requirements.txt << EOF
fastapi==0.104.1
uvicorn[standard]==0.24.0
sqlalchemy==2.0.23
pymysql==1.1.0
cryptography==41.0.7
alembic==1.12.1
pydantic==2.5.0
pydantic-settings==2.1.0
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
celery==5.3.4
redis==5.0.1
python-multipart==0.0.6
aiofiles==23.2.1
loguru==0.7.2
websockets==12.0
ccxt==4.1.0
ccxt.pro==4.0.0
python-dotenv==1.0.0
EOF

pip install -r requirements.txt

# 4. 创建配置文件

cat > config.py << EOF
from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):

# 应用配置
    APP_NAME: str = "Backtrader Web"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

# 数据库配置
    DATABASE_URL: str = "mysql+pymysql://backtrader:password@localhost:3306/backtrader_web"

# Redis 配置
    REDIS_URL: str = "redis://localhost:6379/0"

# JWT 配置
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

# 文件存储
    STORAGE_PATH: str = "./storage"

# CORS
    CORS_ORIGINS: list = ["<http://localhost:5173"]>

    class Config:
        env_file = ".env"

@lru_cache()
def get_settings():
    return Settings()

settings = get_settings()
EOF

# 5. 创建主应用

cat > main.py << EOF
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import settings

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG
)

# CORS 配置

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "Backtrader Web API", "version": settings.APP_VERSION}

@app.get("/health")
async def health():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
EOF

# 6. 创建目录结构

mkdir -p app/{api,models,schemas,services,tasks,core,utils}
mkdir -p database/migrations/versions
mkdir -p storage/{strategies,backtests,logs}

# 7. 创建 .env 文件

cat > .env << EOF
DATABASE_URL=mysql+pymysql://backtrader:password@localhost:3306/backtrader_web
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=your-secret-key-change-in-production
DEBUG=True
EOF

# 8. 测试运行

python main.py

# 访问 <http://localhost:8000>

```bash

### Step 3: 前端项目初始化 (Vue 3)

```bash

# 1. 创建前端项目

cd backtrader/web
npm create vite@latest frontend -- --template vue-ts
cd frontend

# 2. 安装依赖

npm install

# 核心依赖

npm install vue-router@4 pinia element-plus @element-plus/icons-vue
npm install echarts vue-echarts
npm install axios dayjs

# 开发依赖

npm install -D sass unplugin-vue-components unplugin-auto-import

# 3. 配置 vite.config.ts

cat > vite.config.ts << EOF
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

export default defineConfig({
  plugins: [
    vue(),
    AutoImport({
      resolvers: [ElementPlusResolver()],
      imports: ['vue', 'vue-router', 'pinia'],
      dts: true,
    }),
    Components({
      resolvers: [ElementPlusResolver()],
      dts: true,
    }),
  ],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: '<http://localhost:8000',>
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
})
EOF

# 4. 配置 tsconfig.json

cat > tsconfig.json << EOF
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "module": "ESNext",
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "preserve",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "baseUrl": ".",
    "paths": {
      "@/*": ["src/*"]
    }
  },
  "include": ["src/**/*.ts", "src/**/*.d.ts", "src/**/*.tsx", "src/**/*.vue"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
EOF

# 5. 创建目录结构

mkdir -p src/{views,components,stores,composables,api,types,utils,router,assets/styles}
mkdir -p src/views/{strategies,backtests,live,data,settings}
mkdir -p src/components/{layout,charts,strategy,trading,common}

# 6. 启动开发服务器

npm run dev

# 访问 <http://localhost:5173>

```bash

### Step 4: 数据库迁移设置

```bash

# 1. 初始化 Alembic

cd backtrader/web/backend
alembic init alembic

# 2. 配置 alembic.ini

# 修改 sqlalchemy.url = mysql+pymysql://backtrader:password@localhost:3306/backtrader_web

# 3. 创建第一个迁移

alembic revision --autogenerate -m "Initial migration"

# 4. 执行迁移

alembic upgrade head

```bash

### Step 5: 运行整个系统

```bash

# 终端 1: 启动 MySQL

# 确保 MySQL 正在运行

# 终端 2: 启动 Redis

redis-server

# 终端 3: 启动后端

cd backtrader/web/backend
source venv/bin/activate
python main.py

# 终端 4: 启动 Celery Worker

cd backtrader/web/backend
source venv/bin/activate
celery -A app.tasks.celery_app worker --loglevel=info

# 终端 5: 启动前端

cd backtrader/web/frontend
npm run dev

```bash

- --

## 开发优先级

### 第一优先级 (MVP) - 1-2 周

1. 用户登录/注册
2. 策略文件上传和管理
3. 回测配置和运行
4. 回测结果展示（基础图表）

### 第二优先级 - 2-3 周

1. 交易所账户管理
2. 实盘策略启动/停止
3. 实盘状态监控
4. 订单和持仓查询

### 第三优先级 - 2-3 周

1. WebSocket 实时数据推送
2. K 线图表展示（完整版）
3. 参数优化功能
4. 通知系统

### 第四优先级 - 1-2 周

1. 数据管理模块
2. 高级分析工具
3. 多用户权限
4. 性能优化

- --

## 快速开始指南

### 1. 前端项目模板初始化

```bash

# 使用 Vite 创建 Vue 3 + TypeScript 项目

cd backtrader/web
npm create vite@latest frontend -- --template vue-ts
cd frontend

# 安装依赖

npm install

# 核心依赖

npm install vue-router@4 pinia pinia-plugin-persistedstate
npm install element-plus @element-plus/icons-vue
npm install echarts vue-echarts
npm install axios dayjs @vueuse/core
npm install lodash-es

# 开发依赖

npm install -D sass unplugin-vue-components unplugin-auto-import
npm install -D @types/lodash-es vite-plugin-compression

# 配置完成后启动

npm run dev

```bash

### 2. 前端核心配置文件

#### vite.config.ts

```typescript
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

export default defineConfig({
  plugins: [
    vue(),
    AutoImport({
      resolvers: [ElementPlusResolver()],
      imports: ['vue', 'vue-router', 'pinia', '@vueuse/core'],
      dts: true
    }),
    Components({
      resolvers: [ElementPlusResolver()],
      dts: true
    })
  ],
  resolve: {
    alias: { '@': resolve(__dirname, 'src') }
  },
  server: {
    port: 5173,
    proxy: {
      '/api': '<http://localhost:8000',>
      '/ws': { target: 'ws://localhost:8000', ws: true }
    }
  }
})

```bash

#### tsconfig.json

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "module": "ESNext",
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "preserve",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "baseUrl": ".",
    "paths": { "@/*": ["src/*"] }
  },
  "include": ["src/**/*.ts", "src/**/*.d.ts", "src/**/*.tsx", "src/**/*.vue"]
}

```bash

### 3. 基础目录结构创建

```bash

# 创建目录

mkdir -p src/{api,assets/styles,components,charts,composables,directives,layouts,router,stores,types,utils,views}
mkdir -p src/components/{layout,charts,trading,strategy,common}
mkdir -p src/components/charts/{base,trading,analysis,indicators}
mkdir -p src/views/{strategies,backtests,live,data,settings}

# 创建入口文件

touch src/main.ts src.App.vue
touch src/router/index.ts
touch src/stores/index.ts

```bash

### 4. 主入口文件

```typescript
// src/main.ts
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import piniaPluginPersistedstate from 'pinia-plugin-persistedstate'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

import App from './App.vue'
import router from './router'
import '@/assets/styles/index.scss'

const app = createApp(App)
const pinia = createPinia()

pinia.use(piniaPluginPersistedstate)

app.use(pinia)
app.use(router)
app.use(ElementPlus)

// 注册所有图标
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.mount('#app')

```bash

### 5. API 请求封装

```typescript
// src/api/request.ts
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/useUserStore'

const request = axios.create({
  baseURL: '/api',
  timeout: 30000
})

// 请求拦截器
request.interceptors.request.use(
  config => {
    const userStore = useUserStore()
    if (userStore.token) {
      config.headers.Authorization = `Bearer ${userStore.token}`
    }
    return config
  },
  error => Promise.reject(error)
)

// 响应拦截器
request.interceptors.response.use(
  response => response.data,
  error => {
    const message = error.response?.data?.detail || error.message || '请求失败'

    ElMessage.error(message)
    return Promise.reject(error)
  }
)

export default request

```bash

### 6. 第一个页面组件

```vue
<!-- src/views/Dashboard.vue -->
<template>
  <div class="dashboard">
    <el-row :gutter="20">
      <el-col :span="6" v-for="card in cards" :key="card.title">
        <el-card class="stat-card">
          <div class="stat-value">{{ card.value }}</div>
          <div class="stat-label">{{ card.title }}</div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'

const cards = ref([
  { title: '运行策略', value: '0' },
  { title: '总资产', value: '$0' },
  { title: '今日盈亏', value: '+$0' },
  { title: '系统状态', value: '正常' }
])

onMounted(async () => {
  // 加载数据
})
</script>

<style scoped lang="scss">
.stat-card {
  text-align: center;
  .stat-value {
    font-size: 28px;
    font-weight: bold;
    color: var(--el-color-primary);
  }
  .stat-label {
    margin-top: 8px;
    color: var(--el-text-color-secondary);
  }
}
</style>

```bash

### 7. 运行项目

```bash

# 后端

cd backtrader/web/backend
python main.py

# 前端

cd backtrader/web/frontend
npm run dev

# 访问 <http://localhost:5173>

```bash

- --

## 相关文档

- [前端优化方案](./WEB_FRONTEND_OPTIMIZATION.md) - Vue3 + ECharts 详细实现
- [架构设计](./WEB_ARCHITECTURE.md) - 系统架构设计
- [WebSocket 指南](./WEBSOCKET_GUIDE.md) - 实时数据通信
