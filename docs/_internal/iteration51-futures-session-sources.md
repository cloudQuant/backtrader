# Iteration 51 public futures calendar/session inputs

This note records the public-source contract for the shared futures calendar
and minute grid. The implementation is a pure normalizer/planner; it does not
fetch data, create an exchange calendar from weekdays, infer product hours from
a code prefix, or use arriving bars to decide which minutes should exist.

## Input and point-in-time contract

`backtrader.feeds.futures_sessions.ExchangeSessionCalendar` carries the
explicit trading-day set, the declared exchange product universe, one
product/TradingDay row for every requested schedule, and source observations.
Each source observation includes its HTTPS URL, version/publication label,
`available_at`, `retrieved_at`, and the digest of the exact response/document
bytes. If a trustworthy publication time is unavailable, an adapter must use
the retrieval time as `available_at`; it must not backdate availability.

All session boundaries are explicit China UTC+08:00 instants. A window is
half-open (`[start, end)`), whole-minute aligned, and labeled with both its
calendar session date and its CTP TradingDay. The emitted minute close is one
minute after each window start through its end; the final grid converts those
instants to UTC. The grid retains `session_date`, `action_day`, TradingDay,
product, and session identifier for each member at every common minute.

Before building a grid, the planner requires the exact full target product set,
an exchange calendar for each exchange, explicit TradingDay coverage in that
calendar, and a product-session row for each product/day. It checks the
referenced source observations were available and retrieved no later than the
decision time. A holiday's missing night segment must be represented by an
explicit schedule row containing only the published day windows; a fully
closed product day needs an explicit `closed_reason`. A missing row, source,
product, or date blocks the grid. The implementation does not replace missing
days with Monday-Friday or shrink the cohort to the feeds that happen to have
bars.

`build_common_minute_grid` intersects the per-product close timestamps across
every product in the requested cohort. Exchange breaks, different night
session ends, day-only products, and holiday-specific missing night sessions
therefore remove timestamps from the entire group. It does not forward-fill,
concat old/new contracts, or use observed data to define the research grid.
`load_exchange_session_calendar` restores the public JSON representation,
including its source URLs and time/digest fields. Its adapter to the existing
`ExchangeTradingCalendar` passes the explicit date facts to
`select_main_contracts`; it does not synthesize dates.

Both planners reject oversized snapshots and requests before minute expansion:
at most 2,000 target products, six exchange calendars, 10,000 calendar dates,
100,000 product/TradingDay rows, 10,000 requested days per product (100,000
total), 10,000 sources, 16 windows per product-day row and 300,000 windows per
exchange snapshot. A continuous session is at most 24 hours and can cross
midnight once. The finite `build_common_minute_grid` additionally caps expanded
product-minute slots at 1,000,000. It remains suitable for bounded previews and
smaller snapshots.

`iter_common_minute_windows` is the long finite-snapshot path. It preflights
the complete target set, explicit dates, every selected product-day row, and
all source `available_at`/`retrieved_at` times before yielding. It checks for
overlapping session intervals, then intersects sorted per-product session
streams without creating per-product minute dictionaries. It yields tuples of
up to 4,096 `PlannedCommonMinute` records, with a fixed aggregate budget of
65,536 member records per chunk. For `N` target products the effective chunk
size is `min(window_size, 65,536 // N)`, so larger cohorts automatically use
smaller chunks without changing planned closes or member evidence. Total
limits are 300,000 requested session windows, 20,000,000 estimated
product-minute slots, and 1,000,000 common closes per invocation. The iterator
is finite over supplied snapshots,
and callers must exhaust it to prove the range completed. A changed target
pool, master mapping, or calendar needs a new call for the new epoch; this API
does not append assets or invent future dates. These limits accommodate the
20-product 100,000-close plus warmup fixture while bounding planner memory to
finite interval metadata, active product streams, and one output chunk.

`find_planned_common_minute(grid, close_time)` is an exact UTC-normalized
lookup over the frozen sorted materialized grid. It returns the existing
`PlannedCommonMinute` and its per-product TradingDay/session/ActionDay
evidence, or `None` for a close not present in the planned intersection. It
cannot authorize an arbitrary time or callback.

The `complete` field describes the source adapter's coverage claim for the
declared interval. It is not used alone: the runtime checks requested exchange,
product, TradingDay, product-day, window/source references, and point-in-time
timestamps. No third-party signature or separate service-level attestation is
required. A source row still needs to be collected and saved before it can be
used for a historical decision.

## Public source observations

The pages below are primary exchange sources and were reviewed on 2026-10-24.
These are source references, not captured runtime snapshots; this note does
not assign them a response digest or claim a historical `available_at` for a
particular saved response.

