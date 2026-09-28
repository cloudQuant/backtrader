"""Offline tests for preparing the reserved private SimNow config."""

from __future__ import annotations

import hashlib
import io
import json
import os
import stat
from types import SimpleNamespace

import pytest

import backtrader_runtime.ctp_private_config_setup as setup
import backtrader_runtime.cli as cli
from backtrader_runtime.errors import CONFIG_EXISTS, RuntimeConfigError
from backtrader_runtime.inventory import (
    ITERATION41_007_CTP_PRIVATE_RUNTIME_DIR,
    ITERATION41_007_CTP_PRIVATE_RUNTIME_ID,
    ITERATION41_007_CTP_PRIVATE_STRATEGY_ID,
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR,
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID,
    ITERATION41_013_3_STRATEGY_ID,
)

_REAL_SOURCE_SECURITY = setup._source_security


VALUES = {
    "md_front": "tcp://180.168.146.187:10211",
    "td_front": "tcp://180.168.146.187:10201",
    "instrument_id": "SA610",
    "exchange_id": "CZCE",
    "hedge_flag": "1",
    "broker_id": "9999",
    "user_id": "synthetic-user",
    "password": "synthetic-password-never-render",
    "app_id": "simnow_client_test",
    "auth_code": "synthetic-auth-code-never-render",
}


def test_prepared_private_strategy_identity_matches_registered_strategy():
    assert setup.CTP_SIMNOW_PRIVATE_STRATEGY_ID == ITERATION41_013_3_STRATEGY_ID


def test_code_owned_private_config_targets_bind_exact_registered_id_and_strategy():
    assert setup._CTP_PRIVATE_CONFIG_TARGETS == {
        ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID: (
            ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR,
            ITERATION41_013_3_STRATEGY_ID,
        ),
        ITERATION41_007_CTP_PRIVATE_RUNTIME_ID: (
            ITERATION41_007_CTP_PRIVATE_RUNTIME_DIR,
            ITERATION41_007_CTP_PRIVATE_STRATEGY_ID,
        ),
    }
    assert setup.CTP_SIMNOW_PRIVATE_RUNTIME_DIR == ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR
    assert setup.CTP_SIMNOW_PRIVATE_STRATEGY_ID == ITERATION41_013_3_STRATEGY_ID
    assert setup._resolve_private_config_target(None) == (
        ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR,
        ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID,
    )
    assert setup._resolve_private_config_target(ITERATION41_007_CTP_PRIVATE_RUNTIME_ID) == (
        ITERATION41_007_CTP_PRIVATE_RUNTIME_DIR,
        ITERATION41_007_CTP_PRIVATE_RUNTIME_ID,
    )


def test_private_config_target_rejects_arbitrary_path_and_strategy_overrides(tmp_path):
    source = tmp_path / "source.env"
    _write_private_source(source, _env_text())
    target = _target(tmp_path)

    with pytest.raises(TypeError):
        setup.prepare_ctp_simnow_config(source, source_format="env", runtime_dir=target)
    with pytest.raises(TypeError):
        setup.prepare_ctp_simnow_config(
            source,
            source_format="env",
            runtime_dir=ITERATION41_007_CTP_PRIVATE_RUNTIME_DIR,
        )
    with pytest.raises(TypeError):
        setup.prepare_ctp_simnow_config_sources(
            ((source, "env"),),
            runtime_dir=ITERATION41_007_CTP_PRIVATE_RUNTIME_DIR,
        )
    assert not (target / "config.yaml").exists()

    rendered = setup._render_config(VALUES, runtime_id=ITERATION41_007_CTP_PRIVATE_RUNTIME_ID)
    assert '  id: "example.007_ctp.simnow_penetration"' in rendered
    with pytest.raises(TypeError):
        setup._render_config(VALUES, strategy_id="example.unregistered.strategy")


def test_007_private_target_generation_uses_exact_identity_and_never_overwrites(
    tmp_path, monkeypatch
):
    source = tmp_path / "source.env"
    _write_private_source(source, _env_text())
    target = _target(tmp_path)
    targets = dict(setup._CTP_PRIVATE_CONFIG_TARGETS)
    targets[ITERATION41_007_CTP_PRIVATE_RUNTIME_ID] = (
        target,
        ITERATION41_007_CTP_PRIVATE_STRATEGY_ID,
    )
    monkeypatch.setattr(setup, "_CTP_PRIVATE_CONFIG_TARGETS", targets)

    prepared = setup.prepare_ctp_simnow_config(
        source,
        source_format="env",
        runtime_id=ITERATION41_007_CTP_PRIVATE_RUNTIME_ID,
    )
    config_path = target / "config.yaml"
    document = setup._load_strict_yaml(config_path.read_text(encoding="utf-8"))
    assert prepared.path == config_path
    assert document["config_schema_version"] == 4
    assert document["strategy"]["id"] == "example.007_ctp.simnow_penetration"
    assert document["runtime"] == {"mode": "simulation", "preset": "sandbox"}
    assert document["secrets_ref"] == "config_yaml"
    public_text = json.dumps(prepared.as_public_dict(), sort_keys=True)
    for secret in (VALUES["password"], VALUES["auth_code"], VALUES["user_id"]):
        if secret in repr(prepared) or secret in public_text:
            pytest.fail("prepared result exposed a synthetic private source value")

    original_digest = hashlib.sha256(config_path.read_bytes()).digest()
    with pytest.raises(RuntimeConfigError) as rejected:
        setup.prepare_ctp_simnow_config(
            source,
            source_format="env",
            runtime_id=ITERATION41_007_CTP_PRIVATE_RUNTIME_ID,
        )
    assert rejected.value.code == CONFIG_EXISTS
    if hashlib.sha256(config_path.read_bytes()).digest() != original_digest:
        pytest.fail("existing 007 private config changed during the rejected second write")


def test_private_config_target_rejects_unknown_id_and_path_override(tmp_path):
    source = tmp_path / "source.env"
    _write_private_source(source, _env_text())
    target = _target(tmp_path)

    with pytest.raises(RuntimeConfigError) as unknown:
        setup.prepare_ctp_simnow_config(
            source, source_format="env", runtime_id="example.unregistered.private"
        )
    assert unknown.value.reason == "private_target_runtime_id_invalid"
    with pytest.raises(TypeError):
        setup.prepare_ctp_simnow_config(
            source,
            source_format="env",
            runtime_id=ITERATION41_007_CTP_PRIVATE_RUNTIME_ID,
            runtime_dir=target,
        )
    assert not (target / "config.yaml").exists()


