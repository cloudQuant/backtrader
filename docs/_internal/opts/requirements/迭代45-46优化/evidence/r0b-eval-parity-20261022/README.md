# R0b 评价口径对照：旧 dataset 路径 vs 新 panel 路径

日期：2026-10-22。主机：macOS/arm64，Python 3.11.8，pandas 3.0.3。

## 目的

用**冻结的旧实现**（`git archive 4ce64007` 的稀疏 checkout，见 `../r0a-baseline-20261022/frozen-source/`）跑完旧 `ResearchDataset` 采集与 `dataset.evaluate(spec)`，
与当前 panel 路径在同一 025 配置、50 只股票、同一 fincore 研究入口上逐表对照。

## 命令

```bash
# 旧路径（/tmp/bt-old 是 4ce64007 的稀疏 measurement checkout，tests/datas 软链到当前仓库）
python /tmp/run_old_eval.py
# 新路径
python examples/backtest/025_factor_single/run.py --output-dir /tmp/new-eval-50 --max-symbols 50 --no-charts
```

## 结果

| 项 | 旧 dataset 路径 | 新 panel 路径 |
|---|---|---|
| status | OK | OK |
| evaluation_id | `6fff07068f60c09f741621112a2b11a4e96bf86cffc8d277eb3c4ceef548e07f` | `f12c0cb468815548ba34fd03206b236dc160c8681aa372221b224caaf3da91d6` |
| result_fingerprint | `6c04e58a663e915624ebf7e6ebe3cfee6775735efc810617ec8c9fbf8f569236` | `6c04e58a663e915624ebf7e6ebe3cfee6775735efc810617ec8c9fbf8f569236` |
| 旧采集+dataset 阶段 | 3.473 s | 见 r0a/基准 |
| 评价阶段 | 2.052 s | 见新 summary |

11 张表（signals/labels/ic/ic_summary/quantile_returns/turnover/spreads/stability/correlation/coverage/diagnostics）
用 `pandas.testing.assert_frame_equal` 逐表比较，**全部完全相等**；`result_fingerprint` 相等（6c04e58a…）。

`evaluation_id` 不同是预期的：它把输入帧的 `attrs`/索引形状（旧数据集 provenance、long universe）计入身份；
计划 §3.3 明确不要求跨已删除身份合同的 ID 相同，只要求结果内容一致。`result_fingerprint` 只随结果内容变化，因而相等。

## 边界

- 这是 025 单因子、50 只、`next_open_to_open` 的评价口径对照；不覆盖 alpha101 相关核（025 不使用相关/协方差）。
- 旧实现只在冻结的 measurement checkout 中运行，未进入生产路径；新路径的 turnover 表是本轮补实现的。
- 不是 provider、安装产物或 500 只性能证据。
