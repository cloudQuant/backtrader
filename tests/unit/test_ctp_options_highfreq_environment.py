"""Environment-selection coverage for the Iteration 30 CTP-options example.

These tests use an injected resolver, so they never open a socket.  They pin the
frozen SimNow profile table, the family-only fallback rule and the derived
identifiers that must not mention an unrelated environment.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

runner = importlib.import_module("examples.015_ctp_options_highfreq.run")
adapter = importlib.import_module("examples.015_ctp_options_highfreq.engineering_smoke")

RAW_CONFIG, _ = runner.load_config()
DEFAULT_PROFILE = "simnow_first_group1"


def _resolver(actual: str, *, reason: str = "tcp_pair_reachable"):
    """Return a resolver that reports one reachable profile without any I/O."""

    def resolve(**_kwargs: Any) -> Mapping[str, Any]:
        return {
            "actual_profile": actual,
            "td_front": "tcp://127.0.0.1:30001",
            "md_front": "tcp://127.0.0.1:30011",
            "readiness": "tcp_pair_reachable",
            "reason": reason,
        }

    return resolve


def _unreachable(**_kwargs: Any) -> Mapping[str, Any]:
    raise RuntimeError("no reachable CTP front pair for the selected profile group")


def _session(profile: str, *, generation: int = 1) -> dict[str, Any]:
    return {
        "environment_profile": profile,
        "connected": True,
        "read_only_ready": True,
        "execution_gate_armed": False,
        "account_fingerprint": "iter30-injected-account",
        "connection_generation": generation,
    }


def _mapping(generation: int = 1) -> SimpleNamespace:
    return SimpleNamespace(connection_generation=generation, mapping_id="iter30-test-mapping")


class _Blocked(Exception):
    """Stand-in for the example's observation-blocked error type."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# --- frozen table ---------------------------------------------------------


def test_config_selects_the_frozen_first_set_environment_by_default() -> None:
    assert RAW_CONFIG["environment"] == DEFAULT_PROFILE
    assert runner.DEFAULT_ENVIRONMENT == DEFAULT_PROFILE


def test_environment_profiles_are_frozen_and_cover_both_simnow_sets() -> None:
    profiles = runner.ENVIRONMENT_PROFILES
    assert set(profiles) == {
        "simnow_first_group1",
        "simnow_first_group2",
        "simnow_second_7x24",
    }
    assert profiles["simnow_first_group1"] == {
        "family": "set1",
        "market_alignment": "actual_market_hours",
        "sdk_profile": "set1_group1",
        "fallback_sdk_profile": "set1_group1_vpn",
    }
    assert profiles["simnow_first_group2"]["fallback_sdk_profile"] is None
    assert profiles["simnow_second_7x24"] == {
        "family": "set2",
        "market_alignment": "engineering_only",
        "sdk_profile": "set2_7x24_4000x",
        "fallback_sdk_profile": None,
    }


def test_frozen_sdk_profile_names_exist_in_the_sdk_table() -> None:
    sdk = pytest.importorskip("bt_api_ctp.ctp_env_selector")
    for profile in runner.ENVIRONMENT_PROFILES.values():
        for key in ("sdk_profile", "fallback_sdk_profile"):
            name = profile[key]
            if name is None:
                continue
            td_front, md_front = sdk.official_simnow_fronts(name)
            assert td_front.startswith("tcp://") and md_front.startswith("tcp://")


def test_config_environment_must_be_a_frozen_key() -> None:
    config = dict(RAW_CONFIG)
    config["environment"] = "set1_group1"  # a raw SDK name is not a config key
    with pytest.raises(runner.RunnerConfigurationError):
        runner.validate_config(config)


# --- selection ------------------------------------------------------------


def test_selection_uses_the_nominal_profile_when_it_is_reachable() -> None:
    selection = runner.select_environment(RAW_CONFIG, resolver=_resolver("set1_group1"))
    assert selection.requested_profile == "simnow_first_group1"
    assert selection.attempted_profile == "set1_group1"
    assert selection.actual_profile == "set1_group1"
    assert selection.family == "set1"
    assert selection.market_alignment == "actual_market_hours"
    assert (selection.td_front, selection.md_front) == (
        "tcp://127.0.0.1:30001",
        "tcp://127.0.0.1:30011",
    )
    assert selection.readiness == "tcp_pair_reachable"
    assert selection.reason == "tcp_pair_reachable"


