"""Selected-record public rule projections stay formula-only in replay.

The fixture intentionally stores only selected public API fields and response
digests.  It does not retain complete exchange response bodies and cannot be
used as a live-trading metadata source.
"""

from copy import deepcopy
from decimal import Decimal
import http.client
from importlib import import_module
import json
from pathlib import Path
import socket
import urllib.request

from bt_api_py import CrossVenueLeg as InstrumentRule
from bt_api_py import quantity_lattice
import pytest
import requests

from examples.cross_exchange_replay_rules import (
    PublicRuleSnapshotError,
    load_selected_public_rules,
)

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "examples" / "strategy-candidate-manifest.json"
SNAPSHOT = ROOT / "tests" / "fixtures" / "cross_exchange_rules" / "p2_6_public_rule_snapshot.json"
RUNNERS = (
    pytest.param(
        import_module("examples.012_1_midfreq_cross_exchange.run"),
        id="mid-frequency",
    ),
    pytest.param(
        import_module("examples.012_2_event_driven_cross_exchange.run"),
        id="event-driven",
    ),
)


def _install_formula_only_candidate_binding(monkeypatch, runner):
    """Keep this test's binding local while replay remains zero-network.

    The frozen manifest deliberately does not trust the modified runners.
    This helper does not alter it and cannot open a Store or an approval path.
    """

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    candidate = next(
        row for row in manifest["candidates"] if row["strategy_id"] == runner.STRATEGY_ID
    )
    canonical_path = Path(runner.MANIFEST_PATH).resolve()

    def load_test_candidate(path=runner.MANIFEST_PATH):
        assert Path(path).resolve() == canonical_path
        return manifest, candidate, canonical_path

    def unexpected_store(*_args, **_kwargs):
        pytest.fail("formula replay must not construct a Store")

    def unexpected_approval(*_args, **_kwargs):
        pytest.fail("formula replay must not load an approval")

    monkeypatch.setattr(runner, "load_candidate", load_test_candidate)
    monkeypatch.setattr(runner, "build_store", unexpected_store)
    monkeypatch.setattr(runner, "require_demo_approval", unexpected_approval)


def _install_zero_network_and_execution_guards(monkeypatch, runner):
    """Make any hidden transport or order-construction path fail immediately."""

    network_calls = []
    execution_calls = []

    def block_network(label):
        def blocked(*_args, **_kwargs):
            network_calls.append(label)
            pytest.fail(f"formula replay attempted network access through {label}")

        return blocked

    def block_execution(label):
        def blocked(*_args, **_kwargs):
            execution_calls.append(label)
            pytest.fail(f"formula replay attempted execution through {label}")

        return blocked

    for name in ("create_connection", "getaddrinfo", "gethostbyname", "gethostbyname_ex"):
        monkeypatch.setattr(socket, name, block_network(f"socket.{name}"))
    monkeypatch.setattr(socket.socket, "connect", block_network("socket.socket.connect"))
    monkeypatch.setattr(socket.socket, "connect_ex", block_network("socket.socket.connect_ex"))
    monkeypatch.setattr(
        http.client.HTTPConnection, "connect", block_network("HTTPConnection.connect")
    )
    monkeypatch.setattr(
        http.client.HTTPSConnection, "connect", block_network("HTTPSConnection.connect")
    )
    monkeypatch.setattr(urllib.request, "urlopen", block_network("urllib.request.urlopen"))
    monkeypatch.setattr(
        requests.sessions.Session, "request", block_network("requests.Session.request")
    )
    monkeypatch.setattr(runner, "BtApiStore", block_execution("BtApiStore"))
    monkeypatch.setattr(runner, "MixBroker", block_execution("MixBroker"))
    monkeypatch.setattr(runner.bt.Strategy, "buy", block_execution("Strategy.buy"))
    monkeypatch.setattr(runner.bt.Strategy, "sell", block_execution("Strategy.sell"))
    return network_calls, execution_calls


def test_selected_record_snapshot_is_explicitly_not_a_complete_raw_exchange_body():
    payload = json.loads(SNAPSHOT.read_text(encoding="utf-8"))

    assert payload["record_kind"] == "selected_public_instrument_rule_records"
    assert (
        payload["capture"]["repository_content"] == "SELECTED_RECORDS_ONLY_NO_COMPLETE_RAW_BODIES"
    )
    assert (
        payload["capture"]["raw_body_retention"] == "OUTSIDE_REPOSITORY_OWNER_ONLY_LOCAL_EVIDENCE"
    )
    assert payload["projection_policy"] == {
        "taker_fee": "CONSERVATIVE_REPLAY_BOUND_NOT_ACCOUNT_FEE",
        "okx_minimum_notional": "ZERO_NO_NOTIONAL_FLOOR_IN_SELECTED_RECORD_FORMULA_ONLY",
    }
    assert payload["sources"]["okx"]["body_sha256"] == (
        "1a6eeb4c4cc625067010d0110718feaee4a6f03becc60f661b800acb4f5ac4e2"
    )
    assert payload["sources"]["binance"]["body_sha256"] == (
        "27ceb67d0afca04694ae0ae46d9352b5a1ca1415dd1cf5eefaec72cf2011ac95"
    )


