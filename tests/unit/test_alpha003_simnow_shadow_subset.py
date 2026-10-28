"""Read-only golden feed subset contracts for the Alpha003 SimNow runner."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from backtrader.feeds.futures_main_contract import ProductKey


ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "unified" / "028_alpha003_simnow_minute"
RUNNER_PATH = EXAMPLE / "run.py"
UTC = timezone.utc
TRADING_DAY = date(2026, 10, 27)
DECISION_AT = datetime(2026, 10, 27, 1, 0, tzinfo=UTC)
PRODUCTS = tuple(
    sorted(
        (
            ProductKey("DCE", "A"),
            ProductKey("DCE", "M"),
            ProductKey("DCE", "Y"),
            ProductKey("SHFE", "CU"),
            ProductKey("CFFEX", "IF"),
        ),
        key=lambda item: (item.exchange_id, item.product_id),
    )
)
TARGETS = tuple(f"{item.exchange_id}.{item.product_id}" for item in PRODUCTS)
GOLDEN_TARGETS = ("DCE.A", "DCE.M", "DCE.Y")


def _load_runner():
    example_path = str(EXAMPLE)
    if example_path not in sys.path:
        sys.path.insert(0, example_path)
    spec = importlib.util.spec_from_file_location(
        "alpha003_simnow_shadow_subset_runner_under_test", RUNNER_PATH
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


RUNNER = _load_runner()


class _Grid:
    def __init__(self, products, product_days, label):
        self.status = "READY"
        self.decision_at = DECISION_AT
        self.target_products = tuple(products)
        self.product_trading_days = tuple(
            (product, tuple(product_days[product])) for product in products
        )
        self.minutes = (object(),)
        self.evidence_sha256 = hashlib.sha256(label.encode("utf-8")).hexdigest()

    def to_dict(self):
        return {
            "schema": "backtrader.futures_common_minute_grid.v1",
            "status": self.status,
            "decision_at": self.decision_at.isoformat(),
            "target_products": [
                {"exchange_id": item.exchange_id, "product_id": item.product_id}
                for item in self.target_products
            ],
            "product_trading_days": [
                {
                    "product": {
                        "exchange_id": product.exchange_id,
                        "product_id": product.product_id,
                    },
                    "trading_days": [day.isoformat() for day in days],
                }
                for product, days in self.product_trading_days
            ],
            "calendar_hashes": [],
            "minutes": [{"close_time": "2026-10-27T01:01:00Z", "members": []}],
        }


class _Manifest:
    def __init__(self, routes, products=PRODUCTS, status="READY", incomplete_product=None):
        self.status = status
        self.target_products = tuple(products)
        self._routes = dict(routes)
        target_rows = [
            {"exchange_id": product.exchange_id, "product_id": product.product_id}
            for product in products
        ]
        selected_rows = []
        catalog_rows = []
        quote_rows = []
        candidate_rows = []
        query_coverage = []
        for product in products:
            target = target_rows[products.index(product)]
            instrument = routes[product]
            alternate = f"{instrument}_ALT"
            selected_rows.append(
                {
                    "product": target,
                    "in_target_pool": True,
                    "status": "READY",
                    "expected_prior_trading_day": TRADING_DAY.isoformat(),
                    "ranking_trading_day": TRADING_DAY.isoformat(),
                    "selected_instrument_id": instrument,
                }
            )
            for catalog_instrument in (instrument, alternate):
                catalog_rows.append(
                    {
                        "product": target,
                        "instrument_id": catalog_instrument,
                        "asset_type": "future",
                        "is_trading": True,
                        "expiry_date": None,
                        "product_class": "1",
                    }
                )
                quote_rows.append(
                    {
                        "product": target,
                        "instrument_id": catalog_instrument,
                        "trading_day": TRADING_DAY.isoformat(),
                        "open_interest": "100",
                        "volume": "200",
                    }
                )
                candidate_rows.append(
                    {
                        "product": target,
                        "instrument_id": catalog_instrument,
                        "status": "READY",
                        "open_interest": "100",
                        "volume": "200",
                        "ranking_score": "150",
                        "rank": 1 if catalog_instrument == instrument else 2,
                    }
                )
            query_coverage.append(
                {
                    "product": target,
                    "catalog_instrument_ids": [instrument, alternate],
                    "expected_quote_instrument_ids": [instrument, alternate],
                    "metric_unit": "contracts",
                }
            )
        self._document = {
            "schema": "backtrader.futures_main_contract_manifest.v2",
            "status": status,
            "policy": {"ranking_mode": "ctp_query_snapshot_equal_weight_v1"},
            "target_products": target_rows,
            "trading_days": [],
            "calendars": [],
            "coverage": [
                {
                    "product": target_rows[index],
                    "candidate_count": 2,
                    "expected_instrument_ids": [routes[product], f"{routes[product]}_ALT"],
                    "candidate_set_complete": product != incomplete_product,
                    "ranking_values_complete": product != incomplete_product,
                    "finalized": True,
                    "ranking_trading_day": TRADING_DAY.isoformat(),
                    "open_interest_unit": "contracts",
                    "volume_unit": "contracts",
                }
                for index, product in enumerate(products)
            ],
            "products": selected_rows,
            "candidates": candidate_rows,
            "query_coverage": query_coverage,
            "source": {"source_id": "source", "catalog": {"source_id": "catalog"}},
            "query_snapshot": {
                "catalog_records": catalog_rows,
                "quote_records": quote_rows,
            },
        }
        self.manifest_sha256 = hashlib.sha256(
            RUNNER._canonical_json_bytes(self._document).rstrip(b"\n")
        ).hexdigest()

    def selected_mapping(self):
        if self.status != "READY":
            raise ValueError("blocked selection")
        return tuple(self._routes.items())

    def to_dict(self):
        return self._document


def _full_plan(status="READY", incomplete_product=None):
    routes = {
        PRODUCTS[0]: "IF2612",
        PRODUCTS[1]: "A2612",
        PRODUCTS[2]: "M2612",
        PRODUCTS[3]: "Y2612",
        PRODUCTS[4]: "CU2612",
    }
    # Keep the mapping keyed by ProductKey and in the same order as PRODUCTS.
    routes = {product: routes[product] for product in PRODUCTS}
    target_by_product = {
        product: f"{product.exchange_id}.{product.product_id}" for product in PRODUCTS
    }
    product_by_target = {target: product for product, target in target_by_product.items()}
    targets = tuple(target_by_product[product] for product in PRODUCTS)
    days = {product: (TRADING_DAY,) for product in PRODUCTS}
    return {
        "bundle": None,
        "manifest": _Manifest(routes, status=status, incomplete_product=incomplete_product),
        "products": PRODUCTS,
        "routes": routes,
        "targets": targets,
        "product_by_target": product_by_target,
        "target_by_product": target_by_product,
        # Deliberately independent from the active feed set.
        "authorized_targets": ("CFFEX.IF", "DCE.A"),
        "session_calendars": {"DCE": object(), "SHFE": object(), "CFFEX": object()},
        "grid": _Grid(PRODUCTS, days, "full"),
        "selection_path": "ctp-query://catalog|quotes",
        "selection_source": "ctp_query_snapshot_equal_weight_v1",
        "source_snapshot_id": "catalog|quotes",
        "calendar_evidence_mode": "expected_rule_derived",
        "calendar_rules_sha256": "a" * 64,
    }


def _config(targets=GOLDEN_TARGETS, authorized=None):
    return {
        "mode": "live",
        "selection": {
            "source": "ctp_query",
            "daily_bundles": [],
            "authorized_products": authorized,
        },
        "live": {
            "allow_writes": False,
            "arm_templates": [],
            "golden_targets": list(targets) if targets is not None else None,
            "account_scope": "account",
            "strategy_scope": "strategy",
            "logical_run_id": "run",
            "journal_path": "journal.sqlite",
        },
        "cohort": {
            "epoch_id": 1,
            "calendar_id": "calendar",
            "calendar_version": "version",
            "clock_domain_id": "simnow-source-clock",
            "timezone_id": "Asia/Shanghai",
            "session_semantics": "planned-minute-close-v1",
        },
        "factor": {"rebalance_every": 1},
        "risk": {name: None for name in ("policy_id", *RUNNER.RISK_FIELDS)},
        "output": {"decision_tape_path": "golden.jsonl", "decision_tape_max_bytes": 1_000_000},
    }


def test_golden_subset_rejects_incompatible_and_malformed_inputs_before_store_import(monkeypatch):
    decision = SimpleNamespace(effective_tier="live")
    valid = _config(authorized=["DCE.A", "CFFEX.IF"])
    assert RUNNER._validate_golden_targets_option(
        valid, mode="live", decision=decision, allow_write_flag=False
    ) == GOLDEN_TARGETS
    assert RUNNER._write_requested(valid, False, decision) is False

    cases = (
        (valid, "research", False, "GOLDEN_TARGETS_LIVE_CTP_QUERY_REQUIRED"),
        ({**valid, "selection": {**valid["selection"], "source": "bundle"}}, "live", False,
         "GOLDEN_TARGETS_LIVE_CTP_QUERY_REQUIRED"),
        ({**valid, "live": {**valid["live"], "allow_writes": True}}, "live", False,
         "GOLDEN_TARGETS_READ_ONLY_REQUIRED"),
        (valid, "live", True, "GOLDEN_TARGETS_READ_ONLY_REQUIRED"),
        (_config(("DCE.A", "DCE.M")), "live", False, "GOLDEN_TARGETS_COUNT_INVALID"),
        (_config(("DCE.A", "DCE.A", "DCE.M")), "live", False, "GOLDEN_TARGETS_DUPLICATE"),
        (_config(("DCE.A.2612", "DCE.M", "DCE.Y")), "live", False,
         "GOLDEN_TARGETS_INVALID"),
        (_config(authorized=["CFFEX.IF"]), "live", False, "GOLDEN_AUTHORIZED_TARGETS_EMPTY"),
        (
            {**valid, "live": {**valid["live"], "arm_templates": [{"target": "DCE.A"}]}},
            "live",
            False,
            "GOLDEN_TARGETS_WRITE_CONFIGURATION_UNSUPPORTED",
        ),
    )
    for config, mode, allow_write, expected_code in cases:
        with pytest.raises(RUNNER.RunnerError) as caught:
            RUNNER._validate_golden_targets_option(
                config,
                mode=mode,
                decision=decision,
                allow_write_flag=allow_write,
            )
        assert caught.value.code == expected_code

    imported = []
    original_import = __import__

    def tracked_import(name, *args, **kwargs):
        if name == "backtrader.stores.registered_sim":
            imported.append(name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", tracked_import)
    with pytest.raises(RUNNER.RunnerError) as caught:
        RUNNER.run_live(
            {**valid, "live": {**valid["live"], "allow_writes": True}},
            Path("unused-config.yaml"),
            None,
            "native",
            1,
            decision=decision,
            allow_write_flag=False,
        )
    assert caught.value.code == "GOLDEN_TARGETS_READ_ONLY_REQUIRED"
    assert imported == []

    with pytest.raises(RUNNER.RunnerError) as caught:
        RUNNER.run_live(
            _config(authorized=["CFFEX.IF"]),
            Path("unused-config.yaml"),
            None,
            "native",
            1,
            decision=decision,
            allow_write_flag=False,
        )
    assert caught.value.code == "GOLDEN_AUTHORIZED_TARGETS_EMPTY"
    assert imported == []


def test_synthetic_config_keeps_the_complete_pool_as_default():
    config = _config(targets=None)
    assert config["live"]["golden_targets"] is None
    plan = _full_plan()
    evidence = RUNNER._selection_evidence(
        plan,
        1,
        max_bytes=1_000_000,
        rebalance_every=config["factor"]["rebalance_every"],
    )
    identity = RUNNER._live_restart_identity(
        config,
        EXAMPLE / "config.yaml",
        plan,
        factor_mode="native",
        direction=1,
        simnow_profile={"verified": True, "environment": "simnow", "profile": "set1_group1"},
    )
    assert not {"full_selected_targets", "active_shadow_targets"}.intersection(evidence)
    assert "full_routes" not in identity


def test_full_selection_must_be_ready_before_subset_and_active_grid_is_rebuilt(monkeypatch):
    blocked = _full_plan(status="BLOCKED", incomplete_product=PRODUCTS[0])
    blocked_coverage = next(
        row for row in blocked["manifest"].to_dict()["coverage"]
        if row["product"] == {"exchange_id": "CFFEX", "product_id": "IF"}
    )
    assert blocked_coverage["candidate_set_complete"] is False
    assert "CFFEX.IF" not in GOLDEN_TARGETS
    with pytest.raises(RUNNER.RunnerError) as caught:
        RUNNER._apply_golden_target_subset(blocked, GOLDEN_TARGETS)
    assert caught.value.code == "GOLDEN_TARGETS_FULL_SELECTION_NOT_READY"

    requested = []

    def build_grid(products, calendars, product_trading_days, *, decision_at):
        requested.append(
            (tuple(products), tuple(product_trading_days), tuple(calendars), decision_at)
        )
        return _Grid(products, product_trading_days, "active")

    from backtrader.feeds import futures_sessions

    monkeypatch.setattr(futures_sessions, "build_common_minute_grid", build_grid)
    full = _full_plan()
    subset = RUNNER._apply_golden_target_subset(full, GOLDEN_TARGETS)
    assert subset["manifest"] is full["manifest"]
    assert subset["full_grid"] is full["grid"]
    assert subset["full_selected_targets"] == TARGETS
    assert subset["active_shadow_targets"] == GOLDEN_TARGETS
    assert subset["targets"] == GOLDEN_TARGETS
    assert set(subset["routes"].values()) == {"A2612", "M2612", "Y2612"}
    assert subset["authorized_targets"] == ("DCE.A",)
    assert subset["full_authorized_targets"] == ("CFFEX.IF", "DCE.A")
    assert len(requested) == 1
    assert requested[0][0] == tuple(full["product_by_target"][target] for target in GOLDEN_TARGETS)
    assert set(requested[0][1]) == set(requested[0][0])

    with pytest.raises(RUNNER.RunnerError) as caught:
        RUNNER._apply_golden_target_subset(full, ("DCE.A", "DCE.M", "ZZZ.Q"))
    assert caught.value.code == "GOLDEN_TARGETS_OUTSIDE_SELECTED_POOL"


def test_subset_selection_evidence_restart_identity_and_tape_bind_full_and_active_routes(
    monkeypatch, tmp_path
):
    from backtrader.feeds import futures_sessions

    monkeypatch.setattr(
        futures_sessions,
        "build_common_minute_grid",
        lambda products, calendars, product_trading_days, *, decision_at: _Grid(
            products, product_trading_days, "active"
        ),
    )
    full_plan = _full_plan()
    full_plan["authorized_targets"] = ("DCE.A", "CFFEX.IF")
    plan = RUNNER._apply_golden_target_subset(full_plan, GOLDEN_TARGETS)
    config = _config()
    evidence = RUNNER._selection_evidence(
        plan,
        1,
        max_bytes=1_000_000,
        rebalance_every=config["factor"]["rebalance_every"],
    )
    full_manifest = _full_plan()["manifest"].to_dict()
    assert evidence["routes"] == RUNNER._full_route_summary(plan)
    assert evidence["full_selected_targets"] == list(TARGETS)
    assert evidence["active_shadow_targets"] == list(GOLDEN_TARGETS)
    assert evidence["active_routes"] == RUNNER._route_summary(plan)
    manifest = evidence["manifest"]
    assert manifest == full_manifest
    assert len(manifest["query_snapshot"]["catalog_records"]) == 2 * len(TARGETS)
    assert len(manifest["query_snapshot"]["quote_records"]) == 2 * len(TARGETS)
    assert len(manifest["coverage"]) == len(TARGETS)
    assert len(manifest["products"]) == len(TARGETS)
    assert len(manifest["candidates"]) == 2 * len(TARGETS)
    assert len(manifest["query_coverage"]) == len(TARGETS)
    assert RUNNER._query_history_selection_projection(evidence) != b""
    assert RUNNER._validate_selection_evidence(evidence) == evidence

    identity = RUNNER._live_restart_identity(
        config,
        tmp_path / "config.yaml",
        plan,
        factor_mode="native",
        direction=1,
        simnow_profile={"verified": True, "environment": "simnow", "profile": "set1_group1"},
    )
    assert identity["targets"] == list(GOLDEN_TARGETS)
    assert identity["routes"] == RUNNER._route_summary(plan)
    assert identity["full_routes"] == RUNNER._full_route_summary(plan)
    assert RUNNER._selection_evidence_matches_identity(evidence, identity)

    other_plan = RUNNER._apply_golden_target_subset(
        _full_plan(), ("DCE.A", "DCE.M", "SHFE.CU")
    )
    other_evidence = RUNNER._selection_evidence(
        other_plan,
        1,
        max_bytes=1_000_000,
        rebalance_every=config["factor"]["rebalance_every"],
    )
    assert not RUNNER._selection_evidence_matches_identity(other_evidence, identity)
    assert RUNNER._query_history_selection_projection(other_evidence) != (
        RUNNER._query_history_selection_projection(evidence)
    )

    tape = RUNNER._new_decision_tape(
        config,
        tmp_path / "config.yaml",
        plan,
        mode="live",
        factor_mode="native",
        direction=1,
        source_snapshot_id=plan["source_snapshot_id"],
        restart_identity=identity,
        selection_evidence=evidence,
    )
    tape.close()
    header = next(RUNNER.iter_decision_tape(tape.path, max_bytes=tape.max_bytes))
    assert header["targets"] == list(GOLDEN_TARGETS)
    assert header["selection_evidence"]["routes"] == RUNNER._full_route_summary(plan)
    assert header["restart_identity"]["routes"] == RUNNER._route_summary(plan)
