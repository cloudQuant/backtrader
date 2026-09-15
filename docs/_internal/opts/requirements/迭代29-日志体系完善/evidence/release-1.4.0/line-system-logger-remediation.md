# 1.4.0 行系统异常日志最终修复记录

状态：**SOURCE_BOUND_FOCUSED_PASS_PENDING_FINAL_GATES**。本记录覆盖
`backtrader/linebuffer.py`、`backtrader/lineiterator.py`、`backtrader/lineroot.py`
和 `backtrader/lineseries.py` 的最终行系统日志修复源码快照，并补记
`backtrader/plot/locator.py` 的迭代 29 兼容回退。它不是最终提交、包、远程 CI、tag、
Release、实盘、SimNow 或盈利验收。

## 源码绑定

基线 HEAD 为 `404383b7e92690374f33563e90c70497c98860b9`；以下是工作树快照
SHA-256，最终提交产生后必须重新绑定：

| 文件 | SHA-256 | AST `except` | 真正恢复 handler |
| --- | --- | ---: | ---: |
| `backtrader/linebuffer.py` | `7f182cf61a5e137c3e0dc2504b597b5a6de4f7b5a471df707c2e92c586b1cded` | 64 | 30 |
| `backtrader/lineiterator.py` | `afcf6faa5fbd78952d2a839cb02f1b54d8eb4100ec3af00cf10dab9c9d39641d` | 101 | 23 |
| `backtrader/lineroot.py` | `cb192bf65e1ea4ed28a8ae78b26f953ce32961d91562fffeaff9c48967a30f90` | 24 | 14 |
| `backtrader/lineseries.py` | `492ca9ee5a88057e821e41401d8954a5d5e9a645847ba852553a879875e02249` | 87 | 13 |
| **合计** | — | **276** | **80** |

## 静态复核

Python AST 逐个统计 `ExceptHandler`，并检查每个 handler 内的限流调用：

- 80 个真正恢复 handler 都至少有一个 `throttled_warning` 或
  `throttled_error`，使用固定的 key、固定消息和 `exc_info=False`。
- 静态 handler 子树计数遵循机器可读记录中的约定；嵌套的兼容 handler 可以共享
  同一个限流调用，因此 handler 数量不应和调用数量直接等同。
- 10 个静态 `ImportError` WARNING 属启动或导入兼容路径，排除在 80 个恢复
  handler 外：指标别名注册的 EMA、SMA、WMA、HMA、DEMA、TEMA、TSI、BBands、CCI
  共 9 个，加上 `lineroot` 的 `Strategy` 兼容补丁导入 1 个。这些路径不在逐 bar
  热循环中。
- 四个文件中 `logger.debug` 调用为 0；AST 的 `exc_info=True` 调用和源码文本
  `exc_info=True` 出现次数均为 0。

正常的缺属性、空缓冲、不可缓存、不可比长度等 EAFP/协议探测仍保持静默。真正改变
回退值或继续执行的恢复分支产生有界 WARNING/ERROR；消息不携带捕获到的异常载荷，
避免把未知用户数据或 traceback 写入框架日志。

完整的机器可读计数、方法和当前 hash 见
[line-system-logger-remediation.json](line-system-logger-remediation.json)。

## 冻结后附加修复

`lineiterator._ensure_lineactions_inputs_computed` 现在先检查 `src._once` 是否可调用，
再把对象作为孤儿指标排入显式生命周期调度。`LineBuffer` 虽然有直接向量运算的
`once()`，却没有 `LineIterator` 的 `_once()` 生命周期钩子；因此该能力缺失属于正常
协议探测，保持静默。真正可调用的 `_once()` 仍执行，异常继续向调用方传播。

`backtrader/plot/locator.py` 的最终 SHA-256 为
`749f44ae1cc1748d87cafd66e41b87ef36d0f5c60e4df0b8f392a22a3edee000`。它增加两条
独立、固定消息且 `exc_info=False` 的限流 WARNING：

- `plot.locator.legacy_interval_api_fallback`：旧版 Matplotlib locator 的 interval API
  不可用时，改用 axis interval API 后返回 locator；
- `plot.locator.axis_interval_sync_recovery`：axis interval 同步也失败时，保留已创建的
  locator 并返回。

两条回退均不写入捕获异常载荷或 traceback；各自使用独立的稳定 key，避免不同兼容
路径共享限流计数。

## 定向运行证据

以下命令针对冻结后的行系统、能力 guard 和 locator 回退独立执行：

```bash
/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python \
  -m pytest -q \
  tests/unit/core/test_linebuffer_logging_recovery.py \
  tests/unit/core/test_linesystem_logging_recovery.py \
  tests/unit/plot/test_locator_logging.py
```

结果：**59 passed in 5.93s**。范围包含预期协议探测的静默、恢复值保留、异常载荷
脱敏和 250 次重复异常的有界输出；其中 locator 用 Agg 后端对两条回退各执行 250 次，
断言独立 key、固定消息、无 traceback、每 key 三条限流记录和可用 locator。它不替代
完整功能、性能或文档门禁。

## 兼容性边界

`lineroot._apply_strategy_patch` 与 `lineseries._patch_strategy_clk_update` 保留了
模块导入时动态重补 `Strategy._clk_update` 的历史兼容闭包。其实际附着取决于导入
顺序；定向测试通过手动重补受控的 Strategy 目标来覆盖这些闭包。因此这里证明的是
相应路径的日志与回退行为，不证明每一种外部导入顺序最终启用哪一个时钟实现。

## 历史证据与剩余门禁

[logging-exemptions.json](logging-exemptions.json) 和
[logging-exemptions.md](logging-exemptions.md) 中关于这四个文件的旧 hash、行号和
分类现在均为历史快照；本记录明确取代它们作为四文件的当前源码证明，并补记 locator
兼容回退。此前完整功能套件、串行/配对性能、质量和文档构建均早于最终 logger 修复，
不可用于证明当前快照。

下列门禁仍为 `PENDING`，必须在源码冻结后重新执行并绑定最终精确提交：

- 含公开 SDK 和不含 SDK 的完整功能套件；
- 串行性能与前后配对比较；
- 文档构建；
- wheel/sdist 与树外消费者；
- `dev` 到 `development` 的提升、远程 CI、tag 与 Release。

`master` 保持 **NOT_TOUCHED**。
