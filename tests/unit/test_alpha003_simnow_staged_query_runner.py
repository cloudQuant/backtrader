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


def _excluded_product_row(product_id, product_class="2"):
    return {"ExchangeID": "DCE", "ProductID": product_id, "ProductClass": product_class}


def _instrument_row(product_id, product_class="1"):
    return {
        "ExchangeID": "DCE",
        "ProductID": product_id,
        "ProductClass": product_class,
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
        excluded_products=(),
        product_rows=None,
        instrument_product_class="1",
        overflow_stage=None,
        oversized_stage=None,
        oversized_count=0,
        wrong_product_filter=False,
    ):
        self.missing_instruments = frozenset(missing_instruments)
        self.excluded_products = tuple(excluded_products)
        self.product_rows = None if product_rows is None else tuple(product_rows)
        self.instrument_product_class = instrument_product_class
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
        if self.product_rows is None:
            rows = tuple(map(_product_row, PRODUCT_IDS)) + tuple(
                _excluded_product_row(product_id) for product_id in self.excluded_products
            )
        else:
            rows = self.product_rows
        return self._result("products", rows, filters, kwargs)

    def query_instruments_result(self, **kwargs):
        self.calls.append(("instruments", dict(kwargs)))
        product_id = kwargs["product_id"]
        rows = (
            ()
            if product_id in self.missing_instruments
            else (_instrument_row(product_id, self.instrument_product_class),)
        )
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
        if kwargs["instrument_id"]:
            rows = tuple(
                _depth_row(product_id)
                for product_id in PRODUCT_IDS
                if product_id == kwargs["instrument_id"]
            )
        else:
            rows = tuple(map(_depth_row, PRODUCT_IDS))
        return self._result("depth_market_data", rows, filters, kwargs)


class EmptyContractStagedQueryFeed(FakeStagedQueryFeed):
    """A feed whose complete instrument query legitimately returns zero rows."""

    def query_depth_market_data_result(self, **kwargs):
        self.calls.append(("depth", dict(kwargs)))
        filters = (
            ("ExchangeID", kwargs["exchange_id"]),
            ("InstrumentID", kwargs["instrument_id"]),
            ("ProductClass", kwargs["product_class"]),
        )
        if kwargs["instrument_id"]:
            rows = tuple(
                _depth_row(product_id)
                for product_id in PRODUCT_IDS
                if product_id == kwargs["instrument_id"]
                and product_id not in self.missing_instruments
            )
        else:
            rows = tuple(
                _depth_row(product_id)
                for product_id in PRODUCT_IDS
                if product_id not in self.missing_instruments
            )
        return self._result("depth_market_data", rows, filters, kwargs)


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


def _query_config(query_mode="staged_product_set"):
    return {"selection": {"query_mode": query_mode, "authorized_products": None}}


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
        ["ProductClass", ""],
        ["ProductID", ""],
    ]


def test_staged_product_depth_query_plan_uses_per_product_depth(monkeypatch):
    _install_query_fixture(monkeypatch)
    feed = FakeStagedQueryFeed()
    store = SnapshotStore(feed)

    plan = RUNNER.build_ctp_query_market_plan(
        store, _query_config("staged_product_depth"), clock=FixedClock()
    )

    expected_products = tuple(
        futures_main_contract.ProductKey("DCE", item) for item in sorted(PRODUCT_IDS)
    )
    assert store.collect_calls == [
        {
            "max_collection_seconds": 300.0,
            "max_snapshot_age_seconds": 300.0,
            "query_mode": "staged_product_depth",
        }
    ]
    assert [kind for kind, _ in feed.calls] == [
        "products",
        "instruments",
        "instruments",
        "instruments",
        "depth",
        "depth",
        "depth",
    ]
    assert [kwargs["instrument_id"] for kind, kwargs in feed.calls if kind == "depth"] == [
        "A",
        "M",
        "Y",
    ]
    assert [kwargs["exchange_id"] for kind, kwargs in feed.calls if kind == "depth"] == [
        "DCE",
        "DCE",
        "DCE",
    ]
    assert all(
        kwargs["product_class"] == "1" for kind, kwargs in feed.calls if kind == "depth"
    )
    query_set = store.snapshot.query_set
    assert query_set.request_layout == "per_product_depth"
    assert len(query_set.requests) == 2 * len(expected_products) + 1
    assert plan["manifest"].status == "READY"
    assert tuple(plan["products"]) == expected_products
    assert tuple(plan["targets"]) == tuple("DCE." + item for item in sorted(PRODUCT_IDS))
    query_evidence = plan["manifest"].to_dict()["query_snapshot"]["query_set"]
    assert query_evidence["request_layout"] == "per_product_depth"
    assert len(query_evidence["requests"]) == 2 * len(expected_products) + 1


