"""Iteration 67 G5: explicit ``root: package_seed`` runtime binding.

UNIT/FAKE only: the committed synthetic seed is materialized into a temporary
Store runtime directory.  The seed is not exchange truth and grants no daily
update or trading authorization.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import yaml

pytest.importorskip("bt_api_py", reason="needs the bt_api_py SDK")
pytest.importorskip("bt_api_ctp", reason="needs the CTP calendar provider")

from bt_api_py.bt_api import BtApi  # noqa: E402
from bt_api_py.trading_calendar_binding import SIMULATION_ONLY  # noqa: E402

from backtrader.service.trading_calendar_config import (  # noqa: E402
    parse_direct_calendar_status,
)
from backtrader.stores.btapistore import BtApiStore, BtApiStoreError  # noqa: E402

ROUTE = "CTP___FUTURE"
SEED_VERSION = "seed-2026-2027-v1"


def make_store(tmp_path, *, root="package_seed"):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.safe_dump({"calendars": {"root": root}}), encoding="utf-8")
    api = BtApi(debug=False)
    api.exchange_feeds[ROUTE] = object()
    store = BtApiStore(
        api=api,
        config={"exchange_kwargs": {ROUTE: {}}},
        calendar_config_file=config_file,
        calendar_config=yaml.safe_load(config_file.read_text(encoding="utf-8")),
        calendar_ctp_routes=(ROUTE,),
    )
    store._api = api
    store._started = store._connected = store._sdk_configured = True
    return store


def test_store_materializes_the_seed_before_reading_and_labels_it(tmp_path):
    store = make_store(tmp_path)
    root = tmp_path / "calendar_package_seed"
    assert root.is_dir() and (root / "CURRENT.json").is_file()
    assert store._calendar_package_seed_routes == frozenset({ROUTE})

    result = store.trading_calendar_status()
    assert result["status"] == "OBSERVED"
    assert result["sources"] == {ROUTE: "LOCAL_CONFIG_PACKAGE_SEED"}
    observed = result["routes"][ROUTE]
    assert (observed.status, observed.version_id) == (
        "OBSERVED_UNAUTHENTICATED",
        SEED_VERSION,
    )
    assert observed.coverage_status == "DECLARED_UNVERIFIED"
    # The runtime path is never echoed in an observation.
    assert str(tmp_path) not in repr(result)


def test_seed_snapshot_is_readable_through_the_simulation_query(tmp_path):
    from datetime import date

    store = make_store(tmp_path)
    result = store.trading_calendar_query(
        ROUTE,
        venue="CFFEX",
        kind="future",
        product="SYNTH_CFFEX_FUTURE",
        contract="SYNTH_CFFEX_FUTURE_MAIN",
        trading_day=date(2026, 1, 5),
        mode=SIMULATION_ONLY,
    )
    assert (result.status, result.reason) == ("COMPLETE", "EXPLICIT_DATA")
    assert [window.window_id for window in result.windows] == ["day_am", "day_pm"]
    assert result.coverage_status == "DECLARED_UNVERIFIED"
    assert result.data_origin == "SYNTHETIC_MOCK"
    assert result.simulation_provenance is None
    assert result.source_authentication == "NOT_PROVEN"


def test_seed_installation_is_idempotent_across_stores(tmp_path):
    first = make_store(tmp_path)
    before = sorted(path.name for path in (tmp_path / "calendar_package_seed").iterdir())
    second = make_store(tmp_path)
    after = sorted(path.name for path in (tmp_path / "calendar_package_seed").iterdir())
    assert before == after
    assert (
        first.trading_calendar_status()["routes"][ROUTE].publication_id
        == second.trading_calendar_status()["routes"][ROUTE].publication_id
        == SEED_VERSION
    )


def test_parser_keeps_the_frozen_refusal_without_an_explicit_binding(tmp_path):
    with pytest.raises(ValueError, match="calendar_package_seed_unsupported"):
        parse_direct_calendar_status(
            {"calendars": {"root": "package_seed"}},
            config_file=tmp_path / "config.yaml",
            ctp_routes=(ROUTE,),
            configured_routes={ROUTE},
        )
    candidate, roots = parse_direct_calendar_status(
        {"calendars": {"root": "package_seed"}},
        config_file=tmp_path / "config.yaml",
        ctp_routes=(ROUTE,),
        configured_routes={ROUTE},
        package_seed_binding=True,
    )
    assert candidate.root_kind == "package_seed"
    assert roots == {}


def test_a_symlinked_seed_root_fails_closed(tmp_path):
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "calendar_package_seed").symlink_to(
        tmp_path / "elsewhere", target_is_directory=True
    )
    with pytest.raises(BtApiStoreError, match="calendar_package_seed_install_failed"):
        make_store(tmp_path)


def _patched_install(monkeypatch, result):
    import bt_api_py.trading_calendar_package_seed as seed_module

    monkeypatch.setattr(seed_module, "install_package_seed", lambda *a, **k: result)


def test_unknown_install_result_is_a_finite_refusal(tmp_path, monkeypatch):
    _patched_install(monkeypatch, SimpleNamespace(status="UNKNOWN", reason="PUBLISH_UNKNOWN"))
    with pytest.raises(BtApiStoreError, match="calendar_package_seed_unknown"):
        make_store(tmp_path)


def test_not_committed_install_result_is_a_finite_refusal(tmp_path, monkeypatch):
    _patched_install(
        monkeypatch, SimpleNamespace(status="NOT_COMMITTED", reason="SEED_ROOT_INVALID")
    )
    with pytest.raises(BtApiStoreError, match="calendar_package_seed_install_failed"):
        make_store(tmp_path)


def test_package_seed_still_requires_direct_sdk_configuration(tmp_path, monkeypatch):
    import backtrader.stores.btapistore as store_module

    monkeypatch.setattr(store_module, "_is_supported_api_facade", lambda _api: (False, True))
    with pytest.raises(BtApiStoreError, match="calendar_configuration_requires_direct_sdk"):
        BtApiStore(
            api=object(),
            config={"exchange_kwargs": {ROUTE: {}}},
            calendar_config_file=tmp_path / "config.yaml",
            calendar_config={"calendars": {"root": "package_seed"}},
            calendar_ctp_routes=(ROUTE,),
        )
