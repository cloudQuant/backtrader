# I52-A：Observer 启动清理诊断

日期：2026-10-31；仓库 `D:/source_code/backtrader`，分支 `dev`，本轮父提交 `b87e613fc`。本轮提交哈希以 Git 历史为准。

普通 Cerebro 启动失败后，对已完成启动的 Strategy 执行已有 `_stop()` 清理。observer 的 `stop()` 异常原本由 Strategy 记录日志后抑制，协调器不能识别具体失败。本轮仅在同步启动清理期间记录 observer 异常阶段、类型和 traceback 位置，不记录异常消息；清理仍继续，原启动异常保留。该上下文中的 observer 错误日志不输出异常内容，普通顶层运行的原有日志和抑制行为不变。捕获以 Strategy 身份和 ContextVar 隔离嵌套运行。

验收：作者定向测试 17 passed、Ruff 通过；Root 在 Python 3.11 下组合运行启动清理、Cerebro loop 和 Strategy 初始化测试，46 passed、1 条现有 pytest 配置警告。独立静态审阅为普通同步 startup cleanup 范围内 GO。测试使用本地源码和合成组件，不证明线程并发、真实账户或 provider 资源清理，也不增加正式 case 通过数。

未完整返回 `_start()` 的 Strategy 仍不强行调用 `_stop()`：目前没有完整的子组件启动账本，不能安全区分未启动、半启动或已停止的资源。协调器自身故障仍可能无法留下结构化不完整记录。自定义线程不自动继承本清理上下文；Strategy 普通运行既有异常日志行为仍可能包含异常信息。本轮不声明所有资源已关闭或 I52-A 生命周期合同已接受。