| Exchange | Official source | Relevant published facts | Current coverage limit |
| --- | --- | --- | --- |
| SHFE | [Trading hours](https://www.shfe.com.cn/services/calenderandholidays/tradinghours/), [holiday arrangements](https://www.shfe.com.cn/services/calenderandholidays/holiday/), [trading calendar](https://www.shfe.com.cn/services/calenderandholidays/tradingcalendar/) | Product groups differ: common commodity nights include 21:00–01:00, precious metals/crude include 21:00–02:30, another group ends 23:00, and some contracts have day sessions only. Day windows include 09:00–10:15, 10:30–11:30, and 13:30–15:00. The page says a TradingDay's night session starts at 21:00 on the previous working day. | The official pages and published 2026 holiday notice are available, but their retrieved raw bytes and complete product-to-session dataset still need to be materialized into versioned snapshots. |
| INE | [Trading hours](https://www.ine.cn/services/calenderandholidays/tradinghours/), [2026 holidays](https://www.ine.cn/services/calenderandholidays/holiday/), [rules](https://www.ine.cn/regulation/ineregulation/rules/202610/t20261012_833676.html), [trading calendar](https://www.ine.cn/services/calenderandholidays/tradingcalendar/) | BC, SC, NR/LU and EC have different night-session scopes/end times; EC is day-only. The 2026 holiday notice names specific evenings on which no night session precedes a holiday. Rules define the TradingDay/night-session relationship. | The source pages exist, but the dynamic calendar and complete product/session rows have not yet been captured and reconciled into runtime snapshots. |
| DCE | [Official 2026 J/JM factsheet](https://www.dce.com.cn/dce/file/2026-01-15/17684624156122c9a882b9ae6dcbb289019bc092f6fc1681.pdf), [product rules and notices](https://www.dce.com.cn/dceg/) | Official product materials demonstrate that some products publish day-only hours, while night-session eligibility is product-specific. A single product document cannot describe the DCE universe. | The current all-product calendar/session source payload and product-specific holiday-eve overrides are not yet captured as a complete snapshot. Do not infer them from weekdays or copy one product's hours to the DCE universe. |
| CZCE | [Official cotton-futures rules](https://www.czce.com.cn/cn/flfg/zcjywgz/pzxz/webinfo/2024/02/1708568084281851.htm), [rules and notices](https://www.czce.com.cn/cn/) | CF is published with 21:00–23:00 night trading and day windows 09:00–11:30 (10:15–10:30 break) and 13:30–15:00. The rule permits the exchange to suspend/adjust night trading by notice. | One product rule does not establish all CZCE products. The complete current product schedule and holiday-eve overrides still need a saved exchange-wide source snapshot. |
| CFFEX | [Trading rules](https://www.cffex.com.cn/en_new/Rules/TradingRules/), [current official IF contract rules PDF](https://www.cffex.com.cn/u/cms/www/202003/27165450o6vr.pdf), [trading calendar](https://www.cffex.com.cn/) | The current official IF contract rules give continuous trading as 09:30–11:30 and 13:00–15:00, with call auction before continuous trading. The general rules identify exchange TradingDays and product-specific schedules. | The current complete CFFEX TradingDay snapshot and instrument-specific last-trading-day session exceptions are not yet captured as an exchange-wide snapshot. |
| GFEX | [Trading calendar](https://www.gfex.com.cn/gfex/jyrl/list.shtml), [2026 holiday notice](https://www.gfex.com.cn/en/Notices/202601/ecd5e39ce8a04d2eb0a88d47ba2abd26.shtml), [SI rules](https://www.gfex.com.cn/gfex/llbb/202402/73cd6f4cc26b4dd5b3d127b5462b59a7/files/%E5%B9%BF%E5%B7%9E%E6%9C%9F%E8%B4%A7%E4%BA%A4%E6%98%93%E6%89%80%E5%B7%A5%E4%B8%9A%E7%A1%85%E6%9C%9F%E8%B4%A7%E5%90%88%E7%BA%A6%EF%BC%882022%E5%B9%B412%E6%9C%8812%E6%97%A5%E7%89%88%EF%BC%89.pdf) | The 2026 holiday notice specifies closures and reopening dates. SI rules show a day-only product with morning/afternoon windows and a 10:15–10:30 break. Other products still require their own published schedule. | The calendar interface is dynamic and the complete product/session rows are not yet captured as a versioned full-universe snapshot. |

The DCE source portal timed out during this review. INE's interactive calendar
page was visible as a dynamic query page; no full export was captured. These
are retrieval limitations, not evidence that the exchanges lack calendars.
No official all-six-exchange, full-product saved session dataset was available
to this implementation round. The selector and grid therefore remain
fail-closed when any target's source coverage is missing.

## Deterministic six-exchange fixture

The unit fixture uses one representative ordinary futures product from each
exchange to verify mechanics only. SHFE CU and INE BC use a 21:00–01:00 night;
DCE M and CZCE CF use 21:00–23:00; CFFEX IF uses the current 09:30–11:30 and
13:00–15:00 continuous sessions; GFEX SI is day-only with the 09:00–10:15,
10:30–11:30 and 13:30–15:00 windows. It explicitly checks the 195 common
daytime minute closes, the
120-minute SHFE/INE/DCE night intersection, the lunch break gap, and missing or
late coverage rejection. Its fixture documents use synthetic source URLs and
hashes and must never be presented as actual exchange data or full product
universe acceptance.
