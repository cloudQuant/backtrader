# 迭代49：A股日线数据列裁剪与目录替换说明

更新：2026-10-23。本文记录 `tests/datas/a_stocks` 从 14 列聚合输出裁剪为
7 列、并原地替换原目录的数据处理。该处理服务于迭代49对完整流程耗时与内存的
优化：在行数、日期、价格和成交口径不变的前提下，减少 CSV 体量与逐文件解析成本。
它不改变任何因子公式、研究日历或评价口径。

## 1. 处理对象

| 项目 | 处理前（2026-10-22 聚合输出） | 处理后 |
| --- | ---: | ---: |
| 逐股 CSV 文件数 | 5,471 | 5,471 |
| 日线行数 | 1,309,654 | 1,309,654 |
| 字段数 | 14 | 7 |
| CSV 总字节 | 192,406,724 | 87,081,833 |
| 观测日期数 | 243 | 243 |

本次只做逐字段投影：保留列的值逐字节复制，删除列不参与任何重新计算。
裁剪后总字节减少 105,324,891 字节（54.74%），单行平均约由 146.9 字节降为
66.5 字节。源 Parquet 文件、聚合脚本以及 2026-10-22 的聚合验证记录均未修改。

## 2. 保留与删除的列

保留列（顺序固定）：

`trade_time, open, high, low, close, volume, amount`

其中 `trade_time` 是当日统一截面时间，其余六列是聚合得到的 OHLC、成交量和成交额。

删除列及其冗余依据：

| 删除列 | 本数据集中的取值 | 依据 |
| --- | --- | --- |
| `trade_date` | 日期字符串 | 等于 `trade_time` 的前 10 个字符 |
| `symbol` | 股票代码 | 等于 CSV 文件名去掉 `.csv` 后缀 |
| `minute_count` | 恒为 241 | 每条已存在的股票日线恰有 241 条源分钟记录 |
| `first_trade_time` | 当日 09:30:00.000 | 固定交易时段起点，含 09:30 记录 |
| `last_trade_time` | 与 `trade_time` 相同 | 统一截面时间即当日最后一个分钟 |
| `missing_or_invalid_count` | 恒为 0 | 全量聚合记录异常行数为零 |
| `invalid_day` | 恒为 False | `aggregation_validation.json` 记录 `invalid_daily_rows: 0` |

这些等值关系来自聚合脚本的写入口径和 2026-10-22 的全量聚合验证：
5,471 个文件、1,309,654 行，`invalid_daily_rows` 为零，每条日线固定 241 分钟。
`_metadata/observed_calendar.csv` 仍保留 `trade_date`、`first_trade_time`、
`last_trade_time`、`minute_count` 等日历字段（17,566 字节，逐字节未变），
因此研究网格与首末交易时间不依赖逐股 CSV 中的已删除列。

**边界：** 7 列布局无法表达“某日存在异常分钟”的日线。未来若聚合输入出现异常，
应保留 14 列输出或另建异常状态列，不能把本裁剪流程用于带异常的数据。

## 3. 裁剪方法

脚本：`scripts/clean_a_stock_daily_columns.py`（标准库实现，不依赖 pandas）。

对每个源文件：

1. 拒绝含 `\r` 的 CRLF 文件，要求输出统一为 LF。
2. 校验文件字节数与 SHA-256 等于源 `_metadata/manifest.json` 的记录。
3. 校验表头恰为 14 列且顺序固定，行数等于 manifest 记录。
4. 逐行校验字段数为 14；7 个保留字段非空，且不含逗号、双引号、CR、LF
   （即不会触发 CSV 引号规则）。
5. 按固定顺序写出 7 列；写完后重新解析输出，与逐行保留字段元组精确比对。

全部文件通过后：

- 逐字节复制 `observed_calendar.csv` 并回读比对；
- 校验投影后的总行数等于源 manifest 的 `daily_rows`；
- 重写 manifest：更新 `columns`、`format`、`total_bytes` 和逐股
  `bytes`/`sha256`，新增 `cleaning` 段，记录脚本、源目录名、
  源 manifest 的 SHA-256、源文件数/行数/字节数、保留与删除列、校验计数；
- 在临时目录完成后用 `staging.replace(target)` 原子替换目标目录；
  任一步失败则删除临时目录，不留下半成品。

## 4. 执行结果

本次裁剪产生于派生目录 `tests/datas/a_stocks_clean`，校验结果：

- `csv_file_count`: 5,471
- `daily_rows`: 1,309,654
- `retained_field_mismatches`: 0
- `source_file_hashes_checked`: 5,471
- `observed_calendar_bytes`: 17,566

当前 `tests/datas/a_stocks/_metadata/manifest.json` 的 `cleaning` 段记录：