def _env_text(values=VALUES):
    key_map = {
        "md_front": "CTP_MD_FRONT",
        "td_front": "CTP_TD_FRONT",
        "instrument_id": "CTP_INSTRUMENT_ID",
        "exchange_id": "CTP_EXCHANGE_ID",
        "hedge_flag": "CTP_HEDGE_FLAG",
        "broker_id": "CTP_BROKER_ID",
        "user_id": "CTP_USER_ID",
        "password": "CTP_PASSWORD",
        "app_id": "CTP_APP_ID",
        "auth_code": "CTP_AUTH_CODE",
    }
    return (
        "\n".join("{0}={1}".format(key_map[name], value) for name, value in values.items()) + "\n"
    )


def _yaml_text(values):
    block = "\n".join(
        "  {0}: {1}".format(name, json.dumps(value)) for name, value in values.items()
    )
    return "ctp_simnow:\n" + block + "\n"


def _collector_yaml_text(values):
    collector_fields = (
        "md_front",
        "td_front",
        "broker_id",
        "user_id",
        "password",
        "app_id",
        "auth_code",
    )
    block = "\n".join(
        "  {0}: {1}".format(name, json.dumps(values[name])) for name in collector_fields
    )
    return "ctp:\n  env: ignored_label\n  login_timeout_sec: 10\n" + block + "\n"


def _write_private_source(path, text):
    path.write_text(text, encoding="utf-8")
    if os.name == "posix":
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)


@pytest.fixture(autouse=True)
def _source_acl_is_test_input(monkeypatch):
    # Source ACL behavior has platform-specific coverage in credential resolver
    # tests; these cases focus on mapping and on the helper's target ACL writer.
    if os.name == "nt":
        monkeypatch.setattr(setup, "_source_security", lambda *_args: None)


def _target(tmp_path):
    result = tmp_path / "runtime-ctp-private"
    result.mkdir()
    return result


def _prepare_private_config_for_test(source, *, source_format, runtime_dir):
    return setup._prepare_ctp_simnow_config_for_test(
        source, source_format=source_format, runtime_dir=runtime_dir
    )


def _prepare_private_config_sources_for_test(sources, *, runtime_dir):
    return setup._prepare_ctp_simnow_config_sources_for_test(sources, runtime_dir=runtime_dir)


def test_explicit_env_source_creates_redacted_protected_v4_config(tmp_path):
    source = tmp_path / "source.env"
    _write_private_source(source, _env_text())
    target = _target(tmp_path)

    prepared = _prepare_private_config_for_test(source, source_format="env", runtime_dir=target)

    config_path = target / "config.yaml"
    assert prepared.path == config_path
    assert prepared.as_public_dict()["runtime_registered"] is True
    assert prepared.as_public_dict()["provider_io"] is False
    assert prepared.as_public_dict()["external_writes"] is False
    assert prepared.as_public_dict()["execution_authorized"] is False
    assert prepared.as_public_dict()["admission"] == "not_granted"
    content = config_path.read_text(encoding="utf-8")
    assert "mode: simulation" in content
    assert "preset: sandbox" in content
    assert "\nctp:\n" in content
    assert "\nctp_simnow:\n" not in content
    document = setup._load_strict_yaml(content)
    assert document["strategy"]["id"] == ITERATION41_013_3_STRATEGY_ID
    assert 'md_front: "tcp://180.168.146.187:10211"' in content
    assert 'td_front: "tcp://180.168.146.187:10201"' in content
    assert VALUES["password"] in content
    assert VALUES["auth_code"] in content
    assert VALUES["password"] not in repr(prepared)
    assert VALUES["auth_code"] not in json.dumps(prepared.as_public_dict())
    if os.name == "posix":
        assert stat.S_IMODE(target.stat().st_mode) == 0o700
        assert stat.S_IMODE(config_path.stat().st_mode) == 0o600


def test_env_explicit_legacy_sets_make_ordered_deduplicated_front_pairs(tmp_path):
    source = tmp_path / "multi-fronts.env"
    text = _env_text()
    text += "CTP_SET1_MD_FRONT_1={0}\n".format(VALUES["md_front"])
    text += "CTP_SET1_TD_FRONT_1={0}\n".format(VALUES["td_front"])
    text += "CTP_SET1_MD_FRONT_2=tcp://md-secondary.example:10211\n"
    text += "CTP_SET1_TD_FRONT_2=tcp://td-secondary.example:10201\n"
    text += "CTP_SET1_MD_FRONT_3=tcp://md-tertiary.example:10211\n"
    text += "CTP_SET1_TD_FRONT_3=tcp://td-tertiary.example:10201\n"
    text += "CTP_SET2_MD_FRONT=tcp://md-247.example:10211\n"
    text += "CTP_SET2_TD_FRONT=tcp://td-247.example:10201\n"
    _write_private_source(source, text)
    target = _target(tmp_path)

    prepared = _prepare_private_config_for_test(source, source_format="env", runtime_dir=target)

    document = setup._load_strict_yaml(prepared.path.read_text(encoding="utf-8"))
    assert document["ctp"]["front_pairs"] == [
        {"md_front": VALUES["md_front"], "td_front": VALUES["td_front"]},
        {
            "md_front": "tcp://md-secondary.example:10211",
            "td_front": "tcp://td-secondary.example:10201",
        },
        {
            "md_front": "tcp://md-tertiary.example:10211",
            "td_front": "tcp://td-tertiary.example:10201",
        },
        {"md_front": "tcp://md-247.example:10211", "td_front": "tcp://td-247.example:10201"},
    ]
    assert "md_front" not in document["ctp"]
    assert "td_front" not in document["ctp"]


@pytest.mark.parametrize(
    "front_lines",
    (
        ("CTP_SET1_MD_FRONT_1=tcp://md.example:10211",),
        ("CTP_SET2_TD_FRONT=tcp://td.example:10201",),
    ),
)
def test_env_incomplete_explicit_set_pair_fails_without_writing(tmp_path, front_lines):
    source = tmp_path / "incomplete-set.env"
    _write_private_source(source, _env_text() + "\n".join(front_lines) + "\n")
    target = _target(tmp_path)

    with pytest.raises(RuntimeConfigError) as rejected:
        _prepare_private_config_for_test(source, source_format="env", runtime_dir=target)

    assert rejected.value.reason == "source_front_pair_incomplete"
    assert not (target / "config.yaml").exists()


def test_env_conflicting_values_for_same_explicit_set_endpoint_fail_closed():
    text = (
        _env_text()
        + "CTP_SET1_MD_FRONT_1=tcp://md-first.example:10211\n"
        + "CTP_SET1_MD_FRONT_1=tcp://md-conflict.example:10211\n"
        + "CTP_SET1_TD_FRONT_1=tcp://td-first.example:10201\n"
    )

    with pytest.raises(RuntimeConfigError) as rejected:
        setup._parse_env_source(text)

    assert rejected.value.reason == "source_duplicate_field"
    assert rejected.value.field_path == "ctp_simnow.front_pairs"


