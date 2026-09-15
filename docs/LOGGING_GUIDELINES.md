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

- 面向用户的 CLI 输出（如 `btrun`、`reports/reporter.py`）**保留 `print()`**，不要改成
  日志——那是程序的正常输出，不是诊断信息。
- 库内部的进度/诊断 `print()` → 迁移到 `logger.info()` / `logger.debug()`。
- 公共 API（`Analyzer.print()`、`Strategy.log()`）保持原样。

## 分级分天日志（迭代 29）

一次调用即可按 **运行脚本 → 日期 → 级别** 落盘：

```python
bt.configure_logging(level="INFO", log_dir="logs")
# 运行 `python examples/xxx/run.py` 后产出：
#   logs/examples_xxx_run/2026_09_15/error.log    (ERROR+CRITICAL)
#   logs/examples_xxx_run/2026_09_15/warning.log  (仅 WARNING)
#   logs/examples_xxx_run/2026_09_15/info.log     (仅 INFO)
#   logs/examples_xxx_run/2026_09_15/debug.log    (仅 DEBUG, level=DEBUG 时)
```

- **脚本名**自动取自 `sys.argv[0]`（`xxx/run.py` → `xxx_run`），可用 `script_name=`
  显式覆盖；交互式/`-c`/`<stdin>` 回退 `backtrader`。显式名称同样规范化为单个
  安全路径组件；脚本/日期目录及级别文件不接受符号链接。
- **配置即建文件**：当日无事件也创建空文件，保证每次运行可查询。
- **跨午夜滚动**：午夜后首条日志自动切到新日期目录。
- **保留期**：`retention_days=30`（默认）只清理本脚本目录下的超期真实日期目录，
  跳过符号链接和同名普通文件；`None` 禁用清理，负数或非整数无效。
- **写入后端**：`backend="auto"`（默认）优先使用可选包 `spdlog`（性能好，
  `pip install spdlog`；macOS 实测可用，Linux 需源码构建），不可用自动回退标准库
  并提示一次；`backend="spdlog"` 强制（不可用抛 `ImportError`）；`backend="stdlib"`
  纯标准库。`log_dir` 与旧的 `log_file` 互斥。
- **多进程**：Cerebro optimize 序列化仅传递已启用的 `log_dir` 配置，不传递
  handler、文件对象或锁。spawn worker 恢复配置，fork worker 切换到本进程文件，
  文件名带 `.p{pid}` 后缀；未配置时 worker 保持静默。旧 `log_file` 单文件模式
  不自动传播到 spawn worker。
- **重复配置**：配置调用串行化，新配置验证和 handler 创建成功后才替换已有
  配置；调用失败保留原 handler。旧的位置参数仍然有效，新增选项仅按关键字传入。
- **写入故障**：分级文件的写入/午夜切换失败不外抛，stderr 只给一次不含原始
  日志或异常载荷的诊断；保留期清理失败同样不影响回测。
- **凭证保护**：框架管理的格式化器在消息和堆栈中遮蔽常见 password、passphrase、
  API key/secret、token、Authorization 及 URL 密码字段。调用方仍须避免记录完整
  请求、账号或未知命名的敏感载荷；自定义宿主 handler 的脱敏由宿主负责。

### 级别判定边界（错误分级规范）

| 级别 | 判定边界 |
| --- | --- |
| ERROR | 数据损坏、下单失败、连接断开、资金状态不一致、run 异常终止 |
| WARNING | 可恢复降级、重试、兼容性回退、预期外但已处理 |
| INFO | 生命周期节点（run 开始/结束、feed 加载完成、策略相位切换、订单提交/成交） |
| DEBUG | 过程细节、探测性成功/失败、每 bar 级追踪（须 isEnabledFor 门控） |

### 异常风暴抑制

热循环内同类重复异常用 throttled 系列（首次全量，后续计数 + 周期摘要）：

```python
from backtrader.utils.log_message import throttled_error

for item in many:
    try:
        process(item)
    except ValueError as e:
        throttled_error(logger, "batch-parse", "parse failed: %s", e,
                        every=100, window=60.0)
```

`set_throttle(False)` 进入诊断模式（逐条输出）；进程退出时自动输出各 key 的
累计摘要并刷新文件。计数按 logger、key、级别和异常类型隔离，摘要保留原级别且
只计算被抑制的重复记录；`reset_logging()` 丢弃本轮未输出的计数。与 `TradeLogger`
（JSON 结构化交易日志）互补，不互相替代。