def test_mixed_product_query_retains_exclusions_without_querying_or_selecting_them(monkeypatch):
    _install_query_fixture(monkeypatch)
    feed = FakeStagedQueryFeed(excluded_products=("OPTION",))
    store = SnapshotStore(feed)

    plan = RUNNER.build_ctp_query_market_plan(store, _query_config(), clock=FixedClock())

    expected_products = tuple(
        futures_main_contract.ProductKey("DCE", item) for item in sorted(PRODUCT_IDS)
    )
    excluded = store.snapshot.query_set.excluded_products
    assert tuple(item.product for item in store.snapshot.query_set.products) == expected_products
    assert len(excluded) == 1
    assert excluded[0].product == futures_main_contract.ProductKey("DCE", "OPTION")
    assert excluded[0].product_class == "2"
    assert tuple(plan["products"]) == expected_products
    assert tuple(plan["targets"]) == tuple("DCE." + item for item in sorted(PRODUCT_IDS))
    assert all("OPTION" not in target for target in plan["targets"])
    assert [kwargs["product_id"] for kind, kwargs in feed.calls if kind == "instruments"] == [
        "A",
        "M",
        "Y",
    ]
    query_evidence = plan["manifest"].to_dict()["query_snapshot"]["query_set"]
    assert [row["product"]["product_id"] for row in query_evidence["excluded_products"]] == [
        "OPTION"
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


def test_listed_product_without_contracts_narrows_the_plan_pool_only(monkeypatch):
    _install_query_fixture(monkeypatch)
    feed = EmptyContractStagedQueryFeed(missing_instruments=("Y",))
    store = SnapshotStore(feed)
    selector = futures_main_contract.select_main_contracts
    requested_pools = []

    def record_full_pool(snapshot, target_products, *args, **kwargs):
        requested_pools.append(tuple(target_products))
        return selector(snapshot, target_products, *args, **kwargs)

    monkeypatch.setattr(futures_main_contract, "select_main_contracts", record_full_pool)

    plan = RUNNER.build_ctp_query_market_plan(store, _query_config(), clock=FixedClock())

    expected_products = tuple(
        futures_main_contract.ProductKey("DCE", item) for item in sorted(PRODUCT_IDS)
    )
    narrowed = tuple(product for product in expected_products if product.product_id != "Y")
    # The query set itself still covers every requested product.
    assert tuple(item.product for item in store.snapshot.query_set.products) == expected_products
    assert requested_pools == [expected_products]
    assert plan["manifest"].status == "READY"
    assert tuple(plan["manifest"].target_products) == narrowed
    assert tuple(plan["products"]) == narrowed
    assert tuple(plan["targets"]) == tuple("DCE." + product.product_id for product in narrowed)
    assert set(plan["routes"]) == set(narrowed)
    assert set(plan["product_by_target"]) == set(plan["targets"])
    assert set(plan["grid"].target_products) == set(narrowed)
    assert {product for product, _ in plan["grid"].product_trading_days} == set(narrowed)
    excluded = next(
        item for item in plan["manifest"].products if item.product.product_id == "Y"
    )
    assert excluded.in_target_pool is False
    assert excluded.status == "EXCLUDED"
    assert excluded.exclusion_reason == "NO_LISTED_CONTRACTS"


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
    ("feed_options", "expected_detail", "stage_count"),
    [
        (
            {
                "product_rows": (
                    _product_row("M"),
                    _excluded_product_row("M"),
                )
            },
            "PRODUCT_CLASS_CONFLICT",
            1,
        ),
        (
            {"product_rows": (_excluded_product_row("PRIVATE_UNKNOWN", "Z"),)},
            "PRODUCT_CLASS_UNKNOWN",
            1,
        ),
        (
            {"product_rows": (_excluded_product_row("OPTION"),)},
            "PRODUCT_FUTURE_SET_EMPTY",
            1,
        ),
        ({"instrument_product_class": "Z"}, "CATALOG_PRODUCT_CLASS_UNKNOWN", 2),
        ({"instrument_product_class": "2"}, "INSTRUMENT_PRODUCT_CLASS_MISMATCH", 2),
    ],
)
def test_new_staged_product_class_errors_keep_finite_error_projection(
    monkeypatch, feed_options, expected_detail, stage_count
):
    _install_query_fixture(monkeypatch)
    store = SnapshotStore(FakeStagedQueryFeed(**feed_options))

    with pytest.raises(RUNNER.RunnerError) as caught:
        RUNNER.build_ctp_query_market_plan(store, _query_config(), clock=FixedClock())

    diagnostic = caught.value.query_diagnostics
    assert caught.value.detail == expected_detail
    assert diagnostic["schema_version"] == 2
    assert diagnostic["status"] == "AVAILABLE"
    assert len(diagnostic["stages"]) == stage_count
    if expected_detail in {"PRODUCT_CLASS_UNKNOWN", "PRODUCT_CLASS_CONFLICT"}:
        assert diagnostic["stages"][0]["classified_future_product_count"] is None
        assert diagnostic["stages"][0]["classified_excluded_product_count"] is None
    assert "PRIVATE_UNKNOWN" not in str(diagnostic)


