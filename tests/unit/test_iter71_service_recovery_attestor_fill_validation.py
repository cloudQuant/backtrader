"""Malformed paper-fill fields fail closed at the BT attestation boundary."""

import copy

import pytest

from backtrader.service.service_recovery_attestation import (
    BacktraderServiceRecoveryAttestor,
    ServiceRecoveryAttestationError,
)


_MISMATCH = "RECOVERY_EVENT_CONTEXT_MISMATCH"


def _valid_event_context_args():
    datetime_hex = float(1.0).hex()
    quote_binding = {
        "source_ref": "quote-source-1",
        "generation": "generation-1",
        "cursor": 7,
        "instrument": "TEST",
        "as_of_ns": 100,
        "data_name": "feed-test",
        "bar_index": 1,
        "datetime_hex": datetime_hex,
    }
    comminfo = {
        "class_module": "backtrader.commissions",
        "class_name": "CommInfoBase",
        "params": {},
    }
    raw = {
        "data_name": "feed-test",
        "instrument": "TEST",
        "bar_index": 1,
        "datetime_hex": datetime_hex,
        "comminfo": comminfo,
        "commission_currency": "USD",
        "quote_source_ref": "quote-source-1",
        "quote_generation": "generation-1",
        "quote_cursor": 7,
        "quote_instrument": "TEST",
        "quote_as_of_ns": 100,
    }
    manifest = {
        "submit_payload": {"instrument": "TEST"},
        "recovery_binding": {"data_name": "feed-test"},
    }
    execution_context = {
        "feed": {"data_name": "feed-test", "instrument": "TEST"},
        "decision": {"bar_index": 1, "datetime_hex": datetime_hex},
        "comminfo": comminfo,
        "quote_binding": quote_binding,
    }
    paper_fill = {
        "commission_currency": "USD",
        "quote_source_ref": "quote-source-1",
        "quote_generation": "generation-1",
        "quote_cursor": 7,
        "quote_instrument": "TEST",
        "match_time_ns": 200,
    }
    return raw, manifest, execution_context, paper_fill


def _attest(args):
    return BacktraderServiceRecoveryAttestor().attest_event_context(*args)


def _assert_rejected_with_finite_mismatch(args):
    with pytest.raises(ServiceRecoveryAttestationError) as caught:
        _attest(args)
    assert caught.value.code == _MISMATCH


def test_valid_paper_fill_is_attested_without_mutating_inputs():
    args = _valid_event_context_args()
    before = copy.deepcopy(args)

    result = _attest(args)

    assert result.commission_currency == "USD"
    assert dict(result.facts) == args[0]
    assert args == before


def test_missing_commission_currency_is_a_finite_attestation_failure():
    args = _valid_event_context_args()
    del args[3]["commission_currency"]

    _assert_rejected_with_finite_mismatch(args)


def test_distinct_valid_commission_currencies_are_a_mismatch():
    args = _valid_event_context_args()
    args[0]["commission_currency"] = "USD"
    args[3]["commission_currency"] = "EUR"

    _assert_rejected_with_finite_mismatch(args)


@pytest.mark.parametrize("currency", [None, 123, True])
def test_non_string_commission_currency_is_rejected(currency):
    args = _valid_event_context_args()
    args[3]["commission_currency"] = currency

    _assert_rejected_with_finite_mismatch(args)


@pytest.mark.parametrize(
    "match_time_ns",
    [None, "200", 200.0, True, False, 0, -1],
)
def test_non_positive_or_non_exact_int_match_time_is_rejected(match_time_ns):
    args = _valid_event_context_args()
    args[3]["match_time_ns"] = match_time_ns

    _assert_rejected_with_finite_mismatch(args)


def test_missing_match_time_is_rejected_without_substituting_a_default():
    args = _valid_event_context_args()
    del args[3]["match_time_ns"]

    _assert_rejected_with_finite_mismatch(args)


def test_quote_must_not_be_newer_than_the_exact_match_time():
    args = _valid_event_context_args()
    args[3]["match_time_ns"] = 99

    _assert_rejected_with_finite_mismatch(args)


@pytest.mark.parametrize(
    ("context_as_of_ns", "binding_as_of_ns"),
    [
        (1, True),  # bool compares equal to int 1
        (100, 100.0),  # float compares equal to int 100
        (100, None),
        (100, "100"),
        (100, False),
        (100, 0),
        (100, -1),
    ],
)
def test_quote_binding_as_of_ns_requires_exact_positive_int(
    context_as_of_ns, binding_as_of_ns
):
    args = _valid_event_context_args()
    args[0]["quote_as_of_ns"] = context_as_of_ns
    args[2]["quote_binding"]["as_of_ns"] = binding_as_of_ns

    _assert_rejected_with_finite_mismatch(args)


def test_missing_quote_binding_as_of_ns_is_rejected():
    args = _valid_event_context_args()
    del args[2]["quote_binding"]["as_of_ns"]

    _assert_rejected_with_finite_mismatch(args)