def test_missing_fields_are_actionable_and_leave_config_absent(tmp_path):
    source = tmp_path / "partial.env"
    partial = {
        "md_front": VALUES["md_front"],
        "td_front": VALUES["td_front"],
        "broker_id": VALUES["broker_id"],
        "user_id": VALUES["user_id"],
        "password": VALUES["password"],
        "app_id": VALUES["app_id"],
        "auth_code": VALUES["auth_code"],
    }
    _write_private_source(source, _env_text(partial))
    target = _target(tmp_path)
    if os.name == "posix":
        target.chmod(0o750)

    with pytest.raises(RuntimeConfigError) as rejected:
        _prepare_private_config_for_test(source, source_format="env", runtime_dir=target)

    assert rejected.value.reason == "ctp_private_source_incomplete"
    assert "ctp_simnow.instrument_id" in rejected.value.message
    assert "ctp_simnow.exchange_id" in rejected.value.message
    assert "ctp_simnow.hedge_flag" in rejected.value.message
    assert VALUES["password"] not in str(rejected.value)
    assert not (target / "config.yaml").exists()
    # Incomplete input is rejected before changing the reserved folder ACL.
    if os.name == "posix":
        assert stat.S_IMODE(target.stat().st_mode) == 0o750


def test_profile_does_not_select_or_infer_fronts(tmp_path):
    source = tmp_path / "profile-only.env"
    _write_private_source(source, "ITER22_SIMNOW_PROFILE=simnow_second_7x24\n")
    target = _target(tmp_path)

    with pytest.raises(RuntimeConfigError) as rejected:
        _prepare_private_config_for_test(source, source_format="env", runtime_dir=target)

    assert rejected.value.reason == "ctp_private_source_incomplete"
    assert "ctp_simnow.md_front" in rejected.value.message
    assert "ctp_simnow.td_front" in rejected.value.message
    assert not (target / "config.yaml").exists()


def test_yaml_source_copies_only_explicit_ctp_block_and_ignores_runtime_mode(tmp_path):
    source = tmp_path / "source.yaml"
    _write_private_source(
        source,
        "runtime:\n  mode: live\n  preset: managed_live_direct\n" + _yaml_text(VALUES),
    )
    target = _target(tmp_path)

    _prepare_private_config_for_test(source, source_format="yaml", runtime_dir=target)

    output = (target / "config.yaml").read_text(encoding="utf-8")
    assert "mode: simulation" in output
    assert "preset: sandbox" in output
    assert "mode: live" not in output
    assert "managed_live_direct" not in output
    assert "\nctp:\n" in output
    assert "\nctp_simnow:\n" not in output


def test_canonical_ctp_yaml_source_is_accepted_and_renders_the_same_common_block(tmp_path):
    source = tmp_path / "canonical-source.yaml"
    canonical_source = _yaml_text(VALUES).replace("ctp_simnow:", "ctp:", 1)
    _write_private_source(source, canonical_source)
    target = _target(tmp_path)

    _prepare_private_config_for_test(source, source_format="yaml", runtime_dir=target)

    document = setup._load_strict_yaml((target / "config.yaml").read_text(encoding="utf-8"))
    assert document["ctp"] == VALUES
    assert "ctp_simnow" not in document


@pytest.mark.parametrize("pair_count", (1, 2, 8))
def test_yaml_front_pairs_are_preserved_without_candidate_selection(tmp_path, pair_count):
    source = tmp_path / "front-pairs.yaml"
    values = {name: value for name, value in VALUES.items() if name not in ("md_front", "td_front")}
    pairs = [
        {
            "md_front": "tcp://md-{0}.example:10211".format(index),
            "td_front": "tcp://td-{0}.example:10201".format(index),
        }
        for index in range(pair_count)
    ]
    values["front_pairs"] = pairs
    _write_private_source(source, _yaml_text(values))
    target = _target(tmp_path)

    prepared = _prepare_private_config_for_test(source, source_format="yaml", runtime_dir=target)

    config_text = prepared.path.read_text(encoding="utf-8")
    config_document = setup._load_strict_yaml(config_text)
    assert config_document["ctp"]["front_pairs"] == pairs
    assert "md_front:" not in config_document["ctp"]
    assert "td_front:" not in config_document["ctp"]
    assert all(pair["md_front"] in config_text for pair in pairs)
    assert all(pair["td_front"] in config_text for pair in pairs)
    assert prepared.as_public_dict()["provider_io"] is False
    assert prepared.as_public_dict()["execution_authorized"] is False


@pytest.mark.parametrize(
    "pairs",
    (
        [],
        [
            {
                "md_front": "tcp://md-{0}.example:10211".format(index),
                "td_front": "tcp://td-{0}.example:10201".format(index),
            }
            for index in range(9)
        ],
        [{}],
        [{"md_front": "tcp://md.example:10211"}],
        [{"md_front": "tcp://md.example:10211", "td_front": 42}],
    ),
)
def test_yaml_front_pairs_with_invalid_shape_fail_without_writing(tmp_path, pairs):
    source = tmp_path / "invalid-front-pairs.yaml"
    values = {name: value for name, value in VALUES.items() if name not in ("md_front", "td_front")}
    values["front_pairs"] = pairs
    _write_private_source(source, _yaml_text(values))
    target = _target(tmp_path)

    with pytest.raises(RuntimeConfigError) as rejected:
        _prepare_private_config_for_test(source, source_format="yaml", runtime_dir=target)

    assert rejected.value.reason == "source_yaml_schema_invalid"
    assert "front_pairs" in rejected.value.message
    assert not (target / "config.yaml").exists()


def test_yaml_front_pairs_reject_mixed_legacy_front_form(tmp_path):
    values = dict(VALUES)
    values["front_pairs"] = [{"md_front": VALUES["md_front"], "td_front": VALUES["td_front"]}]

    with pytest.raises(RuntimeConfigError) as rejected:
        setup._parse_yaml_source(_yaml_text(values))

    assert rejected.value.reason == "source_front_form_conflict"
    assert "front_pairs" in rejected.value.message


def test_env_pair_must_match_yaml_candidate_and_full_list_is_preserved(tmp_path):
    env_source = tmp_path / "credentials.env"
    yaml_source = tmp_path / "front-pairs.yaml"
    yaml_values = {
        name: value for name, value in VALUES.items() if name not in ("md_front", "td_front")
    }
    pairs = [
        {"md_front": "tcp://md-first.example:10211", "td_front": "tcp://td-first.example:10201"},
        {"md_front": VALUES["md_front"], "td_front": VALUES["td_front"]},
        {"md_front": "tcp://md-third.example:10211", "td_front": "tcp://td-third.example:10201"},
    ]
    yaml_values["front_pairs"] = pairs
    _write_private_source(env_source, _env_text())
    _write_private_source(yaml_source, _yaml_text(yaml_values))
    target = _target(tmp_path)

    prepared = _prepare_private_config_sources_for_test(
        ((env_source, "env"), (yaml_source, "yaml")),
        runtime_dir=target,
    )

    config_document = setup._load_strict_yaml(prepared.path.read_text(encoding="utf-8"))
    assert config_document["ctp"]["front_pairs"] == pairs
    assert "md_front" not in config_document["ctp"]
    assert "td_front" not in config_document["ctp"]


