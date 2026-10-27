"""Focused source-fake contracts for staged CTP futures query sets."""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from types import ModuleType, SimpleNamespace

import pytest

from backtrader.feeds import futures_ctp_snapshot as adapter
from backtrader.feeds.futures_main_contract import (
    CTP_QUERY_SNAPSHOT_EQUAL_WEIGHT_POLICY,
    ExchangeTradingCalendar,
    ExchangeTradingDay,
    select_main_contracts,
)


UTC = timezone.utc
NOW = datetime(2026, 10, 23, 16, 0, tzinfo=UTC)
TRADING_DAY = date(2026, 10, 23)


class FakeQueryResult:
    def __init__(
        self,
        *,
        request_type,
        request_id,
        records,
        request_filters,
        record_limit,
        complete=True,
        record_limit_exceeded=False,
    ):
        self.request_type = request_type
        self.request_id = request_id
        self.connection_generation = 7
        self.account_fingerprint = "fixture-only"
        self.started_at_utc = NOW - timedelta(seconds=5)
        self.completed_at_utc = NOW - timedelta(seconds=1)
        self.is_last_seen = complete
        self.error_code = None
        self.error_message = ""
        self.timed_out = False
        self.complete = complete
        self.records = tuple(records)
        self.late_callback_count = 0
        self.unsupported = False
        self.submit_code = 0
        self.first_completion_origin = "success"
        self.completion_origin = "success" if complete else "record_limit"
        self.record_limit = record_limit
        self.record_limit_exceeded = record_limit_exceeded
        self.query_source = SimpleNamespace(
            request_filters=tuple(sorted(request_filters))
        )


def _product_row(exchange, product_id, product_class="1"):
    return {
        "ExchangeID": exchange,
        "ProductID": product_id,
        "ProductClass": product_class,
    }


def _instrument_row(exchange, product_id, instrument_id, product_class="1"):
    return {
        "ExchangeID": exchange,
        "ProductID": product_id,
        "ProductClass": product_class,
        "InstrumentID": instrument_id,
        "IsTrading": 1,
        "ExpireDate": "20261218",
    }


def _depth_row(exchange, instrument_id):
    return {
        "ExchangeID": exchange,
        "InstrumentID": instrument_id,
        "TradingDay": "20261023",
        "OpenInterest": 1000,
        "Volume": 800,
        "ActionDay": "20261023",
        "UpdateTime": "09:30:00",
        "UpdateMillisec": 0,
    }


def _normalize_instrument(row):
    return {
        "asset_type": "future" if row.get("ProductClass") == "1" else "option",
        "is_trading": row.get("IsTrading") == 1,
        "product_class": row.get("ProductClass"),
    }


class StagedQueryFeed:
    def __init__(self, *, products=None, instruments=None, depth=None, overflow_stage=None):
        self.products = tuple(
            products
            if products is not None
            else (_product_row("DCE", "i"), _product_row("SHFE", "rb"))
        )
        self.instruments = dict(instruments or {})
        self.depth = tuple(
            depth
            if depth is not None
            else (_depth_row("DCE", "i2611"), _depth_row("SHFE", "rb2611"))
        )
        self.overflow_stage = overflow_stage
        self.calls = []
        self.query_instances = []
        self.next_request_id = 100

    def get_session_state(self):
        return {
            "connected": True,
            "read_only_ready": True,
            "connection_generation": 7,
            "trading_day": "20261023",
        }

    def _result(self, kind, rows, kwargs, filters):
        self.next_request_id += 1
        self.query_instances.append(self)
        overflow = self.overflow_stage == kind
        return FakeQueryResult(
            request_type=kind,
            request_id=self.next_request_id,
            records=rows,
            request_filters=filters,
            record_limit=kwargs["max_records"],
            complete=not overflow,
            record_limit_exceeded=overflow,
        )

    def query_products_result(self, **kwargs):
        self.calls.append(("products", dict(kwargs)))
        return self._result(
            "products",
            self.products,
            kwargs,
            (
                ("ExchangeID", kwargs["exchange_id"]),
                ("ProductClass", kwargs["product_class"]),
                ("ProductID", kwargs["product_id"]),
            ),
        )

    def query_instruments_result(self, **kwargs):
        self.calls.append(("instruments", dict(kwargs)))
        key = (kwargs["exchange_id"], kwargs["product_id"])
        rows = self.instruments.get(
            key,
            (_instrument_row(key[0], key[1], key[1] + "2611"),),
        )
        return self._result(
            "instruments",
            rows,
            kwargs,
            (
                ("ExchangeID", kwargs["exchange_id"]),
                ("InstrumentID", kwargs["instrument_id"]),
                ("ProductID", kwargs["product_id"]),
            ),
        )

    def query_depth_market_data_result(self, **kwargs):
        self.calls.append(("depth", dict(kwargs)))
        return self._result(
            "depth_market_data",
            self.depth,
            kwargs,
            (
                ("ExchangeID", kwargs["exchange_id"]),
                ("InstrumentID", kwargs["instrument_id"]),
                ("ProductClass", kwargs["product_class"]),
            ),
        )