def test_instrument_normalizer_class_mismatch_keeps_finite_error_projection(monkeypatch):
    _install_query_fixture(monkeypatch)

    def mismatching_normalizer(row):
        normalized = _normalize_instrument(row)
        normalized["product_class"] = "2"
        return normalized

    monkeypatch.setattr(
        snapshot_adapter,
        "_load_sdk_contract",
        lambda: (FakeQueryResult, mismatching_normalizer),
    )
    store = SnapshotStore(FakeStagedQueryFeed())

    with pytest.raises(RUNNER.RunnerError) as caught:
        RUNNER.build_ctp_query_market_plan(store, _query_config(), clock=FixedClock())

    diagnostic = caught.value.query_diagnostics
    assert caught.value.detail == "CATALOG_PRODUCT_CLASS_MISMATCH"
    assert diagnostic["schema_version"] == 2
    assert [stage["stage"] for stage in diagnostic["stages"]] == [
        "products",
        "instruments_001",
    ]
    assert diagnostic["stages"][0]["classified_future_product_count"] == 3
    assert diagnostic["stages"][0]["classified_excluded_product_count"] == 0


def test_staged_error_projection_uses_classified_future_count_for_instrument_stages(
    monkeypatch,
):
    _install_query_fixture(monkeypatch)
    store = SnapshotStore(
        FakeStagedQueryFeed(excluded_products=("OPTION",), overflow_stage="instruments")
    )

    with pytest.raises(RUNNER.RunnerError) as caught:
        RUNNER.build_ctp_query_market_plan(store, _query_config(), clock=FixedClock())

    diagnostic = caught.value.query_diagnostics
    assert diagnostic["status"] == "AVAILABLE"
    assert diagnostic["schema_version"] == 2
    assert [stage["stage"] for stage in diagnostic["stages"]] == [
        "products",
        "instruments_001",
    ]
    products, instrument = diagnostic["stages"]
    assert products["record_count"] == 4
    assert products["classified_future_product_count"] == 3
    assert products["classified_excluded_product_count"] == 1
    assert instrument["stage"] == "instruments_001"
    assert instrument["error_category"] == "record_limit"
    assert "OPTION" not in str(diagnostic)


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
        "schema_version": 2,
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


def _staged_diagnostic_stage(
    name,
    *,
    prior_stage_complete,
    record_count,
    requested_limit,
    classified_counts=None,
):
    future_count, excluded_count = classified_counts or (None, None)
    return {
        "stage": name,
        "entered": True,
        "returned": True,
        "elapsed_seconds": 0.01,
        "prior_stage_complete": prior_stage_complete,
        "result_type_matches": True,
        "request_type_matches": True,
        "generation_matches": True,
        "request_id_positive": True,
        "timed_out": False,
        "complete": True,
        "is_last_seen": True,
        "unsupported": False,
        "late_callbacks_reported": False,
        "late_callback_count_valid": True,
        "record_count": record_count,
        "record_count_capped": False,
        "submit_category": "accepted",
        "error_code_present": False,
        "error_code_valid": True,
        "error_code_nonzero": False,
        "error_message_present": False,
        "error_message_valid": True,
        "error_category": "none",
        "first_completion_origin": "success",
        "completion_origin": "success",
        "requested_record_limit": requested_limit,
        "record_limit_observed": requested_limit,
        "record_limit_matches": True,
        "record_limit_exceeded": False,
        "request_filters_match": True,
        "classified_future_product_count": future_count,
        "classified_excluded_product_count": excluded_count,
    }