def test_selection_accepts_the_frozen_family_fallback() -> None:
    selection = runner.select_environment(RAW_CONFIG, resolver=_resolver("set1_group1_vpn"))
    assert selection.actual_profile == "set1_group1_vpn"
    assert selection.family == "set1"


def test_selection_rejects_a_result_outside_the_requested_family() -> None:
    with pytest.raises(runner.RunnerConfigurationError) as error:
        runner.select_environment(RAW_CONFIG, resolver=_resolver("set2_7x24_4000x"))
    assert "CTP_SESSION_PROFILE_REQUIRED" in str(error.value)


def test_selection_fails_closed_when_the_family_has_no_reachable_pair() -> None:
    with pytest.raises(runner.RunnerConfigurationError) as error:
        runner.select_environment(RAW_CONFIG, resolver=_unreachable)
    assert "CTP_SESSION_PROFILE_UNAVAILABLE" in str(error.value)


def test_selection_can_target_the_second_set_without_crossing_families() -> None:
    config = dict(RAW_CONFIG, environment="simnow_second_7x24")
    selection = runner.select_environment(config, resolver=_resolver("set2_7x24_4000x"))
    assert selection.family == "set2"
    assert selection.market_alignment == "engineering_only"


def test_selection_override_accepts_only_frozen_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(runner.ENVIRONMENT_SELECTION_ENV, "simnow_second_7x24")
    selection = runner.select_environment(RAW_CONFIG, resolver=_resolver("set2_7x24_4000x"))
    assert selection.requested_profile == "simnow_second_7x24"

    monkeypatch.setenv(runner.ENVIRONMENT_SELECTION_ENV, "set1_group1")
    with pytest.raises(runner.RunnerConfigurationError) as error:
        runner.select_environment(RAW_CONFIG, resolver=_resolver("set1_group1"))
    assert "SIMNOW_PROFILE" in str(error.value)


def test_derived_identifiers_follow_the_actual_profile() -> None:
    selection = runner.select_environment(RAW_CONFIG, resolver=_resolver("set1_group1_vpn"))
    assert selection.clock_domain_id == "iter30-set1_group1_vpn-monotonic-v1"
    assert selection.mapping_source == "iter30-set1_group1_vpn-launcher-anchor"
    assert "set2" not in selection.clock_domain_id
    assert "set2" not in selection.mapping_source


# --- session binding ------------------------------------------------------


def test_session_binding_accepts_any_profile_inside_the_selected_family() -> None:
    selection = runner.select_environment(RAW_CONFIG, resolver=_resolver("set1_group1_vpn"))
    binding = runner.require_session_environment(
        _session("set1_group1_vpn"),
        selection=selection,
        mapping=_mapping(),
        observation_blocked=_Blocked,
    )
    assert binding["actual_environment_profile"] == "set1_group1_vpn"
    assert binding["profile_family_prefix"] == "set1"
    assert binding["source"] == "BtApiStore.get_ctp_session_state"
    assert binding["connection_generation"] == 1


def test_session_binding_rejects_a_cross_family_profile() -> None:
    selection = runner.select_environment(RAW_CONFIG, resolver=_resolver("set1_group1_vpn"))
    with pytest.raises(_Blocked) as error:
        runner.require_session_environment(
            _session("set2_7x24_shadow"),
            selection=selection,
            mapping=_mapping(),
            observation_blocked=_Blocked,
        )
    assert error.value.code == "CTP_SESSION_PROFILE_REQUIRED"


def test_session_binding_rejects_an_unclassifiable_profile() -> None:
    selection = runner.select_environment(RAW_CONFIG, resolver=_resolver("set1_group1_vpn"))
    with pytest.raises(_Blocked) as error:
        runner.require_session_environment(
            _session("custom_route"),
            selection=selection,
            mapping=_mapping(),
            observation_blocked=_Blocked,
        )
    assert error.value.code == "CTP_SESSION_PROFILE_REQUIRED"