def test_env_pair_not_in_yaml_front_pairs_fails_without_writing(tmp_path):
    env_source = tmp_path / "credentials.env"
    yaml_source = tmp_path / "front-pairs.yaml"
    yaml_values = {
        name: value for name, value in VALUES.items() if name not in ("md_front", "td_front")
    }
    yaml_values["front_pairs"] = [
        {"md_front": "tcp://other-md.example:10211", "td_front": "tcp://other-td.example:10201"}
    ]
    _write_private_source(env_source, _env_text())
    _write_private_source(yaml_source, _yaml_text(yaml_values))
    target = _target(tmp_path)

    with pytest.raises(RuntimeConfigError) as rejected:
        _prepare_private_config_sources_for_test(
            ((env_source, "env"), (yaml_source, "yaml")),
            runtime_dir=target,
        )

    assert rejected.value.reason == "source_front_pair_not_in_candidates"
    assert not (target / "config.yaml").exists()


def test_env_front_pair_does_not_relax_other_source_conflicts(tmp_path):
    env_source = tmp_path / "credentials.env"
    yaml_source = tmp_path / "front-pairs.yaml"
    yaml_values = {
        name: value for name, value in VALUES.items() if name not in ("md_front", "td_front")
    }
    yaml_values["password"] = "different-password-must-not-be-printed"
    yaml_values["front_pairs"] = [{"md_front": VALUES["md_front"], "td_front": VALUES["td_front"]}]
    _write_private_source(env_source, _env_text())
    _write_private_source(yaml_source, _yaml_text(yaml_values))
    target = _target(tmp_path)

    with pytest.raises(RuntimeConfigError) as rejected:
        _prepare_private_config_sources_for_test(
            ((env_source, "env"), (yaml_source, "yaml")),
            runtime_dir=target,
        )

    assert rejected.value.reason == "source_field_conflict"
    assert "password" in rejected.value.message
    assert VALUES["password"] not in str(rejected.value)
    assert yaml_values["password"] not in str(rejected.value)
    assert not (target / "config.yaml").exists()


def test_only_env_may_supply_pair_for_yaml_front_pairs(tmp_path):
    collector_source = tmp_path / "collector.yaml"
    scope_source = tmp_path / "scope.yaml"
    scope_values = {
        name: value
        for name, value in VALUES.items()
        if name
        not in ("md_front", "td_front", "broker_id", "user_id", "password", "app_id", "auth_code")
    }
    scope_values["front_pairs"] = [{"md_front": VALUES["md_front"], "td_front": VALUES["td_front"]}]
    _write_private_source(collector_source, _collector_yaml_text(VALUES))
    _write_private_source(scope_source, _yaml_text(scope_values))
    target = _target(tmp_path)

    with pytest.raises(RuntimeConfigError) as rejected:
        _prepare_private_config_sources_for_test(
            ((collector_source, "collector_yaml"), (scope_source, "yaml")),
            runtime_dir=target,
        )

    assert rejected.value.reason == "source_front_form_conflict"
    assert not (target / "config.yaml").exists()


def test_partial_env_pair_cannot_be_mixed_with_yaml_front_pairs(tmp_path):
    env_source = tmp_path / "partial.env"
    yaml_source = tmp_path / "front-pairs.yaml"
    env_values = {
        name: VALUES[name]
        for name in ("md_front", "broker_id", "user_id", "password", "app_id", "auth_code")
    }
    yaml_values = {
        name: value
        for name, value in VALUES.items()
        if name
        not in ("md_front", "td_front", "broker_id", "user_id", "password", "app_id", "auth_code")
    }
    yaml_values["front_pairs"] = [{"md_front": VALUES["md_front"], "td_front": VALUES["td_front"]}]
    _write_private_source(env_source, _env_text(env_values))
    _write_private_source(yaml_source, _yaml_text(yaml_values))
    target = _target(tmp_path)

    with pytest.raises(RuntimeConfigError) as rejected:
        _prepare_private_config_sources_for_test(
            ((env_source, "env"), (yaml_source, "yaml")),
            runtime_dir=target,
        )

    assert rejected.value.reason == "source_front_form_conflict"
    assert not (target / "config.yaml").exists()


def test_explicit_env_and_yaml_sources_merge_disjoint_fields(tmp_path):
    env_values = {
        "broker_id": VALUES["broker_id"],
        "user_id": VALUES["user_id"],
        "password": VALUES["password"],
        "app_id": VALUES["app_id"],
        "auth_code": VALUES["auth_code"],
    }
    yaml_values = {name: value for name, value in VALUES.items() if name not in env_values}
    yaml_values["broker_id"] = VALUES["broker_id"]
    env_source = tmp_path / "credentials.env"
    yaml_source = tmp_path / "connection.yaml"
    _write_private_source(env_source, _env_text(env_values))
    _write_private_source(yaml_source, _yaml_text(yaml_values))
    target = _target(tmp_path)

    prepared = _prepare_private_config_sources_for_test(
        ((env_source, "env"), (yaml_source, "yaml")),
        runtime_dir=target,
    )

    content = prepared.path.read_text(encoding="utf-8")
    for name, value in VALUES.items():
        assert "{0}: {1}".format(name, json.dumps(value)) in content
    assert prepared.as_public_dict()["provider_io"] is False


def test_explicit_collector_yaml_and_scope_yaml_create_config_without_using_env_label(tmp_path):
    collector_source = tmp_path / "collector.yaml"
    scope_source = tmp_path / "scope.yaml"
    _write_private_source(collector_source, _collector_yaml_text(VALUES))
    _write_private_source(
        scope_source,
        _yaml_text({name: VALUES[name] for name in ("instrument_id", "exchange_id", "hedge_flag")}),
    )
    target = _target(tmp_path)

    prepared = _prepare_private_config_sources_for_test(
        ((collector_source, "collector_yaml"), (scope_source, "yaml")),
        runtime_dir=target,
    )

    content = prepared.path.read_text(encoding="utf-8")
    for name, value in VALUES.items():
        assert "{0}: {1}".format(name, json.dumps(value)) in content
    assert "ignored_label" not in content
    assert "login_timeout_sec" not in content


