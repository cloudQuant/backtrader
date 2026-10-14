# 最终报告与资源关闭顺序

2026-10-14，迭代10第07轮 B 的服务读取集成暴露了既有收尾顺序问题：
Cerebro 先停止 Broker，再通过 `Strategy.getwriterinfo()` 读取净值。
生命周期严格的 Broker 会拒绝此时的访问，且报告错误可能覆盖原始运行错误。

现在策略停止后，Cerebro 在 Broker、Data、Feed 和 Store 仍可读取时调用
原有 `stop_writers(runstrats)`。保留动态方法分派和自定义报告逻辑。
报告失败也会进入原资源停止流程；已有运行错误优先于报告错误。
默认 `stop_writers` 会尝试停止全部 writer，并保留首个报告或关闭错误。

自定义 writer 的 `writedict()` 和 `stop()` 现在早于 Broker/Feed/Store 的
`stop()`。依赖旧先后顺序的扩展需要相应调整。某个非 writer 资源自身的
`stop()` 失败仍可能中断后续停止，这是保留的既有行为，本轮没有扩展它。

Root 定向检查 `tests/test_service_writer_lifecycle.py`：4 passed，3.41秒，
1条既有 pytest 配置警告。使用真实 Cerebro、内存 Data、严格 BackBroker
和内存 Writer，覆盖最终净值读取、策略报告失败、writer 写失败、运行首错保留，
并检查正常资源清理。首次4项因合成 Store 缺少通知接口而失败；补齐该接口，
并修正 Writer 测试子类的递归处理后通过。没有放宽生产读取条件。

交付仓库为 Backtrader 现有 dev，父提交为
`4370013d35a3efef5a26689de1322048121bcd60`；本文件的 Git 历史给出提交 SHA。
精确范围是 execution.py、本轮测试和本记录。此轮为本机核心生命周期检查，
不证明 Gateway、真实账户、完整服务集成或 BT01/BT02 验收通过。
