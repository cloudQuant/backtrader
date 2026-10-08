"""Only inert connector/clock samples and public synthetic projection files."""

from dataclasses import replace
import json

import pytest

from scripts import ctp_000_paired_front_selector as selector


def document(count=2):
    return {
        "schema": selector.SCHEMA,
        "venue": "simnow",
        "scope": "transport_only",
        "strategy_id": selector.STRATEGY,
        "front_pairs": [
            {
                "md_front": f"tcp://192.0.2.{2 * i + 1}:10001",
                "td_front": f"tcp://192.0.2.{2 * i + 2}:10002",
            }
            for i in range(count)
        ],
    }


class Fixture:
    def __init__(self, samples):
        self.samples = {host: list(values) for host, values in samples.items()}
        self.elapsed = 0.0
        self.calls = []
        self.closed = 0

    def clock(self):
        return self.elapsed

    def connect(self, host, port, timeout):
        self.calls.append((host, port, timeout))
        value = self.samples[host].pop(0)
        if value is None:
            self.elapsed += timeout
            raise TimeoutError("synthetic only")
        self.elapsed += value / 1000
        fixture = self

        class Socket:
            def close(self):
                fixture.closed += 1

        return Socket()


def observe(samples, count=2):
    fixture = Fixture(samples)
    result = selector.observe_document(
        document(count), connector=fixture.connect, clock=fixture.clock
    )
    return result, fixture


def test_lower_worst_side_median_wins_over_stability_and_pairs_never_mix():
    result, fixture = observe(
        {
            "192.0.2.1": [80, 90, 100],
            "192.0.2.2": [90, 100, 110],
            "192.0.2.3": [1, 1, None],
            "192.0.2.4": [2, 2, 2],
        }
    )
    assert result["selected_config_index"] == 1 and result["degraded_candidate"]
    assert result["pairs"][0]["md"]["median_success_latency_ms"] == 90
    assert result["pairs"][0]["td"]["max_success_latency_ms"] == 110
    assert result["pairs"][1]["eligible_both_reachable"] is True
    assert result["pairs"][1]["stable_both_3_of_3"] is False
    assert result["pairs"][1]["score"] == [2.0, 1]
    assert result["score_order"] == ["worst_side_median_ms", "config_index"]
    assert len(fixture.calls) == 12 and fixture.closed == 11
    assert all(timeout == 1 for _, _, timeout in fixture.calls)
    assert not result["provider_login_started"] and not result["registered_runtime_dispatched"]
    assert result["ctp_gate_status"] == "NO_WRITE / LIVE_NO_GO"
    assert "tcp://" not in json.dumps(result)


def test_worst_side_median_not_fastest_individual_side():
    result, _ = observe(
        {
            "192.0.2.1": [1, 1, 1],
            "192.0.2.2": [100, 100, 100],
            "192.0.2.3": [20, 20, 20],
            "192.0.2.4": [30, 30, 30],
        }
    )
    assert result["selected_config_index"] == 1


def test_equal_median_uses_config_order_and_ignores_maximum_latency():
    result, _ = observe(
        {
            "192.0.2.1": [10, 10, 99],
            "192.0.2.2": [10, 10, 10],
            "192.0.2.3": [10, 10, 20],
            "192.0.2.4": [10, 10, 20],
        }
    )
    assert result["selected_config_index"] == 0
    assert result["pairs"][0]["score"][0] == result["pairs"][1]["score"][0] == 10.0
    assert result["pairs"][0]["score"][1] == 0
    assert result["pairs"][1]["score"][1] == 1
    equal, _ = observe({f"192.0.2.{i}": [10, 10, 10] for i in range(1, 5)})
    assert equal["selected_config_index"] == 0


