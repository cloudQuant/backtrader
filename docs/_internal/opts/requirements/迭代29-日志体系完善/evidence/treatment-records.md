# 迭代 29 实现轮处置记录（M3/M4）

日期：2026-09-15；基线 dev `404383b7`；治理工具：`../treat_silent_excepts.py`（AST 定位、从后向前插入、控制流零改动）。

## 1. except 静默治理（FR29-04）

AST 口径（`../m0-catalogs/summary.json`）：pass 151 / continue 48 / raise 86 / 未 logged。治理规则：
单语句静默体（body 仅一个 pass/continue/raise）插入日志；多语句体（已有处理逻辑）保留不动；
raise → `logger.error(..., exc_info=True)`；窄探测类型（KeyError/AttributeError/IndexError/TypeError/
ValueError/UnicodeDecodeError/OverflowError/InvalidOperation/StopIteration）→ debug；其余 pass/continue → warning。

| 批 | 文件 | 插入数 | 验证 |
| --- | --- | --- | --- |
| P0 | stores/btapistore.py | 27 | tests/unit/stores + tests/unit/brokers 1,116 项全绿 |
| P0 | brokers/btapibroker.py | 22 | 同上 |
| P1 | lineiterator 37 / lineseries 25 / metabase 9 / linebuffer 9 / parameters 5 / lineroot 4 | 89 | tests/unit 3,225 passed + 1 flaky（下述） |
| P2 | 34 个文件（trade_logger/functions/strategy/feeds/bbroker/_cerebro 等） | 91 | observers/utils/integration 115 项全绿 + import 冒烟 |

合计插入 229 行；17 个缺 logger 的文件补充了模块级 `logger = get_logger(__name__)`。

**豁免清单（except 治理，3 处）**：`plot/__init__.py`（包入口，避免 light-import 链新增导入）、
`bokeh/tab.py`（可选后端同理）、`utils/log_message.py` 自身 `_remove_managed_handlers` 的
handler.close 兜底（已有 nosec 注释，日志重配置期递归风险）。

**剩余静默点**（`../m0-catalogs-after/summary.json`：pass 6 / continue 15 / raise 38）：均为多语句体
（已有实质处理）或上述豁免，逐条保留原状的理由 = 已有处理逻辑 / 豁免声明。

**多语句体跳过说明**：治理工具 `len(node.body) > 1: continue`——body 除目标语句外还有实际
处理（赋值/通知/重试等）的 except 不属于"静默吞异常"，插入重复日志反而制造噪声。

## 2. 级别语义修正（FR29-07）

40 处 error-semantic debug（消息含 Failed/Error/Exception/invalid）批量升级 debug→warning，
分布：reports/performance 11、_cerebro/channel 4、lineroot 3、feed 2、bokeh/tabs 4、
plot 2、pandafeed 2、trade_logger 2、reports/charts 2、其余 8 文件各 1。
配套测试合同变更：`tests/unit/analyzers/test_leverage_logreturns_edge_cases.py` 8 项断言
`mock_logger.debug` → `mock_logger.warning`（该文件即断言"无效输入以 debug 记录"的旧行为，
正是 FR29-07 判定的错误降级；断言更新逐条对应上述升级点，18 项全绿）。

## 3. print 治理（FR29-08）

AST 口径 48 处真实调用。治理：`observers/trade_logger.py` 10 处 error-semantic print
（MySQL 写入失败、next() 异常等）→ `logger.warning/error`（Error→error，其余→warning）。

**豁免清单（print，34 处）**：`reports/reporter.py` 18（CLI 报表用户输出）、`btrun/btrun.py` 12
（CLI 交互）、`utils/autodict.py` 2（`__main__` 演示块）、`analyzer.py` 1（`Analyzer.print()`
公共 API）、`strategy.py` 1（`Strategy.log()` 用户 API 输出）。

## 4. 口径差异说明（M0 vs 需求文档近似口径）

需求文档第 2 节 grep 近似（except ~1,245 / print 116）与 AST 精确（1,107 / 48）差异原因：
grep 按行匹配含注释、docstring 示例与字符串字面量；AST 仅统计真实调用节点与异常处理器。
m0-catalogs-before/after 两套 JSON 均可由 `scripts/scan_logging_baseline.py` 再生。

## 5. 已知 flaky（非本轮引入）

- `tests/unit/test_iteration22_ctp_benchmarks.py::test_short_stress_profile_waits_for_deadline_and_is_incomplete`：串行全量下失败，隔离复跑通过（timing 敏感）。
- `tests/unit/stores/test_btapistore_iteration21.py::test_cancel_unknown_query_live_allows_retry_but_blocks_new_opening` 与 `tests/unit/stores/test_btapistore_funding_refresh.py::test_restart_fences_...`：`-n 8` 并行下偶发失败，隔离复跑通过（AGENTS.md 已记载的并行 flaky 类别）。

## 6. 质量门禁（改动文件 53 个）

black --line-length=100：全过（重排仅涉及本轮插入行的折行/空行，与 HEAD 对比确认无无关重排）。
ruff：HEAD 基线全绿；本轮引入的 155 项（PIE790 冗余 pass、datahandler F821、log_message B006/E402）
全部修复后归零。bandit：log_message.py 4 处 B110 加 nosec 说明（teardown 防御）。mypy
log_message.py：HEAD 基线 0 错；本轮引入 7 项修复后 0 错。

## 7. 第二阶段：宽异常捕获治理（用户追加需求，2026-09-15）

第一阶段只覆盖单语句静默体；多语句回退体（`except Exception: x = fallback` /
`return default`）中无 logger 调用者仍是盲区。AST 复扫：**192 处**宽异常捕获
（Exception/BaseException/bare）且 body 无日志。工具：`../treat_broad_excepts.py`。

分级规则（吸收第一阶段协议探测教训）：
- body 含 `raise` → `logger.error(..., exc_info=True)`（上抛前可见）；
- 行系统/构建管线核心（linebuffer/lineiterator/lineseries/lineroot/metabase/
  parameters）→ `debug`（可能为高频探测回退，避免 error/warning 刷屏与开销）；
- 其余（btapi/store/feed/broker/plot/bokeh/trade 等外部 IO 路径）→ `warning`；
- 插入位置：handler body 首语句前同缩进，控制流零改动。

结果：插入 **184 行**（192 − 豁免 8 处 `utils/log_message.py` 自身防御）；5 个新触碰
文件补模块级 logger（bokeh/tabs/analyzer、hft/binance_bbo、plot/__init__、plot/locator、
trade——plot/locator 的多行括号导入内误插已修正）。

**运行时豁免修正（2 处，重要）**：`btapistore.py:90 _safe_log` 与
`btapibroker.py:42 _safe_log` 是"logger 故障兜底"路径——测试
`test_logger_sink_failure_only_increments_health` 模拟 sink 抛异常并断言仅递增
`logging_errors` 计数；插入的 fallback 日志会在计数前再次抛出。该两处回退插入并
加注释说明"logger 自身故障路径禁止再调 logger"（与 log_message.py 豁免同理）。

治理后终态（`../m0-catalogs-after2/summary.json`）：未 logged 的 pass 6 / continue 9 /
raise 6（豁免与 `_safe_log` 类），logged 607；error 级调用 80、warning 256。

验证：btapi/observers/utils/integration 1,231 项全绿（含 logger sink 测试）；
`make test-fast` 4,645 passed（exit 0，本轮无 flaky）；`make test-strategies`
1,271/1,271；black/ruff/py_compile 全过；import 冒烟（plot/bokeh/trade）通过。