def _staged_diagnostic(*stages, schema_version=2):
    output = {"status": "AVAILABLE", "stages": list(stages)}
    if schema_version is not None:
        output["schema_version"] = schema_version
    return output


def test_staged_diagnostics_use_classified_future_count_not_total_product_count():
    products = _staged_diagnostic_stage(
        "products",
        prior_stage_complete=None,
        record_count=5,
        requested_limit=256,
        classified_counts=(2, 3),
    )
    instruments = (
        _staged_diagnostic_stage(
            "instruments_001",
            prior_stage_complete=True,
            record_count=4,
            requested_limit=20_000,
        ),
        _staged_diagnostic_stage(
            "instruments_002",
            prior_stage_complete=True,
            record_count=2,
            requested_limit=19_996,
        ),
    )
    depth = _staged_diagnostic_stage(
        "depth",
        prior_stage_complete=True,
        record_count=8,
        requested_limit=20_000,
    )
    diagnostics = _staged_diagnostic(products, *instruments, depth)

    assert RUNNER._sanitize_ctp_query_diagnostics(diagnostics) == diagnostics


def test_staged_diagnostics_allow_classification_early_stop_but_not_inferred_counts():
    products = _staged_diagnostic_stage(
        "products",
        prior_stage_complete=None,
        record_count=5,
        requested_limit=256,
        classified_counts=None,
    )
    assert RUNNER._sanitize_ctp_query_diagnostics(_staged_diagnostic(products)) == {
        "schema_version": 2,
        "status": "AVAILABLE",
        "stages": [products],
    }

    inferred_instrument = _staged_diagnostic_stage(
        "instruments_001",
        prior_stage_complete=True,
        record_count=2,
        requested_limit=20_000,
    )
    assert RUNNER._sanitize_ctp_query_diagnostics(
        _staged_diagnostic(products, inferred_instrument)
    ) == {"status": "UNAVAILABLE", "category": "INVALID_DIAGNOSTICS"}

    no_futures = _staged_diagnostic_stage(
        "products",
        prior_stage_complete=None,
        record_count=3,
        requested_limit=256,
        classified_counts=(0, 3),
    )
    assert RUNNER._sanitize_ctp_query_diagnostics(_staged_diagnostic(no_futures)) == {
        "schema_version": 2,
        "status": "AVAILABLE",
        "stages": [no_futures],
    }
    assert RUNNER._sanitize_ctp_query_diagnostics(
        _staged_diagnostic(no_futures, inferred_instrument)
    ) == {"status": "UNAVAILABLE", "category": "INVALID_DIAGNOSTICS"}


def test_staged_diagnostics_allow_partial_instrument_early_stop_and_require_depth_last():
    products = _staged_diagnostic_stage(
        "products",
        prior_stage_complete=None,
        record_count=4,
        requested_limit=256,
        classified_counts=(3, 1),
    )
    first_instrument = _staged_diagnostic_stage(
        "instruments_001",
        prior_stage_complete=True,
        record_count=1,
        requested_limit=20_000,
    )
    depth = _staged_diagnostic_stage(
        "depth",
        prior_stage_complete=True,
        record_count=3,
        requested_limit=20_000,
    )

    # A response may be the last observation when row validation stops the
    # collector before the next product request or depth query.
    assert RUNNER._sanitize_ctp_query_diagnostics(
        _staged_diagnostic(products, first_instrument)
    ) == _staged_diagnostic(products, first_instrument)
    assert RUNNER._sanitize_ctp_query_diagnostics(
        _staged_diagnostic(products, first_instrument, depth)
    ) == {"status": "UNAVAILABLE", "category": "INVALID_DIAGNOSTICS"}

    complete_instruments = tuple(
        _staged_diagnostic_stage(
            "instruments_{:03d}".format(index),
            prior_stage_complete=True,
            record_count=1,
            requested_limit=20_000 - index + 1,
        )
        for index in (1, 2, 3)
    )
    valid_depth = _staged_diagnostic_stage(
        "depth",
        prior_stage_complete=True,
        record_count=3,
        requested_limit=20_000,
    )
    assert RUNNER._sanitize_ctp_query_diagnostics(
        _staged_diagnostic(products, *complete_instruments, valid_depth)
    ) == _staged_diagnostic(products, *complete_instruments, valid_depth)


