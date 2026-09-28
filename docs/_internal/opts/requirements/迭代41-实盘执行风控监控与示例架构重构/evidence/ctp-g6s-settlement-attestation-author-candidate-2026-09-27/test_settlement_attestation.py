"""Fake-only tests for the isolated G6-S settlement evidence contract."""
from dataclasses import replace
import hashlib

import pytest

from settlement_attestation import (
    CurrentTdSession,
    SelectedSimNowScope,
    SettlementAttestationError,
    SettlementQueryEvidence,
    SettlementQuerySource,
    VerifiedSettlementQueryProvenance,
    _REQUIRED_COUNTERS,
    attest_simnow_settlement_readback,
    _filters_digest,
    _records_digest,
)

DAY = "20260925"
BROKER = "9999"
INVESTOR = "offline-settlement-test"
MD = "tcp://127.0.0.1:11001"
TD = "tcp://127.0.0.1:12001"


def _scope():
    account = hashlib.sha256((BROKER + ":" + INVESTOR).encode()).hexdigest()[:16]
    account_sha = hashlib.sha256(("acct_" + account).encode("ascii")).hexdigest()
    return SelectedSimNowScope(
        config_digest="1" * 64,
        registration_digest="2" * 64,
        front_pair_set_sha256="3" * 64,
        selected_pair_index=2,
        md_front=MD,
        td_front=TD,
        broker_id=BROKER,
        investor_id=INVESTOR,
        account_fingerprint=account,
        account_fingerprint_sha256=account_sha,
    )


def _session(scope=None, *, issuer=None):
    scope = scope or _scope()
    issuer = issuer if issuer is not None else object()
    return CurrentTdSession(
        issuer=issuer,
        config_digest=scope.config_digest,
        registration_digest=scope.registration_digest,
        front_pair_set_sha256=scope.front_pair_set_sha256,
        selected_pair_index=scope.selected_pair_index,
        md_front_configured=scope.md_front,
        md_front_registered=scope.md_front,
        md_front_connected=scope.md_front,
        td_front_configured=scope.td_front,
        td_front_registered=scope.td_front,
        td_front_connected=scope.td_front,
        broker_id=scope.broker_id,
        investor_id=scope.investor_id,
        account_fingerprint=scope.account_fingerprint,
        account_fingerprint_sha256=scope.account_fingerprint_sha256,
        connection_generation=7,
        trading_day=DAY,
        connected=True,
        read_only_ready=True,
        auto_settlement_confirm=False,
        execution_gate_armed=False,
        native_api_current=True,
        bound_identity_current=True,
    )


def _query(scope=None, current=None, *, records=None):
    scope = scope or _scope()
    current = current or _session(scope)
    records = records if records is not None else (
        {"BrokerID": BROKER, "InvestorID": INVESTOR, "TradingDay": DAY, "ConfirmDate": DAY},
    )
    filters = (("BrokerID", BROKER), ("InvestorID", INVESTOR))
    source = SettlementQuerySource(
        issuer=current.issuer,
        request_type="settlement_confirmation",
        request_id=51,
        account_fingerprint=scope.account_fingerprint,
        connection_generation=current.connection_generation,
        trading_day=current.trading_day,
        broker_id=BROKER,
        investor_id=INVESTOR,
        request_filters=filters,
        explicit_request_filters=(),
        records_sha256=_records_digest(records),
    )
    counts_before = dict((name, 0) for name in _REQUIRED_COUNTERS)
    counts_before["authenticate"] = 1
    counts_before["login"] = 1
    counts_after = dict(counts_before)
    counts_after["query_settlement_confirmation"] = 1
    return SettlementQueryEvidence(
        request_type="settlement_confirmation",
        request_id=51,
        connection_generation=current.connection_generation,
        account_fingerprint=scope.account_fingerprint,
        complete=True,
        is_last_seen=True,
        timed_out=False,
        unsupported=False,
        error_code=0,
        error_message="",
        submit_code=0,
        late_callback_count=0,
        records=records,
        source=source,
        request_counts_before=tuple(sorted(counts_before.items())),
        request_counts_after=tuple(sorted(counts_after.items())),
    )