def test_collector_yaml_without_explicit_contract_scope_leaves_config_absent(tmp_path):
    source = tmp_path / "collector.yaml"
    _write_private_source(source, _collector_yaml_text(VALUES))
    target = _target(tmp_path)

    with pytest.raises(RuntimeConfigError) as rejected:
        _prepare_private_config_for_test(source, source_format="collector_yaml", runtime_dir=target)

    assert rejected.value.reason == "ctp_private_source_incomplete"
    for field in ("instrument_id", "exchange_id", "hedge_flag"):
        assert "ctp_simnow.{0}".format(field) in rejected.value.message
    assert not (target / "config.yaml").exists()


def test_explicit_sources_with_conflicting_values_fail_closed_and_redact(tmp_path):
    env_source = tmp_path / "first.env"
    yaml_source = tmp_path / "second.yaml"
    conflicting = dict(VALUES)
    conflicting["password"] = "different-password-must-not-be-printed"
    _write_private_source(env_source, _env_text())
    _write_private_source(yaml_source, _yaml_text(conflicting))
    target = _target(tmp_path)

    with pytest.raises(RuntimeConfigError) as rejected:
        _prepare_private_config_sources_for_test(
            ((env_source, "env"), (yaml_source, "yaml")),
            runtime_dir=target,
        )

    assert rejected.value.reason == "source_field_conflict"
    assert "ctp_simnow.password" in rejected.value.message
    assert VALUES["password"] not in str(rejected.value)
    assert conflicting["password"] not in str(rejected.value)
    assert not (target / "config.yaml").exists()


def test_all_source_acls_are_checked_before_any_source_bytes_are_read(tmp_path, monkeypatch):
    env_source = tmp_path / "first.env"
    yaml_source = tmp_path / "unsafe.yaml"
    _write_private_source(env_source, _env_text())
    _write_private_source(yaml_source, _yaml_text(VALUES))
    unsafe_identity = yaml_source.stat()
    read_sources = []
    original_read = setup._read_opened_private_source

    def checked_source_security(descriptor, file_stat):
        if (file_stat.st_dev, file_stat.st_ino) == (
            unsafe_identity.st_dev,
            unsafe_identity.st_ino,
        ):
            raise setup._error("private_source_acl_unsafe", "source ACL is unsafe")

    def track_read(source, descriptor, opened):
        read_sources.append(source)
        return original_read(source, descriptor, opened)

    monkeypatch.setattr(setup, "_source_security", checked_source_security)
    monkeypatch.setattr(setup, "_read_opened_private_source", track_read)
    target = _target(tmp_path)

    with pytest.raises(RuntimeConfigError) as rejected:
        _prepare_private_config_sources_for_test(
            ((env_source, "env"), (yaml_source, "yaml")),
            runtime_dir=target,
        )

    assert rejected.value.reason == "private_source_acl_unsafe"
    assert read_sources == []
    assert not (target / "config.yaml").exists()


def test_yaml_with_multiple_endpoint_selection_fields_is_rejected(tmp_path):
    source = tmp_path / "ambiguous.yaml"
    values = dict(VALUES)
    values["md_front_set2"] = "tcp://another.example:10211"
    _write_private_source(source, _yaml_text(values))
    target = _target(tmp_path)

    with pytest.raises(RuntimeConfigError) as rejected:
        _prepare_private_config_for_test(source, source_format="yaml", runtime_dir=target)

    assert rejected.value.reason == "source_yaml_schema_invalid"
    assert "md_front_set2" in rejected.value.message
    assert not (target / "config.yaml").exists()


def test_duplicate_env_aliases_reject_without_writing(tmp_path):
    source = tmp_path / "duplicate.env"
    text = _env_text() + "CTP_INVESTOR_ID=other-user\n"
    _write_private_source(source, text)
    target = _target(tmp_path)

    with pytest.raises(RuntimeConfigError) as rejected:
        _prepare_private_config_for_test(source, source_format="env", runtime_dir=target)

    assert rejected.value.reason == "source_duplicate_field"
    assert "user_id" in rejected.value.message
    assert VALUES["password"] not in str(rejected.value)
    assert not (target / "config.yaml").exists()


def test_project_root_env_instrument_aliases_are_accepted_without_profile_selection(tmp_path):
    source = tmp_path / ".env"
    text = (
        _env_text()
        .replace("CTP_INSTRUMENT_ID", "CTP_INSTRUMENT")
        .replace("CTP_EXCHANGE_ID", "CTP_EXCHANGE")
        + "SIMNOW_PROFILE=simnow_second_7x24\n"
        + "CTP_MD_FRONT_SIMNOW_SET2=tcp://unselected.example:10211\n"
    )
    _write_private_source(source, text)
    target = _target(tmp_path)

    _prepare_private_config_for_test(source, source_format="env", runtime_dir=target)

    config_text = (target / "config.yaml").read_text(encoding="utf-8")
    assert 'instrument_id: "SA610"' in config_text
    assert 'exchange_id: "CZCE"' in config_text
    assert 'md_front: "{0}"'.format(VALUES["md_front"]) in config_text
    assert "unselected.example" not in config_text
    assert "simnow_second_7x24" not in config_text


def test_duplicate_env_aliases_are_accepted_only_after_exact_value_normalization():
    parsed = setup._parse_env_source(
        _env_text() + 'CTP_INSTRUMENT = "SA610"\n' + "CTP_EXCHANGE='CZCE'\n"
    )

    assert parsed["instrument_id"] == VALUES["instrument_id"]
    assert parsed["exchange_id"] == VALUES["exchange_id"]


def test_conflicting_env_instrument_aliases_fail_closed():
    text = _env_text() + "CTP_INSTRUMENT=SA611\n"

    with pytest.raises(RuntimeConfigError) as rejected:
        setup._parse_env_source(text)

    assert rejected.value.reason == "source_duplicate_field"
    assert "ctp_simnow.instrument_id" in rejected.value.message


def test_placeholder_values_are_rejected_without_writing(tmp_path):
    source = tmp_path / "placeholder.env"
    values = dict(VALUES)
    values["password"] = "<enter-locally>"
    _write_private_source(source, _env_text(values))
    target = _target(tmp_path)

    with pytest.raises(RuntimeConfigError) as rejected:
        _prepare_private_config_for_test(source, source_format="env", runtime_dir=target)

    assert rejected.value.reason == "source_placeholder_value"
    assert not (target / "config.yaml").exists()


def test_non_utf8_scalar_from_yaml_is_redacted_and_leaves_config_absent(tmp_path):
    source = tmp_path / "surrogate.yaml"
    values = dict(VALUES)
    block = "\n".join(
        "  {0}: {1}".format(name, '"\\uD800"' if name == "password" else json.dumps(value))
        for name, value in values.items()
    )
    _write_private_source(source, "ctp_simnow:\n" + block + "\n")
    target = _target(tmp_path)

    with pytest.raises(RuntimeConfigError) as rejected:
        _prepare_private_config_for_test(source, source_format="yaml", runtime_dir=target)

    assert rejected.value.reason == "source_value_invalid"
    assert "password" in rejected.value.message
    assert "\\ud800" not in str(rejected.value).lower()
    assert not (target / "config.yaml").exists()