def test_selected_record_snapshot_projects_exact_instrument_rules():
    rules = load_selected_public_rules(SNAPSHOT)

    assert set(rules) == {"okx", "binance"}
    assert all(type(rule) is InstrumentRule for rule in rules.values())
    assert rules["okx"].multiplier == Decimal("0.01")
    assert rules["okx"].quantity_step == Decimal("0.01")
    assert rules["okx"].minimum_quantity == Decimal("0.01")
    # The selected OKX record explicitly rejects the historical assumption
    # that lotSz/minSz were one whole contract.
    assert rules["okx"].quantity_step != Decimal("1")
    assert rules["okx"].base_step == Decimal("0.0001")
    assert rules["okx"].base_minimum == Decimal("0.0001")
    assert rules["binance"].multiplier == Decimal("1")
    assert rules["binance"].quantity_step == Decimal("0.001")
    assert rules["binance"].minimum_quantity == Decimal("0.001")
    assert rules["binance"].minimum_notional == Decimal("50")

    lattice = quantity_lattice(Decimal("0.002"), rules.values())
    assert lattice.common_step_base == Decimal("0.001")
    assert lattice.minimum_base == Decimal("0.001")
    # The captured rules make 0.002 BTC lattice-admissible.  This does not
    # establish a price-dependent notional check or any live-trading status.
    assert lattice.quantity_base == Decimal("0.002")
    assert lattice.tradable is True

    below_minimum = quantity_lattice(Decimal("0.00001"), rules.values())
    assert below_minimum.quantity_base == Decimal("0.000")
    assert below_minimum.tradable is False


def test_selected_record_loader_rejects_unknown_or_tampered_snapshot_fields(tmp_path):
    payload = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    payload["sources"]["binance"]["body_sha256"] = "0" * 64
    changed_digest = tmp_path / "changed-digest.json"
    changed_digest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PublicRuleSnapshotError, match="body_sha256"):
        load_selected_public_rules(changed_digest)

    unknown_field = deepcopy(payload)
    unknown_field["unexpected"] = "not admitted"
    changed_schema = tmp_path / "changed-schema.json"
    changed_schema.write_text(json.dumps(unknown_field), encoding="utf-8")

    with pytest.raises(PublicRuleSnapshotError, match="unexpected"):
        load_selected_public_rules(changed_schema)


@pytest.mark.integration
@pytest.mark.parametrize("runner", RUNNERS)
def test_real_rule_projection_can_drive_formula_replay_without_execution(monkeypatch, runner):
    manifest_before = MANIFEST.read_bytes()
    synthetic_rules = runner.replay_rules()
    actual_rules = load_selected_public_rules(SNAPSHOT)
    network_calls, execution_calls = _install_zero_network_and_execution_guards(monkeypatch, runner)

    # The frozen candidate's source binding remains authoritative outside this
    # test.  The following failure must occur before test-only injection.
    with pytest.raises(runner.RunnerSourceBindingError, match="runner source fingerprint mismatch"):
        runner.run_replay("no_edge")

    # The production fixture remains its own source.  The selected public-rule
    # projection is injected only after the binding check and is not candidate
    # admission or production provenance evidence.
    assert actual_rules is not synthetic_rules
    assert all(actual_rules[venue] == synthetic_rules[venue] for venue in actual_rules)
    _install_formula_only_candidate_binding(monkeypatch, runner)
    monkeypatch.setattr(runner, "replay_rules", lambda: actual_rules)

    report = runner.run_replay("no_edge")

    assert report["status"] == "FORMULA_CHECK_PASS"
    assert report["mode"] == "replay"
    assert report["evidence_level"] == "R0_FORMULA_FIXTURE"
    assert report["research_status"] == "RESEARCH_REJECTED"
    assert report["profitability_claim"] == "NONE_SYNTHETIC_FIXTURE_ONLY"
    assert report["orders_submitted"] == report["fills"] == 0
    assert report["execution_status"] == "NOT_RUN"
    assert report["gross_pnl"] is report["net_pnl"] is None
    assert network_calls == []
    assert execution_calls == []
    assert MANIFEST.read_bytes() == manifest_before