def _install_fake_contract(monkeypatch):
    monkeypatch.setattr(
        adapter,
        "_load_sdk_contract",
        lambda: (FakeQueryResult, _normalize_instrument),
    )
    monkeypatch.setattr(adapter, "_now_utc", lambda: NOW)
    # A stable monotonic clock makes the per-request hard-cap allocation exact.
    monkeypatch.setattr(adapter, "time", SimpleNamespace(monotonic=lambda: 100.0))


def _install_synthetic_ctp_modules(monkeypatch):
    """Provide only import-time CTP class leaves for the real wrapper factory."""
    root = ModuleType("bt_api_ctp")
    root.__path__ = []
    ctp = ModuleType("bt_api_ctp.ctp")
    ctp.__path__ = []
    client = ModuleType("bt_api_ctp.ctp.client")
    md_api = ModuleType("bt_api_ctp.ctp.ctp_md_api")
    structs = ModuleType("bt_api_ctp.ctp.ctp_structs_order")
    trader_api = ModuleType("bt_api_ctp.ctp.ctp_trader_api")

    class SyntheticClient:
        pass

    class SyntheticSpi:
        pass

    class SyntheticOrderField:
        pass

    client.MdClient = SyntheticClient
    client.TraderClient = SyntheticClient
    client._MdSpi = type("SyntheticMdSpi", (), {})
    client._TraderSpi = type("SyntheticTraderSpi", (), {})
    md_api.CThostFtdcMdSpi = SyntheticSpi
    structs.CThostFtdcInputOrderActionField = SyntheticOrderField
    structs.CThostFtdcInputOrderField = SyntheticOrderField
    trader_api.CThostFtdcTraderSpi = SyntheticSpi
    root.ctp = ctp
    ctp.client = client
    ctp.ctp_md_api = md_api
    ctp.ctp_structs_order = structs
    ctp.ctp_trader_api = trader_api
    for name, module in (
        ("bt_api_ctp", root),
        ("bt_api_ctp.ctp", ctp),
        ("bt_api_ctp.ctp.client", client),
        ("bt_api_ctp.ctp.ctp_md_api", md_api),
        ("bt_api_ctp.ctp.ctp_structs_order", structs),
        ("bt_api_ctp.ctp.ctp_trader_api", trader_api),
    ):
        monkeypatch.setitem(sys.modules, name, module)


def _calendar(exchange):
    start = date(2026, 1, 1)
    through = date(2027, 1, 1)
    days = []
    current = start
    while current <= through:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return ExchangeTradingCalendar(
        exchange_id=exchange,
        source_id="fixture.{}.calendar".format(exchange.lower()),
        version="fixture-1",
        available_at=NOW - timedelta(days=20),
        retrieved_at=NOW - timedelta(minutes=1),
        coverage_start=start,
        coverage_through=through,
        trading_days=tuple(days),
    )