- `source_manifest_sha256`: `72e99dd547a86102abaf1396fd72b7c10ef7ca4f1a75698d1116f29b950d53b2`
- `source_total_bytes`: 192,406,724
- `kept_columns`: `trade_time, open, high, low, close, volume, amount`
- `dropped_columns`: `trade_date, symbol, minute_count, first_trade_time,
  last_trade_time, missing_or_invalid_count, invalid_day`

## 5. 目录替换

替换前先做了一次行为对照：用 027（生产 Alpha003 全市场入口）分别在原始 14 列
数据集和 7 列数据集上运行，除 `summary.json` 的 `elapsed_seconds` 外所有输出
逐字节相同，包括因子面板、分块缓存、manifest、oracle 校验和 HTML 报告。

替换方式为把派生文件逐个写回受版本控制的 `tests/datas/a_stocks`，而不是把旧目录
改名后保留双份：

- 覆盖 5,471 个 CSV 和 `_metadata/manifest.json`；
- `_metadata/observed_calendar.csv` 内容与旧目录逐字节一致，覆盖后不变；
- 保留 `_metadata/raw_minute_samples.json` 与
  `_metadata/aggregation_validation.json`，它们记录的是 2026-10-22 的聚合过程，
  其行数、来源哈希和样本结论对当前数据仍然成立；
- 仓库 `.gitattributes` 对 `tests/datas/a_stocks/**` 设置了 `-text`，
  Git 按字节保存 CSV，不会因各平台换行转换改变文件哈希；
- 替换完成后删除派生目录 `tests/datas/a_stocks_clean`，避免仓库外出现第二份 87MB 数据。

## 6. 代码兼容性

- `examples/backtest/025_factor_single/run.py`、`026_factor_multi/run.py`、
  `027_alpha003_panel_acceptance/run.py` 的日线加载只使用文件名对应的
  `entry["symbol"]`、`trade_time` 和 OHLCV 列；`dtype={"trade_date": "string"}`
  只是可选类型提示，列不存在时 pandas 忽略该键，无需改动。
- 三者的研究日历读取 `_metadata/observed_calendar.csv`，该文件未变，
  因此研究网格、首末时间与会话映射不受影响。
- 027 的全市场入口 `run_daily.py` 已支持双 schema：
  7 列文件只校验保留字段，并从 `trade_time` 推导日期；14 列旧布局仍按原逻辑
  校验 `invalid_day`、分钟总数和日历首末时间，禁止同一批文件混用两种 schema。
  缓存块对 7 列源写入哨兵值（`minute_count=-1`、`last_trade_time=trade_time` 等），
  因子 worker 只消费 `symbol/trade_time/OHLCV`，输出与旧布局一致。
- 新增回归测试
  `tests/unit/test_alpha003_daily_runner.py::test_reduced_seven_column_source_matches_legacy_and_runs_end_to_end`
  用同一批合成数据分别生成两种 schema，断言加载数组相等、无效行计数一致，
  并在 7 列源上完整跑通 `run_daily.main`。
- 聚合相关测试 `tests/unit/test_stock_minute_daily_aggregation.py` 使用自建
  Parquet 和输出目录，不读取本数据集表头，保持不变。

## 7. 重现命令

```powershell
python scripts/aggregate_stock_minute_parquet.py --input "D:/股票测试/ChinaStock1MinTradeInfo.1min.20250101_20260101.par" --output-dir tests/datas/a_stocks_full
python scripts/clean_a_stock_daily_columns.py --source tests/datas/a_stocks_full --target tests/datas/a_stocks
```

两个目标目录都必须预先不存在；脚本不会覆盖已有目录。裁剪脚本默认参数为
`--source tests/datas/a_stocks --target tests/datas/a_stocks_clean`，
仅用于从 14 列目录重新生成派生副本。

## 8. 影响与限制

- **时间与 I/O：** 逐文件读取的 CSV 字节减少约 54.7%，解析的列和字符串字段更少；
  排序、因子计算和评价算法没有改动。
- **内存：** 027 加载器仍按 `日期 × 股票` 预分配全部日线数组（6 个 float64 列、
  时间戳和计数矩阵），所以面板数组的峰值内存不变；本处理降低的是文件读取、
  CSV 解析和字符串列驻留，不改变迭代49已确认的 1GB 进程树峰值验收口径。
- **语义：** 不重新聚合、不复权、不做手/股换算、不填充缺失股票日；行集合与
  243 个观测日期保持不变。
- **版本控制：** 本次替换会重写 5,471 个受控 CSV 的字节内容，diff 体量大但属于
  纯列删除；manifest 的 `cleaning` 段和本文是这次数据变更的完整来源记录。