def test_existing_config_is_never_overwritten_or_source_read(tmp_path):
    source = tmp_path / "does-not-exist.env"
    target = _target(tmp_path)
    config_path = target / "config.yaml"
    config_path.write_text("preserve-existing-bytes\n", encoding="utf-8")
    original = config_path.read_bytes()

    with pytest.raises(RuntimeConfigError) as rejected:
        _prepare_private_config_for_test(source, source_format="env", runtime_dir=target)

    assert rejected.value.code == CONFIG_EXISTS
    assert config_path.read_bytes() == original


def test_windows_handle_conversion_cleanup_uses_assigned_crt_fd(tmp_path, monkeypatch):
    path = tmp_path / "opened-file"
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    marked = []

    def mark_for_delete(fd):
        marked.append(fd)

    class Kernel:
        def CloseHandle(self, *_args):
            raise AssertionError("CRT descriptor already owns the native handle")

    monkeypatch.setattr(setup, "_mark_windows_file_for_deletion", mark_for_delete)
    failed = setup._cleanup_windows_handle_conversion(
        SimpleNamespace(value=123), descriptor, Kernel()
    )

    assert not failed
    assert marked == [descriptor]
    with pytest.raises(OSError):
        os.fstat(descriptor)


@pytest.mark.skipif(os.name != "nt", reason="Windows directory-handle path binding")
def test_windows_directory_identity_mismatch_removes_created_file_by_handle(tmp_path, monkeypatch):
    from types import SimpleNamespace

    source = tmp_path / "source.env"
    _write_private_source(source, _env_text())
    target = _target(tmp_path)
    replacement = tmp_path / "replacement"
    replacement.mkdir()
    decoy = replacement / "config.yaml"
    decoy.write_text("replacement entry", encoding="utf-8")
    original_lstat = os.lstat
    target_stat_calls = 0

    def lstat_with_replaced_directory(path, *args, **kwargs):
        nonlocal target_stat_calls
        if os.fspath(path) == os.fspath(target):
            target_stat_calls += 1
            result = original_lstat(path, *args, **kwargs)
            if target_stat_calls == 3:
                return SimpleNamespace(st_mode=result.st_mode, st_file_attributes=0x400)
            return result
        return original_lstat(path, *args, **kwargs)

    monkeypatch.setattr(setup.os, "lstat", lstat_with_replaced_directory)

    with pytest.raises(RuntimeConfigError) as rejected:
        _prepare_private_config_for_test(source, source_format="env", runtime_dir=target)

    assert rejected.value.reason == "private_target_identity_changed"
    assert not (target / "config.yaml").exists()
    assert decoy.read_text(encoding="utf-8") == "replacement entry"


@pytest.mark.skipif(os.name != "nt", reason="Windows ancestor reparse-point rejection")
def test_windows_ancestor_reparse_point_is_rejected_before_target_acl_change(tmp_path, monkeypatch):
    from types import SimpleNamespace

    source = tmp_path / "source.env"
    _write_private_source(source, _env_text())
    target = _target(tmp_path)
    ancestor = target.parent
    original_lstat = os.lstat

    def lstat_with_reparse_ancestor(path, *args, **kwargs):
        result = original_lstat(path, *args, **kwargs)
        if os.fspath(path) == os.fspath(ancestor):
            return SimpleNamespace(st_mode=result.st_mode, st_file_attributes=0x400)
        return result

    monkeypatch.setattr(setup.os, "lstat", lstat_with_reparse_ancestor)
    monkeypatch.setattr(
        setup,
        "_protect_target_directory",
        lambda *_args: (_ for _ in ()).throw(AssertionError("target ACL changed")),
    )

    with pytest.raises(RuntimeConfigError) as rejected:
        _prepare_private_config_for_test(source, source_format="env", runtime_dir=target)

    assert rejected.value.reason == "private_target_directory_invalid"
    assert not (target / "config.yaml").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX ancestor symlink rejection")
def test_posix_ancestor_symlink_is_rejected_before_target_acl_change(tmp_path, monkeypatch):
    source = tmp_path / "source.env"
    _write_private_source(source, _env_text())
    real_parent = tmp_path / "real-parent"
    target = real_parent / "private"
    target.mkdir(parents=True)
    alias = tmp_path / "parent-alias"
    alias.symlink_to(real_parent, target_is_directory=True)
    redirected_target = alias / "private"
    monkeypatch.setattr(
        setup,
        "_protect_target_directory",
        lambda *_args: (_ for _ in ()).throw(AssertionError("target ACL changed")),
    )

    with pytest.raises(RuntimeConfigError) as rejected:
        _prepare_private_config_for_test(source, source_format="env", runtime_dir=redirected_target)

    assert rejected.value.reason == "private_target_directory_invalid"
    assert not (target / "config.yaml").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX post-create failure cleanup")
def test_posix_post_create_directory_sync_failure_removes_created_config(tmp_path, monkeypatch):
    source = tmp_path / "source.env"
    _write_private_source(source, _env_text())
    target = _target(tmp_path)
    original_fsync = os.fsync

    def fail_directory_sync(descriptor):
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("injected directory sync failure")
        return original_fsync(descriptor)

    monkeypatch.setattr(setup.os, "fsync", fail_directory_sync)
    with pytest.raises(OSError, match="injected directory sync failure"):
        _prepare_private_config_for_test(source, source_format="env", runtime_dir=target)

    assert not (target / "config.yaml").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX identity-bound cleanup")
def test_posix_post_create_cleanup_preserves_replacement_entry(tmp_path, monkeypatch):
    source = tmp_path / "source.env"
    _write_private_source(source, _env_text())
    target = _target(tmp_path)
    decoy = target / "decoy"
    decoy.write_text("preserve this replacement", encoding="utf-8")
    original_fsync = os.fsync

    def replace_then_fail_directory_sync(descriptor):
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            os.replace(decoy, target / "config.yaml")
            raise OSError("injected directory sync failure")
        return original_fsync(descriptor)

    monkeypatch.setattr(setup.os, "fsync", replace_then_fail_directory_sync)
    with pytest.raises(RuntimeConfigError) as rejected:
        _prepare_private_config_for_test(source, source_format="env", runtime_dir=target)

    assert rejected.value.reason == "private_config_cleanup_failed"
    assert (target / "config.yaml").read_text(encoding="utf-8") == "preserve this replacement"


