# 2026-09-08 v7 构建、重装与消费收据

> 状态：`G3_ARTIFACT_CONSUMER_PASS`
> 范围：`bt_api_py.cross_venue`、既有 `BtApiStore`/`BtApiFeed`/`BtApiBroker`、012_1、012_2
> 不包含：公开网络、私有账号读取、模拟订单、收益或实盘准入

## 1. 来源与候选绑定

| 项目 | 值 |
|---|---|
| Backtrader branch / HEAD | `codex/iter21-cross-venue-arbitrage` / `ab1ae150f73199fbd64449eb7c43fd1f45a29c5d` |
| bt_api_py branch / HEAD | `codex/iter21-cross-venue-arbitrage` / `2be8dbc25b0f49f4734ad337fcd7abe53840c3b9` |
| candidate manifest SHA-256 | `ace39424097ad7667034b0cac7feaeeebc7dbe25ba1b37ec3c30be6ccaf96f94` |
| candidate state | `RESEARCH_REJECTED_DEMO_PROHIBITED` |

两个 checkout 均已有非本任务的工作树改动。本次没有 reset、checkout、rebase 或覆盖任何
未列入本迭代的文件；上述 HEAD 是构建时的提交基线，candidate manifest 与 wheel hash 才是
本次制品的内容标识。

## 2. v7 制品

所有 wheel 在同一 epoch 使用用户 Anaconda base 的 Python 构建，并保存在本机 ignored 目录
`.git/iter21-evidence/2026-09-08-cross-venue-layer-v7/wheels/`。

| wheel | SHA-256 |
|---|---|
| `backtrader-1.3.0-py3-none-any.whl` | `689146eb2acb084b2787af5e25de8b61c31697b575c6f5232ab27819200c4621` |
| `bt_api_base-0.15.3-py3-none-any.whl` | `8588d39a6ab9c764e9651415a76f9a0b4afab044d34b5b8aa4e118a140543bf0` |
| `bt_api_binance-2.0.1-py3-none-any.whl` | `fe06015439c172bab28f767c0d562910216b0e8a112be5603f4e1cb046b34e6b` |
| `bt_api_okx-0.15.4-py3-none-any.whl` | `13689d0db1820f96fc8c3ff0bc6a3e3bb6af9df42f3401b92d4a670fb89f345a` |
| `bt_api_py-0.15.3-py3-none-any.whl` | `f5e4ceb8442f06d13f231bad05adc06138d1b7a614161ac496216fa1269f7ded` |

构建前曾发现一个必须拒绝的 v5 制品：其 `build/lib` 残留使 wheel 仍包含
`backtrader/utils/cross_exchange.py` 与 `demo_approval.py`。该制品没有用于验收。删除两个
已退役的**生成目录副本**后，后续 wheel 已不包含这两个模块。v7 还吸收了 SDK 顶层 export
的 lint-only import 排序修复，因此取代 v6 成为当前收据。

`unzip -l` 已验证 v7 包含 `bt_api_py/cross_venue.py` 与
`backtrader/stores/btapistore.py`，并不包含两个已退役 Backtrader utils 文件。

## 3. 重装与隔离消费

Anaconda base 以 `pip install --force-reinstall --no-deps` 重装上表五个 wheel；`--no-deps`
避免改变不属于本迭代的环境依赖。另以 `pip install --target` 安装到全新目录，并从 `/tmp`
执行验证。

| 检查 | 结果 |
|---|---|
| 隔离 target 导入 | `PASS`：`backtrader`、`bt_api_py`、`bt_api_py.cross_venue` 均来自 isolated-site |
| base site-packages 导入 | `PASS`：三个模块均来自 Anaconda base 的 `site-packages`，不来自两个源码 checkout |
| 公共 API | `PASS`：`CrossVenueLeg`、`InstrumentSpec` 可从 `bt_api_py` 顶层导入 |
| 退役模块 | `PASS`：`find_spec('backtrader.utils.cross_exchange')` 与 `find_spec('backtrader.utils.demo_approval')` 均为 `None` |
| 012_1 repo 外 replay | `PASS`：`FORMULA_CHECK_PASS`、`orders_submitted=0`、`fills=0`、`execution_status=NOT_RUN` |
| 012_2 repo 外 replay | `PASS`：`FORMULA_CHECK_PASS`、`orders_submitted=0`、`fills=0`、`execution_status=NOT_RUN` |

两个 replay 的 `research_status` 都是 `RESEARCH_REJECTED`。它们验证的是打包后的公式/拒绝
路径，不代表模拟盈利、真实成交或可提交订单。

## 4. 回归与 fail-closed 准入

| 环境 | 命令范围 | 结果 |
|---|---|---|
| bt_api_py 源码 | `tests/bt_api_contract` | `559 passed` |
| Backtrader 源码 + bt_api_py 源码 | Store、Feed、Broker、native replay、candidate approval、两策略、成本 oracle、模式矩阵、性能路径 | `727 passed` |
| 已安装 Backtrader + 已安装 bt_api_py | 同一相关集合，`BACKTRADER_USE_INSTALLED=1` | `727 passed` |

安装态的 candidate approval 测试还验证一个故意的 fail-closed 分支：普通本地 wheel 没有可验证的
Git build attestation 时，`collect_runtime_source_provenance()` 会拒绝为 demo 收据背书，而不会
猜测源码提交。这不影响无网络 replay；它阻止任何未来的 demo receipt。当前候选本来就因研究
否决而禁止 demo 写入。

## 5. 结论与边界

G3 的“源码到 wheel 到消费端”门为 `PASS`。它只证明这次五个制品的安装、公开接口、退役模块
移除和零写 replay 一致；它不关闭 G1 的独立终审、G2 的真实 funding cashflow、G4 公开网络、
G5 模拟写单或实盘门。任一新 package 源文件变更都必须生成新的 wheel epoch，不能复用本收据。

两个 dirty checkout 的完整 `status --short`、tracked `diff --name-status`、`diff --stat` 和本次
task-owned scope 已保存在同一 ignored evidence 目录；该快照明确保留未归属到本迭代的改动，
没有通过 reset 或清理工作树来制造“干净”结论。