class _FakeVerifier:
    def __init__(self, *, source=None, records=None, filters=None, seal=True, history=True,
                 terminal=True, fresh=True, issuer=None, error=None):
        self.source = source or "4" * 64
        self.records = records
        self.filters = filters
        self.seal = seal
        self.history = history
        self.terminal = terminal
        self.fresh = fresh
        self.issuer = issuer
        self.error = error
        self.calls = 0

    def verify_settlement_query(self, query, expected, current):
        self.calls += 1
        if self.error:
            raise RuntimeError("redact this SDK detail")
        return VerifiedSettlementQueryProvenance(
            issuer=self.issuer if self.issuer is not None else current.issuer,
            request_type=query.request_type,
            request_id=query.request_id,
            source_sha256=self.source,
            records_sha256=self.records or query.source.records_sha256,
            request_filters_sha256=self.filters or _filters_digest(query.source.request_filters),
            source_seal_verified=self.seal,
            current_history_matches=self.history,
            terminal_callback_verified=self.terminal,
            fresh=self.fresh,
        )


def _attest(query=None, scope=None, current=None, verifier=None):
    scope = scope or _scope()
    current = current or _session(scope)
    query = query or _query(scope, current)
    return attest_simnow_settlement_readback(
        scope,
        current,
        query,
        provenance_verifier=verifier or _FakeVerifier(),
    )


def test_matching_current_day_row_and_terminal_provenance_yields_non_authorizing_attestation():
    result = _attest()
    assert result.selected_pair_index == 2
    assert result.md_front == MD and result.td_front == TD
    assert result.trading_day == DAY and result.connection_generation == 7
    assert result.query_request_id == 51
    assert result.settlement_confirmation_observed is True
    assert result.query_terminal_provenance_verified is True
    assert result.local_contract_only is True
    assert result.atomic_snapshot_verified is False
    assert result.account_writer_fence_verified is False
    assert result.execution_gate_armed is False
    assert result.write_authority_granted is False


@pytest.mark.parametrize("field,value", [
    ("complete", False),
    ("is_last_seen", False),
    ("timed_out", True),
    ("unsupported", True),
    ("error_code", 9),
    ("error_message", "native failure"),
    ("submit_code", 7),
    ("late_callback_count", 1),
    ("request_type", "orders"),
    ("request_id", 0),
    ("connection_generation", 8),
    ("account_fingerprint", "f" * 16),
])
def test_nonterminal_or_wrong_scope_query_envelope_fails_closed(field, value):
    scope = _scope()
    current = _session(scope)
    query = replace(_query(scope, current), **{field: value})
    with pytest.raises(SettlementAttestationError):
        _attest(query=query, scope=scope, current=current)


@pytest.mark.parametrize("field,value", [
    ("md_front_configured", "tcp://127.0.0.1:11002"),
    ("md_front_registered", "tcp://127.0.0.1:11002"),
    ("md_front_connected", "tcp://127.0.0.1:11002"),
    ("td_front_configured", "tcp://127.0.0.1:12002"),
    ("td_front_registered", "tcp://127.0.0.1:12002"),
    ("td_front_connected", "tcp://127.0.0.1:12002"),
    ("front_pair_set_sha256", "f" * 64),
    ("selected_pair_index", 1),
    ("config_digest", "f" * 64),
    ("registration_digest", "f" * 64),
    ("connected", False),
    ("read_only_ready", False),
    ("auto_settlement_confirm", True),
    ("execution_gate_armed", True),
    ("native_api_current", False),
    ("bound_identity_current", False),
    ("trading_day", "20260924"),
    ("connection_generation", "7"),
])
def test_current_session_pair_day_or_read_only_state_mismatch_fails(field, value):
    scope = _scope()
    current = replace(_session(scope), **{field: value})
    with pytest.raises(SettlementAttestationError):
        _attest(scope=scope, current=current, query=_query(scope, current))