def test_registered_sim_store_forwards_staged_query_set_through_ctp_wrapper(monkeypatch):
    _install_fake_contract(monkeypatch)
    _install_synthetic_ctp_modules(monkeypatch)
    monkeypatch.setenv("BT_STORE_PROVIDER", "ctp")
    from backtrader.stores.btapistore import _create_ctp_wrapper_class
    from backtrader.stores.registered_sim import RegisteredSimStore, RegisteredSimWrapper

    ctp_wrapper = _create_ctp_wrapper_class()
    wrapper_cls = type(
        "SyntheticRegisteredSimCtpWrapper",
        (RegisteredSimWrapper, ctp_wrapper),
        {"__module__": __name__},
    )
    api = wrapper_cls(registered_sim_allow_writes=False)
    trader = StagedQueryFeed()
    api.trader_client = trader
    api._connected = True
    store = RegisteredSimStore(api=api, autostart=False)
    store._connected = True
    store._ensure_api_ready = lambda: pytest.fail("query collector reopened the Store")

    snapshot = store.registered_sim_collect_futures_snapshot(
        max_collection_seconds=300.0,
        max_snapshot_age_seconds=300.0,
        query_mode="staged_product_set",
    )

    assert store._api is api and api.trader_client is trader
    assert store.allow_writes is False
    assert trader.query_instances == [trader, trader, trader, trader]
    assert [kind for kind, _ in trader.calls] == [
        "products",
        "instruments",
        "instruments",
        "depth",
    ]
    expected_limits = [256, 20_000, 19_999, 20_000]
    assert [kwargs["max_records"] for _, kwargs in trader.calls] == expected_limits
    assert [kwargs["deadline_monotonic"] for _, kwargs in trader.calls] == [400.0] * 4
    assert [kwargs["max_duration"] for _, kwargs in trader.calls] == [
        30.0,
        300.0,
        300.0,
        300.0,
    ]
    assert [kwargs["timeout"] for _, kwargs in trader.calls] == [5.0] * 4
    assert trader.calls[0][1]["product_class"] == "1"
    assert trader.calls[0][1]["exchange_id"] == trader.calls[0][1]["product_id"] == ""
    assert trader.calls[1][1]["product_id"] == "i"
    assert trader.calls[1][1]["exchange_id"] == "DCE"
    assert trader.calls[2][1]["product_id"] == "rb"
    assert trader.calls[2][1]["exchange_id"] == "SHFE"
    assert trader.calls[3][1]["product_class"] == "1"
    assert snapshot.query_set is not None


def _select(snapshot):
    products = tuple(item.product for item in snapshot.query_set.products)
    exchanges = tuple(sorted({product.exchange_id for product in products}))
    return select_main_contracts(
        snapshot,
        products,
        tuple(ExchangeTradingDay(exchange, TRADING_DAY) for exchange in exchanges),
        tuple(_calendar(exchange) for exchange in exchanges),
        decision_at=NOW,
        policy=CTP_QUERY_SNAPSHOT_EQUAL_WEIGHT_POLICY,
    )


def test_staged_query_set_preserves_full_product_set_native_case_and_caps(monkeypatch):
    _install_fake_contract(monkeypatch)
    feed = StagedQueryFeed(
        instruments={
            ("DCE", "i"): (_instrument_row("DCE", "i", "i2611"),),
            ("SHFE", "rb"): (),
        },
        depth=(),
    )

    snapshot = adapter.collect_ctp_futures_snapshot(feed, query_mode="staged_product_set")

    assert [kind for kind, _ in feed.calls] == ["products", "instruments", "instruments", "depth"]
    products_call = feed.calls[0][1]
    assert (
        products_call["product_class"],
        products_call["exchange_id"],
        products_call["product_id"],
    ) == (
        "1",
        "",
        "",
    )
    assert [feed.calls[index][1]["product_id"] for index in (1, 2)] == ["i", "rb"]
    assert [feed.calls[index][1]["exchange_id"] for index in (1, 2)] == ["DCE", "SHFE"]
    assert [feed.calls[index][1]["max_records"] for index in (1, 2)] == [20_000, 19_999]
    assert feed.calls[3][1]["product_class"] == "1"
    assert [kwargs["deadline_monotonic"] for _, kwargs in feed.calls] == [400.0] * 4
    assert [kwargs["max_duration"] for _, kwargs in feed.calls] == [
        30.0,
        300.0,
        300.0,
        300.0,
    ]
    assert [kwargs["timeout"] for _, kwargs in feed.calls] == [5.0] * 4

    query_set = snapshot.query_set
    assert query_set is not None
    assert [(item.product.exchange_id, item.product.product_id) for item in query_set.products] == [
        ("DCE", "I"),
        ("SHFE", "RB"),
    ]
    assert [(item.native_exchange_id, item.native_product_id) for item in query_set.products] == [
        ("DCE", "i"),
        ("SHFE", "rb"),
    ]
    assert [source.request_id for source in query_set.requests] == [101, 102, 103, 104]
    assert [source.record_count for source in query_set.requests] == [2, 1, 0, 0]
    assert query_set.requests[1].request_filters == (
        ("ExchangeID", "DCE"),
        ("InstrumentID", ""),
        ("ProductID", "i"),
    )
    assert query_set.requests[2].request_filters[-1] == ("ProductID", "rb")
    assert len(query_set.source_sha256) == 64


