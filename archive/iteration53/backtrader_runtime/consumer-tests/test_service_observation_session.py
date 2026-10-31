from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from time import monotonic
from types import SimpleNamespace

import pytest

from backtrader_runtime import service_observation as observation


def test_write_preflight_runs_before_sdk_source_or_input_inspection(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("write request reached SDK/config setup")

    monkeypatch.setattr(observation, "_source_roots", forbidden)

    class UnreadableMapping(Mapping):
        def __getitem__(self, _key):
            raise AssertionError("write request read configuration/environment")

        def __iter__(self):
            raise AssertionError("write request iterated configuration/environment")

        def __len__(self):
            raise AssertionError("write request inspected configuration/environment")

    with pytest.raises(observation.ServiceObservationError) as caught:
        observation.open_service_read_session(
            UnreadableMapping(),
            instruments=(),
            allow_write=True,
            environ=UnreadableMapping(),
        )

    assert caught.value.code == "SERVICE_OBSERVATION_WRITE_UNSUPPORTED"


def test_instrument_requires_one_explicit_market_identity_form():
    with pytest.raises(ValueError, match="instrument_id is required"):
        observation.ServiceObservationInstrument("IF2612")

    with pytest.raises(ValueError, match="mutually exclusive"):
        observation.ServiceObservationInstrument(
            "IF2612",
            market_key={"opaque": True},
            instrument_id="IF2612",
            exchange_id="CFFEX",
        )


def test_instrument_rejects_non_boolean_descriptor_policy():
    with pytest.raises(ValueError, match="require_source_descriptor must be bool"):
        observation.ServiceObservationInstrument(
            "IF2612",
            market_key={"opaque": True},
            require_source_descriptor=1,
        )


def test_service_config_loader_accepts_only_explicit_service_mapping(tmp_path: Path):
    good = tmp_path / "service.json"
    good.write_text('{"service":{"client_config":{}}}', encoding="utf-8")
    with pytest.raises(observation.ServiceObservationError) as caught:
        observation.load_service_observation_config(good)
    assert caught.value.code == "SERVICE_CONFIG_INVALID"

    allowed = {
        "client_config": {},
        "identity": {},
        "service_principals": {},
        "curve_key_envs": {},
        "account": {},
        "market": {},
    }
    good.write_text(json.dumps({"service": allowed}), encoding="utf-8")
    loaded = observation.load_service_observation_config(good)
    assert dict(loaded) == allowed

    too_large = tmp_path / "oversized.json"
    too_large.write_text(" " * (1024 * 1024 + 1), encoding="utf-8")
    with pytest.raises(observation.ServiceObservationError) as caught:
        observation.load_service_observation_config(too_large)
    assert caught.value.code == "SERVICE_CONFIG_SIZE_INVALID"


def test_collect_observation_reports_identity_without_clock_or_raw_payload(monkeypatch):
    key = SimpleNamespace(stream_id="stream-1")
    descriptor = SimpleNamespace(
        key=key,
        stream_id="stream-1",
        epoch="epoch-1",
        provider="ctp",
        source="ctp.native.md",
        connection_generation=1,
        clock_domain_id="clock-domain",
        clock_source_session_id="source-session",
        clock_source="python.time.monotonic",
    )
    header = SimpleNamespace(
        operation="market.event",
        schema_id="sdk.market.event",
        stream_id="stream-1",
        stream_epoch="epoch-1",
        sequence=3,
        sent_at_utc="2026-10-17T00:00:00Z",
    )
    event = SimpleNamespace(header=header, payload={"secret-price": "must-not-appear"})
    observation_row = SimpleNamespace(
        balances_complete=True,
        positions_complete=True,
        open_orders_complete=True,
        completed_at_utc="2026-10-17T00:00:00Z",
        consistency="consistent",
        coverage=(object(),),
        balances=(),
        positions=(),
        open_orders=(),
    )

    class FakeSession:
        account_view = SimpleNamespace(
            observation=observation_row,
            session_generation="generation-1",
            cursor=4,
            fresh_until_monotonic=monotonic() + 10,
        )
        account_client = SimpleNamespace(healthy=True)
        metadata = {}
        market_clients = {"CFFEX.IF2612": SimpleNamespace(key=key)}
        poll_calls = []

        def subscribe(self, _name):
            return descriptor

        def poll(self, _name, *, timeout_ms):
            self.poll_calls.append(timeout_ms)
            assert 0 <= timeout_ms <= 100
            # A bounded SDK poll may return at an internal head/maintenance
            # boundary before the requested deadline. The collector must keep
            # polling rather than silently falling back to an empty bootstrap.
            if len(self.poll_calls) == 1:
                return None
            return event

        def initial_snapshot(self, _name):
            return None

        def close(self):
            return {"status": "PASS", "facades_closed": True, "runtime_closed": True}

    monkeypatch.setattr(observation, "open_service_read_session", lambda *_a, **_k: FakeSession())
    report = observation.collect_service_observation(
        {},
        instruments=[observation.ServiceObservationInstrument("CFFEX.IF2612", market_key={})],
        timeout_ms=100,
    )
    assert report["status"] == "OBSERVED"
    assert report["write_capability"] == "UNSUPPORTED"
    source = report["instruments"][0]["source"]
    assert source["clock_mapping_qualified"] is False
    assert source["freshness_qualified"] is False
    assert report["instruments"][0]["latest_event"]["sequence"] == 3
    assert len(FakeSession.poll_calls) == 2
    assert "secret-price" not in repr(report)
