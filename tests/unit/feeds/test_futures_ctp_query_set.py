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
    ProductKey,
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
        completion_origin=None,
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
        if completion_origin is None:
            completion_origin = "success" if complete else "record_limit"
        self.first_completion_origin = completion_origin
        self.completion_origin = completion_origin
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


def _depth_row(exchange, instrument_id, open_interest=1000):
    return {
        "ExchangeID": exchange,
        "InstrumentID": instrument_id,
        "TradingDay": "20261023",
        "OpenInterest": open_interest,
        "Volume": 800,
        "ActionDay": "20261023",
        "UpdateTime": "09:30:00",
        "UpdateMillisec": 0,
    }


def _normalize_instrument(row):
    asset_type = {
        "1": "future",
        "2": "option",
        "3": "combination",
        "4": "spot",
        "5": "efp",
        "6": "spot_option",
        "7": "tas",
        "I": "mi",
    }.get(row.get("ProductClass"), "unknown")
    return {
        "asset_type": asset_type,
        "is_trading": row.get("IsTrading") == 1,
        "product_class": row.get("ProductClass"),
    }


class StagedQueryFeed:
    def __init__(
        self,
        *,
        products=None,
        instruments=None,
        depth=None,
        depth_by_product=None,
        incomplete_depth_for=(),
        overflow_stage=None,
    ):
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
        self.depth_by_product = {
            key: tuple(rows) for key, rows in dict(depth_by_product or {}).items()
        }
        self.incomplete_depth_for = frozenset(incomplete_depth_for)
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

    def _result(self, kind, rows, kwargs, filters, complete=None):
        self.next_request_id += 1
        self.query_instances.append(self)
        overflow = self.overflow_stage == kind
        if complete is None:
            complete = not overflow
        return FakeQueryResult(
            request_type=kind,
            request_id=self.next_request_id,
            records=rows,
            request_filters=filters,
            record_limit=kwargs["max_records"],
            complete=complete,
            record_limit_exceeded=overflow,
            completion_origin=(
                "record_limit" if overflow else "success"
            ),
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
        key = (kwargs["exchange_id"], kwargs["instrument_id"])
        complete = True
        if kwargs["instrument_id"]:
            rows = self.depth_by_product.get(key, ())
            if key in self.incomplete_depth_for:
                complete = False
        else:
            rows = self.depth
        return self._result(
            "depth_market_data",
            rows,
            kwargs,
            (
                ("ExchangeID", kwargs["exchange_id"]),
                ("InstrumentID", kwargs["instrument_id"]),
                ("ProductClass", kwargs["product_class"]),
            ),
            complete=complete,
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
    assert trader.calls[0][1]["product_class"] == ""
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


def test_staged_query_set_classifies_all_products_and_queries_only_futures(monkeypatch):
    _install_fake_contract(monkeypatch)
    non_future_rows = tuple(
        _product_row("DCE", "n{:02d}".format(index), product_class=product_class)
        for index, product_class in enumerate(("2", "3", "4", "5", "6", "7", "I"), 1)
    )
    feed = StagedQueryFeed(
        products=(
            _product_row("DCE", "i"),
            _product_row("SHFE", "rb"),
            *non_future_rows,
        ),
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
        "",
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
    assert [source.record_count for source in query_set.requests] == [9, 1, 0, 0]
    assert [item.product_class for item in query_set.products] == ["1", "1"]
    assert [item.product_class for item in query_set.excluded_products] == [
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "I",
    ]
    assert [item.asset_type for item in query_set.excluded_products] == [
        "option",
        "combination",
        "spot",
        "efp",
        "spot_option",
        "tas",
        "mi",
    ]
    assert all(
        item.exclusion_reason == "NON_FUTURE_CTP_PRODUCT_CLASS"
        for item in query_set.excluded_products
    )
    assert feed.calls[0][1]["max_records"] == 256
    assert query_set.requests[1].request_filters == (
        ("ExchangeID", "DCE"),
        ("InstrumentID", ""),
        ("ProductID", "i"),
    )
    assert query_set.requests[2].request_filters[-1] == ("ProductID", "rb")
    assert len(query_set.source_sha256) == 64
    manifest = _select(snapshot)
    projection = manifest.to_dict()["query_snapshot"]["query_set"]
    assert len(projection["excluded_products"]) == 7
    assert projection["digest_schema"] == "v2"
    assert projection["requests"][0]["record_count"] == 9


@pytest.mark.parametrize(
    ("products", "expected_code"),
    [
        ((), "PRODUCT_QUERY_EMPTY"),
        ((_product_row("DCE", "i", product_class="9"),), "PRODUCT_CLASS_UNKNOWN"),
        (({"ExchangeID": "DCE", "ProductID": "i"},), "PRODUCT_CLASS_MISSING"),
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
    observation = caught.value.query_observations[0]
    assert observation.record_count == len(products)
    assert observation.complete is True
    assert observation.is_last_seen is True
    assert observation.record_limit_matches is True
    assert observation.record_limit_exceeded is False
    assert observation.request_filters_match is True
    assert observation.classified_future_product_count is None
    assert observation.classified_excluded_product_count is None


def test_non_future_only_product_result_is_classified_but_stops_before_depth(monkeypatch):
    _install_fake_contract(monkeypatch)
    feed = StagedQueryFeed(products=(_product_row("DCE", "opt", product_class="2"),))

    with pytest.raises(adapter.CtpFuturesSnapshotError) as caught:
        adapter.collect_ctp_futures_snapshot(feed, query_mode="staged_product_set")

    assert caught.value.code == "PRODUCT_FUTURE_SET_EMPTY"
    assert [kind for kind, _ in feed.calls] == ["products"]
    observation = caught.value.query_observations[0]
    assert observation.record_count == 1
    assert observation.classified_future_product_count == 0
    assert observation.classified_excluded_product_count == 1


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


@pytest.mark.parametrize(
    ("instrument_class", "expected_code"),
    [
        ("2", "INSTRUMENT_PRODUCT_CLASS_MISMATCH"),
        ("9", "CATALOG_PRODUCT_CLASS_UNKNOWN"),
    ],
)
def test_instrument_rows_with_mixed_or_unknown_class_block_before_depth(
    monkeypatch, instrument_class, expected_code
):
    _install_fake_contract(monkeypatch)
    feed = StagedQueryFeed(
        products=(_product_row("DCE", "i", product_class="1"),),
        instruments={
            ("DCE", "i"): (
                _instrument_row("DCE", "i", "i2611", instrument_class),
            )
        },
    )

    with pytest.raises(adapter.CtpFuturesSnapshotError) as caught:
        adapter.collect_ctp_futures_snapshot(feed, query_mode="staged_product_set")

    assert caught.value.code == expected_code
    assert [kind for kind, _ in feed.calls] == ["products", "instruments"]


def test_normalizer_cannot_reclassify_raw_non_future_instrument_as_future(monkeypatch):
    _install_fake_contract(monkeypatch)

    def misclassify(row):
        normalized = _normalize_instrument(row)
        normalized["product_class"] = "1"
        normalized["asset_type"] = "future"
        return normalized

    monkeypatch.setattr(adapter, "_load_sdk_contract", lambda: (FakeQueryResult, misclassify))
    feed = StagedQueryFeed(
        products=(_product_row("DCE", "i", product_class="1"),),
        instruments={
            ("DCE", "i"): (_instrument_row("DCE", "i", "i2611", "2"),)
        },
    )

    with pytest.raises(adapter.CtpFuturesSnapshotError) as caught:
        adapter.collect_ctp_futures_snapshot(feed, query_mode="staged_product_set")

    assert caught.value.code == "CATALOG_PRODUCT_CLASS_MISMATCH"
    assert [kind for kind, _ in feed.calls] == ["products", "instruments"]


def test_duplicate_product_key_across_classes_blocks_before_instrument_queries(monkeypatch):
    _install_fake_contract(monkeypatch)
    feed = StagedQueryFeed(
        products=(
            _product_row("DCE", "i", product_class="1"),
            _product_row("DCE", "i", product_class="2"),
        )
    )

    with pytest.raises(adapter.CtpFuturesSnapshotError) as caught:
        adapter.collect_ctp_futures_snapshot(feed, query_mode="staged_product_set")

    assert caught.value.code == "PRODUCT_CLASS_CONFLICT"
    assert [kind for kind, _ in feed.calls] == ["products"]


def test_sdk_record_limit_overflow_stays_incomplete_and_fail_closed(monkeypatch):
    _install_fake_contract(monkeypatch)
    products = tuple(
        _product_row("DCE", "p{:03d}".format(index), product_class="2")
        for index in range(257)
    )
    feed = StagedQueryFeed(products=products, overflow_stage="products")

    with pytest.raises(adapter.CtpFuturesSnapshotError) as caught:
        adapter.collect_ctp_futures_snapshot(feed, query_mode="staged_product_set")

    assert caught.value.code == "QUERY_RECORD_LIMIT_EXCEEDED"
    assert caught.value.query_observations[0].error_category == "record_limit"
    assert caught.value.query_observations[0].requested_record_limit == 256
    assert caught.value.query_observations[0].record_count == 257
    assert caught.value.query_observations[0].record_limit_exceeded is True
    assert caught.value.query_observations[0].completion_origin == "record_limit"
    assert [kind for kind, _ in feed.calls] == ["products"]


def test_exact_product_row_cap_with_terminal_and_no_overflow_is_complete(monkeypatch):
    _install_fake_contract(monkeypatch)
    products = (
        _product_row("DCE", "future"),
        *(
            _product_row("DCE", "other{:03d}".format(index), product_class="2")
            for index in range(255)
        ),
    )
    feed = StagedQueryFeed(products=products, depth=())

    snapshot = adapter.collect_ctp_futures_snapshot(feed, query_mode="staged_product_set")

    product_source = snapshot.query_set.requests[0]
    assert len(snapshot.query_set.products) == 1
    assert len(snapshot.query_set.excluded_products) == 255
    assert product_source.record_count == product_source.record_limit == 256
    assert product_source.complete is True
    assert product_source.is_last_seen is True
    assert product_source.record_limit_exceeded is False
    assert [kind for kind, _ in feed.calls] == ["products", "instruments", "depth"]


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


def test_excluded_product_classification_is_bound_by_query_set_digest(monkeypatch):
    _install_fake_contract(monkeypatch)
    snapshot = adapter.collect_ctp_futures_snapshot(
        StagedQueryFeed(
            products=(
                _product_row("DCE", "i"),
                _product_row("DCE", "opt", product_class="2"),
            )
        ),
        query_mode="staged_product_set",
    )
    original_exclusion = snapshot.query_set.excluded_products[0]
    tampered_exclusion = replace(
        original_exclusion,
        product_class="3",
        asset_type="combination",
    )
    tampered_set = replace(
        snapshot.query_set,
        excluded_products=(tampered_exclusion,),
    )

    manifest = _select(replace(snapshot, query_set=tampered_set))

    assert manifest.status == "BLOCKED"
    assert "QUERY_SET_SOURCE_DIGEST_MISMATCH" in manifest.blockers


def test_catalog_replacement_is_bound_to_per_product_instrument_counts(monkeypatch):
    _install_fake_contract(monkeypatch)
    snapshot = adapter.collect_ctp_futures_snapshot(
        StagedQueryFeed(), query_mode="staged_product_set"
    )
    first, *rest = snapshot.catalog_records
    # Keep the total catalog count unchanged while moving one row from DCE/i
    # to SHFE/rb. Per-product request counts must detect the altered scope.
    replaced = replace(first, product=ProductKey("SHFE", "RB"))

    manifest = _select(replace(snapshot, catalog_records=(replaced, *rest)))

    assert manifest.status == "BLOCKED"
    assert "QUERY_SET_PRODUCT_INSTRUMENT_RECORD_COUNT_MISMATCH" in manifest.blockers


def test_catalog_non_target_product_is_rejected_even_with_class_one(monkeypatch):
    _install_fake_contract(monkeypatch)
    snapshot = adapter.collect_ctp_futures_snapshot(
        StagedQueryFeed(
            products=(
                _product_row("DCE", "i"),
                _product_row("DCE", "opt", product_class="2"),
            )
        ),
        query_mode="staged_product_set",
    )
    first, *rest = snapshot.catalog_records
    replaced = replace(first, product=ProductKey("DCE", "OPT"))

    manifest = _select(replace(snapshot, catalog_records=(replaced, *rest)))

    assert manifest.status == "BLOCKED"
    assert "QUERY_SET_CATALOG_PRODUCT_OUT_OF_SCOPE" in manifest.blockers


def test_catalog_non_future_class_is_rejected_for_future_product(monkeypatch):
    _install_fake_contract(monkeypatch)
    snapshot = adapter.collect_ctp_futures_snapshot(
        StagedQueryFeed(), query_mode="staged_product_set"
    )
    first, *rest = snapshot.catalog_records
    replaced = replace(first, product_class="2", asset_type="option")

    manifest = _select(replace(snapshot, catalog_records=(replaced, *rest)))

    assert manifest.status == "BLOCKED"
    assert "QUERY_SET_CATALOG_PRODUCT_CLASS_MISMATCH" in manifest.blockers


def test_legacy_class_one_query_set_evidence_remains_readable(monkeypatch):
    from backtrader.feeds.futures_main_contract import (
        query_snapshot_set_digest,
    )

    _install_fake_contract(monkeypatch)
    snapshot = adapter.collect_ctp_futures_snapshot(
        StagedQueryFeed(), query_mode="staged_product_set"
    )
    query_set = snapshot.query_set
    product_source = replace(
        query_set.requests[0],
        request_filters=(
            ("ExchangeID", ""),
            ("ProductClass", "1"),
            ("ProductID", ""),
        ),
    )
    requests = (product_source,) + query_set.requests[1:]
    digest = query_snapshot_set_digest(query_set.products, requests)
    legacy_set = replace(
        query_set,
        snapshot_id="ctp-visible-futures-set:7:20261023:{}".format(digest[:16]),
        source_sha256=digest,
        requests=requests,
        excluded_products=(),
    )

    manifest = _select(replace(snapshot, query_set=legacy_set))

    assert manifest.status == "READY"
    assert manifest.blockers == ()
    projection = manifest.to_dict()["query_snapshot"]["query_set"]
    assert projection["digest_schema"] == "v1"
    assert projection["excluded_products"] == []


def test_malformed_product_request_filters_fail_closed_without_raising(monkeypatch):
    from backtrader.feeds.futures_main_contract import query_snapshot_set_digest

    _install_fake_contract(monkeypatch)
    snapshot = adapter.collect_ctp_futures_snapshot(
        StagedQueryFeed(), query_mode="staged_product_set"
    )
    query_set = snapshot.query_set
    malformed_product_source = replace(
        query_set.requests[0],
        request_filters=(("ProductClass",),),
    )
    requests = (malformed_product_source,) + query_set.requests[1:]
    digest = query_snapshot_set_digest(query_set.products, requests)
    tampered_set = replace(
        query_set,
        snapshot_id="ctp-visible-futures-set:7:20261023:{}".format(digest[:16]),
        source_sha256=digest,
        requests=requests,
    )

    manifest = _select(replace(snapshot, query_set=tampered_set))

    assert manifest.status == "BLOCKED"
    assert "QUERY_SET_PRODUCT_FILTER_MODE_INVALID" in manifest.blockers


def test_depth_rows_outside_the_catalog_are_retained_and_block_selection(monkeypatch):
    _install_fake_contract(monkeypatch)
    outside_quote = _depth_row("DCE", "opt2611")
    snapshot = adapter.collect_ctp_futures_snapshot(
        StagedQueryFeed(
            products=(
                _product_row("DCE", "i", product_class="1"),
                _product_row("DCE", "opt", product_class="2"),
            ),
            depth=(outside_quote,),
        ),
        query_mode="staged_product_set",
    )

    manifest = _select(snapshot)

    assert snapshot.quote_records[0].instrument_id == "opt2611"
    assert snapshot.query_set.excluded_products[0].product_class == "2"
    assert manifest.status == "BLOCKED"
    assert "QUOTE_ID_NOT_IN_CATALOG" in manifest.blockers


def _per_product_feed(**overrides):
    defaults = dict(
        products=(_product_row("DCE", "i"), _product_row("SHFE", "rb")),
        instruments={
            ("DCE", "i"): (
                _instrument_row("DCE", "i", "i2611"),
                _instrument_row("DCE", "i", "i2612"),
            ),
            ("SHFE", "rb"): (_instrument_row("SHFE", "rb", "rb2611"),),
        },
        depth_by_product={
            ("DCE", "i"): (
                _depth_row("DCE", "i2611", open_interest=1000),
                _depth_row("DCE", "i2612", open_interest=900),
            ),
            ("SHFE", "rb"): (_depth_row("SHFE", "rb2611"),),
        },
    )
    defaults.update(overrides)
    return StagedQueryFeed(**defaults)


def test_per_product_depth_query_layout_is_ready_and_digest_bound(monkeypatch):
    _install_fake_contract(monkeypatch)
    from backtrader.feeds.futures_main_contract import query_snapshot_set_digest

    feed = _per_product_feed()
    snapshot = adapter.collect_ctp_futures_snapshot(feed, query_mode="staged_product_depth")

    assert [kind for kind, _ in feed.calls] == [
        "products",
        "instruments",
        "instruments",
        "depth",
        "depth",
    ]
    assert [kwargs["max_records"] for _, kwargs in feed.calls] == [
        256,
        20_000,
        19_998,
        20_000,
        19_998,
    ]
    depth_calls = [kwargs for kind, kwargs in feed.calls if kind == "depth"]
    assert [call["instrument_id"] for call in depth_calls] == ["i", "rb"]
    assert [call["exchange_id"] for call in depth_calls] == ["DCE", "SHFE"]
    assert [call["product_class"] for call in depth_calls] == ["1", "1"]

    query_set = snapshot.query_set
    assert query_set.request_layout == "per_product_depth"
    assert len(query_set.requests) == 2 * len(query_set.products) + 1
    assert [source.source_kind for source in query_set.requests] == [
        "products",
        "instruments",
        "instruments",
        "depth_market_data",
        "depth_market_data",
    ]
    assert query_set.requests[3].request_filters == (
        ("ExchangeID", "DCE"),
        ("InstrumentID", "i"),
        ("ProductClass", "1"),
    )
    assert query_set.requests[4].request_filters == (
        ("ExchangeID", "SHFE"),
        ("InstrumentID", "rb"),
        ("ProductClass", "1"),
    )
    assert [source.record_count for source in query_set.requests[3:]] == [2, 1]
    assert query_snapshot_set_digest(
        query_set.products,
        query_set.requests,
        query_set.excluded_products,
        request_layout="per_product_depth",
    ) == query_set.source_sha256
    # The default digest form must not match the layout-bound digest.
    assert query_snapshot_set_digest(
        query_set.products, query_set.requests, query_set.excluded_products
    ) != query_set.source_sha256

    manifest = _select(snapshot)
    assert manifest.status == "READY"
    assert manifest.blockers == ()
    assert dict(manifest.selected_mapping()) == {
        ProductKey("DCE", "I"): "i2611",
        ProductKey("SHFE", "RB"): "rb2611",
    }
    projection = manifest.to_dict()["query_snapshot"]["query_set"]
    assert projection["request_layout"] == "per_product_depth"


def test_per_product_depth_queries_zero_instrument_product(monkeypatch):
    _install_fake_contract(monkeypatch)
    feed = _per_product_feed(
        products=(_product_row("DCE", "i"), _product_row("DCE", "lr")),
        instruments={
            ("DCE", "i"): (_instrument_row("DCE", "i", "i2611"),),
            ("DCE", "lr"): (),
        },
        depth_by_product={
            ("DCE", "i"): (_depth_row("DCE", "i2611"),),
            ("DCE", "lr"): (),
        },
    )

    snapshot = adapter.collect_ctp_futures_snapshot(feed, query_mode="staged_product_depth")

    depth_calls = [kwargs for kind, kwargs in feed.calls if kind == "depth"]
    assert [call["instrument_id"] for call in depth_calls] == ["i", "lr"]
    assert [source.record_count for source in snapshot.query_set.requests[3:]] == [1, 0]
    assert [row.instrument_id for row in snapshot.quote_records] == ["i2611"]
    manifest = _select(snapshot)
    assert manifest.status == "READY"
    assert manifest.blockers == ()
    assert tuple(manifest.target_products) == (ProductKey("DCE", "I"),)
    excluded = next(item for item in manifest.products if item.product.product_id == "LR")
    assert excluded.exclusion_reason == "NO_LISTED_CONTRACTS"


def test_incomplete_per_product_depth_blocks_collection(monkeypatch):
    _install_fake_contract(monkeypatch)
    feed = _per_product_feed(incomplete_depth_for=(("SHFE", "rb"),))

    with pytest.raises(adapter.CtpFuturesSnapshotError) as caught:
        adapter.collect_ctp_futures_snapshot(feed, query_mode="staged_product_depth")

    assert caught.value.code == "QUERY_INCOMPLETE"
    assert [kind for kind, _ in feed.calls] == [
        "products",
        "instruments",
        "instruments",
        "depth",
        "depth",
    ]


def test_per_product_depth_row_outside_every_catalog_blocks(monkeypatch):
    _install_fake_contract(monkeypatch)
    feed = _per_product_feed(
        depth_by_product={
            ("DCE", "i"): (_depth_row("DCE", "zz2611"),),
            ("SHFE", "rb"): (_depth_row("SHFE", "rb2611"),),
        }
    )

    with pytest.raises(adapter.CtpFuturesSnapshotError) as caught:
        adapter.collect_ctp_futures_snapshot(feed, query_mode="staged_product_depth")

    assert caught.value.code == "DEPTH_PRODUCT_ROW_SCOPE_MISMATCH"


def test_per_product_depth_discards_sibling_product_prefix_spillover(monkeypatch):
    _install_fake_contract(monkeypatch)
    # Live CTP treats InstrumentID as a prefix: the DCE "j" query also returns
    # sibling "jd" rows. A row attributed to another class-1 product's catalog
    # is discarded here and retained by that product's own depth query.
    feed = _per_product_feed(
        products=(_product_row("DCE", "j"), _product_row("DCE", "jd")),
        instruments={
            ("DCE", "j"): (_instrument_row("DCE", "j", "j2611"),),
            ("DCE", "jd"): (_instrument_row("DCE", "jd", "jd2611"),),
        },
        depth_by_product={
            ("DCE", "j"): (
                _depth_row("DCE", "j2611"),
                _depth_row("DCE", "jd2611"),
            ),
            ("DCE", "jd"): (_depth_row("DCE", "jd2611"),),
        },
    )

    snapshot = adapter.collect_ctp_futures_snapshot(feed, query_mode="staged_product_depth")

    assert [row.instrument_id for row in snapshot.quote_records] == [
        "j2611",
        "jd2611",
    ]
    query_set = snapshot.query_set
    assert [source.record_count for source in query_set.requests[3:]] == [1, 1]
    manifest = _select(snapshot)
    assert manifest.status == "READY"
    assert manifest.blockers == ()


def test_per_product_duplicate_depth_rows_block(monkeypatch):
    _install_fake_contract(monkeypatch)
    duplicate = _depth_row("SHFE", "rb2611")
    feed = _per_product_feed(
        depth_by_product={
            ("DCE", "i"): (_depth_row("DCE", "i2611"),),
            ("SHFE", "rb"): (duplicate, dict(duplicate)),
        }
    )

    with pytest.raises(adapter.CtpFuturesSnapshotError) as caught:
        adapter.collect_ctp_futures_snapshot(feed, query_mode="staged_product_depth")

    assert caught.value.code == "QUOTE_ROW_DUPLICATE"


def test_legacy_single_depth_layout_is_explicit_and_unchanged(monkeypatch):
    _install_fake_contract(monkeypatch)
    from backtrader.feeds.futures_main_contract import query_snapshot_set_digest

    snapshot = adapter.collect_ctp_futures_snapshot(
        StagedQueryFeed(), query_mode="staged_product_set"
    )

    query_set = snapshot.query_set
    assert query_set.request_layout == "single_depth"
    assert len(query_set.requests) == len(query_set.products) + 2
    assert query_snapshot_set_digest(
        query_set.products, query_set.requests, query_set.excluded_products
    ) == query_set.source_sha256
    assert _select(snapshot).status == "READY"
