# 日志使用规范 (Logging Guidelines)

> 适用于 `backtrader` 框架代码与用户策略。Sprint 2（统一日志基础设施）的产物。

## 单一入口 (Single Entry Point)

**框架内部不要直接 `import logging`**，改用 `backtrader.utils.log_message`
暴露的统一入口（也已在顶层 `bt.` 命名空间导出）：

```python
from backtrader.utils.log_message import get_logger

logger = get_logger(__name__)   # -> "backtrader.<module>"
```

用户侧开启日志（**默认完全静默**，不调用就没有任何输出，也不干扰宿主程序的
logging 配置）：

```python
import backtrader as bt

bt.configure_logging(level="INFO", log_file="run.log")  # 控制台 + 可选滚动文件
logger = bt.get_logger(__name__)
logger.info("strategy started")
```

API：

| 函数 | 作用 |
| --- | --- |
| `get_logger(name=None)` | 获取 `backtrader.*` 命名空间下的 logger |
| `configure_logging(level, log_file=None, console=True, ...)` | 一次性配置（幂等；只动 `backtrader` logger，不动 root） |
| `set_level(level, name=None)` | 运行时调级 |
| `reset_logging()` | 还原到默认静默状态（主要供测试用） |
| `SpdLogManager(...)` | 旧的「按文件 + 每日滚动」工厂，保留兼容（TradeLogger 等沿用） |

底层仍是标准库 `logging`（无第三方依赖），但**调用方一律走上面的封装**，便于
统一格式、级别与 handler 管理。

## 设计约束 (Design Constraints)

- **默认零影响**：导入 backtrader 时，root `backtrader` logger 上只有一个
  `NullHandler`，不产生任何输出。只有用户显式 `configure_logging()` 才会装
  handler。
- **不污染宿主**：`configure_logging` 只配置 `backtrader` logger，且默认
  `propagate=False`；它只会替换自己加的 handler（带内部标记），不会动宿主程序
  挂在 `backtrader` logger 上的 handler。
- **幂等**：重复调用不会叠加 handler。

## 级别使用规范 (Level Conventions)

| 级别 | 使用场景 | 示例 |
| --- | --- | --- |
| `CRITICAL` | 引擎无法继续运行 | Cerebro 配置非法、broker 连接彻底失败 |
| `ERROR` | 操作失败但可恢复 / 需要关注 | 订单被拒、数据加载失败、网络重连失败 |
| `WARNING` | 异常但不影响主流程的降级 | 数据缺失填补、参数被自动修正、回退行为 |
| `INFO` | 关键里程碑事件 | 策略启动/结束、broker 连接成功、订单成交 |
| `DEBUG` | 详细诊断信息 | 每根 bar 的中间值、指标计算细节 |

## 异常 + 日志的写法 (Exceptions + Logging)

**禁止静默吞异常**（`except ...: pass`）。最低要求是落一条带上下文的日志：

```python
try:
    risky_operation()
except (ValueError, KeyError) as e:
    logger.warning("parse row %s failed, skipping: %s", row_id, e)
```

- 真正无所谓的清理/析构失败，用 `logger.debug(...)` 并加注释说明原因。
- 需要把异常向上抛时，先 `logger.error(...)` 再 `raise`；如有上层异常，用
  `raise NewError(...) from e` 保留链路。
- 不要用 f-string 拼接后传给 logger（`logger.info(f"x={x}")`），改用
  **惰性参数**：`logger.info("x=%s", x)`，避免日志被关闭时仍付出格式化开销。

## 热路径守护 (Hot-path Guard)

在 `next()` / `once()` / `_runonce` / `_runnext` 等每根 bar 都会执行的热点里加
DEBUG 日志时，**必须**用守护避免无谓的字符串格式化：

```python
if logger.isEnabledFor(logging.DEBUG):
    logger.debug("bar %d: close=%s sma=%s", len(self), close, sma)
```

## print 的去留 (print vs logging)

- 面向用户的 CLI 输出（如 `btrun`）**保留 `print()` / `click.echo()`**，不要改成
  日志——那是程序的正常输出，不是诊断信息。
- 库内部的进度/诊断 `print()` → 迁移到 `logger.info()` / `logger.debug()`。