def test_staged_diagnostics_keep_historical_v1_count_binding_and_reject_private_fields():
    products = _staged_diagnostic_stage(
        "products",
        prior_stage_complete=None,
        record_count=2,
        requested_limit=256,
        classified_counts=(2, 0),
    )
    instrument = _staged_diagnostic_stage(
        "instruments_001",
        prior_stage_complete=True,
        record_count=1,
        requested_limit=20_000,
    )
    second_instrument = _staged_diagnostic_stage(
        "instruments_002",
        prior_stage_complete=True,
        record_count=1,
        requested_limit=19_999,
    )
    depth = _staged_diagnostic_stage(
        "depth",
        prior_stage_complete=True,
        record_count=2,
        requested_limit=20_000,
    )
    legacy_stages = []
    for stage in (products, instrument, second_instrument, depth):
        legacy_stage = dict(stage)
        legacy_stage.pop("classified_future_product_count")
        legacy_stage.pop("classified_excluded_product_count")
        legacy_stages.append(legacy_stage)
    assert RUNNER._sanitize_ctp_query_diagnostics(
        _staged_diagnostic(*legacy_stages, schema_version=None)
    ) == _staged_diagnostic(*legacy_stages, schema_version=None)
    # The v2 marker makes removal of its new count fields detectable. Removing
    # both the marker and fields is byte-for-byte indistinguishable from v1.
    assert RUNNER._sanitize_ctp_query_diagnostics(
        _staged_diagnostic(*legacy_stages)
    ) == {"status": "UNAVAILABLE", "category": "INVALID_DIAGNOSTICS"}

    private_payload = dict(products, private_provider_text="must-not-leak")
    serialized = RUNNER._sanitize_ctp_query_diagnostics(
        _staged_diagnostic(private_payload)
    )
    assert serialized == {"status": "UNAVAILABLE", "category": "INVALID_DIAGNOSTICS"}
    assert "must-not-leak" not in str(serialized)


def test_staged_diagnostics_reject_inconsistent_partition_and_stage_sequence():
    products = _staged_diagnostic_stage(
        "products",
        prior_stage_complete=None,
        record_count=5,
        requested_limit=256,
        classified_counts=(2, 3),
    )
    first_instrument = _staged_diagnostic_stage(
        "instruments_001",
        prior_stage_complete=True,
        record_count=1,
        requested_limit=20_000,
    )
    second_instrument = _staged_diagnostic_stage(
        "instruments_002",
        prior_stage_complete=True,
        record_count=1,
        requested_limit=19_999,
    )
    depth = _staged_diagnostic_stage(
        "depth",
        prior_stage_complete=True,
        record_count=2,
        requested_limit=20_000,
    )

    inconsistent_partition = dict(
        products,
        classified_excluded_product_count=2,
    )
    boolean_count = dict(
        products,
        classified_future_product_count=True,
        classified_excluded_product_count=4,
    )
    partition_on_instrument = dict(
        second_instrument,
        classified_future_product_count=2,
        classified_excluded_product_count=3,
    )
    for diagnostic in (
        _staged_diagnostic(inconsistent_partition),
        _staged_diagnostic(boolean_count),
        _staged_diagnostic(products, first_instrument, depth),
        _staged_diagnostic(products, first_instrument, partition_on_instrument),
        _staged_diagnostic(products, first_instrument, second_instrument, second_instrument),
    ):
        assert RUNNER._sanitize_ctp_query_diagnostics(diagnostic) == {
            "status": "UNAVAILABLE",
            "category": "INVALID_DIAGNOSTICS",
        }


@pytest.mark.parametrize(
    ("future_count", "excluded_count", "record_count"),
    [
        (None, 3, 5),
        (2, None, 5),
        (-1, 6, 5),
        (2.5, 2.5, 5),
        (257, 0, 257),
        (256, 256, 512),
    ],
)
def test_staged_diagnostics_reject_missing_invalid_and_oversized_counts(
    future_count, excluded_count, record_count
):
    products = _staged_diagnostic_stage(
        "products",
        prior_stage_complete=None,
        record_count=record_count,
        requested_limit=256,
        classified_counts=(future_count, excluded_count),
    )

    assert RUNNER._sanitize_ctp_query_diagnostics(_staged_diagnostic(products)) == {
        "status": "UNAVAILABLE",
        "category": "INVALID_DIAGNOSTICS",
    }
