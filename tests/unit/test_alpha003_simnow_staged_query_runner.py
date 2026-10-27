"""Runner contracts for the public staged CTP futures query mode."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from backtrader.feeds import futures_ctp_snapshot as snapshot_adapter
from backtrader.feeds import futures_main_contract


ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "unified" / "028_alpha003_simnow_minute"
RUNNER_PATH = EXAMPLE / "run.py"
UTC = timezone.utc
TRADING_DAY = date(2026, 10, 27)
NOW = datetime(2026, 10, 27, 0, 29, tzinfo=UTC)
DECISION_AT = datetime(2026, 10, 27, 0, 30, tzinfo=UTC)
PRODUCT_IDS = ("M", "Y", "A")


def _load_runner():
    example_path = str(EXAMPLE)
    if example_path not in sys.path:
        sys.path.insert(0, example_path)
    spec = importlib.util.spec_from_file_location(
        "alpha003_simnow_staged_query_runner_under_test", RUNNER_PATH
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


RUNNER = _load_runner()


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
        self.query_source = SimpleNamespace(request_filters=tuple(sorted(request_filters)))


def _normalize_instrument(row):
    return {
        "asset_type": "future" if row.get("ProductClass") == "1" else "option",
        "is_trading": row.get("IsTrading") == 1,
        "product_class": row.get("ProductClass"),
    }


def _product_row(product_id):
    return {"ExchangeID": "DCE", "ProductID": product_id, "ProductClass": "1"}


def _instrument_row(product_id):
    return {
        "ExchangeID": "DCE",
        "ProductID": product_id,
        "ProductClass": "1",
        "InstrumentID": product_id + "2611",
        "IsTrading": 1,
        "ExpireDate": "20261218",
    }


def _depth_row(product_id):
    return {
        "ExchangeID": "DCE",
        "InstrumentID": product_id + "2611",
        "TradingDay": TRADING_DAY.strftime("%Y%m%d"),
        "OpenInterest": 1000,
        "Volume": 800,
        "ActionDay": TRADING_DAY.strftime("%Y%m%d"),
        "UpdateTime": "08:29:00",
        "UpdateMillisec": 0,
    }


class FakeStagedQueryFeed:
    def __init__(
        self,
        *,
        missing_instruments=(),
        overflow_stage=None,
        oversized_stage=None,
        oversized_count=0,
        wrong_product_filter=False,
    ):
        self.missing_instruments = frozenset(missing_instruments)
        self.overflow_stage = overflow_stage
        self.oversized_stage = oversized_stage
        self.oversized_count = oversized_count
        self.wrong_product_filter = wrong_product_filter
        self.calls = []
        self.request_id = 100

    def get_session_state(self):
        return {
            "connected": True,
            "read_only_ready": True,
            "connection_generation": 7,
            "trading_day": TRADING_DAY.strftime("%Y%m%d"),
        }

    def _result(self, kind, records, filters, kwargs):
        self.request_id += 1
        overflow = self.overflow_stage == kind
        diagnostic_stage = "depth" if kind == "depth_market_data" else kind
        if self.oversized_stage == diagnostic_stage and records:
            records = (records[0],) * self.oversized_count
        return FakeQueryResult(
            request_type=kind,
            request_id=self.request_id,
            records=records,
            request_filters=filters,
            record_limit=kwargs["max_records"],
            complete=not overflow,
            record_limit_exceeded=overflow,
        )

    def query_products_result(self, **kwargs):
        self.calls.append(("products", dict(kwargs)))
        filters = (
            ("ExchangeID", kwargs["exchange_id"]),
            (
                "ProductClass",
                "2" if self.wrong_product_filter else kwargs["product_class"],
            ),
            ("ProductID", kwargs["product_id"]),
        )
        return self._result("products", tuple(map(_product_row, PRODUCT_IDS)), filters, kwargs)

    def query_instruments_result(self, **kwargs):
        self.calls.append(("instruments", dict(kwargs)))
        product_id = kwargs["product_id"]
        rows = () if product_id in self.missing_instruments else (_instrument_row(product_id),)
        filters = (
            ("ExchangeID", kwargs["exchange_id"]),
            ("InstrumentID", kwargs["instrument_id"]),
            ("ProductID", product_id),
        )
        return self._result("instruments", rows, filters, kwargs)

    def query_depth_market_data_result(self, **kwargs):
        self.calls.append(("depth", dict(kwargs)))
        filters = (
            ("ExchangeID", kwargs["exchange_id"]),
            ("InstrumentID", kwargs["instrument_id"]),
            ("ProductClass", kwargs["product_class"]),
        )
        return self._result(
            "depth_market_data", tuple(map(_depth_row, PRODUCT_IDS)), filters, kwargs
        )


class SnapshotStore:
    def __init__(self, feed):
        self.feed = feed
        self.snapshot = None
        self.collect_calls = []

    def registered_sim_collect_futures_snapshot(self, **kwargs):
        self.collect_calls.append(dict(kwargs))
        self.snapshot = snapshot_adapter.collect_ctp_futures_snapshot(
            self.feed, **kwargs
        )
        return self.snapshot


def _install_query_fixture(monkeypatch):
    monkeypatch.setattr(
        snapshot_adapter,
        "_load_sdk_contract",
        lambda: (FakeQueryResult, _normalize_instrument),
    )
    monkeypatch.setattr(snapshot_adapter, "_now_utc", lambda: NOW)
    monkeypatch.setattr(snapshot_adapter, "time", SimpleNamespace(monotonic=lambda: 100.0))


def _query_config():
    return {"selection": {"query_mode": "staged_product_set", "authorized_products": None}}


class FixedClock:
    def utc_now(self):
        return DECISION_AT


def test_staged_query_plan_uses_real_full_product_query_set_and_its_identity(monkeypatch):
    _install_query_fixture(monkeypatch)
    feed = FakeStagedQueryFeed()
    store = SnapshotStore(feed)

    plan = RUNNER.build_ctp_query_market_plan(store, _query_config(), clock=FixedClock())

    expected_products = tuple(
        futures_main_contract.ProductKey("DCE", item) for item in sorted(PRODUCT_IDS)
    )
    assert store.collect_calls == [
        {
            "max_collection_seconds": 300.0,
            "max_snapshot_age_seconds": 300.0,
            "query_mode": "staged_product_set",
        }
    ]
    assert tuple(item.product for item in store.snapshot.query_set.products) == expected_products
    assert plan["manifest"].status == "READY"
    assert tuple(plan["products"]) == expected_products
    assert tuple(plan["targets"]) == tuple(
        "DCE." + item for item in sorted(PRODUCT_IDS)
    )
    assert tuple(plan["manifest"].target_products) == expected_products
    assert plan["source_snapshot_id"] == store.snapshot.query_set.snapshot_id
    assert plan["selection_path"] == "ctp-query://" + store.snapshot.query_set.snapshot_id
    manifest_projection = plan["manifest"].to_dict()["query_snapshot"]
    query_evidence = manifest_projection["query_set"]
    assert [row["product"]["product_id"] for row in query_evidence["products"]] == [
        "A",
        "M",
        "Y",
    ]
    assert len(query_evidence["requests"]) == len(expected_products) + 2
    assert len(manifest_projection["catalog_records"]) == len(expected_products)
    assert len(manifest_projection["quote_records"]) == len(expected_products)
    assert query_evidence["requests"][0]["request_filters"] == [
        ["ExchangeID", ""],
        ["ProductClass", "1"],
        ["ProductID", ""],
    ]


def test_missing_instrument_coverage_still_selects_against_full_product_set(monkeypatch):
    _install_query_fixture(monkeypatch)
    feed = FakeStagedQueryFeed(missing_instruments=("Y",))
    store = SnapshotStore(feed)
    selector = futures_main_contract.select_main_contracts
    requested_pools = []

    def record_full_pool(snapshot, target_products, *args, **kwargs):
        requested_pools.append(tuple(target_products))
        return selector(snapshot, target_products, *args, **kwargs)

    monkeypatch.setattr(futures_main_contract, "select_main_contracts", record_full_pool)

    with pytest.raises(RUNNER.RunnerError) as caught:
        RUNNER.build_ctp_query_market_plan(store, _query_config(), clock=FixedClock())

    expected_products = tuple(
        futures_main_contract.ProductKey("DCE", item) for item in sorted(PRODUCT_IDS)
    )
    assert caught.value.code == "POINT_IN_TIME_SELECTION_BLOCKED"
    assert store.snapshot.query_set is not None
    assert tuple(item.product for item in store.snapshot.query_set.products) == expected_products
    assert requested_pools == [expected_products]
    assert [kind for kind, _ in feed.calls] == [
        "products",
        "instruments",
        "instruments",
        "instruments",
        "depth",
    ]


@pytest.mark.parametrize(
    ("feed_options", "expected_detail", "expected_category"),
    [
        ({"overflow_stage": "products"}, "QUERY_RECORD_LIMIT_EXCEEDED", "record_limit"),
        ({"wrong_product_filter": True}, "QUERY_REQUEST_FILTERS_MISMATCH", "scope_mismatch"),
    ],
)
def test_staged_query_failures_keep_bounded_limit_and_scope_diagnostics(
    monkeypatch, feed_options, expected_detail, expected_category
):
    _install_query_fixture(monkeypatch)
    store = SnapshotStore(FakeStagedQueryFeed(**feed_options))

    with pytest.raises(RUNNER.RunnerError) as caught:
        RUNNER.build_ctp_query_market_plan(store, _query_config(), clock=FixedClock())

    assert caught.value.code == "CTP_FUTURES_SNAPSHOT_COLLECTION_FAILED"
    assert caught.value.detail == expected_detail
    diagnostic = caught.value.query_diagnostics
    assert diagnostic["status"] == "AVAILABLE"
    assert len(diagnostic["stages"]) == 1
    stage = diagnostic["stages"][0]
    assert stage["stage"] == "products"
    assert stage["requested_record_limit"] == 256
    assert stage["record_limit_observed"] == 256
    assert stage["error_category"] == expected_category


@pytest.mark.parametrize(
    ("stage_name", "row_count", "expected_count", "count_capped", "stage_count"),
    [
        ("products", 257, 257, False, 1),
        ("products", 20_001, 20_000, True, 1),
        ("depth", 20_001, 20_000, True, 5),
    ],
)
def test_staged_row_overflow_diagnostics_use_observed_count_not_sdk_flag(
    monkeypatch, stage_name, row_count, expected_count, count_capped, stage_count
):
    _install_query_fixture(monkeypatch)
    store = SnapshotStore(
        FakeStagedQueryFeed(oversized_stage=stage_name, oversized_count=row_count)
    )

    with pytest.raises(RUNNER.RunnerError) as caught:
        RUNNER.build_ctp_query_market_plan(store, _query_config(), clock=FixedClock())

    assert caught.value.code == "CTP_FUTURES_SNAPSHOT_COLLECTION_FAILED"
    assert caught.value.detail == "QUERY_RECORD_LIMIT_EXCEEDED"
    diagnostic = caught.value.query_diagnostics
    assert diagnostic["status"] == "AVAILABLE"
    assert len(diagnostic["stages"]) == stage_count
    stage = diagnostic["stages"][-1]
    assert stage["stage"] == stage_name
    assert stage["record_count"] == expected_count
    assert stage["record_count_capped"] is count_capped
    assert stage["requested_record_limit"] == (256 if stage_name == "products" else 20_000)
    assert stage["record_limit_observed"] == stage["requested_record_limit"]
    assert stage["record_limit_exceeded"] is True
    assert stage["error_category"] == "record_limit"

    # A contradictory sanitized projection must not turn an observed row or
    # diagnostic-cap overflow into an apparently successful query.
    contradictory = {
        "status": "AVAILABLE",
        "stages": [dict(item) for item in diagnostic["stages"]],
    }
    contradictory_stage = contradictory["stages"][-1]
    contradictory_stage["record_limit_exceeded"] = False
    contradictory_stage["error_category"] = "none"
    assert RUNNER._sanitize_ctp_query_diagnostics(contradictory) == {
        "status": "UNAVAILABLE",
        "category": "INVALID_DIAGNOSTICS",
    }