def test_single_pair_with_one_success_per_side_is_eligible_and_degraded():
    result, fixture = observe(
        {"192.0.2.1": [None, 11, None], "192.0.2.2": [None, 13, None]}, count=1
    )
    assert result["status"] == "TRANSPORT_CANDIDATE"
    assert result["selected_config_index"] == 0
    assert result["degraded_candidate"] is True
    assert result["pairs"][0]["eligible_both_reachable"] is True
    assert result["pairs"][0]["stable_both_3_of_3"] is False
    assert result["pairs"][0]["score"] == [13.0, 0]
    assert len(fixture.calls) == 6 and fixture.closed == 2


def test_tied_latency_prefers_earlier_one_of_three_pair_over_later_stable_pair():
    result, _ = observe(
        {
            "192.0.2.1": [10, None, None],
            "192.0.2.2": [20, None, None],
            "192.0.2.3": [10, 10, 10],
            "192.0.2.4": [20, 20, 20],
        }
    )
    assert result["selected_config_index"] == 0
    assert result["pairs"][0]["score"][0] == result["pairs"][1]["score"][0] == 20.0
    assert result["pairs"][0]["score"][1] == 0
    assert result["pairs"][1]["score"][1] == 1
    assert result["pairs"][0]["stable_both_3_of_3"] is False
    assert result["pairs"][1]["stable_both_3_of_3"] is True


def test_one_sided_success_and_all_unavailable_have_no_candidate():
    result, _ = observe(
        {
            "192.0.2.1": [1, None, None],
            "192.0.2.2": [None, None, None],
        },
        count=1,
    )
    assert result["status"] == "NO_CANDIDATE" and result["selected_config_index"] is None
    assert result["pairs"][0]["eligible_both_reachable"] is False
    assert result["pairs"][0]["score"] is None

    down, _ = observe(
        {"192.0.2.1": [None, None, None], "192.0.2.2": [None, None, None]}, count=1
    )
    assert down["status"] == "NO_CANDIDATE" and down["selected_config_index"] is None


def test_successes_on_opposite_pairs_cannot_make_one_reachable_pair():
    result, fixture = observe(
        {
            "192.0.2.1": [1, 1, 1],
            "192.0.2.2": [None, None, None],
            "192.0.2.3": [None, None, None],
            "192.0.2.4": [1, 1, 1],
        }
    )
    assert result["status"] == "NO_CANDIDATE" and result["selected_config_index"] is None
    assert len(fixture.calls) == 12


@pytest.mark.parametrize(
    "change", ["007", "credential", "hostname", "ninth", "duplicate", "ipv6", "url_auth"]
)
def test_invalid_projection_rejects_before_probe_import(monkeypatch, change):
    value = document()
    if change == "007":
        value["strategy_id"] = "example.007_ctp.simnow_penetration"
    elif change == "credential":
        value["password"] = "synthetic"
    elif change == "hostname":
        value["front_pairs"][0]["md_front"] = "tcp://simnow.invalid:10001"
    elif change == "ninth":
        value = document(9)
    elif change == "duplicate":
        value["front_pairs"][1] = value["front_pairs"][0]
    elif change == "ipv6":
        value["front_pairs"][0]["md_front"] = "tcp://[::1]:10001"
    else:
        value["front_pairs"][0]["md_front"] = "tcp://name:secret@192.0.2.1:10001"
    monkeypatch.setattr(
        selector, "_probe_module", lambda: pytest.fail("validation must precede probe")
    )
    with pytest.raises(selector.SelectorError):
        selector.observe_document(value)


def test_duplicate_json_keys_and_oversize_are_rejected():
    raw = json.dumps(document()).encode()
    with pytest.raises(selector.SelectorError, match="duplicate_json_key"):
        selector.parse_document(
            raw.replace(b'"venue": "simnow"', b'"venue": "simnow", "venue": "simnow"')
        )
    with pytest.raises(selector.SelectorError, match="size_invalid"):
        selector.parse_document(b" " * 8193)


