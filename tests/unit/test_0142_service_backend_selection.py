"""Config-first selection for the 014_2 normal live backend."""

from __future__ import annotations

import importlib
import json
import sys
from types import SimpleNamespace

import pytest


_RUNNER_NAME = "examples.unified.014_2_ctp_options_midfreq.run"
_SERVICE_NAME = "examples.unified.014_2_ctp_options_midfreq.service_live_backend"


@pytest.fixture
def entry():
    if sys.version_info[:2] != (3, 11):
        pytest.skip("live entry routing is supported only on Python 3.11")
    return importlib.import_module(_RUNNER_NAME)


def _args(module):
    return SimpleNamespace(
        allow_write=False,
        tier_decision=SimpleNamespace(as_evidence=lambda: {"effective_tier": "live"}),
    )


def test_explicit_service_backend_dispatches_before_direct_or_env_loader(
    entry, monkeypatch
):
    raw_config = {entry.LIVE_ADAPTER_KEY: {"backend": "service"}}
    monkeypatch.setattr(entry, "_load_raw_config", lambda: raw_config)
    monkeypatch.setattr(
        entry,
        "_ensure_dev_sdk_path",
        lambda **_kwargs: pytest.fail("service route entered the direct SDK bootstrap"),
    )
    monkeypatch.setattr(
        entry,
        "_load_env",
        lambda: pytest.fail("service route read the direct .env loader"),
    )
    service = importlib.import_module(_SERVICE_NAME)
    marker = object()
    calls = []

    def dispatch(args, config, decision, runner):
        calls.append((args, config, decision, runner))
        return marker

    monkeypatch.setattr(service, "run_live_service", dispatch)
    args = _args(entry)
    decision = args.tier_decision

    assert entry.run_live(args) is marker
    assert calls == [(args, raw_config, decision, entry)]


def test_unsupported_backend_fails_closed_without_echo_or_direct_fallback(
    entry, monkeypatch, capsys
):
    secret_like_value = "unsupported-secret-looking-config-value"
    monkeypatch.setattr(
        entry,
        "_load_raw_config",
        lambda: {entry.LIVE_ADAPTER_KEY: {"backend": secret_like_value}},
    )
    monkeypatch.setattr(
        entry,
        "_ensure_dev_sdk_path",
        lambda **_kwargs: pytest.fail("unsupported backend fell back to direct bootstrap"),
    )
    monkeypatch.setattr(
        entry,
        "_load_env",
        lambda: pytest.fail("unsupported backend read the direct .env loader"),
    )

    assert entry.run_live(_args(entry)) == entry.EXIT_BLOCKED
    output = capsys.readouterr().out
    summary = json.loads(output)
    assert summary["reason"] == "live_backend_unsupported"
    assert secret_like_value not in output


def test_missing_service_configuration_does_not_fall_back_to_direct(
    entry, monkeypatch, capsys
):
    monkeypatch.setattr(
        entry,
        "_load_raw_config",
        lambda: {
            entry.LIVE_ADAPTER_KEY: {
                "backend": "service",
                "schema_version": 1,
                "venue": "simnow",
                "policy": {"allow_write": False},
                "live_candidate": {"contracts": {}},
            }
        },
    )
    monkeypatch.setattr(
        entry,
        "_ensure_dev_sdk_path",
        lambda **_kwargs: pytest.fail("service config failure fell back to direct bootstrap"),
    )
    monkeypatch.setattr(
        entry,
        "_load_env",
        lambda: pytest.fail("service config failure read the direct .env loader"),
    )

    assert entry.run_live(_args(entry)) == entry.EXIT_BLOCKED
    summary = json.loads(capsys.readouterr().out)
    assert summary["backend"] == "service"
    assert summary["reason"] == "SERVICE_CONFIG_INVALID"

def test_omitted_backend_keeps_the_existing_direct_route(entry, monkeypatch, capsys):
    raw_config = {entry.LIVE_ADAPTER_KEY: {"schema_version": 1}}
    monkeypatch.setattr(entry, "_load_raw_config", lambda: raw_config)
    direct_bootstrap = []
    monkeypatch.setattr(entry, "_ensure_dev_sdk_path", lambda: direct_bootstrap.append("direct"))
    monkeypatch.setattr(
        entry,
        "_load_env",
        lambda: pytest.fail("direct validation rejection must precede env loading"),
    )
    monkeypatch.setattr(entry, "_live_section_errors", lambda _live: ["DIRECT_CONFIG_SENTINEL"])
    monkeypatch.setitem(
        sys.modules,
        "legacy_runner",
        SimpleNamespace(load_config=dict),
    )
    monkeypatch.setitem(sys.modules, "simnow_direct", SimpleNamespace())
    service = importlib.import_module(_SERVICE_NAME)
    monkeypatch.setattr(
        service,
        "run_live_service",
        lambda *_args, **_kwargs: pytest.fail("missing backend must keep direct default"),
    )

    assert entry.run_live(_args(entry)) == entry.EXIT_BLOCKED
    assert direct_bootstrap == ["direct"]
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "REJECTED"
    assert summary["errors"] == ["DIRECT_CONFIG_SENTINEL"]


