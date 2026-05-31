# 测试覆盖率基线 (Coverage Baseline)

> 创建于 2026-05-31（R2-S5）。这是**非策略子集**的覆盖率快照，用于防止后续 PR
> 大幅拉低覆盖率。策略回归套件（`tests/functional/strategies/`，1000+ 用例）单独
> 计量、不计入此基线（运行成本高，且本基线的目的是守住「核心库 + 单元/功能测试」
> 这条快速反馈线）。

## 度量命令 (Measurement Command)

```bash
pytest tests --ignore=tests/functional/strategies \
  --cov=backtrader --cov-report=term-missing -n 8
```

- 测试规模：**1,746 passed / 1 skipped**
- 度量日期：2026-05-31
- 配置：`pyproject.toml [tool.coverage.run]`（omit tests/crypto_tests/setup.py）

## 总览 (Summary)

| 指标 | 值 |
| --- | --- |
| **总行覆盖率（非策略子集）** | **60%** |
| 总语句数 | 31,771 |
| 未覆盖语句 | 12,654 |

> 注：策略回归套件会覆盖大量 indicators/lineseries/strategy 路径，故**完整套件**
> 的真实覆盖率显著高于 60%。此 60% 仅为「非策略快速线」的保守地板。

## 核心模块覆盖率 (Core Modules)

| 模块 | 语句 | 未覆盖 | 覆盖率 |
| --- | --- | --- | --- |
| position.py | 90 | 0 | **100%** |
| position_modes.py | 70 | 0 | **100%** |
| sizer.py | 14 | 0 | **100%** |
| comminfo.py | 244 | 20 | 92% |
| trade.py | 115 | 15 | 87% |
| observer.py | 22 | 3 | 86% |
| parameters.py | 814 | 158 | 81% |
| order.py | 325 | 70 | 78% |
| analyzer.py | 198 | 43 | 78% |
| signal.py | 9 | 2 | 78% |
| strategy.py | 1221 | 287 | 76% |
| feed.py | 570 | 157 | 72% |
| cerebro.py | 945 | 272 | 71% |
| indicator.py | 192 | 68 | 65% |
| linebuffer.py | 1362 | 527 | 61% |
| lineseries.py | 1082 | 448 | 59% |
| lineroot.py | 474 | 223 | 53% |
| lineiterator.py | 1311 | 681 | 48% |
| metabase.py | 845 | 447 | 47% |

> 说明：line 系统（lineiterator/lineroot/lineseries/linebuffer/metabase）覆盖率
> 偏低，是因为其大量分支只在**策略实际运行**（runonce/runnext 多数据/重放/多时间框）
> 时才命中——这些路径由策略回归套件覆盖，而非非策略单元测试。**不应**据此盲目给
> line 系统补单测刷数字（成本高、易写出脆弱测试）；真正的回归网是策略套件。

## 较低覆盖率的非核心模块 (Low-coverage, non-core)

主要是绘图/可选后端/CLI/可选依赖（合理，不强求）：

| 模块 | 覆盖率 | 备注 |
| --- | --- | --- |
| talib.py | 5% | 需 TA-Lib 可选依赖 |
| plot/plot.py | 6% | matplotlib 绘图（手动验证为主） |
| utils/ordereddefaultdict.py | 0% | 兼容垫片，少用 |
| plot/multicursor.py | 13% | 交互式绘图 |
| stores/vchartfile.py | 24% | 特定数据源 |

## CI 地板策略 (CI Floor)

为防回退，CI `lint` job 增加**非阻塞**覆盖率看板（先观察、稳定后再考虑阻塞）：

- 阈值：`--cov-fail-under=55`（基线 60% 下留 5% 余量，吸收并行/抽样抖动）。
- 范围：非策略子集（与本基线一致），跑在快速 job 内。
- 升级路径：观察 1–2 周稳定后，把阈值提到 58 并改为阻塞。

## 后续 (Follow-ups)

- 不追求统一 80%；聚焦**核心非 line 模块**的真实盲区（如 `indicator.py` 65%、
  `order.py` 78% 中的错误分支）。
- line 系统覆盖率依赖策略套件，保持现状；如要补，应补**针对性单测**而非泛化用例。
