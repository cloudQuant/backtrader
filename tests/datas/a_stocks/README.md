# A股逐股日线数据

由用户提供的 `D:/股票测试/ChinaStock1MinTradeInfo.1min.20250101_20260101.par`
聚合而来，保留文件内全部股票和全年数据。每只股票对应一个 UTF-8 CSV，例如
`sh600000.csv`、`sz000001.csv` 和 `bj920000.csv`。

2026-10-23 对本目录执行了一次列裁剪：由聚合脚本生成的 14 列日线投影为 7 列，
行数、日期、价格、成交量与成交额均未重新计算。裁剪过程与依据见
[迭代49-A股日线列裁剪说明](../../../docs/_internal/opts/requirements/迭代49-因子分析性能优化/A股日线列裁剪说明.md)。

## 数据范围与口径

- 原始文件：5,638,657,541 字节，323 个 Parquet row group，315,626,614 条分钟记录。
- 原始 SHA-256：`a9df0336c2da13b395aeb7167f662a795b6df9b10127bec09ec96bf7f069d50c`。
- 输出：5,471 个股票 CSV，共 1,309,654 条日线，CSV 总计 87,081,833 字节
  （裁剪前的 14 列布局为 192,406,724 字节）。
- 日期：2025-01-02 至 2025-12-31，共 243 个源数据观测日期。
- 按源时间的 `Asia/Shanghai` 本地日期分组，open 取首分钟，high 取最大值，
  low 取最小值，close 取末分钟，volume 和 amount 分别求和。
- 价格沿用源数据，本次不应用复权；未独立确认源数据原有的复权口径。
  成交量保持源单位 `SOURCE_NATIVE`，不自动做手/股换算。
- 每条已存在的股票日线恰有 241 条源分钟记录，含 09:30 记录。
  不丢弃开盘记录、不前填、不推断停牌原因、不补不存在的股票日期。
- `trade_time` 是当日全文件最后一个分钟时间，作为统一截面时间；
  每股实际的首末分钟在该数据集中恒为当日 09:30 与 `trade_time`。

## 字段

| 列 | 含义 |
| --- | --- |
| `trade_time` | 当日统一截面时间，`Asia/Shanghai` 本地时间 |
| `open` | 当日首分钟价格 |
| `high` | 当日最高价 |
| `low` | 当日最低价 |
| `close` | 当日末分钟价格 |
| `volume` | 当日成交量之和，源单位 |
| `amount` | 当日成交额之和 |

聚合结果中的以下列已删除，原因是它们在本数据集中是常量或可从保留列直接得到：

| 已删除列 | 依据 |
| --- | --- |
| `trade_date` | 等于 `trade_time` 的日期部分 |
| `symbol` | 等于文件名去掉 `.csv` 后缀 |
| `minute_count` | 每条已存在日线恒为 241 |
| `first_trade_time` | 恒为当日 `09:30:00.000` |
| `last_trade_time` | 恒等于 `trade_time` |
| `missing_or_invalid_count` | 全量聚合记录为 0 |
| `invalid_day` | 全量聚合记录为 `False` |

因此 7 列布局不能表达“存在异常分钟”的日线。若未来的聚合输入出现异常记录，
应保留完整 14 列输出，或为异常状态另建列；不要把本裁剪脚本直接用于此类数据。

## 目录内容

- 5,471 个逐股 CSV，每行一个股票日。
- `_metadata/manifest.json`：来源哈希与源文件前后状态、schema、逐股文件哈希/字节数/
  行数/首末日期，以及 `cleaning` 段记录的裁剪脚本、源目录、源 manifest 哈希、
  保留/删除列和校验计数。
- `_metadata/observed_calendar.csv`：源数据观测日历（17,566 字节），裁剪时按字节原样保留。
  它仍然是聚合输出，不是另行认证的交易所日历。
- `_metadata/raw_minute_samples.json`：2026-10-22 聚合时的独立分钟样本及计算方法。
- `_metadata/aggregation_validation.json`：2026-10-22 全量聚合检查与样本比较结果。

## 重现

在仓库根目录安装 pandas、numpy、pyarrow 后运行聚合：

```powershell
python scripts/aggregate_stock_minute_parquet.py --input "D:/股票测试/ChinaStock1MinTradeInfo.1min.20250101_20260101.par" --output-dir tests/datas/a_stocks_full
```

聚合输出目录必须不存在；已有数据可直接使用。原分钟文件不纳入本仓库且聚合过程不修改它。

再把 14 列聚合目录投影为 7 列（目标目录同样必须不存在）：

```powershell
python scripts/clean_a_stock_daily_columns.py --source tests/datas/a_stocks_full --target tests/datas/a_stocks
```

脚本使用标准库流式读写，逐文件校验源 manifest 的字节数与 SHA-256、表头、行数和
每行字段数，拒绝需要 CSV 引号的保留字段，写完后重新读取并逐行比对；
`observed_calendar.csv` 原样复制，manifest 中补充 `cleaning` 来源信息，
最后以临时目录原子替换目标目录。

## 验证记录

- 2026-10-22 全量聚合（14 列）：退出码为零；逐股文件哈希、行数、日期顺序、日历计数
  全部匹配；分钟数总和等于全部 315,626,614 条源记录；9 组独立抽样核对全部字段，
  成交量/成交额最大差为零。微型测试 9 passed，Black、Ruff 通过。
- 2026-10-23 列裁剪：5,471 个文件、1,309,654 行的保留字段逐一比对无差异；
  5,471 个源文件哈希全部核对；`observed_calendar.csv` 17,566 字节保持一致。
  027 每日入口在裁剪前后输出除耗时字段外逐字节相同；对应的 7 列/14 列双 schema
  单元测试通过。

使用这些 CSV 运行生产版 Alpha003，见
`examples/backtest/027_alpha003_panel_acceptance/README.md` 的真实日线入口。
