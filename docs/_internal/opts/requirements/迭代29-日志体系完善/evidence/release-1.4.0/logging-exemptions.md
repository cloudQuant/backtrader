# 迭代29异常日志豁免逐项复核

> **四文件范围已被后续修复取代。** 本文中的 `backtrader/linebuffer.py` 与
> `backtrader/lineiterator.py` 源码 hash、行号和逐项分类对应较早工作树；
> `backtrader/lineroot.py` 与 `backtrader/lineseries.py` 则不在原始源码绑定表中。
> 对四个行系统文件的当前源码、AST 计数、恢复语义、locator 兼容回退和 59 项定向证据，只能使用
> [line-system-logger-remediation.md](line-system-logger-remediation.md) 及其
> [JSON](line-system-logger-remediation.json)。本文对其余文件仍保留为历史静态豁免
> 复核，不能作为最终候选的完整测试或发行证明。后继记录还补记了独立的
> `plot/locator.py` 兼容回退。

当前扫描核对 **23 个未 logged 的 broad Exception**：7 个热协议探针、4 个 SDK 诊断/脱敏保护、12 个日志内部保护。原先的22项因安全关闭 helper 新增1项变为23项。

未 logged 的 pass/continue/raise 共32项，其中14项已经包含在 broad 清单；额外窄异常18项，合计41个不重复处理点。此处没有把“多语句 handler”当作豁免理由。

本轮只读源码并生成证据，测试为 NOT_RUN；既有回归由主任务汇总。JSON 保存每项完整理由、可观察性、函数、精确行号、源码 SHA-256 和 except 源片段。

## Broad Exception 逐项清单

| 位置 / 函数 | 具体理由 | 已有可观察性 |
|---|---|---|
| backtrader/brokers/btapibroker.py:46 / _safe_log | 日志器或脱敏步骤已经失败，再次向同一日志器写入会让异常逃逸，阻断经纪商的原控制流 | _LOGGING_HEALTH['logging_errors'] 增一；BtApiBroker.get_logging_health() 可读取。 |
| backtrader/feeds/btapifeed.py:32 / _safe_log | 保护行情回调免受日志器或脱敏失败影响 | _LOGGING_HEALTH['logging_errors'] 增一；BtApiFeed.get_logging_health() 可读取。 |
| backtrader/linebuffer.py:2324 / LinesOperation._operand_value | 操作数未实现可用长度时，仅跳过可选 minperiod 长度保护 | 返回实际操作数值；若后续取值本身失败，异常不由本段吞掉。 |
| backtrader/linebuffer.py:2351 / LinesOperation._next_operand_if_due | clock 或 operand 不支持可比长度时，不能判定已经推进，因此沿原协议调用 operand._next() | 后续 _next() 的推进效果和异常仍对调用方可见；无独立日志或计数。 |
| backtrader/linebuffer.py:2440 / LinesOperation._next | LinesOperation 的可选时钟去重探针失败时，继续原有操作数推进、advance、next 与绑定更新 | 运算线和 bindings 的值仍更新；后续执行失败不在此 except 内。 |
| backtrader/lineiterator.py:95 / _lineaction_source_clock.finish | 对象使用 __slots__ 或禁止写属性时不能保存时钟缓存 | 返回已解析的 source clock；不支持缓存仅影响后续重新解析，没有单独错误计数。 |
| backtrader/lineiterator.py:1916 / LineIterator._next | 数据和时钟没有可比长度时跳过去重判断，继续 data._next() | 数据继续推进，后续 _next() 的异常和结果保持可见。 |
| backtrader/stores/btapistore.py:85 / _redact_diagnostic | 无法安全复制未知供应商对象时只返回类型名称 | 调用方收到安全的 type(value).__name__ 替代值；无专门失败计数。外层 _safe_log 对诊断失败另有计数。 |
| backtrader/stores/btapistore.py:94 / _safe_log | 日志器或脱敏步骤已经失败，重复记录会把观测故障带入 Store 的命令、行情或风控控制流 | _LOGGING_HEALTH['logging_errors'] 增一，并进入 Store 命令健康报告 logging_errors 字段。 |
| backtrader/strategy.py:665 / Strategy._next_strategy_lineactions | 已到当前时钟位置但缓冲区此索引尚未就绪时，跳过当前 LineAction | 本次不推进该 LineAction；250 次空缓冲回归断言推进次数为零且无日志。 |
| backtrader/strategy.py:675 / Strategy._next_strategy_lineactions | 直接挂在策略上的 LineActions 无法进行时钟或值比较时，沿既有路径回退 lineaction._next() | 后续 _next() 保持执行；250 次时钟不可比回归检查推进次数。该宽捕获的既有范围包含比较与 lineaction.next()，本轮未缩改其业务语义。 |
| backtrader/utils/log_message.py:84 / _warn_once | 固定、脱敏的最后一级 stderr 诊断本身失败 | 调用前 _warned_failures 已登记 key；stderr 成功时每 key 一次，stderr 也失败时不保证外部可观察。 |
| backtrader/utils/log_message.py:183 / _remove_managed_handlers | 重新配置移除 handler 后，关闭可能已关闭或故障的资源属于尽力清理 | logger 已移除该 handler，继续处理其余托管 handler；无独立关闭失败计数。 |
| backtrader/utils/log_message.py:194 / _close_handler_safely | handler.close 失败不得替换原配置异常，也不得在新 handler 已安装后阻断 level/backend/config snapshot 提交 | _warn_once('handler_close', 固定文本) 提供至多一次 stderr 提示；调用方继续清理或提交配置，提示不包含 handler 或异常载荷。 |
| backtrader/utils/log_message.py:330 / configure_logging | 新 handler 构建失败时不应使用尚未安装的日志链重复报告 | 原配置异常通过 bare raise 传播；pending handler 逐个经 _close_handler_safely 清理，单个关闭故障不替换原异常，也不阻止其余清理。 |
| backtrader/utils/log_message.py:507 / _mp_log_suffix | multiprocessing 模块或 parent_process 查询在退出期不可用时，进程识别不应破坏日志关闭 | 返回空 suffix 作为最终兼容回退；没有错误计数。不能据此声称异常环境下仍保证 spawn 文件隔离。 |
| backtrader/utils/log_message.py:567 / _cleanup_retention | 过期目录清理是附属维护任务，删除失败不应停止回测 | _warn_once('retention', 固定文本) 至多提示一次，_RETENTION_WARNED=True；不输出路径载荷或原异常。 |
| backtrader/utils/log_message.py:620 / _DailyLevelFileHandler.emit | stdlib split handler 轮转或写入失败时不能让异常进入交易回调 | _NonFatalHandlerMixin.handleError -> _warn_once('write', 固定文本)，最多一次 stderr 提示；不输出原 record/traceback。 |
| backtrader/utils/log_message.py:664 / _detect_spdlog | 可选 spdlog 的导入、能力和临时写入探针允许失败，返回 None 交给配置入口决定降级或拒绝 | backend='auto' 在 configure_logging 发一次固定降级提示并选择 stdlib；显式 backend='spdlog' 抛 ImportError。 |
| backtrader/utils/log_message.py:730 / SpdlogHandler.emit | spdlog 后端轮转、格式化或写入失败时交给 handleError | _NonFatalHandlerMixin.handleError -> _warn_once('write', 固定文本)，最多一次 stderr 提示；原载荷不进入故障提示。 |
| backtrader/utils/log_message.py:752 / SpdlogHandler.flush | spdlog 的 flush 发生在受锁保护的关闭/刷新流程 | 锁在 finally 释放，调用正常返回；无独立失败计数或落盘保证。 |
| backtrader/utils/log_message.py:765 / SpdlogHandler.close | spdlog 的 flush/drop 是尽力资源回收 | Handler 关闭状态与锁释放继续完成；无独立失败计数，不保证失败的原生 drop 已完成。 |
| backtrader/utils/log_message.py:780 / flush_all | flush_all 对每个框架托管 handler 做尽力刷新 | 继续刷新后续 handler；无独立失败计数，也不保证故障发生时数据已持久化。 |