@pytest.mark.parametrize("records", [
    (),
    ({"BrokerID": BROKER, "InvestorID": INVESTOR, "ConfirmDate": DAY},
     {"BrokerID": BROKER, "InvestorID": INVESTOR, "ConfirmDate": DAY}),
    ({"BrokerID": "elsewhere", "InvestorID": INVESTOR, "ConfirmDate": DAY},),
    ({"BrokerID": BROKER, "InvestorID": "other-user", "ConfirmDate": DAY},),
    ({"BrokerID": BROKER, "InvestorID": INVESTOR, "ConfirmDate": "20260924"},),
    ({"BrokerID": BROKER, "InvestorID": INVESTOR, "TradingDay": "20260925",
      "ConfirmDate": "20260924"},),
    ({"BrokerID": BROKER, "InvestorID": INVESTOR},),
    (None,),
])
def test_missing_ambiguous_or_wrong_settlement_record_fails(records):
    scope = _scope()
    current = _session(scope)
    query = _query(scope, current, records=records)
    with pytest.raises(SettlementAttestationError):
        _attest(scope=scope, current=current, query=query)


@pytest.mark.parametrize("mutate", [
    lambda source: replace(source, request_filters=(("BrokerID", BROKER),)),
    lambda source: replace(source, request_filters=(("BrokerID", BROKER),
                                                   ("InvestorID", "other-user"))),
    lambda source: replace(source, request_type="orders"),
    lambda source: replace(source, request_id=52),
    lambda source: replace(source, connection_generation=8),
    lambda source: replace(source, trading_day="20260924"),
    lambda source: replace(source, broker_id="other-broker"),
    lambda source: replace(source, investor_id="other-user"),
    lambda source: replace(source, explicit_request_filters=("BrokerID",)),
])
def test_source_scope_filter_and_provenance_binding_mismatches_fail(mutate):
    scope = _scope()
    current = _session(scope)
    query = _query(scope, current)
    query = replace(query, source=mutate(query.source))
    with pytest.raises(SettlementAttestationError):
        _attest(scope=scope, current=current, query=query)


@pytest.mark.parametrize("kwargs", [
    {"seal": False},
    {"history": False},
    {"terminal": False},
    {"fresh": False},
    {"source": "bad"},
    {"records": "5" * 64},
    {"filters": "6" * 64},
    {"issuer": object()},
    {"error": True},
])
def test_injected_source_verifier_must_prove_seal_history_terminal_and_freshness(kwargs):
    scope = _scope()
    current = _session(scope)
    query = _query(scope, current)
    with pytest.raises(SettlementAttestationError):
        _attest(scope=scope, current=current, query=query, verifier=_FakeVerifier(**kwargs))


def test_injected_verifier_must_return_exact_typed_result():
    class BoolVerifier:
        def verify_settlement_query(self, *_args):
            return True

    with pytest.raises(SettlementAttestationError) as exc:
        _attest(verifier=BoolVerifier())
    assert exc.value.reason == "settlement_query_provenance_unverified"


@pytest.mark.parametrize("gap", ["request_filters", "source_seal", "history", "records_digest"])
def test_correct_looking_row_without_exact_native_provenance_rejects_with_zero_writes(gap):
    scope = _scope()
    current = _session(scope)
    query = _query(scope, current)
    verifier = _FakeVerifier()
    if gap == "request_filters":
        query = replace(query, source=replace(query.source, request_filters=()))
    elif gap == "source_seal":
        verifier = _FakeVerifier(seal=False)
    elif gap == "history":
        verifier = _FakeVerifier(history=False)
    else:
        verifier = _FakeVerifier(records="5" * 64)

    assert query.records == (
        {"BrokerID": BROKER, "InvestorID": INVESTOR, "TradingDay": DAY, "ConfirmDate": DAY},
    )
    with pytest.raises(SettlementAttestationError):
        _attest(scope=scope, current=current, query=query, verifier=verifier)

    counts_after = dict(query.request_counts_after)
    assert counts_after["query_settlement_confirmation"] == 1
    assert counts_after["settlement_confirm"] == 0
    assert counts_after["order_insert"] == 0
    assert counts_after["order_action"] == 0
    if gap == "request_filters":
        assert verifier.calls == 0
    else:
        assert verifier.calls == 1