@pytest.mark.skipif(os.name != "nt", reason="Windows file descriptor cleanup")
@pytest.mark.parametrize("failure_point", ("fstat", "fdopen"))
def test_windows_prewrite_failures_close_descriptor_and_remove_empty_config(
    tmp_path, monkeypatch, failure_point
):
    source = tmp_path / "source.env"
    _write_private_source(source, _env_text())
    target = _target(tmp_path)
    created_fds = []
    original_create = setup._create_windows_private_file_descriptor
    original_fstat = os.fstat
    original_fdopen = os.fdopen

    def create_and_track(directory_fd):
        output_fd = original_create(directory_fd)
        created_fds.append(output_fd)
        return output_fd

    monkeypatch.setattr(setup, "_create_windows_private_file_descriptor", create_and_track)
    if failure_point == "fstat":

        def failing_fstat(descriptor):
            if created_fds and descriptor == created_fds[0]:
                raise OSError("injected metadata failure")
            return original_fstat(descriptor)

        monkeypatch.setattr(setup.os, "fstat", failing_fstat)
    else:

        def failing_fdopen(descriptor, *args, **kwargs):
            if created_fds and descriptor == created_fds[0]:
                raise OSError("injected stream setup failure")
            return original_fdopen(descriptor, *args, **kwargs)

        monkeypatch.setattr(setup.os, "fdopen", failing_fdopen)

    with pytest.raises(RuntimeConfigError) as rejected:
        _prepare_private_config_for_test(source, source_format="env", runtime_dir=target)

    assert rejected.value.reason == "private_config_write_failed"
    assert created_fds
    with pytest.raises(OSError):
        original_fstat(created_fds[0])
    assert not (target / "config.yaml").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows fail-closed cleanup error reporting")
def test_windows_delete_failure_is_reported_without_secret_echo(tmp_path, monkeypatch):
    source = tmp_path / "source.env"
    _write_private_source(source, _env_text())
    target = _target(tmp_path)
    created_fds = []
    original_create = setup._create_windows_private_file_descriptor
    original_fsync = os.fsync

    def create_and_track(directory_fd):
        output_fd = original_create(directory_fd)
        created_fds.append(output_fd)
        return output_fd

    def fail_output_sync(descriptor):
        if created_fds and descriptor == created_fds[0]:
            raise OSError("injected write verification failure")
        return original_fsync(descriptor)

    def fail_delete(_descriptor):
        raise OSError("injected deletion failure")

    monkeypatch.setattr(setup, "_create_windows_private_file_descriptor", create_and_track)
    monkeypatch.setattr(setup.os, "fsync", fail_output_sync)
    monkeypatch.setattr(setup, "_mark_windows_file_for_deletion", fail_delete)

    try:
        with pytest.raises(RuntimeConfigError) as rejected:
            _prepare_private_config_for_test(source, source_format="env", runtime_dir=target)

        assert rejected.value.reason == "private_config_cleanup_failed"
        assert VALUES["password"] not in str(rejected.value)
        assert created_fds
        with pytest.raises(OSError):
            os.fstat(created_fds[0])
        assert (target / "config.yaml").exists()
    finally:
        (target / "config.yaml").unlink(missing_ok=True)


@pytest.mark.skipif(os.name != "nt", reason="Windows interruption cleanup")
def test_windows_interrupt_during_write_cleans_file_and_preserves_interrupt(tmp_path, monkeypatch):
    source = tmp_path / "source.env"
    _write_private_source(source, _env_text())
    target = _target(tmp_path)
    created_fds = []
    original_create = setup._create_windows_private_file_descriptor
    original_fsync = os.fsync
    original_fstat = os.fstat

    def create_and_track(directory_fd):
        output_fd = original_create(directory_fd)
        created_fds.append(output_fd)
        return output_fd

    def interrupt_output_sync(descriptor):
        if created_fds and descriptor == created_fds[0]:
            raise KeyboardInterrupt()
        return original_fsync(descriptor)

    monkeypatch.setattr(setup, "_create_windows_private_file_descriptor", create_and_track)
    monkeypatch.setattr(setup.os, "fsync", interrupt_output_sync)

    with pytest.raises(KeyboardInterrupt):
        _prepare_private_config_for_test(source, source_format="env", runtime_dir=target)

    assert created_fds
    with pytest.raises(OSError):
        original_fstat(created_fds[0])
    assert not (target / "config.yaml").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL cleanup failure")
def test_windows_acl_cleanup_failure_closes_descriptor_and_reports_failure(tmp_path, monkeypatch):
    import msvcrt

    import backtrader_runtime.credential_resolver as credential_resolver

    source = tmp_path / "source.env"
    _write_private_source(source, _env_text())
    target = _target(tmp_path)
    created_fds = []
    directory_handles = set()
    original_open_osfhandle = msvcrt.open_osfhandle
    original_acl_check = credential_resolver._windows_acl_for_handle
    original_set_owner_acl = setup._set_windows_owner_acl

    def open_and_track(handle, flags):
        descriptor = original_open_osfhandle(handle, flags)
        created_fds.append((descriptor, int(handle)))
        return descriptor

    def track_directory_acl(descriptor, *, directory):
        if directory:
            directory_handles.add(msvcrt.get_osfhandle(descriptor))
        return original_set_owner_acl(descriptor, directory=directory)

    def fail_file_acl(handle):
        if created_fds and handle not in directory_handles:
            raise OSError("injected file ACL failure")
        return original_acl_check(handle)

    def fail_delete(_descriptor):
        raise OSError("injected deletion failure")

    monkeypatch.setattr(msvcrt, "open_osfhandle", open_and_track)
    monkeypatch.setattr(setup, "_set_windows_owner_acl", track_directory_acl)
    monkeypatch.setattr(credential_resolver, "_windows_acl_for_handle", fail_file_acl)
    monkeypatch.setattr(setup, "_mark_windows_file_for_deletion", fail_delete)

    try:
        with pytest.raises(RuntimeConfigError) as rejected:
            _prepare_private_config_for_test(source, source_format="env", runtime_dir=target)

        assert rejected.value.reason == "private_config_cleanup_failed"
        assert len(created_fds) == 2
        file_fd = created_fds[-1][0]
        with pytest.raises(OSError):
            os.fstat(file_fd)
        assert (target / "config.yaml").exists()
    finally:
        (target / "config.yaml").unlink(missing_ok=True)


def test_relative_source_path_is_rejected_without_searching_current_directory(tmp_path):
    target = _target(tmp_path)

    with pytest.raises(RuntimeConfigError) as rejected:
        _prepare_private_config_for_test(".env", source_format="env", runtime_dir=target)

    assert rejected.value.reason == "source_path_must_be_absolute"
    assert not (target / "config.yaml").exists()


