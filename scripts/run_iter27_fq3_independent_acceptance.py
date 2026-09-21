#!/usr/bin/env python
"""Run a fresh, source-bound, zero-network acceptance attempt for Iteration 27 T6.

The runner deliberately does not consume an old FQ3 receipt as evidence.  It
reconstructs the 49 original observations and the 17 CP03 controls against the
current low-frequency source, then runs the current two-file target suite in a
separate Python process protected by a socket audit hook.  Its output directory
is single-use and must live below ``logs/``.

This is local synthetic evidence only.  It does not certify CTP, SimNow,
authoritative reconciliation, actual fills, PnL, or profitability.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import json
import math
import os
import re
import subprocess
import sys
import traceback
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Mapping
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
LOG_ROOT = ROOT / "logs"
NANOSECOND = 1_000_000_000
BASE = datetime(2026, 1, 5, 9, tzinfo=timezone.utc)
DOTENV_BASENAME = ".env"
SOCKET_AUDIT_EVENTS = frozenset(
    {"socket.connect", "socket.getaddrinfo", "socket.sendto"}
)

SOURCE_PATHS = (
    Path("examples/014_1_ctp_options_lowfreq/config.yaml"),
    Path("examples/014_1_ctp_options_lowfreq/ctp_options_lowfreq_strategy.py"),
    Path("examples/014_1_ctp_options_lowfreq/execution_timing.py"),
    Path("examples/014_1_ctp_options_lowfreq/run.py"),
    Path("examples/014_1_ctp_options_lowfreq/simnow_adapter.py"),
    Path("tests/unit/test_ctp_options_lowfreq_example.py"),
    Path("tests/unit/test_ctp_options_lowfreq_timing.py"),
    Path("backtrader/cerebro.py"),
    Path("backtrader/_cerebro/__init__.py"),
    Path("backtrader/_cerebro/registry.py"),
    Path("backtrader/_cerebro/notifications.py"),
    Path("backtrader/_cerebro/lifecycle.py"),
    Path("backtrader/_cerebro/channel.py"),
    Path("backtrader/_cerebro/execution.py"),
    Path("backtrader/_cerebro/runnext.py"),
    Path("backtrader/_cerebro/runonce.py"),
    Path("backtrader/_cerebro/presentation.py"),
    Path("backtrader/strategy.py"),
    Path("backtrader/brokers/bbroker.py"),
    Path("pytest.ini"),
    Path("conftest.py"),
    Path("pyproject.toml"),
    Path("scripts/run_iter27_fq3_independent_acceptance.py"),
)
TARGET_TEST_FILES = (
    "tests/unit/test_ctp_options_lowfreq_example.py",
    "tests/unit/test_ctp_options_lowfreq_timing.py",
)
EXPECTED_TARGET_JUNIT_NODES = (
    (
        "tests.unit.test_ctp_options_lowfreq_example",
        "test_example_packages_keep_same_named_modules_isolated",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_example",
        "test_directory_is_a_direct_self_contained_strategy_entrypoint",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_example",
        "test_replay_runs_a_complete_local_basket_and_never_reports_external_writes",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_example",
        "test_no_edge_and_budget_rejection_are_fail_closed",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_example",
        "test_non_replay_api_entry_is_fail_closed_before_cerebro[shadow]",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_example",
        "test_non_replay_api_entry_is_fail_closed_before_cerebro[simnow]",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_example",
        "test_non_replay_api_entry_is_fail_closed_before_cerebro[production]",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_example",
        "test_misaligned_three_leg_closed_bars_reset_confirmation_and_do_not_trade",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_example",
        "test_idle_probe_has_no_local_clock_fallback_and_explicit_facts_are_separate",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_example",
        "test_config_unknown_field_is_rejected_before_replay",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_example",
        "test_fixed_budget_boundaries_are_rejected_before_replay[capital_limit-10001-CNY 10000]",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_example",
        "test_fixed_budget_boundaries_are_rejected_before_replay[ordinary_limit-8001-CNY 8000]",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_example",
        "test_fixed_budget_boundaries_are_rejected_before_replay[recovery_reserve-1999-at least CNY 2000]",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_example",
        "test_frozen_signal_and_session_thresholds_cannot_be_weakened[strategy_params-entry_z-2.49]",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_example",
        "test_frozen_signal_and_session_thresholds_cannot_be_weakened[strategy_params-minimum_score-19]",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_example",
        "test_frozen_signal_and_session_thresholds_cannot_be_weakened[timing-session_stop_entry_seconds-1799]",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_example",
        "test_frozen_signal_and_session_thresholds_cannot_be_weakened[timing-session_exit_seconds-599]",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_example",
        "test_frozen_signal_and_session_thresholds_cannot_be_weakened[timing-session_handover_seconds-179]",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_example",
        "test_stricter_signal_and_session_thresholds_remain_valid",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_example",
        "test_early_callback_is_correlated_and_foreign_or_partial_callbacks_halt",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_example",
        "test_scoped_completed_protection_requires_confirmed_fill_before_next_leg",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_example",
        "test_partial_is_not_terminal_and_late_completed_fact_is_kept_without_new_leg",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_example",
        "test_partial_to_canceled_keeps_terminal_fact_and_ignores_late_duplicate",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_example",
        "test_shadow_mode_blocks_before_any_external_client_is_constructed",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_example",
        "test_cli_creates_an_explicit_output_parent_directory",
    ),
    ("tests.unit.test_ctp_options_lowfreq_timing", "test_bar_envelope_and_strict_economic_score"),
    (
        "tests.unit.test_ctp_options_lowfreq_timing",
        "test_price_and_exchange_limit_intersection_is_fail_closed",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_timing",
        "test_six_side_offset_fee_schedule_is_complete_or_rejected",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_timing",
        "test_bar_envelope_rejects_nonpositive_or_nonfinite_tick[True]",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_timing",
        "test_bar_envelope_rejects_nonpositive_or_nonfinite_tick[nan]",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_timing",
        "test_bar_envelope_rejects_nonpositive_or_nonfinite_tick[inf]",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_timing",
        "test_bar_envelope_rejects_nonpositive_or_nonfinite_tick[0.0]",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_timing",
        "test_deadline_boundaries_do_not_move_on_ack_or_retry",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_timing",
        "test_hold_projection_uses_fill_upper_for_min_and_exposure_lower_for_max",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_timing",
        "test_clock_domain_regression_and_wall_jump_are_separate",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_timing",
        "test_external_clock_requires_source_and_generation_and_binds_generation",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_timing",
        "test_risk_mapping_age_cannot_be_renewed_by_wall_rollback_or_untrusted_clock",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_timing",
        "test_ohlc_cannot_prove_ttl_fill_but_explicit_fact_can",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_timing",
        "test_scoped_execution_facts_require_identity_and_are_idempotent",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_timing",
        "test_execution_fact_admission_requires_one_order_and_complete_scope[order_id-foreign-order-FILL_ORDER_MISMATCH]",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_timing",
        "test_execution_fact_admission_requires_one_order_and_complete_scope[decision_id-foreign-decision-FILL_DECISION_MISMATCH]",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_timing",
        "test_execution_fact_admission_requires_one_order_and_complete_scope[basket_id-foreign-basket-FILL_BASKET_MISMATCH]",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_timing",
        "test_execution_fact_admission_requires_one_order_and_complete_scope[clock_domain-foreign-clock-FILL_CLOCK_DOMAIN_MISMATCH]",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_timing",
        "test_execution_fact_admission_requires_one_order_and_complete_scope[generation-2-FILL_CLOCK_GENERATION_MISMATCH]",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_timing",
        "test_token_and_confirmation_projection_resets_invalid_scope_direction_and_gap",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_timing",
        "test_risk_bar_age_and_session_gate_are_conservative",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_timing",
        "test_risk_bar_evidence_requires_current_scope_source_and_reference",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_timing",
        "test_session_and_loss_projection_keeps_missing_account_facts_unknown",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_timing",
        "test_actual_cerebro_no_bar_dispatches_notify_idle_without_bar_time_fallback",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_timing",
        "test_actual_cerebro_confirmed_legs_use_frozen_holds_and_fresh_exit_window",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_timing",
        "test_actual_foreign_fact_cannot_authorize_next_protection_leg[order_id-foreign-order-FILL_ORDER_MISMATCH]",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_timing",
        "test_actual_foreign_fact_cannot_authorize_next_protection_leg[decision_id-foreign-decision-FILL_DECISION_MISMATCH]",
    ),
    (
        "tests.unit.test_ctp_options_lowfreq_timing",
        "test_actual_foreign_fact_cannot_authorize_next_protection_leg[basket_id-foreign-basket-FILL_BASKET_MISMATCH]",
    ),
)
EXPECTED_TARGET_NODEIDS = tuple(
    f"{classname.replace('.', '/')}.py::{name}" for classname, name in EXPECTED_TARGET_JUNIT_NODES
)
EXPECTED_TARGET_TESTS = len(EXPECTED_TARGET_JUNIT_NODES)
ARCHIVED_REFERENCE = (
    ROOT / "logs/iteration23-25/20260910-q_rhtzc4/"
    "astra-fq3-independent-20260911-repair01-final/repair-contract.json"
)

ORIGINAL_OBSERVATIONS = (
    "root_bar_envelope",
    "root_cost20_strict_score",
    "root_cost25_strict_score",
    "complete_six_fees_reserves_positive",
    "missing_six_side_fee_rejected",
    "bar_only_price_boundaries",
    "empty_price_intersection_rejected",
    "first_send_exact_and_plus1",
    "remaining_legs_exact_and_plus1",
    "root_minimum_fill_upper",
    "root_maximum_exposure_lower",
    "process_local_token_once_sdk_durability_unknown",
    "confirmation_positive",
    "confirmation_invalid",
    "confirmation_direction",
    "confirmation_generation",
    "root_future_ohlc_not_fill",
    "ack_zero_confirmed_possible_retained",
    "timestamped_synthetic_fill_positive",
    "wall_jump_does_not_move_mono_deadline",
    "new_domain_rejected",
    "missing_clock_trust_source_rejected",
    "same_domain_new_generation_rejected",
    "risk_(910, True, True)",
    "risk_(911, True, True)",
    "risk_(1, False, True)",
    "risk_(1, True, False)",
    "wall_rollback_cannot_renew_risk_bar",
    "untrusted_clock_cannot_price_recovery",
    "actual_cerebro_bar_only_fill_unknown",
    "local_flat_not_authoritative",
    "actual_first_handoff_0",
    "actual_first_handoff_1",
    "actual_remaining_handoff_0",
    "actual_remaining_handoff_1",
    "strict_clock_unknown_protection_cannot_advance_leg",
    "actual_next_uses_confirmed_fill_upper_minimum",
    "actual_idle_supplied_closed_session_and_unknown_limits_block",
    "foreign_and_predecision_fill_is_not_confirmed",
    "duplicate_fill_does_not_add_quantity",
    "actual_cerebro_no_bar_noarg_idle_1hz_risk",
    "config_cannot_weaken_entry_z",
    "config_cannot_weaken_minimum_score",
    "config_cannot_weaken_session_stop_entry_seconds",
    "config_cannot_weaken_session_exit_seconds",
    "config_cannot_weaken_session_handover_seconds",
    "stricter_signal_session_configuration_allowed",
    "isolated_current_scope_within_ttl_fill_positive",
    "isolated_foreign_within_ttl_rejected",
)
CP03_CONTROLS = (
    "actual_ordinary_cycle_protection_positive",
    "actual_ordinary_next_after_min_before_max",
    "actual_fresh_exit_1s_60s_window",
    "actual_foreign_order_fact_not_confirmed_or_handoff",
    "actual_foreign_decision_fact_not_confirmed_or_handoff",
    "actual_foreign_basket_fact_not_confirmed_or_handoff",
    "actual_idle_missing_trust_rejected",
    "actual_idle_missing_generation_rejected",
    "actual_idle_missing_source_rejected",
    "actual_current_risk_current",
    "actual_current_risk_foreign_session",
    "actual_current_risk_foreign_limits",
    "actual_current_risk_missing_limit_reference",
    "scoped_clock_generation_latches",
    "scoped_clock_boot_latches",
    "scoped_clock_regression_latches",
    "halted_later_fact_preserved_no_new_leg",
)
EXPECTED_OBSERVATION_NAMES = ORIGINAL_OBSERVATIONS + CP03_CONTROLS


class NetworkForbidden(RuntimeError):
    """Raised when this local-only harness sees a socket operation."""


class EnvFileForbidden(RuntimeError):
    """Raised when the harness or target suite attempts to open a ``.env`` file."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_text(value: Any) -> str:
    return json.dumps(_normalise(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _write_new_text(path: Path, value: str) -> None:
    with path.open("x", encoding="utf-8") as handle:
        handle.write(value)


def _write_new_json(path: Path, value: Any) -> None:
    _write_new_text(path, _json_text(value))


def _normalise(value: Any) -> Any:
    """Convert probe evidence to deterministic JSON without hiding values."""

    if is_dataclass(value):
        return _normalise(asdict(value))
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _normalise(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalise(item) for item in value]
    if isinstance(value, set):
        return [_normalise(item) for item in sorted(value, key=repr)]
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    return value


def _source_hashes() -> dict[str, str]:
    return {str(path): _sha256(ROOT / path) for path in SOURCE_PATHS}


def _require_anaconda_base_python() -> Path:
    """Return the active Conda base interpreter, or fail closed.

    A literal path identifies one developer machine, not the Conda base
    environment.  Conda installations expose ``conda-meta`` plus a root Conda
    executable; an activated non-base environment instead has a different
    prefix.  Use those portable facts while preserving a strict refusal for
    arbitrary interpreters.
    """

    executable = Path(sys.executable).resolve()
    prefix = Path(sys.prefix).resolve()
    conda_executables = (
        prefix / "Scripts" / "conda.exe",
        prefix / "condabin" / "conda.bat",
        prefix / "bin" / "conda",
        prefix / "bin" / "conda.exe",
    )
    active_prefix = os.environ.get("CONDA_PREFIX")
    active_environment = os.environ.get("CONDA_DEFAULT_ENV")
    valid = (
        executable.is_relative_to(prefix)
        and (prefix / "conda-meta").is_dir()
        and any(path.is_file() for path in conda_executables)
        and (not active_prefix or Path(active_prefix).resolve() == prefix)
        and (not active_environment or active_environment == "base")
    )
    if not valid:
        raise RuntimeError(
            "run through the active Conda base interpreter (for example: conda run -n base python)"
        )
    return executable


def _run_git(*args: str) -> dict[str, Any]:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "argv": ["git", *args],
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _output_dir(raw: str | None) -> Path:
    if raw:
        output = Path(raw)
        if not output.is_absolute():
            output = ROOT / output
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output = LOG_ROOT / f"iter27-fq3-independent-{stamp}-{uuid.uuid4().hex[:10]}"
    output = output.resolve()
    try:
        output.relative_to(LOG_ROOT.resolve())
    except ValueError as exc:
        raise ValueError("--output-dir must be inside this repository's logs/ directory") from exc
    output.mkdir(parents=True, exist_ok=False)
    return output


def _opened_path(audit_args: tuple[object, ...]) -> str | None:
    """Return an ``open`` audit path without dereferencing a file descriptor."""

    if not audit_args:
        return None
    candidate = audit_args[0]
    if isinstance(candidate, int):
        return None
    try:
        value = os.fspath(candidate)
    except TypeError:
        return None
    return os.fsdecode(value)


def _is_dotenv_open(audit_args: tuple[object, ...]) -> bool:
    path = _opened_path(audit_args)
    if path is None:
        return False
    try:
        return Path(path).name == DOTENV_BASENAME
    except (TypeError, ValueError):
        return False


def _expect_rejection(
    call: Callable[[], Any],
    *,
    expected_exception: type[Exception],
    expected_code: str,
) -> tuple[bool, dict[str, str | bool | None]]:
    """Require one documented safety exception and its exact contract code.

    The low-frequency timing module exposes its contract codes in exception
    messages.  A different exception (including ``AttributeError``) is an
    acceptance failure, rather than proof that a negative control was safely
    rejected.
    """

    try:
        call()
    except Exception as exc:
        observed_type = type(exc)
        observed_code = str(exc)
        passed = observed_type is expected_exception and observed_code == expected_code
        return passed, {
            "expected_exception": expected_exception.__name__,
            "expected_code": expected_code,
            "observed_exception": observed_type.__name__,
            "observed_code": observed_code,
            "unexpected_exception": not passed,
        }
    return False, {
        "expected_exception": expected_exception.__name__,
        "expected_code": expected_code,
        "observed_exception": None,
        "observed_code": None,
        "unexpected_exception": False,
    }


def _expect_success(call: Callable[[], Any]) -> tuple[bool, dict[str, str | None]]:
    """Make a positive control fail visibly on every exception type."""

    try:
        result = call()
    except Exception as exc:
        return False, {
            "observed_exception": type(exc).__name__,
            "observed_code": str(exc),
        }
    return True, {"observed_exception": None, "result_type": type(result).__name__}


class ObservationBook:
    """Record independently executed product observations; never wrap pytest outcomes."""

    def __init__(self) -> None:
        self._observations: list[dict[str, Any]] = []
        self._names: set[str] = set()

    def add(
        self,
        name: str,
        oracle_group: str,
        evaluator: Callable[[], tuple[bool, Mapping[str, Any]]],
    ) -> None:
        if name in self._names:
            raise RuntimeError(f"duplicate FQ3 observation: {name}")
        self._names.add(name)
        try:
            passed, evidence = evaluator()
            entry = {
                "id": name,
                "oracle_group": oracle_group,
                "status": "PASS" if passed else "FAIL",
                "evidence": _normalise(evidence),
            }
        except BaseException as exc:  # Keep the remaining named probes observable.
            entry = {
                "id": name,
                "oracle_group": oracle_group,
                "status": "FAIL",
                "exception": repr(exc),
                "traceback": traceback.format_exc(),
            }
        self._observations.append(entry)

    @property
    def observations(self) -> list[dict[str, Any]]:
        return list(self._observations)

    @property
    def all_passed(self) -> bool:
        return bool(self._observations) and all(
            item["status"] == "PASS" for item in self._observations
        )

    def validate_shape(self) -> tuple[bool, dict[str, Any]]:
        actual = tuple(item["id"] for item in self._observations)
        expected = EXPECTED_OBSERVATION_NAMES
        return actual == expected and len(actual) == 66, {
            "expected_count": len(expected),
            "actual_count": len(actual),
            "expected_names": list(expected),
            "actual_names": list(actual),
        }


def _module_origin(module: Any) -> dict[str, str]:
    path = Path(module.__file__).resolve()
    try:
        relative = path.relative_to(ROOT)
    except ValueError as exc:
        raise RuntimeError(
            f"module origin escaped current source tree: {module.__name__}: {path}"
        ) from exc
    return {"path": str(relative), "sha256": _sha256(path)}


def _import_current_source() -> tuple[Any, Any, Any, Any, dict[str, dict[str, str]]]:
    """Import current source explicitly; no historical runner is executable input."""

    os.chdir(ROOT)
    sys.dont_write_bytecode = True
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import backtrader as bt

    runner = importlib.import_module("examples.014_1_ctp_options_lowfreq.run")
    timing = importlib.import_module("examples.014_1_ctp_options_lowfreq.execution_timing")
    strategy_module = importlib.import_module(
        "examples.014_1_ctp_options_lowfreq.ctp_options_lowfreq_strategy"
    )
    if runner.CtpOptionsLowfreqStrategy is not strategy_module.CtpOptionsLowfreqStrategy:
        raise RuntimeError("runner and source strategy resolve to different current modules")
    origins = {
        "backtrader": _module_origin(bt),
        "runner": _module_origin(runner),
        "timing": _module_origin(timing),
        "strategy": _module_origin(strategy_module),
    }
    return bt, runner, timing, strategy_module.CtpOptionsLowfreqStrategy, origins


def _synthetic_params(runner: Any, **overrides: Any) -> tuple[dict[str, Any], tuple[str, str, str]]:
    config = copy.deepcopy(runner.load_config())
    candidate = config["candidate"]
    symbols = (candidate["future"], candidate["call"], candidate["put"])
    params = dict(config["strategy_params"])
    params.update(config["timing"])
    params.update(
        candidate_id="iter27-fq3-independent-current-source",
        future_symbol=symbols[0],
        call_symbol=symbols[1],
        put_symbol=symbols[2],
        strike=candidate["strike"],
        multiplier=candidate["multiplier"],
        discount=candidate["discount"],
        capital_limit=config["budget"]["capital_limit"],
        ordinary_limit=config["budget"]["ordinary_limit"],
        recovery_reserve=config["budget"]["recovery_reserve"],
        price_ticks=dict.fromkeys(symbols, params["price_tick"]),
        exchange_limits={
            symbol: {
                "lower": 0.01,
                "upper": 10_000_000.0,
                "source": "iter27-fq3-local-synthetic-reference",
                "reference_identity": "iter27-fq3-local-synthetic-reference-v1",
            }
            for symbol in symbols
        },
        fee_schedule=dict.fromkeys(
            (
                "open_buy",
                "open_sell",
                "close_buy",
                "close_sell",
                "close_today_buy",
                "close_today_sell",
            ),
            float(params["round_trip_cost"]) / 6.0,
        ),
        exit_reserve=0.0,
        financing_reserve=0.0,
        model_reserve=0.0,
    )
    params.update(overrides)
    return params, symbols


def _slice_replay_rows(
    runner: Any, count: int
) -> tuple[dict[str, list[dict[str, Any]]], tuple[str, str, str]]:
    config = runner.load_config()
    candidate = config["candidate"]
    symbols = (candidate["future"], candidate["call"], candidate["put"])
    rows = runner.replay_bars(candidate, "eligible")
    return {symbol: list(rows[symbol][:count]) for symbol in symbols}, symbols


def _wall_for_current_decision(strategy: Any, monotonic_ns: int) -> datetime:
    """Map an explicit synthetic clock to the source barrier's frozen replay map."""

    decision = getattr(strategy, "_last_decision_input", None)
    mapping = getattr(decision, "clock_mapping", None)
    if mapping is None:
        return BASE + timedelta(seconds=monotonic_ns / NANOSECOND)
    return mapping.wall_utc_at_anchor + timedelta(
        seconds=(monotonic_ns - int(mapping.mono_ns_at_anchor)) / NANOSECOND
    )


def _run_strategy(
    bt: Any,
    runner: Any,
    strategy_type: Any,
    params: Mapping[str, Any],
    rows: Mapping[str, list[dict[str, Any]]],
    *,
    clock_state: dict[str, Any] | None = None,
) -> tuple[Any, Any]:
    class LoggingBroker(bt.brokers.BackBroker):
        def __init__(self) -> None:
            super().__init__()
            self.handoffs: list[dict[str, Any]] = []

        def buy(self, *args: Any, **kwargs: Any) -> Any:
            self.handoffs.append(
                {
                    "side": "buy",
                    "monotonic_ns": None if clock_state is None else clock_state.get("now"),
                }
            )
            return super().buy(*args, **kwargs)

        def sell(self, *args: Any, **kwargs: Any) -> Any:
            self.handoffs.append(
                {
                    "side": "sell",
                    "monotonic_ns": None if clock_state is None else clock_state.get("now"),
                }
            )
            return super().sell(*args, **kwargs)

    cerebro = bt.Cerebro(stdstats=False, quicknotify=True)
    broker = LoggingBroker()
    cerebro.setbroker(broker)
    broker.setcash(float(params["capital_limit"]))
    for symbol, values in rows.items():
        cerebro.adddata(runner._feed(values), name=symbol)
    cerebro.addstrategy(strategy_type, **dict(params))
    return cerebro.run(runonce=False)[0], broker


def _run_boundary_trace(
    bt: Any,
    runner: Any,
    strategy_class: Any,
    *,
    count: int,
    clock_values: list[int],
    inject_facts: bool = False,
    fact_patch: Mapping[str, Any] | None = None,
) -> tuple[Any, Any, dict[str, Any]]:
    """Exercise the current strategy with an explicit strict-clock trace."""

    state: dict[str, Any] = {"now": None, "remaining": list(clock_values), "strategy": None}

    def provider() -> dict[str, Any]:
        if state["remaining"]:
            state["now"] = state["remaining"].pop(0)
        elif state["now"] is None:
            raise RuntimeError("strict-clock trace did not supply an initial time")
        return {
            "monotonic_ns": state["now"],
            "wall_utc": _wall_for_current_decision(state["strategy"], state["now"]),
            # The current replay barrier seals this exact domain.  A distinct
            # synthetic provider must still bind to it rather than silently
            # creating a second clock domain.
            "domain": "iter23-replay-clock",
            "generation": 1,
            "trusted": True,
            "source": "iter27-fq3-explicit-synthetic-clock",
            "boot_id": "iter27-fq3-boot-1",
        }

    class BoundaryStrategy(strategy_class):
        def __init__(self) -> None:
            state["strategy"] = self
            self.submission_fact_counts: list[tuple[int, int]] = []
            self.injected_facts: list[dict[str, Any]] = []
            super().__init__()

        def _submit_next_leg(self) -> None:
            if self._state == "ENTERING" and self._leg_index < len(self._planned_legs):
                self.submission_fact_counts.append((self._leg_index, len(self._execution_facts)))
            return super()._submit_next_leg()

        def notify_order(self, order: Any) -> None:
            if inject_facts and order.status == order.Completed and self._state == "ENTERING":
                anchor = self._execution_window.decision_mono_ns
                fill_ns = anchor + NANOSECOND
                fact = {
                    "leg": order.data._name,
                    "quantity": 1,
                    "status": "completed",
                    "fill_lower_ns": fill_ns,
                    "fill_upper_ns": fill_ns,
                    "source": "synthetic_timestamped_execution",
                    "clock_domain": "iter23-replay-clock",
                    "generation": 1,
                    "decision_id": self._active_decision_id,
                    "basket_id": self._active_basket_id,
                    "order_id": str(order.ref),
                    "fact_id": f"iter27-fq3-boundary-{order.ref}",
                    "source_identity": "iter27-fq3-explicit-synthetic-executions",
                }
                fact.update(fact_patch or {})
                self.injected_facts.append(dict(fact))
                self.record_execution_fact(fact)
            return super().notify_order(order)

    params, _ = _synthetic_params(runner, clock_provider=provider)
    rows, _ = _slice_replay_rows(runner, count)
    strategy, broker = _run_strategy(bt, runner, BoundaryStrategy, params, rows, clock_state=state)
    return strategy, broker, state


def _run_confirmed_cycle(
    bt: Any,
    runner: Any,
    strategy_class: Any,
    *,
    fact_patch: Mapping[str, Any] | None = None,
) -> tuple[Any, Any, dict[str, Any]]:
    """Drive a valid synthetic three-leg path through current Cerebro source."""

    state: dict[str, Any] = {"strategy": None, "now": None, "calls": 0}

    def provider() -> dict[str, Any]:
        strategy = state["strategy"]
        current = getattr(strategy, "_current_clock_now_ns", 0) or 0
        strategy_state = getattr(strategy, "_state", "FLAT")
        if state["now"] is None or (strategy_state == "OPEN" and current > state["now"]):
            value = current
        else:
            value = state["now"] + 100_000_000
        state["now"] = value
        state["calls"] += 1
        wall_utc = _wall_for_current_decision(strategy, value)
        return {
            "now_monotonic_ns": value,
            # C/P/F bar evidence freezes the current replay domain as
            # ``iter23-replay-clock``; the provider is checked against it.
            "clock_domain_id": "iter23-replay-clock",
            "generation": 1,
            "trusted": True,
            "source": "iter27-fq3-cycle-clock",
            "now_epoch": wall_utc.timestamp(),
            "boot_id": "iter27-fq3-cycle-boot-1",
        }

    class ConfirmedCycleStrategy(strategy_class):
        def __init__(self) -> None:
            state["strategy"] = self
            self.submission_fact_counts: list[tuple[int, int]] = []
            self.injected_facts: list[dict[str, Any]] = []
            super().__init__()

        def _submit_next_leg(self) -> None:
            if self._state == "ENTERING" and self._leg_index < len(self._planned_legs):
                self.submission_fact_counts.append((self._leg_index, len(self._execution_facts)))
            return super()._submit_next_leg()

        def notify_order(self, order: Any) -> None:
            if order.status == order.Completed and self._state == "ENTERING":
                fill_ns = (
                    self._execution_window.decision_mono_ns
                    + 500_000_000
                    + (self._leg_index * 100_000_000)
                )
                fact = {
                    "leg": order.data._name,
                    "quantity": 1,
                    "status": "completed",
                    "fill_lower_ns": fill_ns,
                    "fill_upper_ns": fill_ns,
                    "source": "synthetic_timestamped_execution",
                    "clock_domain": "iter23-replay-clock",
                    "generation": 1,
                    "decision_id": self._active_decision_id,
                    "basket_id": self._active_basket_id,
                    "order_id": str(order.ref),
                    "fact_id": f"iter27-fq3-cycle-{order.ref}",
                    "source_identity": "iter27-fq3-explicit-synthetic-executions",
                }
                fact.update(fact_patch or {})
                self.injected_facts.append(dict(fact))
                self.record_execution_fact(fact)
            return super().notify_order(order)

    params, _ = _synthetic_params(runner, clock_provider=provider)
    config = runner.load_config()
    rows = runner.replay_bars(config["candidate"], "eligible")
    strategy, broker = _run_strategy(
        bt, runner, ConfirmedCycleStrategy, params, rows, clock_state=state
    )
    return strategy, broker, state


def _minimal_admission_strategy(timing: Any, strategy_class: Any) -> Any:
    """Use the current strategy admission methods without a test-module fixture."""

    strategy = SimpleNamespace(
        p=SimpleNamespace(clock_provider=None),
        _decision_scope=("iter27-fq3", 1, "day", "rules", "iter27-fq3-clock"),
        _active_decision_id="iter27-fq3-decision",
        _active_basket_id="iter27-fq3-basket",
        _planned_legs=[{"symbol": "P"}],
        _leg_index=0,
        _pending_order_ref=7,
        _submitted_order_ids_by_leg={"P": {"7"}},
        _execution_window=None,
        _execution_facts=[],
        _execution_fact_history=[],
        _execution_fact_keys=set(),
        _quarantined_execution_facts=[],
        _rejected_execution_possible=False,
        _hold_projection=timing.HoldProjection(("P",)),
        _confirmed_fill_by_leg={},
        _confirmed_fill_quantity=0.0,
        _fill_timing=timing.replay_fill_status(),
    )
    strategy._strict_execution_scope = strategy_class._strict_execution_scope.__get__(strategy)
    strategy._confirmed_leg_quantity = strategy_class._confirmed_leg_quantity.__get__(strategy)
    return strategy


def _admission_fact(**changes: Any) -> dict[str, Any]:
    fact = {
        "leg": "P",
        "quantity": 1,
        "status": "completed",
        "fill_lower_ns": 100,
        "fill_upper_ns": 100,
        "source": "synthetic_timestamped_execution",
        "clock_domain": "iter27-fq3-clock",
        "generation": 1,
        "decision_id": "iter27-fq3-decision",
        "basket_id": "iter27-fq3-basket",
        "order_id": "7",
        "fact_id": "iter27-fq3-admission-fact",
        "source_identity": "iter27-fq3-explicit-synthetic-executions",
    }
    fact.update(changes)
    return fact


def _report_summary(strategy: Any, broker: Any) -> dict[str, Any]:
    report = strategy.report()
    timing = report.get("timing_projection", {})
    return {
        "state": strategy._state,
        "basket_status": report.get("flat_status", report.get("basket_status")),
        "handoffs": list(getattr(broker, "handoffs", ())),
        "orders": len(report.get("orders", ())),
        "ordinary_decisions": report.get("ordinary_decisions"),
        "confirmed_fill_quantity": timing.get("confirmed_fill_quantity"),
        "confirmed_fill_by_leg": timing.get("confirmed_fill_by_leg"),
        "possible_exposure": timing.get("possible_exposure"),
        "fill_timing": timing.get("fill_timing"),
        "execution_window": timing.get("execution_window"),
        "exit_execution_window": timing.get("exit_execution_window"),
        "hold": timing.get("hold"),
        "quarantined_execution_facts": timing.get("quarantined_execution_facts"),
        "rejections": list(getattr(strategy, "_rejections", ())),
    }


def _run_observations(bt: Any, runner: Any, timing: Any, strategy_class: Any) -> ObservationBook:
    """Execute the 66 named FQ3 contracts against current imported source."""

    book = ObservationBook()
    bars = {
        "F": {"close": 1000.0, "high": 1002.0, "low": 998.0},
        "C": {"close": 20.0, "high": 22.0, "low": 18.0},
        "P": {"close": 10.0, "high": 12.0, "low": 8.0},
    }
    limits = {
        symbol: {
            "lower": 1.0,
            "upper": 100_000.0,
            "source": "iter27-fq3-explicit-synthetic-reference",
            "reference_identity": "iter27-fq3-g1-session1",
        }
        for symbol in bars
    }
    envelopes = timing.freeze_bar_envelopes(
        bars,
        ticks=dict.fromkeys(bars, 1.0),
        scope="iter27-fq3-g1-session1",
        exchange_limits=limits,
    )
    fee_keys = (
        "open_buy",
        "open_sell",
        "close_buy",
        "close_sell",
        "close_today_buy",
        "close_today_sell",
    )

    def root_envelope() -> tuple[bool, Mapping[str, Any]]:
        observed = {symbol: asdict(envelope) for symbol, envelope in envelopes.items()}
        passed = all(
            (envelope.half_envelope, envelope.lower, envelope.upper)
            == (2.0, bars[symbol]["close"] - 2.0, bars[symbol]["close"] + 2.0)
            for symbol, envelope in envelopes.items()
        )
        return passed, {"envelopes": observed}

    book.add("root_bar_envelope", "frozen_bar_envelope", root_envelope)

    for cost in (20.0, 25.0):

        def cost_observation(cost: float = cost) -> tuple[bool, Mapping[str, Any]]:
            scores = timing.economic_scores(
                envelopes,
                multiplier=10.0,
                discount=1.0,
                strike=1000.0,
                total_costs={"conversion": cost, "reversal": cost},
            )
            expected = 40.0 - cost
            passed = (
                scores["conversion"].gross_cny == 40.0
                and scores["reversal"].gross_cny == -160.0
                and scores["conversion"].net_cny == expected
                and not scores["conversion"].eligible
            )
            return passed, {
                "cost": cost,
                "scores": {key: asdict(value) for key, value in scores.items()},
            }

        book.add(f"root_cost{int(cost)}_strict_score", "frozen_bar_envelope", cost_observation)

    def complete_six_fees() -> tuple[bool, Mapping[str, Any]]:
        high = copy.deepcopy(bars)
        high["C"] = {"close": 25.0, "high": 27.0, "low": 23.0}
        high_envelopes = timing.freeze_bar_envelopes(
            high,
            ticks=dict.fromkeys(bars, 1.0),
            scope="iter27-fq3-g1-session1",
            exchange_limits=limits,
        )
        score = timing.economic_scores(
            high_envelopes,
            multiplier=10.0,
            discount=1.0,
            strike=1000.0,
            fee_schedule=dict.fromkeys(fee_keys, 1.0),
            reserves={"exit": 4.0, "financing": 5.0, "model": 10.0},
        )["conversion"]
        return (
            score.net_cny == 65.0 and score.total_cost_cny == 25.0 and score.eligible,
            {"score": asdict(score)},
        )

    book.add("complete_six_fees_reserves_positive", "frozen_bar_envelope", complete_six_fees)

    def missing_six_fee() -> tuple[bool, Mapping[str, Any]]:
        fee_schedule = dict.fromkeys(fee_keys, 1.0)
        fee_schedule.pop("close_today_sell")
        rejected, rejection = _expect_rejection(
            lambda: timing.economic_scores(
                envelopes,
                multiplier=10.0,
                discount=1.0,
                strike=1000.0,
                fee_schedule=fee_schedule,
            ),
            expected_exception=timing.TimingContractError,
            expected_code="fee_schedule.close_today_sell must be finite",
        )
        return rejected, {"rejection": rejection, "fee_keys": sorted(fee_schedule)}

    book.add("missing_six_side_fee_rejected", "frozen_bar_envelope", missing_six_fee)

    def price_boundaries() -> tuple[bool, Mapping[str, Any]]:
        results = {
            "buy_above": timing.execution_price_allowed(envelopes["F"], "buy", 1003.0),
            "sell_below": timing.execution_price_allowed(envelopes["F"], "sell", 997.0),
            "buy_inside": timing.execution_price_allowed(envelopes["F"], "buy", 1000.0),
        }
        return results == {"buy_above": False, "sell_below": False, "buy_inside": True}, results

    book.add("bar_only_price_boundaries", "bar_prices_only", price_boundaries)

    def empty_intersection() -> tuple[bool, Mapping[str, Any]]:
        bad_limits = copy.deepcopy(limits)
        bad_limits["F"].update(lower=1010.0, upper=1020.0)
        rejected, rejection = _expect_rejection(
            lambda: timing.freeze_bar_envelopes(
                bars,
                ticks=dict.fromkeys(bars, 1.0),
                scope="iter27-fq3-g1-session1",
                exchange_limits=bad_limits,
            ),
            expected_exception=timing.TimingContractError,
            expected_code="F bar and exchange envelopes do not intersect",
        )
        return rejected, {"rejection": rejection}

    book.add("empty_price_intersection_rejected", "bar_prices_only", empty_intersection)

    def deadline_observation(stage: str) -> tuple[bool, Mapping[str, Any]]:
        window = timing.ExecutionWindow(100 * NANOSECOND)
        before = window.projection()
        window.observe_ack(199 * NANOSECOND)
        deadline = (
            window.first_send_deadline_ns
            if stage == "first_send"
            else window.completion_deadline_ns
        )
        exact = window.gate(deadline, stage, possible_exposure=True)
        plus_one = window.gate(deadline + 1, stage, possible_exposure=True)
        passed = (
            exact.status == "ELIGIBLE_FOR_OTHER_GATES"
            and plus_one.status == "RECOVERY_REQUIRED"
            and before == window.projection()
        )
        return passed, {
            "exact": asdict(exact),
            "plus_one": asdict(plus_one),
            "projection": window.projection(),
        }

    book.add(
        "first_send_exact_and_plus1",
        "first_leg_deadline",
        lambda: deadline_observation("first_send"),
    )
    book.add(
        "remaining_legs_exact_and_plus1",
        "remaining_leg_envelope_deadline",
        lambda: deadline_observation("remaining_legs"),
    )

    def hold_projection() -> Any:
        hold = timing.HoldProjection(("F", "C", "P"))
        hold.record_possible_exposure("P", lower_ns=1000 * NANOSECOND)
        for symbol in ("F", "C", "P"):
            hold.record_confirmed_fill(symbol, 1025 * NANOSECOND, 1030 * NANOSECOND)
        return hold

    def min_fill_upper() -> tuple[bool, Mapping[str, Any]]:
        hold = hold_projection()
        return (
            hold.minimum_deadline_ns == 2830 * NANOSECOND
            and not hold.normal_exit_allowed(2830 * NANOSECOND - 1)
            and hold.normal_exit_allowed(2830 * NANOSECOND),
            {"hold": hold.projection()},
        )

    def max_exposure_lower() -> tuple[bool, Mapping[str, Any]]:
        hold = hold_projection()
        return (
            hold.maximum_deadline_ns == 8200 * NANOSECOND
            and hold.risk_exit_allowed(8200 * NANOSECOND),
            {"hold": hold.projection()},
        )

    book.add("root_minimum_fill_upper", "minimum_hold_uses_last_fill_upper_bound", min_fill_upper)
    book.add(
        "root_maximum_exposure_lower",
        "maximum_hold_uses_first_exposure_lower_bound",
        max_exposure_lower,
    )

    def token_once() -> tuple[bool, Mapping[str, Any]]:
        token = timing.ExecutionToken("candidate", "20260105", "day", "2026-01-05T09:00:00Z")
        projection = timing.TokenProjection()
        first, second = projection.consume(token), projection.consume(token)
        return (
            first and not second and projection.durability_status == "SDK_OWNER_REQUIRED",
            {"first": first, "second": second, "durability_status": projection.durability_status},
        )

    book.add("process_local_token_once_sdk_durability_unknown", "token_consumed_once", token_once)

    confirmation_cases = {
        "positive": [("conversion", 1, True), ("conversion", 1, True)],
        "invalid": [("conversion", 1, True), ("conversion", 1, False), ("conversion", 1, True)],
        "direction": [("conversion", 1, True), ("reversal", 1, True)],
        "generation": [("conversion", 1, True), ("conversion", 2, True)],
    }
    for label, states in confirmation_cases.items():

        def confirmation_observation(
            label: str = label, states: list[tuple[str, int, bool]] = states
        ) -> tuple[bool, Mapping[str, Any]]:
            projection = timing.ConfirmationProjection()
            results = [
                projection.accept(
                    direction,
                    generation,
                    BASE + timedelta(seconds=900 * index),
                    qualified=qualified,
                )
                for index, (direction, generation, qualified) in enumerate(states)
            ]
            return sum(results) == int(label == "positive"), {"results": results, "label": label}

        book.add(f"confirmation_{label}", "confirmation_resets", confirmation_observation)

    def future_ohlc() -> tuple[bool, Mapping[str, Any]]:
        result = timing.classify_bar_only_fill(
            decision_mono_ns=100 * NANOSECOND,
            next_bar_seconds=900,
            execution_window_seconds=60,
            touched=True,
            volume=10_000,
        )
        return result.status == "FILL_TIMING_UNKNOWN" and result.confirmed_quantity == 0, {
            "result": result
        }

    book.add("root_future_ohlc_not_fill", "future_bar_does_not_prove_short_ttl_fill", future_ohlc)

    def ack_is_not_fill() -> tuple[bool, Mapping[str, Any]]:
        result = timing.classify_execution_facts(
            [timing.ExecutionFact("P", 1, "accepted"), timing.ExecutionFact("P", 1, "ack")],
            deadline_ns=160 * NANOSECOND,
        )
        return result.confirmed_quantity == 0 and result.possible_exposure, {"result": result}

    book.add("ack_zero_confirmed_possible_retained", "ack_is_not_fill", ack_is_not_fill)

    def synthetic_fill() -> tuple[bool, Mapping[str, Any]]:
        fact = timing.ExecutionFact(
            "P",
            1,
            "completed",
            100 * NANOSECOND,
            101 * NANOSECOND,
            "synthetic_timestamped_execution",
        )
        result = timing.classify_execution_facts([fact], deadline_ns=160 * NANOSECOND)
        return (
            result.confirmed_quantity == 1 and result.status == "TIMESTAMPED_SYNTHETIC_ONLY",
            {"result": result},
        )

    book.add(
        "timestamped_synthetic_fill_positive",
        "future_bar_does_not_prove_short_ttl_fill",
        synthetic_fill,
    )

    def wall_jump() -> tuple[bool, Mapping[str, Any]]:
        clock = timing.ScopedClock()
        clock.observe(timing.ClockObservation(100 * NANOSECOND, BASE, "d1", trusted=True))
        clock.observe(
            timing.ClockObservation(101 * NANOSECOND, BASE - timedelta(hours=1), "d1", trusted=True)
        )
        return clock.last.monotonic_ns == 101 * NANOSECOND, {"last": clock.last}

    book.add("wall_jump_does_not_move_mono_deadline", "clock_domain_and_restart", wall_jump)

    def clock_rejection(kind: str) -> tuple[bool, Mapping[str, Any]]:
        clock = timing.ScopedClock()
        clock.observe(timing.ClockObservation(100, BASE, "d1", generation=1, trusted=True))
        if kind == "domain":
            expected_code = "CLOCK_DOMAIN_CHANGED"
            rejected, rejection = _expect_rejection(
                lambda: clock.observe(
                    timing.ClockObservation(101, BASE, "d2", generation=1, trusted=True)
                ),
                expected_exception=timing.ClockSafetyError,
                expected_code=expected_code,
            )
        elif kind == "generation":
            expected_code = "CLOCK_GENERATION_CHANGED"
            rejected, rejection = _expect_rejection(
                lambda: clock.observe(
                    timing.ClockObservation(101, BASE, "d1", generation=2, trusted=True)
                ),
                expected_exception=timing.ClockSafetyError,
                expected_code=expected_code,
            )
        else:
            expected_code = "TRUSTED_CLOCK_INVALID"
            rejected, rejection = _expect_rejection(
                lambda: timing.ScopedClock().observe(
                    {"monotonic_ns": 100, "domain": "unsourced", "wall_utc": BASE}
                ),
                expected_exception=timing.ClockSafetyError,
                expected_code=expected_code,
            )
        return rejected, {
            "kind": kind,
            "rejection": rejection,
            "rejection_reason": clock.rejection_reason,
        }

    book.add("new_domain_rejected", "clock_domain_and_restart", lambda: clock_rejection("domain"))
    book.add(
        "missing_clock_trust_source_rejected",
        "clock_domain_and_restart",
        lambda: clock_rejection("missing_source"),
    )
    book.add(
        "same_domain_new_generation_rejected",
        "clock_domain_and_restart",
        lambda: clock_rejection("generation"),
    )

    for age, session_open, limits_known, expected in (
        (910, True, True, True),
        (911, True, True, False),
        (1, False, True, False),
        (1, True, False, False),
    ):

        def risk_observation(
            age: int = age,
            session_open: bool = session_open,
            limits_known: bool = limits_known,
            expected: bool = expected,
        ) -> tuple[bool, Mapping[str, Any]]:
            result = timing.project_risk_bar(
                bucket_end=BASE,
                now=timing.ClockObservation(
                    age * NANOSECOND,
                    BASE + timedelta(seconds=age),
                    "d1",
                    trusted=True,
                ),
                session_open=session_open,
                price_limits_known=limits_known,
                mapping_error_ns=0,
            )
            return (
                result.can_propose_recovery == expected and not result.successful_flat_exit,
                {"result": result},
            )

        book.add(
            f"risk_{(age, session_open, limits_known)}",
            "risk_without_executable_bar",
            risk_observation,
        )

    def wall_rollback() -> tuple[bool, Mapping[str, Any]]:
        clock = timing.ScopedClock()
        first = clock.observe(
            timing.ClockObservation(
                911 * NANOSECOND, BASE + timedelta(seconds=911), "d1", trusted=True
            )
        )
        before = timing.project_risk_bar(
            bucket_end=BASE, now=first, session_open=True, price_limits_known=True
        )
        second = clock.observe(
            timing.ClockObservation(
                912 * NANOSECOND, BASE + timedelta(seconds=12), "d1", trusted=True
            )
        )
        after = timing.project_risk_bar(
            bucket_end=BASE, now=second, session_open=True, price_limits_known=True
        )
        return not after.can_propose_recovery, {"before": before, "after": after}

    book.add("wall_rollback_cannot_renew_risk_bar", "risk_without_executable_bar", wall_rollback)

    def untrusted_clock() -> tuple[bool, Mapping[str, Any]]:
        result = timing.project_risk_bar(
            bucket_end=BASE,
            now=timing.ClockObservation(
                NANOSECOND, BASE + timedelta(seconds=1), "d1", trusted=False
            ),
            session_open=True,
            price_limits_known=True,
        )
        return not result.can_propose_recovery, {"result": result}

    book.add(
        "untrusted_clock_cannot_price_recovery", "risk_without_executable_bar", untrusted_clock
    )

    def replay_report() -> dict[str, Any]:
        return runner.run_replay(runner.load_config(), "eligible")

    def actual_bar_only() -> tuple[bool, Mapping[str, Any]]:
        report = replay_report()
        timing_projection = report["timing_projection"]
        passed = (
            timing_projection["confirmed_fill_quantity"] == 0
            and all(order["fill_timing"] == "FILL_TIMING_UNKNOWN" for order in report["orders"])
            and report["external_request_counts"] == {"network": 0, "order_write": 0}
        )
        return passed, {
            "state": report["state"],
            "orders": len(report["orders"]),
            "timing": timing_projection["fill_timing"],
            "external_request_counts": report["external_request_counts"],
        }

    def local_flat() -> tuple[bool, Mapping[str, Any]]:
        report = replay_report()
        passed = (
            report["flat_status"] == "LOCAL_BASKET_FLAT_UNVERIFIED"
            and report["authoritative_flat_status"] == "NOT_RUN_SDK_TWO_ROUND_RECONCILIATION"
        )
        return passed, {
            "flat_status": report["flat_status"],
            "authoritative_flat_status": report["authoritative_flat_status"],
        }

    book.add(
        "actual_cerebro_bar_only_fill_unknown",
        "future_bar_does_not_prove_short_ttl_fill",
        actual_bar_only,
    )
    book.add("local_flat_not_authoritative", "token_consumed_once", local_flat)

    anchor = int((41 * 900 + 0.7) * NANOSECOND)

    for extra in (0, 1):

        def first_handoff(extra: int = extra) -> tuple[bool, Mapping[str, Any]]:
            strategy, broker, state = _run_boundary_trace(
                bt,
                runner,
                strategy_class,
                count=42,
                clock_values=[anchor, anchor + NANOSECOND + extra],
            )
            expected = 1 if extra == 0 else 0
            return len(broker.handoffs) == expected, {
                "handoffs": broker.handoffs,
                "state": strategy._state,
                "clock_remaining": state["remaining"],
                "rejections": strategy._rejections,
            }

        book.add(f"actual_first_handoff_{extra}", "first_leg_deadline", first_handoff)

    for extra in (0, 1):

        def remaining_handoff(extra: int = extra) -> tuple[bool, Mapping[str, Any]]:
            strategy, broker, state = _run_boundary_trace(
                bt,
                runner,
                strategy_class,
                count=43,
                clock_values=[anchor, anchor + NANOSECOND, anchor + 60 * NANOSECOND + extra],
                inject_facts=True,
            )
            expected = 2 if extra == 0 else 1
            return len(broker.handoffs) == expected, {
                "handoffs": broker.handoffs,
                "state": strategy._state,
                "clock_remaining": state["remaining"],
                "rejections": strategy._rejections,
                "facts": strategy.injected_facts,
            }

        book.add(
            f"actual_remaining_handoff_{extra}",
            "remaining_leg_envelope_deadline",
            remaining_handoff,
        )

    def strict_unknown_protection() -> tuple[bool, Mapping[str, Any]]:
        strategy, broker, state = _run_boundary_trace(
            bt,
            runner,
            strategy_class,
            count=43,
            clock_values=[anchor, anchor + NANOSECOND, anchor + 60 * NANOSECOND],
        )
        passed = len(broker.handoffs) <= 1 and strategy._confirmed_fill_quantity == 0
        return passed, {
            "summary": _report_summary(strategy, broker),
            "clock_remaining": state["remaining"],
        }

    book.add(
        "strict_clock_unknown_protection_cannot_advance_leg",
        "ack_is_not_fill",
        strict_unknown_protection,
    )

    def confirmed_cycle_values() -> tuple[Any, Any, dict[str, Any], Mapping[str, Any]]:
        strategy, broker, state = _run_confirmed_cycle(bt, runner, strategy_class)
        return strategy, broker, state, strategy.report()

    def minimum_hold_actual() -> tuple[bool, Mapping[str, Any]]:
        strategy, broker, state, report = confirmed_cycle_values()
        timing_projection = report["timing_projection"]
        hold = timing_projection["hold"]
        exit_window = timing_projection["exit_execution_window"]
        events = [event for event in report["events"] if event["kind"] == "exit_decision"]
        passed = (
            bool(events)
            and all(event["reason"] == "residual_reverted" for event in events)
            and timing_projection["confirmed_fill_quantity"] == 3
            and hold["minimum_deadline_ns"]
            <= exit_window["decision_mono_ns"]
            < hold["maximum_deadline_ns"]
        )
        return passed, {
            "summary": _report_summary(strategy, broker),
            "exit_events": events,
            "clock_calls": state["calls"],
        }

    book.add(
        "actual_next_uses_confirmed_fill_upper_minimum",
        "minimum_hold_uses_last_fill_upper_bound",
        minimum_hold_actual,
    )

    def idle_closed_limits() -> tuple[bool, Mapping[str, Any]]:
        config = runner.load_config()
        report = runner.run_replay(
            config,
            "eligible",
            idle_now={
                "monotonic_ns": anchor + NANOSECOND,
                "wall_utc": BASE + timedelta(seconds=anchor / NANOSECOND + 1),
                "domain": "iter23-replay-clock",
                "generation": 1,
                "trusted": True,
                "source": "iter27-fq3-idle-source",
                "session_open": False,
                "price_limits_known": False,
            },
        )
        idle = report["timing_projection"]["idle"]
        return idle.get("status") != "RECOVERY_PRICE_ELIGIBLE", {"idle": idle}

    book.add(
        "actual_idle_supplied_closed_session_and_unknown_limits_block",
        "risk_without_executable_bar",
        idle_closed_limits,
    )

    def foreign_predecision_and_duplicate() -> tuple[Any, Mapping[str, Any]]:
        strategy = _minimal_admission_strategy(timing, strategy_class)
        foreign = _admission_fact(
            clock_domain="foreign-clock",
            generation=999,
            order_id="foreign-order",
            fact_id="iter27-fq3-foreign-predecision",
        )
        first = strategy_class.record_execution_fact(strategy, foreign)
        before = strategy._confirmed_fill_quantity
        duplicate = strategy_class.record_execution_fact(strategy, foreign)
        return strategy, {
            "first": first,
            "duplicate": duplicate,
            "before": before,
            "after": strategy._confirmed_fill_quantity,
            "history_count": len(strategy._execution_fact_history),
            "admitted_count": len(strategy._execution_facts),
            "quarantine": strategy._quarantined_execution_facts,
        }

    def foreign_predecision() -> tuple[bool, Mapping[str, Any]]:
        strategy, evidence = foreign_predecision_and_duplicate()
        return strategy._confirmed_fill_quantity == 0 and not strategy._execution_facts, evidence

    def duplicate_fact() -> tuple[bool, Mapping[str, Any]]:
        strategy, evidence = foreign_predecision_and_duplicate()
        return (
            evidence["before"] == evidence["after"] == 0
            and len(strategy._execution_fact_keys) == 1,
            evidence,
        )

    book.add(
        "foreign_and_predecision_fill_is_not_confirmed",
        "clock_domain_and_restart",
        foreign_predecision,
    )
    book.add("duplicate_fill_does_not_add_quantity", "ack_is_not_fill", duplicate_fact)

    def idle_no_bar() -> tuple[bool, Mapping[str, Any]]:
        class IdleFeed(bt.feed.DataBase):
            params = (("qcheck", 0.0),)

            def __init__(self) -> None:
                super().__init__()
                self.calls = 0

            def islive(self) -> bool:
                return True

            def _load(self) -> bool | None:
                self.calls += 1
                return None if self.calls == 1 else False

        now_calls: list[int] = []

        def provider() -> dict[str, Any]:
            now_calls.append(len(now_calls) + 1)
            return {
                "now_monotonic_ns": now_calls[-1],
                "clock_domain_id": "iter27-fq3-idle-no-bar",
                "now_epoch": 1_790_000_000.0,
                "generation": 1,
                "trusted": True,
                "source": "iter27-fq3-idle-no-bar-source",
            }

        params, symbols = _synthetic_params(runner, clock_provider=provider)
        cerebro = bt.Cerebro(stdstats=False, quicknotify=True)
        for symbol in symbols:
            cerebro.adddata(IdleFeed(), name=symbol)
        cerebro.addstrategy(strategy_class, **params)
        strategy = cerebro.run(runonce=False)[0]
        passed = (
            now_calls == [1]
            and strategy._clock.last.monotonic_ns == 1
            and strategy._clock_rejection_latched is False
        )
        return passed, {
            "now_calls": now_calls,
            "last_clock": strategy._clock.last,
            "clock_rejection_latched": strategy._clock_rejection_latched,
        }

    book.add(
        "actual_cerebro_no_bar_noarg_idle_1hz_risk",
        "maximum_hold_uses_first_exposure_lower_bound",
        idle_no_bar,
    )

    config_cases = (
        ("strategy_params", "entry_z", 2.49, "strategy_params.entry_z must be at least 2.5"),
        (
            "strategy_params",
            "minimum_score",
            19,
            "strategy_params.minimum_score must be at least 20",
        ),
        (
            "timing",
            "session_stop_entry_seconds",
            1799,
            "timing.session_stop_entry_seconds must be at least 1800",
        ),
        ("timing", "session_exit_seconds", 599, "timing.session_exit_seconds must be at least 600"),
        (
            "timing",
            "session_handover_seconds",
            179,
            "timing.session_handover_seconds must be at least 180",
        ),
    )
    for group, field, value, expected_code in config_cases:

        def config_weakened(
            group: str = group,
            field: str = field,
            value: Any = value,
            expected_code: str = expected_code,
        ) -> tuple[bool, Mapping[str, Any]]:
            config = copy.deepcopy(runner.load_config())
            config[group][field] = value
            rejected, rejection = _expect_rejection(
                lambda: runner.validate_config(config),
                expected_exception=runner.RunnerConfigurationError,
                expected_code=expected_code,
            )
            return rejected, {
                "group": group,
                "field": field,
                "value": value,
                "rejection": rejection,
            }

        book.add(f"config_cannot_weaken_{field}", "confirmation_resets", config_weakened)

    def stricter_config() -> tuple[bool, Mapping[str, Any]]:
        config = copy.deepcopy(runner.load_config())
        config["strategy_params"].update(entry_z=2.51, minimum_score=21)
        config["timing"].update(
            session_stop_entry_seconds=1900,
            session_exit_seconds=700,
            session_handover_seconds=200,
        )
        accepted, acceptance = _expect_success(lambda: runner.validate_config(config))
        return accepted, {"acceptance": acceptance}

    book.add(
        "stricter_signal_session_configuration_allowed", "confirmation_resets", stricter_config
    )

    def isolated_scope(foreign: bool) -> tuple[bool, Mapping[str, Any]]:
        strategy = _minimal_admission_strategy(timing, strategy_class)
        fact = _admission_fact(
            fact_id=f"iter27-fq3-isolated-{foreign}",
            clock_domain="foreign-clock" if foreign else "iter27-fq3-clock",
            generation=999 if foreign else 1,
        )
        result = strategy_class.record_execution_fact(strategy, fact)
        expected = 0 if foreign else 1
        return strategy._confirmed_fill_quantity == expected, {
            "fact": fact,
            "result": result,
            "confirmed_fill_quantity": strategy._confirmed_fill_quantity,
            "quarantine": strategy._quarantined_execution_facts,
        }

    book.add(
        "isolated_current_scope_within_ttl_fill_positive",
        "clock_domain_and_restart",
        lambda: isolated_scope(False),
    )
    book.add(
        "isolated_foreign_within_ttl_rejected",
        "clock_domain_and_restart",
        lambda: isolated_scope(True),
    )

    def cycle_control() -> tuple[Any, Any, dict[str, Any], Mapping[str, Any]]:
        return confirmed_cycle_values()

    def ordinary_cycle() -> tuple[bool, Mapping[str, Any]]:
        strategy, broker, state, report = cycle_control()
        timing_projection = report["timing_projection"]
        passed = (
            len(broker.handoffs) == 6
            and strategy._state == "FLAT"
            and strategy.submission_fact_counts[:3] == [(0, 0), (1, 1), (2, 2)]
            and len(strategy.injected_facts) == 3
            and timing_projection["confirmed_fill_quantity"] == 3
            and report["flat_status"] == "LOCAL_BASKET_FLAT_UNVERIFIED"
        )
        return passed, {
            "summary": _report_summary(strategy, broker),
            "submission_fact_counts": strategy.submission_fact_counts,
            "injected_facts": strategy.injected_facts,
            "clock_calls": state["calls"],
        }

    def ordinary_next() -> tuple[bool, Mapping[str, Any]]:
        strategy, broker, state, report = cycle_control()
        timing_projection = report["timing_projection"]
        hold = timing_projection["hold"]
        exit_window = timing_projection["exit_execution_window"]
        events = [event for event in report["events"] if event["kind"] == "exit_decision"]
        passed = (
            bool(events)
            and all(event["reason"] == "residual_reverted" for event in events)
            and hold["minimum_deadline_ns"]
            <= exit_window["decision_mono_ns"]
            < hold["maximum_deadline_ns"]
        )
        return passed, {
            "events": events,
            "hold": hold,
            "exit_window": exit_window,
            "clock_calls": state["calls"],
        }

    def fresh_exit_window() -> tuple[bool, Mapping[str, Any]]:
        strategy, broker, state, report = cycle_control()
        timing_projection = report["timing_projection"]
        entry = timing_projection["execution_window"]
        exit_window = timing_projection["exit_execution_window"]
        handoffs = broker.handoffs
        passed = (
            exit_window["decision_mono_ns"] > entry["decision_mono_ns"]
            and all(
                window["first_send_deadline_ns"] == window["decision_mono_ns"] + NANOSECOND
                and window["completion_deadline_ns"] == window["decision_mono_ns"] + 60 * NANOSECOND
                for window in (entry, exit_window)
            )
            and len(handoffs) == 6
            and entry["decision_mono_ns"]
            <= handoffs[0]["monotonic_ns"]
            <= entry["first_send_deadline_ns"]
            and all(
                item["monotonic_ns"] <= entry["completion_deadline_ns"] for item in handoffs[:3]
            )
            and exit_window["decision_mono_ns"]
            <= handoffs[3]["monotonic_ns"]
            <= exit_window["first_send_deadline_ns"]
            and all(
                item["monotonic_ns"] <= exit_window["completion_deadline_ns"]
                for item in handoffs[3:]
            )
        )
        return passed, {
            "entry": entry,
            "exit": exit_window,
            "handoffs": handoffs,
            "clock_calls": state["calls"],
        }

    book.add("actual_ordinary_cycle_protection_positive", "ack_is_not_fill", ordinary_cycle)
    book.add(
        "actual_ordinary_next_after_min_before_max",
        "minimum_hold_uses_last_fill_upper_bound",
        ordinary_next,
    )
    book.add(
        "actual_fresh_exit_1s_60s_window", "remaining_leg_envelope_deadline", fresh_exit_window
    )

    for label, patch, reason in (
        ("order", {"order_id": "foreign-order"}, "FILL_ORDER_MISMATCH"),
        ("decision", {"decision_id": "foreign-decision"}, "FILL_DECISION_MISMATCH"),
        ("basket", {"basket_id": "foreign-basket"}, "FILL_BASKET_MISMATCH"),
    ):

        def foreign_control(
            patch: Mapping[str, Any] = patch, reason: str = reason
        ) -> tuple[bool, Mapping[str, Any]]:
            strategy, broker, state = _run_confirmed_cycle(
                bt, runner, strategy_class, fact_patch=patch
            )
            passed = (
                len(broker.handoffs) == 1
                and strategy._confirmed_fill_quantity == 0
                and sum(strategy._confirmed_fill_by_leg.values()) == 0
                and strategy._state == "HALTED"
                and strategy._quarantined_execution_facts
                and strategy._quarantined_execution_facts[0]["reason"] == reason
            )
            return passed, {
                "summary": _report_summary(strategy, broker),
                "facts": strategy.injected_facts,
                "clock_calls": state["calls"],
            }

        book.add(
            f"actual_foreign_{label}_fact_not_confirmed_or_handoff",
            "ack_is_not_fill",
            foreign_control,
        )

    def strict_entry_strategy() -> tuple[Any, Any, dict[str, Any]]:
        return _run_boundary_trace(
            bt,
            runner,
            strategy_class,
            count=42,
            clock_values=[anchor, anchor + NANOSECOND],
        )

    for label, absent in (("trust", "trusted"), ("generation", "generation"), ("source", "source")):

        def missing_idle(
            label: str = label, absent: str = absent
        ) -> tuple[bool, Mapping[str, Any]]:
            strategy, broker, state = strict_entry_strategy()
            decision = strategy._last_decision_input
            observation: dict[str, Any] = {
                "monotonic_ns": int(round(decision.barrier_ready_mono * NANOSECOND)) + NANOSECOND,
                "wall_utc": _wall_for_current_decision(
                    strategy,
                    int(round(decision.barrier_ready_mono * NANOSECOND)) + NANOSECOND,
                ),
                "domain": decision.clock_domain,
                "generation": decision.generation,
                "trusted": True,
                "source": "iter27-fq3-explicit-synthetic-clock",
                "boot_id": "iter27-fq3-boot-1",
            }
            observation.pop(absent)
            strategy.notify_idle(observation)
            passed = (
                strategy._clock_rejection_latched
                and strategy._last_idle_projection["status"] == "OFFLINE_SIGNAL_ONLY"
            )
            return passed, {
                "label": label,
                "observation": observation,
                "rejection": strategy._clock_rejection_reason,
                "projection": strategy._last_idle_projection,
                "handoffs": broker.handoffs,
                "clock_remaining": state["remaining"],
            }

        book.add(f"actual_idle_missing_{label}_rejected", "clock_domain_and_restart", missing_idle)

    for label, change in (
        ("current", {}),
        ("foreign_session", {"session_scope": ("foreign",)}),
        ("foreign_limits", {"price_limits_scope": ("foreign",)}),
        ("missing_limit_reference", {"price_limits_reference_identity": None}),
    ):

        def risk_scope_control(
            label: str = label, change: Mapping[str, Any] = change
        ) -> tuple[bool, Mapping[str, Any]]:
            strategy, broker, state = strict_entry_strategy()
            decision = strategy._last_decision_input
            observation: dict[str, Any] = {
                "monotonic_ns": int(round(decision.barrier_ready_mono * NANOSECOND)) + NANOSECOND,
                "wall_utc": _wall_for_current_decision(
                    strategy,
                    int(round(decision.barrier_ready_mono * NANOSECOND)) + NANOSECOND,
                ),
                "domain": decision.clock_domain,
                "generation": decision.generation,
                "trusted": True,
                "source": "iter27-fq3-explicit-synthetic-clock",
                "boot_id": "iter27-fq3-boot-1",
                "scope": strategy._decision_scope,
                "session_open": True,
                "price_limits_known": True,
                "session_scope": strategy._decision_scope,
                "price_limits_scope": strategy._decision_scope,
                "price_limits_source": "iter27-fq3-current-limits",
                "price_limits_reference_identity": "iter27-fq3-current-reference",
            }
            observation.update(change)
            strategy.notify_idle(observation)
            eligible = strategy._last_idle_projection["status"] == "RECOVERY_PRICE_ELIGIBLE"
            return (
                eligible == (label == "current")
                and strategy._last_idle_projection["risk_actions"] == [],
                {
                    "label": label,
                    "observation": observation,
                    "projection": strategy._last_idle_projection,
                    "handoffs": broker.handoffs,
                    "clock_remaining": state["remaining"],
                },
            )

        book.add(f"actual_current_risk_{label}", "risk_without_executable_bar", risk_scope_control)

    for label, field, value, expected_code in (
        ("generation", "generation", 2, "CLOCK_GENERATION_CHANGED"),
        ("boot", "boot_id", "iter27-fq3-boot-2", "CLOCK_BOOT_CHANGED"),
        ("regression", "monotonic_ns", 99 * NANOSECOND, "CLOCK_REGRESSION"),
    ):

        def clock_latch(
            label: str = label,
            field: str = field,
            value: Any = value,
            expected_code: str = expected_code,
        ) -> tuple[bool, Mapping[str, Any]]:
            clock = timing.ScopedClock()
            first = {
                "monotonic_ns": 100 * NANOSECOND,
                "wall_utc": BASE,
                "domain": "d1",
                "generation": 1,
                "trusted": True,
                "source": "iter27-fq3-latch-clock",
                "boot_id": "iter27-fq3-boot-1",
            }
            clock.observe(first)
            bad = dict(first)
            bad["monotonic_ns"] = 101 * NANOSECOND
            bad[field] = value
            first_rejection, first_evidence = _expect_rejection(
                lambda: clock.observe(bad),
                expected_exception=timing.ClockSafetyError,
                expected_code=expected_code,
            )
            second_rejection, second_evidence = _expect_rejection(
                lambda: clock.observe({**first, "monotonic_ns": 102 * NANOSECOND}),
                expected_exception=timing.ClockSafetyError,
                expected_code=expected_code,
            )
            return (
                first_rejection and second_rejection and clock.rejection_reason == expected_code,
                {
                    "label": label,
                    "bad": bad,
                    "first_rejection": first_evidence,
                    "second_rejection": second_evidence,
                    "rejection_reason": clock.rejection_reason,
                },
            )

        book.add(f"scoped_clock_{label}_latches", "clock_domain_and_restart", clock_latch)

    def halted_later_fact() -> tuple[bool, Mapping[str, Any]]:
        strategy, broker, state = _run_confirmed_cycle(
            bt, runner, strategy_class, fact_patch={"order_id": "foreign-order"}
        )
        before = len(broker.handoffs)
        decision = strategy._last_decision_input
        strategy.record_execution_fact(
            {
                "leg": strategy.p.put_symbol,
                "quantity": 1,
                "status": "completed",
                "fill_lower_ns": strategy._execution_window.decision_mono_ns + NANOSECOND,
                "fill_upper_ns": strategy._execution_window.decision_mono_ns + NANOSECOND,
                "source": "synthetic_timestamped_execution",
                "clock_domain": decision.clock_domain,
                "generation": decision.generation,
                "decision_id": strategy._active_decision_id,
                "basket_id": strategy._active_basket_id,
                "order_id": str(next(iter(strategy._terminal_order_refs))),
                "fact_id": "iter27-fq3-late-after-halt",
                "source_identity": "iter27-fq3-explicit-synthetic-executions",
            }
        )
        strategy._submit_next_leg()
        passed = (
            strategy._state == "HALTED"
            and before == len(broker.handoffs) == 1
            and len(strategy._execution_fact_history) == 2
        )
        return passed, {
            "summary": _report_summary(strategy, broker),
            "history_count": len(strategy._execution_fact_history),
            "clock_calls": state["calls"],
        }

    book.add("halted_later_fact_preserved_no_new_leg", "ack_is_not_fill", halted_later_fact)
    return book


def _network_guard_source(events_path: Path) -> str:
    """Generate the target-suite socket and ``.env`` audit guard."""

    return f"""# Generated only inside an ignored immutable acceptance output directory.
import json
import os
import sys
from pathlib import Path

EVENTS = Path({str(events_path)!r})
DOTENV_BASENAME = {DOTENV_BASENAME!r}
SOCKET_EVENTS = {{"socket.connect", "socket.getaddrinfo", "socket.sendto"}}

def _record(event, args):
    with EVENTS.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({{
            "event": event,
            "arguments": repr(args),
            "pid": os.getpid(),
            "argv": sys.argv,
            "cwd": os.getcwd(),
            "phase": os.environ.get("FQ3_GUARD_PHASE"),
            "executable": sys.executable,
            "executable_resolved": str(Path(sys.executable).resolve()),
        }}) + "\\n")

def _opened_path(args):
    if not args:
        return None
    candidate = args[0]
    if isinstance(candidate, int):
        return None
    try:
        path = os.fspath(candidate)
    except TypeError:
        return None
    return os.fsdecode(path)

def _is_dotenv_open(args):
    path = _opened_path(args)
    if path is None:
        return False
    try:
        return Path(path).name == DOTENV_BASENAME
    except (TypeError, ValueError):
        return False

def _audit(event, args):
    if event in SOCKET_EVENTS:
        _record(event, args)
        raise RuntimeError("ITER27_FQ3_NETWORK_FORBIDDEN")
    if event == "open" and _is_dotenv_open(args):
        _record("dotenv_file_open", args)
        raise RuntimeError("ITER27_FQ3_ENV_FILE_FORBIDDEN")

_record("guard_loaded", ())
sys.addaudithook(_audit)
"""


def _child_environment(guard_dir: Path, events_path: Path) -> dict[str, str]:
    """Do not inherit credential-like variables or arbitrary PYTHONPATH entries."""

    allowed: dict[str, str] = {}
    inherited_names = ["PATH", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL"]
    if os.name == "nt":
        # Windows loads Winsock through the system-root DLL search path during
        # ``asyncio`` import; these are OS-loader state, not user credentials.
        inherited_names.extend(("SYSTEMROOT", "WINDIR", "COMSPEC"))
    for name in inherited_names:
        value = os.environ.get(name)
        if value:
            allowed[name] = value
    allowed.update(
        {
            # ``sitecustomize`` must load first, but the declared ``run.py``
            # shadow child must still import the current workspace—not an
            # unrelated installed backtrader package.
            "PYTHONPATH": os.pathsep.join((str(guard_dir), str(ROOT))),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTEST_ADDOPTS": "-p no:cacheprovider -p no:rerunfailures",
            "FQ3_NETWORK_EVENTS": str(events_path),
        }
    )
    return allowed


def _write_subprocess_text(path: Path, text: str) -> None:
    _write_new_text(path, text)


def _run_target_suite(output: Path) -> dict[str, Any]:
    """Run a fresh current-source test suite under a separate socket guard."""

    base_python = _require_anaconda_base_python()
    guard_dir = output / "network_guard"
    guard_dir.mkdir()
    events_path = output / "pytest-network-events.jsonl"
    _write_new_text(events_path, "")
    _write_new_text(guard_dir / "sitecustomize.py", _network_guard_source(events_path))
    environment = _child_environment(guard_dir, events_path)
    collection_environment = {**environment, "FQ3_GUARD_PHASE": "collection"}
    suite_environment = {**environment, "FQ3_GUARD_PHASE": "suite"}
    common = [
        "-q",
        "-rXx",
        "-p",
        "no:cacheprovider",
        "-p",
        "no:rerunfailures",
        *TARGET_TEST_FILES,
    ]
    collection = subprocess.run(
        [str(base_python), "-m", "pytest", "--collect-only", *common],
        cwd=ROOT,
        env=collection_environment,
        capture_output=True,
        text=True,
        check=False,
    )
    _write_subprocess_text(output / "target-collection.stdout.txt", collection.stdout)
    _write_subprocess_text(output / "target-collection.stderr.txt", collection.stderr)
    junit_path = output / "target-suite.junit.xml"
    suite = subprocess.run(
        [str(base_python), "-m", "pytest", *common, f"--junitxml={junit_path}"],
        cwd=ROOT,
        env=suite_environment,
        capture_output=True,
        text=True,
        check=False,
    )
    _write_subprocess_text(output / "target-suite.stdout.txt", suite.stdout)
    _write_subprocess_text(output / "target-suite.stderr.txt", suite.stderr)
    guard_events: list[dict[str, Any]] = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if line:
            guard_events.append(json.loads(line))
    network_attempts = [
        event for event in guard_events if event.get("event") in SOCKET_AUDIT_EVENTS
    ]
    env_file_attempts = [
        event for event in guard_events if event.get("event") == "dotenv_file_open"
    ]
    allowed_guard_events = {"guard_loaded", "dotenv_file_open", *SOCKET_AUDIT_EVENTS}
    unexpected_guard_events = [
        event for event in guard_events if event.get("event") not in allowed_guard_events
    ]
    loaded_events = [event for event in guard_events if event.get("event") == "guard_loaded"]
    example_dir = (ROOT / "examples/014_1_ctp_options_lowfreq").resolve()

    def guard_role(event: Mapping[str, Any]) -> str | None:
        argv = event.get("argv")
        if not isinstance(argv, list) or len(argv) < 2:
            return None
        if event.get("executable") != str(base_python) or event.get(
            "executable_resolved"
        ) != str(base_python):
            return None
        cwd = Path(str(event.get("cwd", ""))).resolve()
        phase = event.get("phase")
        # ``python -m pytest`` exposes ``sys.argv`` from pytest's perspective:
        # its first item is ``-m`` and the module name itself is absent.
        is_pytest = argv and argv[0] == "-m"
        if (
            phase == "collection"
            and cwd == ROOT
            and is_pytest
            and argv[1:]
            == [
                "--collect-only",
                *common,
            ]
        ):
            return "collection_pytest"
        if (
            phase == "suite"
            and cwd == ROOT
            and is_pytest
            and argv[1:]
            == [
                *common,
                f"--junitxml={junit_path}",
            ]
        ):
            return "suite_pytest"
        if (
            phase == "suite"
            and cwd == example_dir
            and argv
            in (["run.py", "--mode", "shadow"], [str(example_dir / "run.py"), "--mode", "shadow"])
        ):
            return "suite_declared_runpy_shadow_child"
        return None

    guard_roles = [guard_role(event) for event in loaded_events]
    expected_guard_roles = {
        "collection_pytest",
        "suite_pytest",
        "suite_declared_runpy_shadow_child",
    }
    guard_loaded = (
        len(loaded_events) == 3
        and set(guard_roles) == expected_guard_roles
        and None not in guard_roles
        and len({event.get("pid") for event in loaded_events}) == 3
    )
    collect_match = re.search(r"(\d+) tests collected", collection.stdout + collection.stderr)
    collected = int(collect_match.group(1)) if collect_match else None
    collection_nodeids = _collection_nodeids(collection.stdout, collection.stderr)
    junit = _junit_summary(junit_path)
    expected_failure_markers = _pytest_expected_failure_markers(
        collection.stdout,
        collection.stderr,
        suite.stdout,
        suite.stderr,
    )
    expected_failure_policy = {
        "runxfail_present": "--runxfail" in common,
        "junit_skipped": junit.get("skipped"),
        "junit_expected_failure_nodes": junit.get("expected_failure_nodes"),
        "terminal_markers": expected_failure_markers,
        "refused": (
            "--runxfail" not in common
            and junit.get("skipped") == 0
            and not junit.get("expected_failure_nodes")
            and not expected_failure_markers
        ),
    }
    return {
        "command": [
            str(base_python),
            "-m",
            "pytest",
            *common,
            f"--junitxml={junit_path}",
        ],
        "collection_command": [
            str(base_python),
            "-m",
            "pytest",
            "--collect-only",
            *common,
        ],
        "collection_returncode": collection.returncode,
        "collected_testcases": collected,
        "collection_nodeids": list(collection_nodeids),
        "expected_collection_nodeids": list(EXPECTED_TARGET_NODEIDS),
        "collection_nodeids_match": collection_nodeids == EXPECTED_TARGET_NODEIDS,
        "suite_returncode": suite.returncode,
        "junit": junit,
        "guard_loaded": guard_loaded,
        "guard_load_policy": {
            "expected_roles": sorted(expected_guard_roles),
            "actual_roles": guard_roles,
            "actual_pids": [event.get("pid") for event in loaded_events],
            "expected_interpreter": str(base_python),
            "expected_resolved_interpreter": str(base_python),
            "actual_interpreters": [event.get("executable") for event in loaded_events],
            "actual_resolved_interpreters": [
                event.get("executable_resolved") for event in loaded_events
            ],
            "reason_for_third": (
                "test_shadow_mode_blocks_before_any_external_client_is_constructed "
                "launches the declared local run.py --mode shadow child"
            ),
        },
        "network_attempts": network_attempts,
        "env_file_attempts": env_file_attempts,
        "unexpected_guard_events": unexpected_guard_events,
        "expected_failure_markers": expected_failure_markers,
        "expected_failure_policy": expected_failure_policy,
        "guard_events": guard_events,
        "guard_sha256": _sha256(guard_dir / "sitecustomize.py"),
        "environment_allowlist": sorted(environment),
    }


def _junit_summary(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {
            "exists": False,
            "testcases": None,
            "failures": None,
            "errors": None,
            "skipped": None,
            "expected_failure_nodes": None,
            "node_identities": None,
            "node_identities_match": False,
        }
    try:
        root = ElementTree.parse(path).getroot()
    except ElementTree.ParseError as exc:
        return {"exists": True, "parse_error": repr(exc), "testcases": None}

    def local_name(element: ElementTree.Element) -> str:
        return str(element.tag).rsplit("}", 1)[-1]

    nodes = list(root.iter())
    testcases = [node for node in nodes if local_name(node) == "testcase"]
    failures = [node for node in nodes if local_name(node) == "failure"]
    errors = [node for node in nodes if local_name(node) == "error"]
    skipped = [node for node in nodes if local_name(node) == "skipped"]
    expected_failure_nodes: list[dict[str, Any]] = []
    for node in nodes:
        name = local_name(node)
        values = " ".join(
            value for value in [name, *node.attrib.values(), node.text or ""] if value
        ).lower()
        if name in {"xfail", "xpass"} or (
            name in {"skipped", "failure", "error"}
            and ("pytest.xfail" in values or "xpass" in values)
        ):
            expected_failure_nodes.append(
                {"tag": name, "attributes": dict(node.attrib), "text": (node.text or "").strip()}
            )
    node_identities = tuple(
        (str(node.attrib.get("classname", "")), str(node.attrib.get("name", "")))
        for node in testcases
    )
    return {
        "exists": True,
        "testcases": len(testcases),
        "failures": len(failures),
        "errors": len(errors),
        "skipped": len(skipped),
        "expected_failure_nodes": expected_failure_nodes,
        "node_identities": [
            {"classname": classname, "name": name} for classname, name in node_identities
        ],
        "expected_node_identities": [
            {"classname": classname, "name": name}
            for classname, name in EXPECTED_TARGET_JUNIT_NODES
        ],
        "node_identities_match": node_identities == EXPECTED_TARGET_JUNIT_NODES,
    }


def _collection_nodeids(stdout: str, stderr: str) -> tuple[str, ...]:
    """Extract exactly the two target files' collected node IDs in pytest order."""

    prefixes = tuple(f"{path}::" for path in TARGET_TEST_FILES)
    return tuple(
        stripped
        for output in (stdout, stderr)
        for line in output.splitlines()
        if (stripped := line.strip()).startswith(prefixes)
    )


def _pytest_expected_failure_markers(*outputs: str) -> list[dict[str, str]]:
    """Surface pytest XFAIL/XPASS terminal semantics instead of accepting them silently."""

    marker = re.compile(r"(?i)(?:^|\s)(?:xfail(?:ed)?|xpass(?:ed)?)(?=\s|:|\[|$)")
    findings: list[dict[str, str]] = []
    for output_index, output in enumerate(outputs):
        for line_number, line in enumerate(output.splitlines(), start=1):
            if marker.search(line):
                findings.append(
                    {"output_index": str(output_index), "line": str(line_number), "text": line}
                )
    return findings


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        help="New, non-existing directory under logs/ for this immutable attempt.",
    )
    return parser.parse_args()


def main() -> int:
    process_network_attempts: list[dict[str, str]] = []
    process_env_file_attempts: list[dict[str, str | None]] = []

    def audit(event: str, audit_args: tuple[object, ...]) -> None:
        if event in SOCKET_AUDIT_EVENTS:
            process_network_attempts.append({"event": event, "arguments": repr(audit_args)})
            raise NetworkForbidden("ITER27_FQ3_NETWORK_FORBIDDEN")
        if event == "open" and _is_dotenv_open(audit_args):
            process_env_file_attempts.append(
                {
                    "event": "dotenv_file_open",
                    "path": _opened_path(audit_args),
                    "arguments": repr(audit_args),
                }
            )
            raise EnvFileForbidden("ITER27_FQ3_ENV_FILE_FORBIDDEN")

    # This covers all source hashing, import, observation, and target-suite
    # launch work below.  The module import that reaches ``main`` is the only
    # pre-hook boundary and does not open project input files.
    sys.addaudithook(audit)
    args = _parse_args()
    base_python = _require_anaconda_base_python()
    output = _output_dir(args.output_dir)
    _write_new_text(
        output / "attempt.lock",
        json.dumps(
            {
                "opened_at_utc": datetime.now(timezone.utc).isoformat(),
                "pid": os.getpid(),
                "non_reusable": True,
            },
            sort_keys=True,
        )
        + "\n",
    )

    source_before = _source_hashes()
    reference = {
        "path": str(ARCHIVED_REFERENCE.relative_to(ROOT)),
        "exists": ARCHIVED_REFERENCE.is_file(),
        "sha256": _sha256(ARCHIVED_REFERENCE) if ARCHIVED_REFERENCE.is_file() else None,
        "usage": "contract-name reference only; no archived executable or receipt is replayed",
    }
    manifest = {
        "schema_version": "backtrader.iter27.fq3-independent-attempt.v2",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "repository_root": str(ROOT),
        "output_dir": str(output),
        "python": {
            "required_executable": str(base_python),
            "required_resolved_executable": str(base_python),
            "executable": sys.executable,
            "resolved_executable": str(Path(sys.executable).resolve()),
            "version": sys.version,
            "prefix": sys.prefix,
            "exact_base_interpreter": True,
        },
        "source_before": source_before,
        "source_binding_policy": {
            "acceptance_runner": "scripts/run_iter27_fq3_independent_acceptance.py",
            "pytest_configuration": ["pytest.ini", "conftest.py", "pyproject.toml"],
            "sealed_binding_artifact": "source-bindings.json",
        },
        "git_head": _run_git("rev-parse", "HEAD"),
        "git_status": _run_git("status", "--short"),
        "archived_reference": reference,
        "expected_observations": list(EXPECTED_OBSERVATION_NAMES),
        "expected_observation_count": 66,
        "target_test_files": list(TARGET_TEST_FILES),
        "expected_target_testcases": EXPECTED_TARGET_TESTS,
        "expected_collection_nodeids": list(EXPECTED_TARGET_NODEIDS),
        "expected_junit_node_identities": [
            {"classname": classname, "name": name}
            for classname, name in EXPECTED_TARGET_JUNIT_NODES
        ],
        "network_policy": "socket connect/getaddrinfo/sendto are forbidden in harness and target suite; local bind is not outbound network I/O",
        "env_file_policy": {
            "forbidden_basename": DOTENV_BASENAME,
            "expected_direct_harness_attempts": 0,
            "expected_target_guard_attempts": 0,
            "direct_harness": (
                "an audit hook is installed before source hashes, imports, observations, and "
                "target-suite launch; matching open events are recorded then refused"
            ),
            "target_guard": (
                "sitecustomize is loaded before pytest and its declared local shadow child; "
                "matching open events are recorded then refused"
            ),
            "environment": "target subprocess receives a fixed non-secret environment allowlist",
        },
        "junit_policy": (
            "exact ordered collection and JUnit node identities, zero failures/errors/skips, "
            "and no XFAIL/XPASS terminal or JUnit semantics"
        ),
        "scope": "current local low-frequency synthetic timing evidence only; no CTP/SimNow/native/account/order/PnL claim",
    }
    _write_new_json(output / "manifest.json", manifest)

    imported_origins: dict[str, dict[str, str]] | None = None
    book = ObservationBook()
    harness_error: str | None = None
    target_suite: dict[str, Any] | None = None
    try:
        bt, runner, timing, strategy_class, imported_origins = _import_current_source()
        book = _run_observations(bt, runner, timing, strategy_class)
    except BaseException as exc:
        harness_error = repr(exc)
    try:
        target_suite = _run_target_suite(output)
    except BaseException as exc:
        target_suite = {"runner_exception": repr(exc), "traceback": traceback.format_exc()}

    source_after = _source_hashes()
    source_stable = source_before == source_after
    source_bindings = {
        "schema_version": "backtrader.iter27.fq3-source-bindings.v1",
        "acceptance_runner": "scripts/run_iter27_fq3_independent_acceptance.py",
        "pytest_configuration": ["pytest.ini", "conftest.py", "pyproject.toml"],
        "source_before": source_before,
        "source_after": source_after,
        "source_stable": source_stable,
    }
    _write_new_json(output / "source-bindings.json", source_bindings)
    shape_ok, shape_evidence = book.validate_shape()
    target_ok = bool(
        target_suite
        and target_suite.get("collection_returncode") == 0
        and target_suite.get("collected_testcases") == EXPECTED_TARGET_TESTS
        and target_suite.get("collection_nodeids_match") is True
        and target_suite.get("suite_returncode") == 0
        and target_suite.get("junit", {}).get("testcases") == EXPECTED_TARGET_TESTS
        and target_suite.get("junit", {}).get("node_identities_match") is True
        and target_suite.get("junit", {}).get("failures") == 0
        and target_suite.get("junit", {}).get("errors") == 0
        and target_suite.get("junit", {}).get("skipped") == 0
        and not target_suite.get("junit", {}).get("expected_failure_nodes")
        and target_suite.get("expected_failure_policy", {}).get("refused") is True
        and target_suite.get("guard_loaded") is True
        and not target_suite.get("network_attempts")
        and not target_suite.get("env_file_attempts")
        and not target_suite.get("unexpected_guard_events")
        and not target_suite.get("expected_failure_markers")
    )
    accepted = bool(
        harness_error is None
        and book.all_passed
        and shape_ok
        and target_ok
        and source_stable
        and not process_network_attempts
        and not process_env_file_attempts
    )
    _write_new_json(
        output / "harness-audit-events.json",
        {
            "network_attempts": process_network_attempts,
            "env_file_attempts": process_env_file_attempts,
        },
    )
    consolidated = {
        "accepted": accepted,
        "status": (
            "LOCAL_FQ3_INDEPENDENT_ACCEPTANCE_PASS"
            if accepted
            else "LOCAL_FQ3_INDEPENDENT_ACCEPTANCE_FAIL"
        ),
        "harness_error": harness_error,
        "source_after": source_after,
        "source_stable": source_stable,
        "source_bindings": source_bindings,
        "imported_current_source_origins": imported_origins,
        "process_network_attempts": process_network_attempts,
        "process_env_file_attempts": process_env_file_attempts,
        "observation_total": len(book.observations),
        "observation_pass": sum(item["status"] == "PASS" for item in book.observations),
        "observation_fail": sum(item["status"] != "PASS" for item in book.observations),
        "observation_shape": shape_evidence,
        "target_suite": target_suite,
        "target_suite_ok": target_ok,
        "unproven": [
            "CTP or SimNow connection/authentication/account observation",
            "actual exchange order submission/cancel/fill",
            "authoritative two-round flat reconciliation",
            "actual funding, fees, PnL, profitability, or live-trading admission",
        ],
    }
    _write_new_json(output / "observations.json", {"observations": book.observations})
    _write_new_json(output / "consolidated.json", consolidated)

    sealed_paths = (
        output / "attempt.lock",
        output / "manifest.json",
        output / "source-bindings.json",
        output / "observations.json",
        output / "target-collection.stdout.txt",
        output / "target-collection.stderr.txt",
        output / "target-suite.stdout.txt",
        output / "target-suite.stderr.txt",
        output / "target-suite.junit.xml",
        output / "pytest-network-events.jsonl",
        output / "harness-audit-events.json",
        output / "network_guard/sitecustomize.py",
        output / "consolidated.json",
    )
    seal = {
        "schema_version": "backtrader.iter27.acceptance-seal.v3",
        "sealed_at_utc": datetime.now(timezone.utc).isoformat(),
        "files": {
            str(path.relative_to(output)): _sha256(path) for path in sealed_paths if path.is_file()
        },
        "excludes": ["seal.json"],
        "no_self_hash": True,
    }
    _write_new_json(output / "seal.json", seal)
    print(
        json.dumps(
            {"accepted": accepted, "output_dir": str(output), "status": consolidated["status"]}
        )
    )
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