def test_query_source_must_be_from_current_same_issuer():
    scope = _scope()
    current = _session(scope)
    query = _query(scope, current)
    query = replace(query, source=replace(query.source, issuer=object()))
    with pytest.raises(SettlementAttestationError) as exc:
        _attest(scope=scope, current=current, query=query)
    assert exc.value.reason == "settlement_query_source_scope_mismatch"


def test_record_mutation_during_provenance_verification_fails_closed():
    class MutatingVerifier(_FakeVerifier):
        def verify_settlement_query(self, query, expected, current):
            query.records[0]["ConfirmDate"] = "20260924"
            return super().verify_settlement_query(query, expected, current)

    scope = _scope()
    current = _session(scope)
    query = _query(scope, current)
    with pytest.raises(SettlementAttestationError) as exc:
        _attest(scope=scope, current=current, query=query, verifier=MutatingVerifier())
    assert exc.value.reason == "settlement_query_records_mutated_during_verification"


def test_injected_verifier_is_called_only_after_structural_validation():
    verifier = _FakeVerifier()
    scope = _scope()
    current = _session(scope)
    query = replace(_query(scope, current), is_last_seen=False)
    with pytest.raises(SettlementAttestationError):
        _attest(scope=scope, current=current, query=query, verifier=verifier)
    assert verifier.calls == 0


@pytest.mark.parametrize("which,name,value", [
    ("before", "settlement_confirm", 1),
    ("after", "settlement_confirm", 1),
    ("after", "order_insert", 1),
    ("after", "order_action", 1),
    ("before", "query_settlement_confirmation", 1),
    ("after", "query_settlement_confirmation", 2),
    ("after", "login", 2),
    ("after", "unknown_native_request", 1),
])
def test_request_counter_delta_requires_one_read_and_zero_writes(which, name, value):
    scope = _scope()
    current = _session(scope)
    query = _query(scope, current)
    before = dict(query.request_counts_before)
    after = dict(query.request_counts_after)
    target = before if which == "before" else after
    target[name] = value
    query = replace(
        query,
        request_counts_before=tuple(sorted(before.items())),
        request_counts_after=tuple(sorted(after.items())),
    )
    with pytest.raises(SettlementAttestationError):
        _attest(scope=scope, current=current, query=query)


def test_request_counter_shape_change_fails_closed():
    scope = _scope()
    current = _session(scope)
    query = _query(scope, current)
    query = replace(query, request_counts_after=query.request_counts_after[:-1])
    with pytest.raises(SettlementAttestationError):
        _attest(scope=scope, current=current, query=query)


def test_attestation_constructor_rejects_caller_minted_or_authorizing_value():
    with pytest.raises(SettlementAttestationError) as exc:
        from settlement_attestation import CtpSimNowSettlementAttestation
        CtpSimNowSettlementAttestation(
            config_digest="1" * 64,
            registration_digest="2" * 64,
            front_pair_set_sha256="3" * 64,
            selected_pair_index=2,
            md_front=MD,
            td_front=TD,
            account_fingerprint_sha256="4" * 64,
            account_fingerprint="0123456789abcdef",
            broker_id=BROKER,
            investor_id=INVESTOR,
            trading_day=DAY,
            connection_generation=7,
            query_request_id=51,
            query_source_sha256="4" * 64,
            query_records_sha256="5" * 64,
            settlement_confirmation_observed=True,
            query_terminal_provenance_verified=True,
            local_contract_only=True,
            atomic_snapshot_verified=False,
            account_writer_fence_verified=False,
            execution_gate_armed=False,
            write_authority_granted=False,
            query_settlement_confirmation_calls=1,
            settlement_confirm_write_calls=0,
            order_insert_write_calls=0,
            order_action_write_calls=0,
        )
    assert exc.value.reason == "settlement_attestation_unissued"