def test_source_security_failure_precedes_parse_and_write(tmp_path, monkeypatch):
    source = tmp_path / "unprotected.env"
    _write_private_source(source, _env_text())
    target = _target(tmp_path)

    def reject_unprotected_source(*_args):
        raise setup._error(
            "private_source_acl_unsafe",
            "Windows could not verify an owner-only source ACL",
        )

    monkeypatch.setattr(setup, "_source_security", reject_unprotected_source)
    with pytest.raises(RuntimeConfigError) as rejected:
        _prepare_private_config_for_test(source, source_format="env", runtime_dir=target)

    assert rejected.value.reason == "private_source_acl_unsafe"
    assert VALUES["password"] not in str(rejected.value)
    assert not (target / "config.yaml").exists()


def test_cli_requires_one_explicit_source_and_reports_redacted_summary(tmp_path, monkeypatch):
    source = tmp_path / "source.env"
    target = tmp_path / "config.yaml"
    prepared = setup.PreparedCtpSimNowConfig(target, "a" * 64)
    calls = []

    def fake_prepare(path, *, source_format):
        calls.append((path, source_format))
        return prepared

    monkeypatch.setattr(setup, "prepare_ctp_simnow_config", fake_prepare)
    output, errors = io.StringIO(), io.StringIO()

    exit_code = cli.main(
        ["prepare-ctp-config", "--source-env", str(source)],
        stdout=output,
        stderr=errors,
    )

    assert exit_code == 0
    assert calls == [(source, "env")]
    assert "runtime_registered" in output.getvalue()
    assert "not_granted" in output.getvalue()
    assert VALUES["password"] not in output.getvalue()
    assert not errors.getvalue()


def test_cli_explicitly_passes_both_sources_in_fixed_flag_order(tmp_path, monkeypatch):
    env_source = tmp_path / "source.env"
    yaml_source = tmp_path / "source.yaml"
    prepared = setup.PreparedCtpSimNowConfig(tmp_path / "config.yaml", "b" * 64)
    calls = []

    def fake_prepare(sources):
        calls.append(tuple(sources))
        return prepared

    monkeypatch.setattr(setup, "prepare_ctp_simnow_config_sources", fake_prepare)
    output, errors = io.StringIO(), io.StringIO()

    exit_code = cli.main(
        [
            "prepare-ctp-simnow-config",
            "--source-env",
            str(env_source),
            "--source-yaml",
            str(yaml_source),
        ],
        stdout=output,
        stderr=errors,
    )

    assert exit_code == 0
    assert calls == [((env_source, "env"), (yaml_source, "yaml"))]
    assert "prepared_offline" in output.getvalue()
    assert not errors.getvalue()


def test_cli_passes_only_the_selected_code_owned_private_runtime_id(tmp_path, monkeypatch):
    source = tmp_path / "source.env"
    prepared = setup.PreparedCtpSimNowConfig(tmp_path / "config.yaml", "c" * 64)
    calls = []

    def fake_prepare(path, *, source_format, runtime_id):
        calls.append((path, source_format, runtime_id))
        return prepared

    monkeypatch.setattr(setup, "prepare_ctp_simnow_config", fake_prepare)
    output, errors = io.StringIO(), io.StringIO()
    exit_code = cli.main(
        [
            "prepare-ctp-config",
            "--source-env",
            str(source),
            "--runtime-id",
            ITERATION41_007_CTP_PRIVATE_RUNTIME_ID,
        ],
        stdout=output,
        stderr=errors,
    )

    assert exit_code == 0
    assert calls == [(source, "env", ITERATION41_007_CTP_PRIVATE_RUNTIME_ID)]
    assert "not_granted" in output.getvalue()
    assert not errors.getvalue()


def test_cli_rejects_unregistered_private_runtime_id_before_helper_dispatch(tmp_path, monkeypatch):
    source = tmp_path / "source.env"
    calls = []
    monkeypatch.setattr(
        setup,
        "prepare_ctp_simnow_config",
        lambda *_args, **_kwargs: calls.append("called"),
    )
    output, errors = io.StringIO(), io.StringIO()

    exit_code = cli.main(
        [
            "prepare-ctp-config",
            "--source-env",
            str(source),
            "--runtime-id",
            "example.unregistered.private",
        ],
        stdout=output,
        stderr=errors,
    )

    assert exit_code == 2
    assert not calls
    assert not output.getvalue()
    assert "command-line arguments are not permitted" in errors.getvalue()


def test_cli_does_not_expose_the_private_test_target_seam(tmp_path, monkeypatch):
    source = tmp_path / "source.env"
    calls = []
    monkeypatch.setattr(
        setup,
        "prepare_ctp_simnow_config",
        lambda *_args, **_kwargs: calls.append("called"),
    )
    output, errors = io.StringIO(), io.StringIO()

    exit_code = cli.main(
        [
            "prepare-ctp-config",
            "--source-env",
            str(source),
            "--runtime-dir",
            str(tmp_path / "arbitrary-target"),
        ],
        stdout=output,
        stderr=errors,
    )

    assert exit_code == 2
    assert not calls
    assert not output.getvalue()
    assert "command-line arguments are not permitted" in errors.getvalue()


def test_cli_requires_at_least_one_explicit_source(tmp_path):
    output, errors = io.StringIO(), io.StringIO()

    exit_code = cli.main(
        ["prepare-ctp-config"],
        stdout=output,
        stderr=errors,
    )

    assert exit_code == 2
    assert not output.getvalue()
    assert "source_required" in errors.getvalue()


@pytest.mark.skipif(os.name != "nt", reason="Windows owner-only source ACL gate")
def test_windows_owner_only_source_acl_passes_the_real_read_gate(tmp_path, monkeypatch):
    import ctypes
    import msvcrt

    source = tmp_path / "owner-only.env"
    source.write_bytes(b"CTP_USER_ID=synthetic-user\n")
    kernel32 = ctypes.WinDLL("Kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    )
    create_file.restype = ctypes.c_void_p
    handle = create_file(
        str(source),
        0x40000000 | 0x00020000 | 0x00040000,  # GENERIC_WRITE | READ_CONTROL | WRITE_DAC
        0x00000001 | 0x00000002 | 0x00000004,  # share read/write/delete
        None,
        3,  # OPEN_EXISTING
        0x00000080,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle == invalid_handle or handle == -1:
        raise OSError(ctypes.get_last_error(), "could not open temporary source with WRITE_DAC")
    descriptor = msvcrt.open_osfhandle(
        handle,
        os.O_RDWR | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0),
    )
    try:
        setup._set_windows_owner_acl(descriptor, directory=False)
        _REAL_SOURCE_SECURITY(descriptor, os.fstat(descriptor))
    finally:
        os.close(descriptor)

    monkeypatch.setattr(setup, "_source_security", _REAL_SOURCE_SECURITY)
    assert setup._read_explicit_private_source(source) == "CTP_USER_ID=synthetic-user\n"
