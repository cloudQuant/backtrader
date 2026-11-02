# I52-A：Cerebro 启动失败清理源码小轮

日期：2026-10-30。仓库 `D:/source_code/backtrader`、分支 `dev`，本轮父提交 `8c2e4a83329a1f6f20634b32aace1ca2a971d847`。本轮提交哈希由包含此记录的 Git 历史确定。范围为普通 `runstrategies` 启动失败时的尽力清理及定向测试；不改 channel 路径，不改变成功路径的调度或原 `_prepare_run(self, predata=False)` 签名。

- 启动尝试按本次 run 独立记录。失败时按现有生命周期顺序尝试停止已触及资源，保留原异常；清理异常与未确认的所有权、未完整启动策略、外部 owner 和无 stop 接口的 timer 等边界记为不完整。feed ownership 不确定时不强行双重停止。
- 新增定向启动失败测试及签名兼容检查：16 passed，0 skipped，1 条 pytest 配置警告。嵌套两个真实 Cerebro 实例并在失败后再次运行，检查资源事件不串线；本项不证明线程并发或真实外部资源清理。
- 既有普通 Cerebro/loop 15 项、Feed/Strategy 7 项、非 channel runstop 7 项、非 channel logging 10 项通过；各批次使用 Python 3.11 和 `-p no:asyncio`，均有 1 条已存在的未知配置项警告。源码编译、Ruff 与 diff whitespace 检查通过；独立源码审阅给出限于 best-effort startup cleanup 的 GO。
- 将已安装 runtime wheel 与本轮 Backtrader 源码候选、合同包及 SDK base 本地源码组合，25 passed、1 条 Quandl 弃用警告。该检查不涉及真实 provider/账户，不是完整安装、paper 账户或 live 写入验收。

此轮不能保证所有资源物理关闭：未完整返回 `_start` 的 Strategy 不会被强行 `_stop`；`Strategy._stop` 可能吞掉 observer stop 异常，因此存在 observer 时其结果保守标记为不可观测，并不代表已观察到失败。若清理协调器自身异常，原启动异常仍保留，但结构化不完整记录可能无法写入。线程并发及真实账户资源清理未验收；不改变任何正式 case 状态，也没有运行 replay、shadow 或旧本地撮合。