def test_service_metadata_price_tick_must_fit_the_strategy_float_path():
    service = importlib.import_module(_SERVICE_NAME)
    from decimal import Decimal

    assert service._positive_decimal("0.5") == Decimal("0.5")
    for value in ("1e999", "1e-999"):
        with pytest.raises(service.ServiceBackendError, match="SERVICE_METADATA_INVALID"):
            service._positive_decimal(value)


def test_service_candidate_multiplier_must_match_each_typed_market_contract():
    from types import SimpleNamespace

    service = importlib.import_module(_SERVICE_NAME)
    metadata = {
        leg: SimpleNamespace(volume_multiple=100)
        for leg in ("future", "call", "put")
    }

    service._validate_candidate_multiplier({"multiplier": 100}, metadata)
    service._validate_candidate_multiplier(
        {}, metadata, fallback_candidate={"multiplier": 100}
    )
    with pytest.raises(service.ServiceBackendError, match="SERVICE_VOLUME_MULTIPLIER_MISMATCH"):
        service._validate_candidate_multiplier({"multiplier": 10}, metadata)
    metadata["put"] = SimpleNamespace(volume_multiple=10)
    with pytest.raises(service.ServiceBackendError, match="SERVICE_VOLUME_MULTIPLIER_MISMATCH"):
        service._validate_candidate_multiplier({"multiplier": 100}, metadata)
    for invalid in (True, float("nan"), "NaN", 0):
        with pytest.raises(service.ServiceBackendError):
            service._validate_candidate_multiplier({"multiplier": invalid}, metadata)


def test_unstarted_broker_still_closes_store_owned_service_proxy():
    service = importlib.import_module(_SERVICE_NAME)
    calls = []

    class Broker:
        def stop(self):
            calls.append("broker.stop")
            return {}

    class Store:
        def stop(self, *, timeout):
            calls.append(("store.stop", timeout))
            return {"shutdown_state": "PASS"}

    broker_health, store_health, errors = service._stop_broker_and_store(
        Broker(), Store(), 5.0
    )

    assert broker_health == {}
    assert store_health == {"shutdown_state": "PASS"}
    assert calls == ["broker.stop", ("store.stop", 5.0)]
    assert errors == []


def test_store_close_failure_remains_an_explicit_cleanup_error():
    service = importlib.import_module(_SERVICE_NAME)

    class Broker:
        def stop(self):
            return {}

    class Store:
        def stop(self, *, timeout):
            raise service.ServiceBackendError("PROXY_CLOSE_FAILED")

    broker_health, store_health, errors = service._stop_broker_and_store(
        Broker(), Store(), 5.0
    )

    assert broker_health == {}
    assert store_health is None
    assert errors == ["store_stop:PROXY_CLOSE_FAILED", "store_shutdown_unconfirmed"]


def test_shared_market_descriptor_requires_one_clock_implementation():
    from bt_api_base.market_protocol import MarketInstrumentKey, MarketSourceDescriptor, MarketSubscriptionKey

    service = importlib.import_module(_SERVICE_NAME)
    descriptors = []
    for name, clock_source in (("future", "python.time.monotonic"), ("call", "python.time.monotonic"), ("put", "other.monotonic")):
        key = MarketSubscriptionKey(
            source_ref="ctp-market-source-r1",
            entitlement_ref="ctp-market-entitlement-r1",
            instrument=MarketInstrumentKey(
                provider="ctp",
                venue="CFFEX",
                environment="simnow",
                product_type="option" if name != "future" else "future",
                instrument_id=name,
                native_symbol=name,
            ),
            channel="ctp.quote.v2",
        )
        descriptors.append(
            MarketSourceDescriptor(
                key=key,
                stream_id=key.stream_id,
                epoch=f"epoch-{name}",
                provider="ctp",
                source="ctp.native.md",
                connection_generation=1,
                clock_domain_id="runtime:monotonic:shared-session",
                clock_source_session_id="shared-session",
                clock_source=clock_source,
            )
        )

    clock_sources = {item.clock_source for item in descriptors}
    assert len(clock_sources) != 1
    with pytest.raises(service.ServiceBackendError, match="SERVICE_MARKET_SOURCE_SESSION_MISMATCH"):
        service._validate_shared_market_source_descriptors(descriptors)
