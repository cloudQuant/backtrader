# Iteration 51 official EOD ranking source check

Research checkpoint: 2026-10-24. This note records public-source observations
for the additional exchanges. It does not claim that a ranking snapshot is
complete until the report is joined and reconciled against the actual CTP
instrument catalog for the same exchange/product scope.

## CFFEX: bounded daily CSV observed

The official dated endpoint used for the bounded sample was:

`http://www.cffex.com.cn/fzjy/mrhq/202610/23/20261023_1.csv`

The endpoint returned HTTP 200 with `Content-Type: text/csv`,
`Content-Length: 59905`, `Accept-Ranges: bytes`, ETag
`"ea01-65e7d68b6d740"`, and `Last-Modified: Fri, 23 Oct 2026 08:03:01 GMT`.
The complete response was parsed by the new bounded adapter on 2026-10-24 at
02:47:20 UTC. Its SHA-256 was
`4ebaf266f94ce2bf962ded1a194ebe9d35cc3c5daecd2576081775ceb06ef2e9`.
Later bounded requests were intermittent, including one that timed out after
receiving 56,169 of 59,905 bytes; no retry is treated as a publication-time
guarantee.

The sample had 753 physical lines: 28 futures rows across the CFFEX product
codes IF, IH, IC, IM, TF, TS, T, and TL; 712 option rows; and 12 explicit
summary rows (11 `小计`, one `合计`). The observed CP936/GB18030 text header was:

`合约代码,今开盘,最高价,最低价,成交量,成交金额,持仓量,持仓变化,今收盘,今结算,前结算,涨跌1,涨跌2,Delta`

