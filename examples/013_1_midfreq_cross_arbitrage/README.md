# 013_1 中低频跨品种套利（豆粕 m / 菜粕 RM）

> **历史 direct SimNow 已退役**：`run.py` 现在是 config-first 兼容入口；不带参数时只会转到本目录已登记的
> `runtime/config.yaml` replay 路径，缺配置返回 `CONFIG_REQUIRED`。历史 `--replay`、`--config`、
> `--mode` 等参数一律以 `legacy_cli_arguments_not_supported` 拒绝，`run_live()` 也以
> `legacy_direct_live_not_supported` fail-closed。它们均不构成 SimNow、live 或受管执行入口。
> 原 runner 的已知缺陷仍见迭代23 基线 B03（`_limit()` 盘口缺失回退 close、按品种前缀猜平仓 offset、
> 订单超时依赖数据时钟）与迭代26 验收报告 A8/A10；处置决策见
> [ADR-013-legacy-reference](../../docs/_internal/opts/requirements/迭代26-迭代20-21-22验收/ADR-013-legacy-reference.md)。

## 迭代 41：最简且受控的本地回放

从仓库根目录操作。推荐的首次创建与运行路径只有两条命令：

```powershell
bt-runtime bootstrap --strategy-dir examples/013_1_midfreq_cross_arbitrage/runtime
bt-runtime run --strategy-dir examples/013_1_midfreq_cross_arbitrage/runtime
```

`bootstrap` 只会首次创建 `runtime/config.yaml`，已有文件会以 `CONFIG_EXISTS` 拒绝而不会覆盖。首次建立配置始终使用上述 `bt-runtime bootstrap` 命令，避免从模板手工复制到错误目录；受版本控制的 `runtime/config.example.yaml` 只供审阅，不是运行时回退来源。

`runtime/config.yaml` 是必填的 schema-v4 启动合同；缺失时会以 `CONFIG_REQUIRED` 拒绝，绝不从模板、
当前目录或父目录回退读取。当前受审核的代码清单只为本目录登记
`runtime.mode: simulation` 与 `runtime.preset: replay`，并只允许 `parameters.scenario`。模式和预设由
该文件及中央代码清单共同封存，命令行、环境变量和旧配置都不能覆盖它们。

该入口执行 code-owned `run_runtime.py`，定向测试证明本地 replay 不访问网络、不构造 provider、也不产生
外部订单写入。它只是 `LOCAL_REPLAY_ONLY` 的合成 tick 回放，不是 SimNow、实盘、受管执行、成交或盈利准入。

日常请使用上述 `bt-runtime` 命令。为了防止旧自动化的无参数调用直接进入 SimNow，`python run.py`
只会转到同一个已登记的 config-v4 replay 路径；它读取 `runtime/config.yaml`，不读取旧根目录
`config.yaml`，也不接受历史 CLI 参数。受控壳在配置检查通过后才复用冻结的本地 replay fixture。

## 历史策略说明（非 Iteration 41 启动指南）

留档的历史三件套为 `strategy.py`（策略逻辑）+ 根目录 `config.yaml`（旧参数）+ `run.py`（现为安全
兼容壳）。根目录参数文件不是 Iteration 41 启动合同，不能选择运行模式、凭据或写入权限。
策略信号完全复用 Backtrader 框架能力：`bt.indicators.SpreadZScore`
（本迭代新增于 `backtrader/indicators/spread.py`）在 `next()` 中给出双腿价差
z-score；限价参考 `notify_tick` 缓存的买卖一档。已退役的历史 SimNow 接线曾复用
`examples/007_ctp/ctp_example_support.py`，不属于当前可执行路径。

- 标的：m 主力 × RM 主力（`run.py` 按交割月历自动识别，郑商所三位代码如 `RM701`；
  `--symbols` 或 yaml `symbols` 可覆盖）
- 信号：价差 z-score 突破 ±2σ 开仓（三次确认、间隔 5s），回归 0.5σ/超时 30min/亏损平仓
- 执行：逐腿顺序限价 IOC；先空腿、按第一腿实际成交量提交多腿；裸腿立即反向平掉；
  平仓 offset 按交易所规则（上期所 `close_today`，大商所/郑商所 `close`）

历史 `run.py` 的 replay/SimNow 命令及其参数不再是可执行接口；它们会在配置加载、框架或 provider 导入前
被拒绝，不能作为 Iteration 41 的模式控制或写入保障证据。

每次运行都会挂载通用的 `bt.observers.TradeLogger`：它实时汇总订单、成交、持仓、资金和
事件计数，并在结束时冻结报告；本策略只以 `pair_arbitrage` 扩展补充配对状态、风控和业务
字段。运行中可调用 `strategy.stats.trade_logger.snapshot()` 查看该扩展；策略只从 broker 的
本地 `get_cached_report_state()` 读取持仓和资金，不会因生成报告刷新 CTP 账户。最终 JSON 同时
保留完整 `trade_logger` 遥测，并给出排除该易变遥测和进程全局订单引用的
`business_summary` 与 `business_summary_hash`，可用于等价 replay 的稳定比对。发布失败后重试按
最近一次尝试的 tick 水位节流；若停止时最后成功快照之后仍有发布失败，runner 会拒绝该陈旧扩展。
报告写入 stdout；合成回放不构成盈利证据，历史 SimNow 记录也不能构成盈利或准入证据。
