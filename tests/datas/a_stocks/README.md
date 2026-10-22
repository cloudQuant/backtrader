# A股逐股日线数据

由用户提供的 `D:/股票测试/ChinaStock1MinTradeInfo.1min.20250101_20260101.par`
聚合而来，保留文件内全部股票和全年数据。每只股票对应一个 UTF-8 CSV，例如
`sh600000.csv`、`sz000001.csv` 和 `bj920000.csv`。

## 数据范围与口径

- 原始文件：5,638,657,541 字节，323 个 Parquet row group，315,626,614 条分钟记录。
- 原始 SHA-256：`a9df0336c2da13b395aeb7167f662a795b6df9b10127bec09ec96bf7f069d50c`。
- 输出：5,471 个股票 CSV，共 1,309,654 条日线，CSV 总计 192,406,724 字节。
- 日期：2025-01-02 至 2025-12-31，共 243 个源数据观测日期。
- 按源时间的 `Asia/Shanghai` 本地日期分组，open 取首分钟，high 取最大值，
  low 取最小值，close 取末分钟，volume 和 amount 分别求和。
- 价格沿用源数据，本次不应用复权；未独立确认源数据原有的复权口径。
  成交量保持源单位 `SOURCE_NATIVE`，不自动做手/股换算。
- 每条已存在的股票日线恰有 241 条源分钟记录，含 09:30 记录。
  不丢弃开盘记录、不前填、不推断停牌原因、不补不存在的股票日期。
- `trade_time` 是当日全文件最后一个分钟时间，作为统一截面时间；
  每股实际首末时间另存于 `first_trade_time`、`last_trade_time`。

`minute_count` 表示实际源分钟行数；`missing_or_invalid_count` 只统计存在但数值异常
的源行，不表示与交易所完整交易日历比较后的缺失分钟数。本次检测到的异常行数为零。
若未来输入含异常，脚本保留每日记录并将受影响的日线字段置空；重复键和乱序直接报错。

## 重现

在仓库根目录安装 pandas、numpy、pyarrow 后运行：

```powershell
python scripts/aggregate_stock_minute_parquet.py --input "D:/股票测试/ChinaStock1MinTradeInfo.1min.20250101_20260101.par" --output-dir tests/datas/a_stocks
```

输出目录必须不存在；已有数据可直接使用。重新验证聚合时请选择新的输出目录，
避免覆盖现有数据。原分钟文件不纳入本仓库且聚合过程不修改它。

## 验证记录（2026-10-22）

本轮直接在 Backtrader `dev` 开发，起点 `bb934e6d02b628d111fc03f32dcca22fd6fc6786`。
范围为聚合脚本、9项微型数据测试、本目录和字节保持规则；无生产因子代码变更。
微型测试 9 passed；Black、Ruff 通过。环境存在一条已有 pytest 配置警告。

实际全量聚合退出码为零。逐股文件哈希、行数、日期顺序、日历计数全部匹配；
分钟数总和等于全部 315,626,614 条源记录。独立读取年初、年中、年末的三只股票，
用实际首末分钟、max/min 和 `math.fsum` 核对9组股票日，所有字段吻合，成交量/成交额最大差为零。

- `_metadata/manifest.json`：来源哈希、源文件前后状态、完整 schema、逐股文件哈希与统计。
- `_metadata/observed_calendar.csv`：源数据观测日历，不是另行认证的交易所日历。
- `_metadata/raw_minute_samples.json`：独立分钟样本及计算方法。
- `_metadata/aggregation_validation.json`：全量输出检查与样本比较结果。

使用这些 CSV 运行生产版 Alpha003，见
`examples/backtest/027_alpha003_panel_acceptance/README.md` 的真实日线入口。
