- --

stepsCompleted: ["step-01-validate-prerequisites"]
inputDocuments: ["prd.md", "architecture.md"]
status: in-progress
project_name: backtrader

- --

# Backtrader - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for Backtrader, decomposing the requirements from the PRD and Architecture into implementable stories.

## Requirements Inventory

### Functional Requirements

- *策略开发 (Strategy Development)**

- FR1: 用户可以创建继承自 Strategy 基类的自定义交易策略
- FR2: 用户可以在策略中访问技术指标（SMA、EMA、RSI 等 60+指标）
- FR3: 用户可以访问 OHLCV 行情数据和自定义数据列
- FR4: 用户可以定义策略参数并在初始化时配置

- *回测引擎 (Backtesting Engine)**

- FR5: 系统可以使用历史数据执行策略回测
- FR6: 系统可以生成回测性能报告（收益率、夏普比率、最大回撤等）
- FR7: 用户可以进行参数优化
- FR8: 系统可以模拟交易成本（滑点、佣金）

- *实盘交易 (Live Trading)**

- FR9: 用户可以通过统一 Broker 接口连接 CCXT 交易所
- FR10: 用户可以通过统一 Broker 接口连接 CTP 期货接口
- FR11: 用户可以通过统一 Broker 接口连接国内股票接口
- FR12: 用户可以执行市价单和限价单
- FR13: 用户可以取消待处理订单
- FR14: 用户可以查询当前持仓和账户余额
- FR15: 系统可以处理订单状态更新和成交回报

- *数据管理 (Data Management)**

- FR16: 用户可以添加自定义数据列（不限于 OHLCV）
- FR17: 系统支持多种数据源（CSV、Pandas DataFrame、实时数据）
- FR18: 系统可以处理不同时间粒度的数据（tick、分钟、日频）

- *系统兼容 (System Compatibility)**

- FR19: 旧版 Backtrader 策略代码无需修改即可运行
- FR20: 系统提供完整的 API 文档和代码示例
- FR21: 系统支持 Python 3.8+版本

### NonFunctional Requirements

- *性能 (Performance)**

- NFR-P1: 系统应能在合理时间内完成 10 年日频数据的双均线策略回测
- NFR-P2: 系统应支持参数优化功能
- NFR-P3: 后续 C++重构目标：回测速度提升 5-10 倍
- NFR-P4: 订单执行延迟应控制在交易所 API 允许的范围内
- NFR-P5: 系统应处理实时行情数据更新

- *安全 (Security)**

- NFR-S1: API 密钥应安全存储，不应在日志或代码中硬编码
- NFR-S2: 敏感配置信息应支持加密存储
- NFR-S3: 系统应在执行订单前进行基本验证（资金充足、参数合法）
- NFR-S4: 系统应记录所有交易操作以便审计

- *可靠性 (Reliability)**

- NFR-R1: 实盘运行应达到 99.9%可用性
- NFR-R2: 系统应能从网络断线中自动恢复
- NFR-R3: 系统应妥善处理交易所 API 错误和限流
- NFR-R4: 回测和实盘应使用相同的策略逻辑
- NFR-R5: 系统应确保持仓和余额数据的准确性

- *兼容性 (Compatibility)**

- NFR-C1: 旧版 Backtrader 策略代码应无需修改即可运行
- NFR-C2: 现有 API 接口应保持稳定
- NFR-C3: 系统应支持 Python 3.8+
- NFR-C4: 系统应在主流操作系统上运行

- *集成 (Integration)**

- NFR-I1: 系统应通过 CCXT 库支持数字货币交易所
- NFR-I2: 系统应通过 CTP 接口支持国内期货
- NFR-I3: 系统应支持国内股票交易接口

### Additional Requirements

- *From Architecture Document:**

- AR1: 不引入新元类，使用显式初始化 (donew()) 模式
- AR2: API 必须向后兼容 backtrader_web（FastAPI + Vue 3 架构）
- AR3: 不使用 Cython 进行性能优化（按用户要求）
- AR4: 通过 Observer 模式扩展监控功能，不破坏 Line System 架构
- AR5: 存储后端扩展在 TradeLogger 类内实现（Redis P1、MongoDB P2、DolphinDB P3）
- AR6: 统一错误处理策略：网络错误指数退避重试、限流动态调整、订单失败记录通知
- AR7: WebSocket 断线自动重连 + 订阅恢复
- AR8: 实时监控 Observer（性能指标、告警通知）待实现
- AR9: 统一 Broker API 设计（后续长期目标，暂不实施）
- AR10: 数据存储选型：CSV(回测)、Redis(实时缓存)、MySQL(交易记录)、MongoDB(策略日志)

- *No UX Design Document (no UI in MVP scope)**

### FR Coverage Map

{{requirements_coverage_map}}

## Epic List

{{epics_list}}