def test_session_binding_requires_the_mapping_generation_to_match() -> None:
    selection = runner.select_environment(RAW_CONFIG, resolver=_resolver("set1_group1_vpn"))
    with pytest.raises(_Blocked) as error:
        runner.require_session_environment(
            _session("set1_group1_vpn", generation=2),
            selection=selection,
            mapping=_mapping(generation=1),
            observation_blocked=_Blocked,
        )
    assert error.value.code == "CTP_SESSION_GENERATION_REQUIRED"


# --- offline selection seam ----------------------------------------------


def test_offline_selection_never_probes_and_matches_the_frozen_table() -> None:
    selection = runner.environment_selection_from_profile("simnow_first_group1")
    assert selection.actual_profile == "set1_group1"
    assert selection.readiness == "not_probed"
    assert selection.family == "set1"
    assert selection.td_front is None and selection.md_front is None


def test_offline_selection_rejects_unknown_profiles() -> None:
    with pytest.raises(runner.RunnerConfigurationError):
        runner.environment_selection_from_profile("simnow_third_set")


def test_observation_seam_accepts_any_frozen_environment_key() -> None:
    """The injected seam is environment-agnostic (Iteration 30, FR30-02)."""

    for key in ("simnow_first_group1", "simnow_second_7x24"):
        selection = runner.environment_selection_from_profile(key)
        assert selection.requested_profile == key
        assert selection.family == runner.ENVIRONMENT_PROFILES[key]["family"]
    with pytest.raises(runner.RunnerConfigurationError):
        runner.environment_selection_from_profile("simnow_second_7x24_unfrozen")


# --- launcher wiring ------------------------------------------------------


launcher = importlib.import_module("examples.015_ctp_options_highfreq.simnow_launcher")

_CREDENTIALS = {
    "CTP_USER_ID": "iter30-user",
    "CTP_PASSWORD": "iter30-password",
    "CTP_BROKER_ID": "9999",
    "CTP_APP_ID": "simnow_client_test",
    "CTP_AUTH_CODE": "0000000000000000",
}


def test_launcher_kwargs_use_the_selected_profiles_fronts_and_identifiers() -> None:
    selection = runner.select_environment(RAW_CONFIG, resolver=_resolver("set1_group1_vpn"))
    kwargs = launcher.build_exchange_kwargs(_CREDENTIALS, selection, rules_hash="iter30hash")
    block = kwargs[launcher.CTP_EXCHANGE]
    assert block["td_front"] == "tcp://127.0.0.1:30001"
    assert block["md_front"] == "tcp://127.0.0.1:30011"
    assert block["ctp_env_profile"] == "set1_group1_vpn"
    assert block["require_ctp_profile"] == "set1_group1_vpn"
    assert block["quote_v2_metadata"]["clock_domain_id"] == selection.clock_domain_id
    assert block["quote_v2_metadata"]["rules_hash"] == "iter30hash"
    assert "set2" not in block["quote_v2_metadata"]["clock_domain_id"]


def test_launcher_rejects_env_endpoint_overrides_that_disagree() -> None:
    selection = runner.select_environment(RAW_CONFIG, resolver=_resolver("set1_group1_vpn"))
    environ = {"CTP_TD_FRONT": "tcp://127.0.0.1:9999"}
    with pytest.raises(SystemExit) as error:
        launcher.require_frozen_fronts(environ, selection)
    assert "SIMNOW_PROFILE_OVERRIDE_REJECTED" in str(error.value)


def test_launcher_accepts_an_env_endpoint_that_matches_the_frozen_pair() -> None:
    selection = runner.select_environment(RAW_CONFIG, resolver=_resolver("set1_group1_vpn"))
    environ = {"CTP_TD_FRONT": "tcp://127.0.0.1:30001", "CTP_MD_FRONT": "tcp://127.0.0.1:30011"}
    # Matching values are inert, never a routing input, and are recorded so the
    # report shows they were not used.
    assert launcher.require_frozen_fronts(environ, selection) == ["CTP_TD_FRONT", "CTP_MD_FRONT"]


def test_launcher_requires_credentials_without_leaking_them() -> None:
    selection = runner.select_environment(RAW_CONFIG, resolver=_resolver("set1_group1_vpn"))
    with pytest.raises(SystemExit) as error:
        launcher.build_exchange_kwargs({"CTP_USER_ID": "iter30-user"}, selection)
    message = str(error.value)
    assert "CTP_PASSWORD" in message
    assert "iter30-password" not in message