@pytest.mark.parametrize(
    ("products", "expected_code"),
    [
        ((), "PRODUCT_QUERY_EMPTY"),
        ((_product_row("DCE", "i", product_class="2"),), "PRODUCT_CLASS_MISMATCH"),
    ],
)
def test_empty_or_wrong_product_universe_fails_before_instrument_queries(
    monkeypatch, products, expected_code
):
    _install_fake_contract(monkeypatch)
    feed = StagedQueryFeed(products=products)

    with pytest.raises(adapter.CtpFuturesSnapshotError) as caught:
        adapter.collect_ctp_futures_snapshot(feed, query_mode="staged_product_set")

    assert caught.value.code == expected_code
    assert [kind for kind, _ in feed.calls] == ["products"]


def test_instrument_rows_must_match_exact_native_product_filter(monkeypatch):
    _install_fake_contract(monkeypatch)
    feed = StagedQueryFeed(
        products=(_product_row("DCE", "i"),),
        instruments={("DCE", "i"): (_instrument_row("DCE", "I", "I2611"),)},
        depth=(),
    )

    with pytest.raises(adapter.CtpFuturesSnapshotError) as caught:
        adapter.collect_ctp_futures_snapshot(feed, query_mode="staged_product_set")

    assert caught.value.code == "INSTRUMENT_QUERY_ROW_SCOPE_MISMATCH"
    assert feed.calls[1][1]["product_id"] == "i"
    assert [kind for kind, _ in feed.calls] == ["products", "instruments"]


def test_sdk_record_limit_overflow_stays_incomplete_and_fail_closed(monkeypatch):
    _install_fake_contract(monkeypatch)
    feed = StagedQueryFeed(overflow_stage="products")

    with pytest.raises(adapter.CtpFuturesSnapshotError) as caught:
        adapter.collect_ctp_futures_snapshot(feed, query_mode="staged_product_set")

    assert caught.value.code == "QUERY_RECORD_LIMIT_EXCEEDED"
    assert caught.value.query_observations[0].error_category == "record_limit"
    assert caught.value.query_observations[0].requested_record_limit == 256
    assert caught.value.query_observations[0].record_limit_exceeded is True
    assert caught.value.query_observations[0].completion_origin == "record_limit"
    assert [kind for kind, _ in feed.calls] == ["products"]


def test_complete_query_set_runs_through_the_existing_full_pool_selector(monkeypatch):
    _install_fake_contract(monkeypatch)
    feed = StagedQueryFeed()
    snapshot = adapter.collect_ctp_futures_snapshot(feed, query_mode="staged_product_set")
    products = tuple(item.product for item in snapshot.query_set.products)
    manifest = _select(snapshot)

    assert manifest.status == "READY"
    assert manifest.blockers == ()
    assert tuple(product for product, _ in manifest.selected_mapping()) == products
    projection = manifest.to_dict()["query_snapshot"]["query_set"]
    assert [item["native_product_id"] for item in projection["products"]] == ["i", "rb"]
    assert len(projection["requests"]) == len(products) + 2


def test_tampered_query_set_identity_blocks_selection(monkeypatch):
    _install_fake_contract(monkeypatch)
    snapshot = adapter.collect_ctp_futures_snapshot(
        StagedQueryFeed(), query_mode="staged_product_set"
    )
    tampered_set = replace(snapshot.query_set, snapshot_id="unbound-query-set")
    tampered_snapshot = replace(snapshot, query_set=tampered_set)

    manifest = _select(tampered_snapshot)

    assert manifest.status == "BLOCKED"
    assert "QUERY_SET_SNAPSHOT_ID_MISMATCH" in manifest.blockers


def test_depth_rows_outside_the_catalog_are_retained_and_block_selection(monkeypatch):
    _install_fake_contract(monkeypatch)
    outside_quote = _depth_row("DCE", "unknown2611")
    snapshot = adapter.collect_ctp_futures_snapshot(
        StagedQueryFeed(depth=(outside_quote,)), query_mode="staged_product_set"
    )

    manifest = _select(snapshot)

    assert snapshot.quote_records[0].instrument_id == "unknown2611"
    assert manifest.status == "BLOCKED"
    assert "QUOTE_ID_NOT_IN_CATALOG" in manifest.blockers