## 额外窄异常

完整18项逐行列在 JSON 的 narrow_classifications：

- cancellation：2 项。
- cleanup_reraise：1 项。
- constructor_dispatch：1 项。
- narrow_protocol：3 项。
- optional_discovery：2 项。
- optional_import：3 项。
- structured_drop：2 项。
- structured_validation：4 项。

可选依赖通过能力标志或带说明的 ImportError 暴露；CancelledError 清理 pending/授权后继续传播；验证与行情丢弃进入 errors 或 _record_market_drop；VisualChart 注册表探针返回路径或空字符串（format_exception 的结果并未输出，不能算日志）。

## 配置清理发现及闭环

LOG-EX-01：原 configure_logging 的回滚/替换关闭调用可能让 close 故障覆盖原错误或阻断状态提交。已核对日志 owner 的 _close_handler_safely 修复，两处都经该 helper 关闭；helper 只发一次固定 stderr 提示。新增异常分支已纳入本表。执行结果单列于主任务测试证据。

## 源码绑定

| 文件 | SHA-256 |
|---|---|
| backtrader/bokeh/tab.py | 5141ca7a5b54a43ea0d6183abd62b654c8c785bac55ee50de32492dc11c43c38 |
| backtrader/brokers/btapibroker.py | 9a413b8c4dee3db3f7e825424246ba37f5d68c6fa97e4623b22dee737a0d524a |
| backtrader/feeds/btapifeed.py | 5e4832c355009e01805255e210751ffeb06b4e38374ea0cafcf24ed4d56f3f52 |
| backtrader/feeds/yahoo.py | d833d420b802a9a13434b8b554903839354896541f828ad6792f76a0d8e68289 |
| backtrader/linebuffer.py | 25c6c6eccd3bcd8b52eb83fbb79eb7d77cb43f108a7e3de901ba02759aa5efb4 |
| backtrader/lineiterator.py | c43e277f6d74296dc32ef6d79dd382ff11c653019835f1d281eb0a305bd480a1 |
| backtrader/metabase.py | d28e098e66891b0a9cd55e3857030e23d24f1df5cfb80371d9a666bfcb865a8d |
| backtrader/plot/__init__.py | 2810c46ddcb78c411770a53998a96abba4cd71ff87ee6bbb092e04d63398bb97 |
| backtrader/stores/btapistore.py | d2cb0234ca2ad45ff4385083349269be4b8a52bf5d6d40616d0b4497efaa11c6 |
| backtrader/stores/vchartfile.py | 799568271be111b450c1e725f10981ce79e25a85950f493b47c5e3a9817e2e0f |
| backtrader/strategy.py | 44226caca3cee9238bc01ad6fc9838fc8f52d1668bf529c5ac29c373833a38f8 |
| backtrader/utils/log_message.py | cc9aa513ea9a9f4ecf0f41832c20ae2ef3242f0f7a89437f0489c8c1239bacc7 |

完整机器可读记录：[logging-exemptions.json](logging-exemptions.json)。原始 M0 基线未覆盖。