def test_swapped_evidence_endpoint_cannot_change_config_pair(monkeypatch):
    probe = selector._probe_module()
    value = document(1)
    fixture = Fixture({"192.0.2.1": [1, 1, 1], "192.0.2.2": [2, 2, 2]})
    selection = probe.select_ctp_front_pair(
        value["front_pairs"],
        timeout_seconds=1,
        max_pairs=8,
        repeated_samples=3,
        connector=fixture.connect,
        clock=fixture.clock,
    )
    wrong = replace(selection.evidence[0], md=selection.evidence[0].td)
    with pytest.raises(selector.SelectorError, match="evidence_invalid"):
        selector.rank_evidence(tuple(value["front_pairs"]), (wrong,), probe)


@pytest.mark.parametrize(
    "latency",
    [float("nan"), float("inf"), -0.1, True, 10**10000],
    ids=("nan", "infinity", "negative", "boolean", "integer_overflow"),
)
def test_malformed_or_nonfinite_latency_evidence_fails_closed(latency):
    probe = selector._probe_module()
    pair = document(1)["front_pairs"][0]

    def endpoint(front, value):
        samples = (
            probe.CtpFrontProbeSample(True, value),
            probe.CtpFrontProbeSample(False, None),
            probe.CtpFrontProbeSample(False, None),
        )
        return probe.CtpFrontEndpointEvidence(front, samples)

    evidence = probe.CtpFrontPairEvidence(
        config_index=0,
        pair=probe.CtpConfiguredFrontPair(pair["md_front"], pair["td_front"]),
        md=endpoint(pair["md_front"], latency),
        td=endpoint(pair["td_front"], 1.0),
        reachable=True,
        latency_score_ms=1.0,
    )
    with pytest.raises(selector.SelectorError, match="probe_evidence_invalid"):
        selector.rank_evidence((pair,), (evidence,), probe)


def test_full_deadline_never_emits_stale_candidate(monkeypatch):
    probe = selector._probe_module()
    value = document(1)
    fixture = Fixture({"192.0.2.1": [1, 1, 1], "192.0.2.2": [2, 2, 2]})
    selection = probe.select_ctp_front_pair(
        value["front_pairs"],
        timeout_seconds=1,
        max_pairs=8,
        repeated_samples=3,
        connector=fixture.connect,
        clock=fixture.clock,
    )
    times = iter([0.0, 31.0])
    monkeypatch.setattr(probe, "select_ctp_front_pair", lambda *a, **kw: selection)
    result = selector.observe_document(value, clock=lambda: next(times))
    assert result["selected_config_index"] is None and result["deadline_observed_exceeded"]


def test_cli_check_is_offline_and_missing_confirmation_precedes_read(monkeypatch, tmp_path, capsys):
    path = tmp_path / "public-pairs.json"
    path.write_text(json.dumps(document()), encoding="utf-8")
    monkeypatch.setattr(selector, "_probe_module", lambda: pytest.fail("check cannot probe"))
    assert selector.main(["--check", "--pairs-json", str(path)]) == 0
    value = json.loads(capsys.readouterr().out)
    assert value["status"] == "INPUT_VALIDATED_ONLY" and not value["tcp_probe_started"]
    assert "tcp://" not in json.dumps(value)
    assert selector.main(["--probe", "--pairs-json", str(tmp_path / "missing.json")]) == 2
    assert (
        json.loads(capsys.readouterr().out)["reason"]
        == "explicit_transport_probe_confirmation_required"
    )


def test_cli_probe_requires_explicit_scope_and_reports_no_authority(monkeypatch, tmp_path, capsys):
    path = tmp_path / "public-pairs.json"
    path.write_text(json.dumps(document(1)), encoding="utf-8")
    real = selector.observe_document

    def fake_transport(value):
        fixture = Fixture({"192.0.2.1": [1, 1, 1], "192.0.2.2": [2, 2, 2]})
        return real(value, connector=fixture.connect, clock=fixture.clock)

    monkeypatch.setattr(selector, "observe_document", fake_transport)
    assert selector.main(["--probe", "--confirm-transport-only", "--pairs-json", str(path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["selected_config_index"] == 0 and result["execution_authority"] == "NONE"