An observed row was `IC2611,6540,6811.4,6388,55053,7237216.7,61020,2863,...`;
the source ID is `IC2611`, volume is 55,053 lots, open interest is 61,020,
and open-interest change is 2,863. The official CFFEX trading rules define
volume and open interest as unilateral counts in the [Trading Rules
(PDF)](https://www.cffex.com.cn/u/cms/www/202003/27160915uqs5.pdf).
The [CFFEX market-data authorization guide
(PDF)](https://www.cffex.com.cn/u/cms/www/202201/20211342wucd.pdf) is separate
source context; this adapter does not redistribute quote data or make a
licensing determination.

The CSV does not embed its trading date; the adapter binds `trading_day` to the
date in the requested URL. It preserves source contract IDs and only parses
ordinary month futures rows; option rows are counted and not ranked. It uses
local full-response retrieval completion as both `available_at` and
`retrieved_at`. The observed HTTP `Last-Modified` value is retained separately
and is not represented as the first publication time. The direct source used
HTTP, not TLS; the content digest identifies retrieved bytes but does not
authenticate their origin. Catalog reconciliation must succeed before the
rows can become selector candidates. No universal availability or
publication-latency statement is inferred from this single sample.

The adapter and focused tests are:

- `backtrader/feeds/futures_eod_cffex.py`
- `tests/unit/feeds/test_futures_eod_cffex.py`

## DCE: official public page blocks bounded unauthenticated retrieval

The official public daily-quote page attempted was
`http://www.dce.com.cn/publicweb/quotesdata/dayQuotesCh.html`. A bounded GET
returned HTTP 412 `Precondition Failed` with a cookie and no quote payload.
The corresponding HTTPS request timed out on port 443.
The public response therefore did not establish a usable daily schema or
candidate coverage. The official [DCE multicast market-data specification
(PDF)](https://www.dce.com.cn/dalianshangpin/ywfw/ywzy/jsfwzy/jszl/jkgfjwd/6284851/2022041909582038762.pdf)
describes contract/market status messages and an end-of-day data-service
notification; that is a separate feed protocol, not evidence that the public
HTTP report can be parsed or that the local environment has a configured
market-data entitlement. No DCE ranking adapter is claimed here.

## CZCE: official daily path could not be fetched to schema

A bounded request to the official-host path
`http://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20261023/FutureDataDaily.txt`
returned a same-host redirect to HTTPS. The HTTPS fetch timed out, so this
attempt did not verify response bytes, encoding, headers, fields, or row
coverage. CZCE's current [Futures Trading Management Rules
(PDF)](https://www.czce.com.cn/cn/content_file/flfg/zcjywgz/ywbf/2026/5/a5ad00e02e484498abdbac8ddbfd5c35.pdf)
states that daily quotations include delivery month, volume, open interest,
and related fields and are published after each trading-day close. That
supports the data need but does not substitute for an observed daily-file
sample. No CZCE daily adapter is claimed here.

## GFEX: official data menu exists; bounded retrieval met a bot challenge

GFEX's [official site map](https://www.gfex.com.cn/en/WebsiteMap/WebsiteMap.shtml)
lists Historical Market Data → Daily Statistics → Daily Market Data and Daily
Volume & Position Ranking. GFEX's [Trading Rules (PDF)](https://www.gfex.com.cn/gfex/llbb/202402/e91439278d3a44b4aefe7ca126167e1a/files/%E5%B9%BF%E5%B7%9E%E6%9C%9F%E8%B4%A7%E4%BA%A4%E6%98%93%E6%89%80%E4%BA%A4%E6%98%93%E8%A7%84%E5%88%99%EF%BC%882022%E5%B9%B44%E6%9C%8829%E6%97%A5%E7%89%88%EF%BC%89.pdf)
includes contract name/month, volume, open interest, and related fields among
published information.

A bounded request to the public daily-market page at
`http://www.gfex.com.cn/gfex/rihq/hqsj_tjsj.shtml` returned a 986-byte
TencentEdgeOne JavaScript challenge rather than its page. A bounded POST to
`http://www.gfex.com.cn/u/interfacesWebTiDayQuotes/loadList` returned the same
challenge. The HTTPS page request failed certificate hostname validation, so
no certificate bypass was attempted. The exact request schema and response
body were therefore not observed; no GFEX daily adapter or completeness claim
is made.

## Coverage boundary

This checkpoint adds only the CFFEX source parser. It does not narrow the
selector's target products or exchanges. SHFE/INE remains in its separately
accepted source adapter. DCE, CZCE, and GFEX still need an actual bounded
official response and schema validation before source adapters can be claimed.
No exchange candidate list is complete merely because a report fetch
succeeded; the caller must join exact source IDs to the actual current CTP
catalog and record missing, duplicate, and ambiguous IDs per product.

## Follow-up public access check and composite coverage adapter (2026-10-24)

The official-source check used search-indexed exchange pages and a normal
browser tab as alternate public surfaces; it did not repeat the same raw GET
loops or bypass a site challenge/certificate error. It found no additional
dated report bytes:

| Exchange | Official public source checked | Follow-up result |
| --- | --- | --- |
| DCE | [Daily quote query](http://www.dce.com.cn/publicweb/quotesdata/dayQuotesCh.html) and [multicast market-data specification](https://www.dce.com.cn/dalianshangpin/ywfw/ywzy/jsfwzy/jszl/jkgfjwd/6284851/2022041909582038762.pdf) | The prior bounded public request returned HTTP 412 with a cookie and no quote body; HTTPS timed out. The official specification describes an end-of-day data-service notification on multicast, but that is not an observed public daily-file response or proof of a configured local entitlement. |
| CZCE | [Official futures trading management rules](https://www.czce.com.cn/cn/content_file/flfg/zcjywgz/ywbf/2026/5/a5ad00e02e484498abdbac8ddbfd5c35.pdf) and candidate dated [FutureDataDaily.txt](https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20261023/FutureDataDaily.txt) | The current rules state that daily futures information includes contract name, delivery month, volume, open interest, and related quote fields, published after close. The previously observed HTTP route redirects to HTTPS; the bounded HTTPS fetch timed out. Neither the field schema nor current sample bytes were observed. |
| GFEX | [Official site map](https://www.gfex.com.cn/en/WebsiteMap/WebsiteMap.shtml), [daily quote page](http://www.gfex.com.cn/gfex/rihq/hqsj_tjsj.shtml), and [trading rules](https://www.gfex.com.cn/gfex/llbb/202402/e91439278d3a44b4aefe7ca126167e1a/files/%E5%B9%BF%E5%B7%9E%E6%9C%9F%E8%B4%A7%E4%BA%A4%E6%98%93%E6%89%80%E4%BA%A4%E6%98%93%E8%A7%84%E5%88%99%EF%BC%882022%E5%B9%B44%E6%9C%8829%E6%97%A5%E7%89%88%EF%BC%89.pdf) | The official site map lists Daily Market Data and Daily Volume & Position Ranking; the rules describe published contract/month, volume, and open interest facts. The prior page/API request returned a JavaScript bot challenge; the normal browser rejected the site certificate hostname and the web fetch timed out. No challenge was solved or certificate warning bypassed, so the request format and response schema remain unknown. |

`backtrader.feeds.futures_ranking_sources` provides a typed composite-input
builder for the accepted SHFE/INE and CFFEX adapters and future exchange
adapters. The caller must provide the complete product set and CTP catalog
snapshot; a missing DCE, CZCE, or GFEX source produces explicit per-product
coverage blockers. The composite digest binds constituent report identities,
raw-report digests, timestamps, units, status facts, and normalized joined
rows. Its availability is no earlier than the latest constituent observed
availability. It is a manifest digest, not a raw exchange body or evidence
that any missing exchange is covered. No current all-market-ready snapshot is
claimed.
