# Iteration 51 SHFE/INE daily ranking source record

## Endpoint and observed format

SHFE's public JavaScript helper at
[`https://www.shfe.com.cn/images/api.js`](https://www.shfe.com.cn/images/api.js)
defines the daily futures report path as
`/data/tradedata/future/dailydata/kx` + `YYYYMMDD` + `.dat`, with an optional
cache-busting `params` query. The adapter uses the dated path without that
query. A bounded GET of
[`https://www.shfe.com.cn/data/tradedata/future/dailydata/kx20261021.dat`](https://www.shfe.com.cn/data/tradedata/future/dailydata/kx20261021.dat)
returned HTTP 200 and JSON (`Content-Type: application/json`) with a
122,540-byte body. The observed ETag was `W/"6ad8690b-1deac"` and
`Last-Modified` was `2026-10-21 07:26:03Z`. The exact body SHA-256 recorded for
that bounded observation was
`1928b23fd611dde20d444e2a8393434a36abe91d234cbf4c2083b40340615822`.

The report has `report_date`, `update_date`, `o_curinstrument`, and
`o_curproduct` fields. The observed instrument table had 331 rows: 327 with
`PRODUCTCLASS` `"1"` and four with class `"6"`. Product aggregates are kept in
the separate `o_curproduct` table. An ordinary copper row for delivery month
`2611` contained `PRODUCTGROUPID="cu"`, `PRODUCTID="cu_f"`,
`PRODUCTCLASS="1"`, `VOLUME=66085`, `OPENINTEREST=147002`, and
`OPENINTERESTCHG=-14051`. These are exchange-reported quantities. The SHFE
daily-data report page describes volume and open interest in contracts,
single-sided (`手，单边计算`).

In the observed instrument-table shape, a per-product subtotal has a present,
empty `DELIVERYMONTH` and `PRODUCTCLASS="1"`; the overall total has present,
empty `PRODUCTGROUPID`, `PRODUCTCLASS`, and `DELIVERYMONTH` fields. The parser
filters only those two shapes. A nonempty month outside the four-digit
year/month form is rejected rather than treated as an aggregate.

The report combines SHFE and INE products, but its rows do not carry the CTP
`ExchangeID` or `InstrumentID`. The adapter parses ordinary rows and excludes
other product classes and aggregate rows. Its separate catalog join matches
`PRODUCTGROUPID`, `DELIVERYMONTH`, and a supplied current CTP catalog's
`ProductID` and exact `InstrumentID`; unmatched, duplicate, and ambiguous
rows remain explicit in the join result. The caller still has to establish
that its catalog scope is complete. This source does not cover DCE, CZCE, CFFEX,
or GFEX and does not establish all-market ranking completeness.

## Point-in-time limits

The body contains an exchange `update_date`; the HTTP response also exposes a
`Last-Modified` header. Neither observation establishes the first moment the
report became public. `fetch_shfe_eod` therefore records the completed local
retrieval time as both `available_at` and `retrieved_at`, and rejects a report
whose stated update time is later than that retrieval. Historical downloads
must not be backdated as if they had been observed at their original
publication time. A complete trading calendar, latest-report comparison, and
all-contract catalog reconciliation remain separate inputs to a selector.

The fixture in `tests/unit/feeds/test_futures_eod_shfe.py` is a small synthetic
JSON payload shaped from these observed fields; it is not the full 122,540-byte
exchange response.

## Official source and terms references

- [SHFE JavaScript endpoint definition](https://www.shfe.com.cn/images/api.js)
- [SHFE/INE daily report page](https://www.shfe.com.cn/reports/tradedata/dailyandweeklydata/?query_date=20261021&query_options=1&query_params=kx&query_product_code=cu_f)
- [SHFE daily report JSON sample](https://www.shfe.com.cn/data/tradedata/future/dailydata/kx20261021.dat)
- [SHFE website copyright and use statement](https://otc.shfe.com.cn/disclaimer/index.html)
- [SHFE information-sales guidance](https://www.shfe.com.cn/services/information/sale/)

SHFE's use statement permits noncommercial browsing and downloading and
restricts commercial-profit use and redistribution without written permission.
That is recorded as source context; this parser does not assert a vendor SLA or
make an exchange-data license determination.
