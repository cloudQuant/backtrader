# ChangeLog

## [Unreleased] - 2026-02-07

### 中频回测增强（迭代7）

- **重构 `MixBroker` 为中频协调层**: 移除旧的 `bar_fallback`/`tick_timeout` 语义，`process_bar` 仅更新低频状态，不再承担订单撮合。
- **新增 `MidFreqContext` 统一上下文**: 策略可通过 `self.context` 读取高频窗口、已完成 bar、SMA、账户与多品种快照。
- **统一 channel 时间线**: 同一时间戳下固定按 `tick -> orderbook -> bar` 顺序处理，支持多品种全局时间推进。
- **新增多品种 mixed channel / 套利样例**: 增加 `build_mixed_channel()`、`examples/004_midfreq_demo/`、`examples/005_midfreq_arbitrage/`。
- **新增测试覆盖**: 补充单品种、多品种、集成与性能基线测试，验证高频优先执行、bar 不撮合、跨品种快照与 `get_ob_ratio()` 延迟基线。

### Bug 修复

- **修复 position 日志缺少 dt 的问题**: 当数据源尚无数据时（`len(data)==0`），跳过该数据源的持仓记录，避免 dt 为空。

### TradeLogger Observer 增强 (迭代 137)

#### 新增功能

- **实时日志写入**: 日志文件在回测运行过程中实时追加写入（每个 bar 写入一次），而非运行结束后批量写入。即使进程崩溃，已写入的数据也不会丢失。
- **log_time 字段**: 所有日志记录（order、trade、position、data）的第一个字段增加 `log_time`，记录精确到微秒的写入时间。
- **current_position.json**: 每个 bar 运行后更新 `current_position.json` 文件，保存当前持仓快照。
- **策略指标记录**: 新增 `log_indicators` 参数，支持将策略中计算的指标（如 SMA、CrossOver 等）写入 data 日志文件。
- **可配置文件格式**: 新增 `file_format` 参数，支持 `"log"`（tab 分隔，默认）和 `"csv"`（逗号分隔）两种格式。
- **MySQL 持久化**: 支持将 order、trade、position 日志批量写入 MySQL 数据库。
  - 数据库名：`backtrder_web`
  - 表：`bt_order`、`bt_trade`、`bt_position`
  - data 日志因列不固定，仅保存到文件，不写入 MySQL
  - 支持 `log_time`（DATETIME(6) 微秒精度）和 `created_at`（自动时间戳）列
  - 复合索引 `(strategy_name, run_id)` 支持高效查询
- **数据库初始化脚本**: 新增 `scripts/setup_mysql_db.py`，支持交互式或命令行方式创建数据库和表。

#### 文件输出结构

```bash
{log_dir}/{StrategyName}_{YYYYMMDD_HHMMSS}/
    run_info.json           # 运行元数据
    current_position.json   # 最新持仓（每 bar 更新）
    order.log               # 订单日志
    trade.log               # 交易日志
    position.log            # 持仓日志
    data.log                # 行情+指标数据

```bash

#### 使用示例

```python
cerebro.addobserver(
    bt.observers.TradeLogger,
    log_orders=True,
    log_trades=True,
    log_positions=True,
    log_data=True,
    log_indicators=True,        # 记录策略指标
    log_dir='logs',
    file_format='log',          # 'log'(tab 分隔) 或 'csv'

# MySQL 配置（可选）

# mysql_enabled=True,

# mysql_host='localhost',

# mysql_database='backtrder_web',

# mysql_user='root',

# mysql_password='your_password',

)

```bash

#### 测试

- 日志文件名和 MySQL 表名移除 `_log` 后缀（如 `order_log.log` → `order.log`，`bt_order_log` → `bt_order`）
- 新增 19 个测试用例，覆盖：实时写入、log_time 字段、文件格式、current_position.json、策略指标、MySQL 读写、MySQL 不创建 data_log 表等
- 全部 497 个测试通过

#### 修改的文件

- `backtrader/observers/tradelogger.py` - TradeLogger 核心实现
- `backtrader/strategy.py` - 确保 observer.stop() 在回测结束时被调用
- `examples/001_multi_extend_data/run.py` - 更新示例
- `tests/add_tests/test_observer_tradelogger.py` - 测试用例
- `scripts/setup_mysql_db.py` - 数据库初始化脚本（新增）
