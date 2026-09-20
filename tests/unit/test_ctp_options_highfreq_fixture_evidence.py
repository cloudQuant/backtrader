"""Fixture metadata-evidence coverage for the Iteration 30 example.

Iteration 30 binds the frozen contract metadata to a recorded CTP instrument
query: the bundle must match the evidence, the evidence must be self-consistent
and it must participate in the bundle identity hash.  Every case here uses the
real fixture plus an in-memory mutation, so no network or credential is needed.
"""

from __future__ import annotations

import copy
import importlib
from typing import Any, Mapping

import pytest

runner = importlib.import_module("examples.015_ctp_options_highfreq.run")

RAW_CONFIG, _ = runner.load_config()
EVIDENCE_SCHEMA = "iter30.ctp-instrument-evidence.v1"


def _fixture() -> dict[str, Any]:
    config = runner.effective_config(RAW_CONFIG, mode="replay", purpose="formula")
    fixture, _path, _hash = runner.load_fixture(config)
    return copy.deepcopy(fixture)


def _validate(fixture: Mapping[str, Any]) -> dict[str, Any]:
    config = runner.effective_config(RAW_CONFIG, mode="replay", purpose="formula")
    return runner.validate_bundle(fixture, config)


def _reseal(fixture: dict[str, Any]) -> None:
    """Recompute the evidence self-hash after an intentional mutation."""

    fixture["metadata_evidence"]["legs_sha256"] = runner._canonical_hash(
        fixture["metadata_evidence"]["legs"]
    )


def _code(error: pytest.ExceptionInfo[Exception]) -> str:
    return str(error.value)


# --- frozen real metadata -------------------------------------------------


def test_bundle_matches_the_recorded_czce_instrument_query() -> None:
    bundle = _validate(_fixture())
    assert bundle["strike"] == "970"
    assert bundle["future"]["multiplier"] == "20"
    assert bundle["future"]["tick_size"] == "1"
    assert bundle["future"]["expiry"] == "20270114"
    for role in ("call", "put"):
        assert bundle[role]["multiplier"] == "20"
        assert bundle[role]["tick_size"] == "0.5"
        assert bundle[role]["strike"] == "970"
        assert bundle[role]["expiry"] == "20261211"


def test_evidence_is_recorded_and_self_consistent() -> None:
    fixture = _fixture()
    evidence = fixture["metadata_evidence"]
    assert evidence["schema_version"] == EVIDENCE_SCHEMA
    assert evidence["source"] == "ctp_instrument_query"
    assert evidence["legs_sha256"] == runner._canonical_hash(evidence["legs"])
    bundle = _validate(fixture)
    assert bundle["metadata_evidence"]["legs"]["call"]["strike_price"] == "970"
    assert bundle["metadata_evidence"]["query"]["instrument_ids"] == [
        "FG701",
        "FG701C970",
        "FG701P970",
    ]


def test_evidence_participates_in_the_bundle_identity_hash() -> None:
    fixture = _fixture()
    baseline = runner.canonical_sha256(_validate(fixture))

    mutated = _fixture()
    mutated["metadata_evidence"]["provider"]["profile_family"] = "set2"
    _reseal(mutated)
    assert runner.canonical_sha256(_validate(mutated)) != baseline


# --- fail-closed evidence rules ------------------------------------------


def test_missing_evidence_fails_closed() -> None:
    fixture = _fixture()
    del fixture["metadata_evidence"]
    with pytest.raises(runner.RunnerConfigurationError) as error:
        _validate(fixture)
    assert "FIXTURE_METADATA_EVIDENCE_MISSING" in _code(error)


def test_synthetic_evidence_sources_fail_closed() -> None:
    fixture = _fixture()
    fixture["metadata_evidence"]["source"] = "local_synthetic_fixture"
    with pytest.raises(runner.RunnerConfigurationError) as error:
        _validate(fixture)
    assert "FIXTURE_METADATA_EVIDENCE_MISSING" in _code(error)


def test_tampered_evidence_without_a_new_seal_fails_closed() -> None:
    fixture = _fixture()
    fixture["metadata_evidence"]["legs"]["call"]["multiplier"] = "10"
    with pytest.raises(runner.RunnerConfigurationError) as error:
        _validate(fixture)
    assert "FIXTURE_METADATA_EVIDENCE_TAMPERED" in _code(error)


def test_evidence_disagreeing_with_the_bundle_names_the_field() -> None:
    fixture = _fixture()
    # Keep the bundle internally consistent so the dedicated evidence check is
    # the rule that must fire.
    for role in ("future", "call", "put"):
        fixture["bundle"][role]["multiplier"] = "10"
    with pytest.raises(runner.RunnerConfigurationError) as error:
        _validate(fixture)
    assert "FIXTURE_METADATA_MISMATCH:future:multiplier" in _code(error)


def test_symbol_embedded_strike_must_match_the_declared_strike() -> None:
    fixture = _fixture()
    fixture["metadata_evidence"]["legs"]["call"]["strike_price"] = "1000"
    _reseal(fixture)
    with pytest.raises(runner.RunnerConfigurationError) as error:
        _validate(fixture)
    assert "FIXTURE_SYMBOL_STRIKE_CONFLICT" in _code(error)


def test_option_type_must_match_the_leg_kind() -> None:
    fixture = _fixture()
    fixture["metadata_evidence"]["legs"]["call"]["option_type"] = "2"
    _reseal(fixture)
    with pytest.raises(runner.RunnerConfigurationError) as error:
        _validate(fixture)
    assert "FIXTURE_OPTION_TYPE_CONFLICT" in _code(error)


# --- parity-consistent synthetic quotes ----------------------------------


def test_synthetic_quotes_are_parity_consistent_and_price_the_conversion_edge() -> None:
    fixture = _fixture()
    bundle = _validate(fixture)
    quotes = fixture["base_quotes"]
    strike = float(bundle["strike"])
    multiplier = float(bundle["future"]["multiplier"])
    conversion = multiplier * (
        float(quotes["call"]["bid"])
        - float(quotes["put"]["ask"])
        - (float(quotes["future"]["ask"]) - strike)
    )
    reversal = multiplier * (
        float(quotes["put"]["bid"])
        - float(quotes["call"]["ask"])
        + (float(quotes["future"]["bid"]) - strike)
    )
    assert (conversion, reversal) == (60.0, -140.0)
    # The synthetic future must be priced near the real 970 strike, not at the
    # old placeholder 1000.
    assert abs(float(quotes["future"]["last"]) - strike) < 5.0


def test_every_synthetic_quote_sits_on_its_leg_price_grid() -> None:
    fixture = _fixture()
    bundle = _validate(fixture)
    for role in ("future", "call", "put"):
        tick = float(bundle[role]["tick_size"])
        for field in ("bid", "ask", "last"):
            value = float(fixture["base_quotes"][role][field])
            assert abs(value / tick - round(value / tick)) <= 1e-9, (role, field, value)
