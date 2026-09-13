#!/usr/bin/env python
"""Create a fresh, self-attested local receipt for Iteration 27 T8.

The runner deliberately stays inside one checkout and one Python process.  It
does not claim an independently trusted build, an OS-level network sandbox,
CTP/SimNow/native API evidence, a live fill, queue/latency evidence, or HFT
admission.  It binds the frozen contract/oracles/source observations, runs
separate synthetic golden probes, and then invokes the exact selected pytest
nodes under Python-level no-network/native guards.
"""

from __future__ import annotations

import argparse
import builtins
import contextlib
import copy
import hashlib
import importlib
import importlib.metadata
import importlib.util
import inspect
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Iterable, Mapping
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
LOG_ROOT = ROOT / "logs"
EXAMPLE = ROOT / "examples" / "015_ctp_options_highfreq"
FIXTURE_DIR = ROOT / "scripts" / "fixtures" / "iter27_hf_t1" / "v1"
FROZEN_INPUTS: dict[str, tuple[Path, str]] = {
    "contract": (
        FIXTURE_DIR / "contract.v1.json",
        "116ec5111dd7236284af5460656a6973833ef1b960d37d8426b2a3074cac4517",
    ),
    "timing_oracles": (
        FIXTURE_DIR / "timing-oracles.v1.json",
        "e4ee9e39f0917237037a34f9ca4d126c30f60e1610045e3e4a8b37dc16d61b04",
    ),
    "source_observations": (
        FIXTURE_DIR / "source-observations.v3.json",
        "3e4da00ef1122e037bfdf1e3e9483fba4c0b757c7fac6f7b40ff80a77ceab944",
    ),
    "assertion_map": (
        FIXTURE_DIR / "assertion-map.v1.json",
        "18b63640da4c5c97dec79bd2c7c621794a434365efb7a90ef33ff8f662f738e9",
    ),
    "fixture_provenance": (
        FIXTURE_DIR / "fixture-provenance.v1.json",
        "68181ecc0808ee460f59470a9b4b7073a584d5f593ae48532e70091be60eed4d",
    ),
}

OWNED_RECEIPT_INPUTS = (
    Path("scripts/run_iter27_hf_t1_independent_acceptance.py"),
    Path("scripts/fixtures/iter27_hf_t1/v1/contract.v1.json"),
    Path("scripts/fixtures/iter27_hf_t1/v1/timing-oracles.v1.json"),
    Path("scripts/fixtures/iter27_hf_t1/v1/source-observations.v3.json"),
    Path("scripts/fixtures/iter27_hf_t1/v1/assertion-map.v1.json"),
    Path("scripts/fixtures/iter27_hf_t1/v1/fixture-provenance.v1.json"),
    Path("scripts/fixtures/iter27_hf_t1/v1/README.md"),
)

# These are both the directly exercised example code and the framework modules
# that make its Cerebro/channel/TickBroker path meaningful.  Dynamic module
# hashes below add every local Python module actually imported by the harness.
STATIC_DEPENDENCIES = (
    Path("examples/015_ctp_options_highfreq/__init__.py"),
    Path("examples/015_ctp_options_highfreq/config.yaml"),
    Path("examples/015_ctp_options_highfreq/ctp_options_highfreq_strategy.py"),
    Path("examples/015_ctp_options_highfreq/execution_timing.py"),
    Path("examples/015_ctp_options_highfreq/fixtures/three_leg_tick_cohorts_v1.json"),
    Path("examples/015_ctp_options_highfreq/run.py"),
    Path("tests/unit/test_ctp_options_highfreq_example.py"),
    Path("conftest.py"),
    Path("pytest.ini"),
    Path("pyproject.toml"),
    Path("setup.py"),
    Path("backtrader/__init__.py"),
    Path("backtrader/version.py"),
    Path("backtrader/cerebro.py"),
    Path("backtrader/channel.py"),
    Path("backtrader/events.py"),
    Path("backtrader/feed.py"),
    Path("backtrader/strategy.py"),
    Path("backtrader/brokers/tickbroker.py"),
    Path("backtrader/feeds/ctpcohort.py"),
    Path("scripts/run_iter27_hf_t1_independent_acceptance.py"),
)

TEST_FILE = "tests/unit/test_ctp_options_highfreq_example.py"
STATUS_PASS_SEALED_CLEAN_COMMIT = "LOCAL_HIGHFREQ_TIMING_PROJECTION_SUBSET_PASS_SEALED_CLEAN_COMMIT"
STATUS_PASS_UNSEALED_SAME_TREE = "LOCAL_HIGHFREQ_TIMING_PROJECTION_SUBSET_PASS_UNSEALED_SAME_TREE"
STATUS_FAIL = "LOCAL_HIGHFREQ_TIMING_PROJECTION_SUBSET_FAIL"
TEST_NODE_IDS = (
    "tests/unit/test_ctp_options_highfreq_example.py::"
    "test_hf_t1_root02_root03_root04_ttl_boundaries_and_late_ack_cannot_extend_origin"
    "[-1-False-per_leg-1000000000-per_leg_expired-PER_LEG_TTL_EXCEEDED]",
    "tests/unit/test_ctp_options_highfreq_example.py::"
    "test_hf_t1_root02_root03_root04_ttl_boundaries_and_late_ack_cannot_extend_origin"
    "[-1-False-aggregate-3000000000-aggregate_expired-UNHEDGED_TTL_EXCEEDED]",
    "tests/unit/test_ctp_options_highfreq_example.py::"
    "test_hf_t1_root02_root03_root04_ttl_boundaries_and_late_ack_cannot_extend_origin"
    "[-1-False-hold-60000000000-hold_expired-HOLDING_TTL_EXCEEDED]",
    "tests/unit/test_ctp_options_highfreq_example.py::"
    "test_hf_t1_root02_root03_root04_ttl_boundaries_and_late_ack_cannot_extend_origin"
    "[0-True-per_leg-1000000000-per_leg_expired-PER_LEG_TTL_EXCEEDED]",
    "tests/unit/test_ctp_options_highfreq_example.py::"
    "test_hf_t1_root02_root03_root04_ttl_boundaries_and_late_ack_cannot_extend_origin"
    "[0-True-aggregate-3000000000-aggregate_expired-UNHEDGED_TTL_EXCEEDED]",
    "tests/unit/test_ctp_options_highfreq_example.py::"
    "test_hf_t1_root02_root03_root04_ttl_boundaries_and_late_ack_cannot_extend_origin"
    "[0-True-hold-60000000000-hold_expired-HOLDING_TTL_EXCEEDED]",
    "tests/unit/test_ctp_options_highfreq_example.py::"
    "test_hf_t1_root02_root03_root04_ttl_boundaries_and_late_ack_cannot_extend_origin"
    "[1-True-per_leg-1000000000-per_leg_expired-PER_LEG_TTL_EXCEEDED]",
    "tests/unit/test_ctp_options_highfreq_example.py::"
    "test_hf_t1_root02_root03_root04_ttl_boundaries_and_late_ack_cannot_extend_origin"
    "[1-True-aggregate-3000000000-aggregate_expired-UNHEDGED_TTL_EXCEEDED]",
    "tests/unit/test_ctp_options_highfreq_example.py::"
    "test_hf_t1_root02_root03_root04_ttl_boundaries_and_late_ack_cannot_extend_origin"
    "[1-True-hold-60000000000-hold_expired-HOLDING_TTL_EXCEEDED]",
    "tests/unit/test_ctp_options_highfreq_example.py::"
    "test_hf_t1_root01_actual_cerebro_no_bar_idle_uses_explicit_synthetic_provider_only",
    "tests/unit/test_ctp_options_highfreq_example.py::"
    "test_hf_t1_root01_tick_only_normal_exit_is_a_zero_write_proposal",
    "tests/unit/test_ctp_options_highfreq_example.py::"
    "test_hf_t1_root02_leg_origin_freezes_proved_send_or_earlier_durable_intent",
    "tests/unit/test_ctp_options_highfreq_example.py::"
    "test_hf_t1_root03_root04_earliest_exposure_controls_basket_and_hold_deadlines",
    "tests/unit/test_ctp_options_highfreq_example.py::"
    "test_hf_t1_root05_root06_clock_faults_and_foreign_facts_latch_closed_but_keep_risk",
    "tests/unit/test_ctp_options_highfreq_example.py::"
    "test_hf_t1_root06_foreign_exposure_latches_protection_over_valid_confirmations",
    "tests/unit/test_ctp_options_highfreq_example.py::"
    "test_hf_t1_root06_quarantine_bypasses_still_latch_untrusted_exposure"
    "[duplicate_fact_id]",
    "tests/unit/test_ctp_options_highfreq_example.py::"
    "test_hf_t1_root06_quarantine_bypasses_still_latch_untrusted_exposure"
    "[conflicting_trade_id]",
    "tests/unit/test_ctp_options_highfreq_example.py::"
    "test_hf_t1_root07_idle_cadence_boundaries_are_explicit_and_local[49999999-False]",
    "tests/unit/test_ctp_options_highfreq_example.py::"
    "test_hf_t1_root07_idle_cadence_boundaries_are_explicit_and_local[50000000-False]",
    "tests/unit/test_ctp_options_highfreq_example.py::"
    "test_hf_t1_root07_idle_cadence_boundaries_are_explicit_and_local[50000001-True]",
    "tests/unit/test_ctp_options_highfreq_example.py::"
    "test_hf_t1_root07_parallel_synthetic_query_cannot_block_the_idle_consumer",
    "tests/unit/test_ctp_options_highfreq_example.py::"
    "test_hf_t1_root08_only_confirmed_volume_advances_the_protected_path",
    "tests/unit/test_ctp_options_highfreq_example.py::"
    "test_hf_t1_root09_cancel_and_duplicate_trade_conflict_remain_unresolved",
    "tests/unit/test_ctp_options_highfreq_example.py::"
    "test_hf_t1_root10_cohort_rechecks_and_fresh_quotes_never_extend_execution_deadlines",
    "tests/unit/test_ctp_options_highfreq_example.py::"
    "test_hf_t1_root11_calendar_is_explicit_and_unpriced_risk_stays_unresolved"
    "[1800-STOP_ENTRY-False]",
    "tests/unit/test_ctp_options_highfreq_example.py::"
    "test_hf_t1_root11_calendar_is_explicit_and_unpriced_risk_stays_unresolved"
    "[600-RISK_EXIT-True]",
    "tests/unit/test_ctp_options_highfreq_example.py::"
    "test_hf_t1_root11_calendar_is_explicit_and_unpriced_risk_stays_unresolved"
    "[180-HANDOVER_IF_PENDING-True]",
    "tests/unit/test_ctp_options_highfreq_example.py::"
    "test_hf_t1_root12_stop_keeps_original_pending_audit_and_unresolved_exposure",
    "tests/unit/test_ctp_options_highfreq_example.py::"
    "test_hf_t1_source_observations_keep_replay_offline_and_free_of_native_io",
)
EXPECTED_TESTCASE_COUNT = len(TEST_NODE_IDS)
EXPECTED_JUNIT_NAMES = tuple(node.rsplit("::", 1)[1] for node in TEST_NODE_IDS)

ROOT_TEST_COVERAGE = {
    "ROOT-HFT1-01": tuple(node for node in TEST_NODE_IDS if "root01_" in node),
    "ROOT-HFT1-02": tuple(
        node for node in TEST_NODE_IDS if "root02_" in node or "root02_root03_root04" in node
    ),
    "ROOT-HFT1-03": tuple(
        node for node in TEST_NODE_IDS if "root03_" in node or "root02_root03_root04" in node
    ),
    "ROOT-HFT1-04": tuple(
        node for node in TEST_NODE_IDS if "root04_" in node or "root02_root03_root04" in node
    ),
    "ROOT-HFT1-05": tuple(node for node in TEST_NODE_IDS if "root05_" in node),
    "ROOT-HFT1-06": tuple(
        node for node in TEST_NODE_IDS if "root06_" in node or "root05_root06" in node
    ),
    "ROOT-HFT1-07": tuple(node for node in TEST_NODE_IDS if "root07_" in node),
    "ROOT-HFT1-08": tuple(node for node in TEST_NODE_IDS if "root08_" in node),
    "ROOT-HFT1-09": tuple(node for node in TEST_NODE_IDS if "root09_" in node),
    "ROOT-HFT1-10": tuple(node for node in TEST_NODE_IDS if "root10_" in node),
    "ROOT-HFT1-11": tuple(node for node in TEST_NODE_IDS if "root11_" in node),
    "ROOT-HFT1-12": tuple(node for node in TEST_NODE_IDS if "root12_" in node),
}
SOURCE_TEST_NODE = (
    "tests/unit/test_ctp_options_highfreq_example.py::"
    "test_hf_t1_source_observations_keep_replay_offline_and_free_of_native_io"
)

# Each map entry names exact nodes from TEST_NODE_IDS.  The map is deliberately
# narrow: a successful arbitrary test file cannot satisfy a field assertion.
JUNIT_ASSERTION_NODES: dict[str, tuple[str, ...]] = {
    "JUNIT_ROOT01_ACTIVE_ENGINE_IDLE": (
        "tests/unit/test_ctp_options_highfreq_example.py::"
        "test_hf_t1_root01_actual_cerebro_no_bar_idle_uses_explicit_synthetic_provider_only",
    ),
    "JUNIT_ROOT01_TICK_ONLY_EXIT": (
        "tests/unit/test_ctp_options_highfreq_example.py::"
        "test_hf_t1_root01_tick_only_normal_exit_is_a_zero_write_proposal",
    ),
    "JUNIT_ROOT02_PROVED_NATIVE_SEND": (
        "tests/unit/test_ctp_options_highfreq_example.py::"
        "test_hf_t1_root02_leg_origin_freezes_proved_send_or_earlier_durable_intent",
    ),
    "JUNIT_ROOT03_EARLIEST_EXPOSURE": (
        "tests/unit/test_ctp_options_highfreq_example.py::"
        "test_hf_t1_root03_root04_earliest_exposure_controls_basket_and_hold_deadlines",
    ),
    "JUNIT_ROOT04_IDLE_TRIGGER": (
        "tests/unit/test_ctp_options_highfreq_example.py::"
        "test_hf_t1_root03_root04_earliest_exposure_controls_basket_and_hold_deadlines",
    ),
    "JUNIT_ROOT06_FAULT_MATRIX": tuple(
        node for node in TEST_NODE_IDS if "root05_root06" in node or "root06_" in node
    ),
    "JUNIT_ROOT07_ACTIVE_ENGINE_CADENCE": tuple(
        node for node in TEST_NODE_IDS if "root07_" in node
    ),
    "JUNIT_ROOT08_PRODUCTION_LOT": (
        "tests/unit/test_ctp_options_highfreq_example.py::"
        "test_hf_t1_root08_only_confirmed_volume_advances_the_protected_path",
    ),
    "JUNIT_ROOT09_IDENTITY_AND_DETAIL": (
        "tests/unit/test_ctp_options_highfreq_example.py::"
        "test_hf_t1_root09_cancel_and_duplicate_trade_conflict_remain_unresolved",
    ),
    "JUNIT_ROOT10_RECHECK": (
        "tests/unit/test_ctp_options_highfreq_example.py::"
        "test_hf_t1_root10_cohort_rechecks_and_fresh_quotes_never_extend_execution_deadlines",
    ),
    "JUNIT_ROOT12_AUDIT_RETENTION": (
        "tests/unit/test_ctp_options_highfreq_example.py::"
        "test_hf_t1_root12_stop_keeps_original_pending_audit_and_unresolved_exposure",
    ),
    "JUNIT_SOURCE_BOUNDARY": (SOURCE_TEST_NODE,),
}
NATIVE_API_TOKENS = (
    "CreateFtdc",
    "RegisterFront(",
    "ReqUserLogin(",
    "ReqOrderInsert(",
    "ReqOrderAction(",
    "ReqQryTradingAccount(",
    "ReqQryInvestorPosition(",
    "ReqQryOrder(",
    "ReqQryTrade(",
)
BLOCKED_IMPORT_ROOTS = frozenset(
    {"bt_api", "bt_api_ctp", "ctp", "ctpbee", "pyctp", "vnpy", "openctp"}
)


class NetworkAttemptError(RuntimeError):
    """Raised when a Python-visible non-loopback network operation is attempted."""


class NativeAPIAttemptError(RuntimeError):
    """Raised when this local runner observes a blocked native API import/use."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_dump(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def _assert(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def _receipt_status(*, accepted: bool, sealed_build_claim: bool) -> str:
    """Select the receipt label from the same acceptance/sealing facts it reports."""

    if not accepted:
        return STATUS_FAIL
    if sealed_build_claim:
        return STATUS_PASS_SEALED_CLEAN_COMMIT
    return STATUS_PASS_UNSEALED_SAME_TREE


def _status_label_contract() -> dict[str, Any]:
    """Exercise every status branch so a sealed claim cannot retain an unsealed label."""

    cases = {
        "failed": {
            "actual": _receipt_status(accepted=False, sealed_build_claim=False),
            "expected": STATUS_FAIL,
        },
        "unsealed_same_tree": {
            "actual": _receipt_status(accepted=True, sealed_build_claim=False),
            "expected": STATUS_PASS_UNSEALED_SAME_TREE,
        },
        "sealed_clean_commit": {
            "actual": _receipt_status(accepted=True, sealed_build_claim=True),
            "expected": STATUS_PASS_SEALED_CLEAN_COMMIT,
        },
    }
    return {
        "cases": cases,
        "passed": all(case["actual"] == case["expected"] for case in cases.values()),
    }


def _output_path(raw: str) -> Path:
    output = Path(raw)
    if not output.is_absolute():
        output = ROOT / output
    output = output.resolve()
    try:
        output.relative_to(LOG_ROOT.resolve())
    except ValueError as exc:
        raise ValueError("--output-dir must be inside the repository logs/ directory") from exc
    if output.exists():
        raise FileExistsError(f"refusing to reuse acceptance output directory: {output}")
    output.mkdir(parents=True)
    return output


def _git_read(args: Iterable[str]) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git read failed ({' '.join(args)}): {completed.stderr.strip()}")
    return completed.stdout


def _git_state() -> dict[str, Any]:
    status = _git_read(("status", "--porcelain=v1", "--untracked-files=all"))
    index = _git_read(("ls-files", "--stage", "--", *(str(path) for path in OWNED_RECEIPT_INPUTS)))
    at_head = _git_read(
        (
            "ls-tree",
            "-r",
            "--name-only",
            "HEAD",
            "--",
            *(str(path) for path in OWNED_RECEIPT_INPUTS),
        )
    )
    index_paths = sorted({line.rsplit("\t", 1)[-1] for line in index.splitlines() if "\t" in line})
    head_paths = sorted(line for line in at_head.splitlines() if line)
    return {
        "head": _git_read(("rev-parse", "HEAD")).strip(),
        "status_porcelain_v1": status.splitlines(),
        "status_sha256": hashlib.sha256(status.encode("utf-8")).hexdigest(),
        "worktree_clean": not bool(status.strip()),
        "owned_inputs_expected": [str(path) for path in OWNED_RECEIPT_INPUTS],
        "owned_inputs_index_tracked": index_paths,
        "owned_inputs_committed_at_head": head_paths,
        "all_owned_inputs_index_tracked": set(index_paths)
        == {str(path) for path in OWNED_RECEIPT_INPUTS},
        "all_owned_inputs_committed_at_head": set(head_paths)
        == {str(path) for path in OWNED_RECEIPT_INPUTS},
    }


def _copy_frozen_inputs_to_receipt(output: Path) -> dict[str, str]:
    destination = output / "frozen-inputs"
    destination.mkdir()
    copied: dict[str, str] = {}
    for name, (source, expected_digest) in FROZEN_INPUTS.items():
        target = destination / source.name
        shutil.copyfile(source, target)
        actual_digest = _sha256(target)
        _assert(actual_digest == expected_digest, f"receipt copy hash mismatch for {name}")
        copied[_relative(target)] = actual_digest
    return dict(sorted(copied.items()))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        required=True,
        help="New directory under logs/ for this immutable local attempt.",
    )
    return parser.parse_args()


def _hash_paths(paths: Iterable[Path]) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in paths:
        resolved = path.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"required dependency is absent: {resolved}")
        result[_relative(resolved)] = _sha256(resolved)
    return dict(sorted(result.items()))


def _loaded_local_module_hashes() -> dict[str, str]:
    """Bind every local Python source module already imported by this process."""

    files: set[Path] = set()
    root_resolved = ROOT.resolve()
    for module in tuple(sys.modules.values()):
        if not isinstance(module, ModuleType):
            continue
        raw_path = getattr(module, "__file__", None)
        if not raw_path:
            continue
        path = Path(raw_path).resolve()
        try:
            path.relative_to(root_resolved)
        except ValueError:
            continue
        if path.suffix in {".py", ".pyi"} and path.is_file():
            files.add(path)
    return _hash_paths(sorted(files))


def _load_frozen_inputs() -> tuple[dict[str, Any], dict[str, str]]:
    payloads: dict[str, Any] = {}
    hashes: dict[str, str] = {}
    for name, (path, expected_hash) in FROZEN_INPUTS.items():
        actual_hash = _sha256(path)
        _assert(
            actual_hash == expected_hash,
            f"frozen {name} hash mismatch: expected {expected_hash}, got {actual_hash}",
        )
        payloads[name] = json.loads(path.read_text(encoding="utf-8"))
        hashes[_relative(path)] = actual_hash

    contract = payloads["contract"]
    oracle_cases = payloads["timing_oracles"]["cases"]
    source_observations = payloads["source_observations"]["observations"]
    root_ids = tuple(f"ROOT-HFT1-{number:02d}" for number in range(1, 13))
    source_ids = tuple(f"HF-SOURCE-{number:02d}" for number in range(1, 7))
    _assert(
        contract["oracle_registration"]["groups"] == 12,
        "frozen contract must register all 12 root oracle groups",
    )
    _assert(
        contract["maximum_acceptance"] == "LOCAL_HIGHFREQ_TIMING_PROJECTION_SUBSET_PASS",
        "frozen contract maximum acceptance changed",
    )
    _assert(
        tuple(case["id"] for case in oracle_cases) == root_ids,
        "frozen timing oracle IDs are incomplete or reordered",
    )
    _assert(
        tuple(item["id"] for item in source_observations) == source_ids,
        "frozen source observation IDs are incomplete or reordered",
    )
    _assert(
        len(contract["acceptance"]) >= 6
        and any("native account APIs/external net" in text for text in contract["acceptance"]),
        "frozen contract acceptance boundary is absent",
    )
    assertion_map = payloads["assertion_map"]
    _assert(
        tuple(assertion_map["root_groups"]) == root_ids,
        "frozen field-to-assertion map must cover exactly the 12 root groups",
    )
    _assert(
        tuple(assertion_map["source_groups"]) == source_ids,
        "frozen field-to-assertion map must cover exactly the six source groups",
    )
    for case in oracle_cases:
        mapped = assertion_map["root_groups"][case["id"]]
        _assert(
            set(mapped["inputs"]) == set(case["inputs"])
            and set(mapped["expected"]) == set(case["expected"]),
            f"field map is incomplete for {case['id']}",
        )
        _assert(
            all(mapped["inputs"].values()) and all(mapped["expected"].values()),
            f"field map has an empty assertion reference for {case['id']}",
        )
    for observation in source_observations:
        mapped = assertion_map["source_groups"][observation["id"]]
        _assert(
            set(mapped["fields"]) == {"file", "line", "fact", "implication"}
            and all(mapped["fields"].values()),
            f"source field map is incomplete for {observation['id']}",
        )
    provenance = payloads["fixture_provenance"]
    provenance_hashes = {
        item["tracked_path"]: item["tracked_sha256"] for item in provenance["copies"]
    }
    for name in ("contract", "timing_oracles", "source_observations"):
        path, digest = FROZEN_INPUTS[name]
        _assert(
            provenance_hashes.get(path.name) == digest,
            f"fixture provenance does not pin {path.name}",
        )
    _assert(
        "historical provenance" in provenance["historical_source_line_policy"],
        "frozen source-line policy is not explicit",
    )
    return payloads, dict(sorted(hashes.items()))


class _LocalGuard:
    """Python-level audit and socket/import guard; explicitly not an OS sandbox."""

    def __init__(self) -> None:
        self.external_network_attempts: list[dict[str, str]] = []
        self.loopback_network_events: list[dict[str, str]] = []
        self.native_api_attempts: list[dict[str, str]] = []
        self.process_attempts: list[dict[str, str]] = []
        self.runtime_loader_events: list[dict[str, str]] = []
        self.bootstrap_process_events: list[dict[str, str]] = []
        self.guarded_local_read_events: list[dict[str, Any]] = []
        self._process_enforced = False
        self._allow_postflight_git_reads = False
        self.postflight_git_read_events: list[dict[str, Any]] = []
        self._old_import: Callable[..., Any] | None = None
        self._old_socket_functions: dict[str, Callable[..., Any]] = {}

    @staticmethod
    def _destination(value: object) -> tuple[str, bool]:
        candidate = value
        if isinstance(candidate, tuple) and candidate:
            candidate = candidate[0]
        if isinstance(candidate, bytes):
            candidate = candidate.decode("ascii", errors="replace")
        if not isinstance(candidate, str):
            return ("unknown", False)
        text = candidate.strip().lower()
        loopback = text in {"localhost", "127.0.0.1", "::1"} or text.startswith("127.")
        return (text[:200], loopback)

    def _network_event(self, event: str, destination: object) -> None:
        target, loopback = self._destination(destination)
        record = {"event": event, "destination": target}
        if loopback:
            self.loopback_network_events.append(record)
            return
        self.external_network_attempts.append(record)
        raise NetworkAttemptError(f"ITER27_HF_T1_EXTERNAL_NETWORK_FORBIDDEN:{event}:{target}")

    def _audit(self, event: str, audit_args: tuple[object, ...]) -> None:
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto", "socket.bind"}:
            if event == "socket.getaddrinfo":
                destination = audit_args[0] if audit_args else None
            else:
                destination = audit_args[-1] if audit_args else None
            self._network_event(event, destination)
        elif event == "ctypes.dlopen":
            library = audit_args[0] if audit_args else None
            # NumPy's normal import path opens the already-running Python
            # process with PyDLL(None).  It is not an external library or a
            # CTP API.  Any named ctypes library is blocked, which is the
            # strongest compatible local guard without rejecting the standard
            # scientific dependency stack used by Backtrader.
            if library in (None, ""):
                self.runtime_loader_events.append({"event": event, "library": "python-process"})
                return
            self.process_attempts.append({"event": event, "library": str(library)[:200]})
            raise NativeAPIAttemptError(f"ITER27_HF_T1_NAMED_CTYPES_LOAD_FORBIDDEN:{library}")
        elif event in {"subprocess.Popen", "os.system", "os.posix_spawn"}:
            record = {"event": event}
            if not self._process_enforced:
                # Importing the pinned local scientific stack can query a
                # CPU capability through a local child process.  Network and
                # native CTP guards are already active; record this bounded
                # bootstrap exception, then enforce a no-child-process policy
                # before any oracle or pytest code is executed.
                self.bootstrap_process_events.append(record)
                return
            if self._allow_postflight_git_reads and self._is_allowed_postflight_git_read(
                event, audit_args
            ):
                self.postflight_git_read_events.append(record)
                return
            self.process_attempts.append(record)
            raise NativeAPIAttemptError(f"ITER27_HF_T1_PROCESS_OR_NATIVE_LOAD_FORBIDDEN:{event}")

    def enforce_no_child_processes(self) -> None:
        self._process_enforced = True

    def allow_postflight_git_reads(self) -> None:
        """Allow only receipt-state Git reads after guarded test execution."""

        self._allow_postflight_git_reads = True

    @staticmethod
    def _is_allowed_postflight_git_read(event: str, audit_args: tuple[object, ...]) -> bool:
        if event != "subprocess.Popen" or len(audit_args) < 2:
            return False
        executable, argv = audit_args[0], audit_args[1]
        executable_name = Path(str(executable)).name
        if executable_name != "git" or not isinstance(argv, (list, tuple)):
            return False
        tokens = [str(item) for item in argv]
        return len(tokens) >= 2 and tokens[1] in {"status", "rev-parse", "ls-files", "ls-tree"}

    def record_guarded_local_read(self, **event: Any) -> None:
        """Record the fixture-only concurrent read used by ROOT-HFT1-07."""

        self.guarded_local_read_events.append(dict(event))

    def install(self) -> None:
        # An audit hook cannot be removed; this dedicated one-shot Python
        # process exits after the receipt is sealed.
        sys.addaudithook(self._audit)
        self._old_import = builtins.__import__

        def guarded_import(name: str, *args: object, **kwargs: object) -> Any:
            root_name = name.split(".", 1)[0].lower()
            if root_name in BLOCKED_IMPORT_ROOTS:
                self.native_api_attempts.append({"event": "import", "module": root_name})
                raise NativeAPIAttemptError(f"ITER27_HF_T1_NATIVE_IMPORT_FORBIDDEN:{root_name}")
            assert self._old_import is not None
            return self._old_import(name, *args, **kwargs)

        builtins.__import__ = guarded_import

        for name in ("create_connection", "getaddrinfo", "gethostbyname", "gethostbyname_ex"):
            original = getattr(socket, name)
            self._old_socket_functions[name] = original

            def guarded(
                *args: object,
                _name: str = name,
                _original: Callable[..., Any] = original,
                **kwargs: object,
            ) -> Any:
                destination = args[0] if args else kwargs.get("host")
                self._network_event(f"socket.{_name}", destination)
                return _original(*args, **kwargs)

            setattr(socket, name, guarded)

    def restore(self) -> None:
        if self._old_import is not None:
            builtins.__import__ = self._old_import
        for name, original in self._old_socket_functions.items():
            setattr(socket, name, original)


def _load_example_modules() -> tuple[ModuleType, ModuleType, ModuleType, ModuleType]:
    """Load the numeric example directory through a private package name."""

    package = "iter27_hf_t1_independent_harness_example"
    if package not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            package,
            EXAMPLE / "__init__.py",
            submodule_search_locations=[str(EXAMPLE)],
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("cannot load the Iteration 25 example package")
        module = importlib.util.module_from_spec(spec)
        sys.modules[package] = module
        spec.loader.exec_module(module)
    runner = importlib.import_module(f"{package}.run")
    strategy = importlib.import_module(f"{package}.ctp_options_highfreq_strategy")
    timing = importlib.import_module(f"{package}.execution_timing")
    backtrader = importlib.import_module("backtrader")
    return runner, strategy, timing, backtrader


def _scope(timing: ModuleType, **overrides: object) -> Any:
    values: dict[str, object] = {
        "provider_id": "iter27-hf-t1-local-provider",
        "source_id": "iter27-hf-t1-local-source",
        "environment": "local-fixture",
        "account_fingerprint": "iter27-local-synthetic-account",
        "trading_day": "20260911",
        "connection_generation": 7,
        "subscription_epoch": 3,
        "rules_hash": "iter27-hf-t1-local-rules-v1",
        "candidate_id": "iter25-options-replay-v1",
        "clock_domain_id": "iter27-hf-t1-local-domain",
        "boot_id": "iter27-hf-t1-local-boot",
        "calendar_source": "iter27-hf-t1-local-calendar",
        "synthetic": True,
    }
    values.update(overrides)
    return timing.TimingScope(**values)


def _context(
    timing: ModuleType, *, lots_per_leg: int = 1, scope_value: Any = None
) -> tuple[Any, dict[str, Any], Any]:
    scope_value = _scope(timing) if scope_value is None else scope_value
    associations = {
        leg: timing.OrderAssociation(
            intent_id="intent-1",
            decision_id="decision-1",
            basket_id="basket-1",
            cycle_id="cycle-1",
            leg_id=leg,
            order_id=f"order-{leg}",
            aliases=(("bt_ref", f"bt-{leg}"), ("order_ref", f"native-{leg}")),
        )
        for leg in ("FG701", "FG701C970", "FG701P970")
    }
    projector = timing.TimingProjector(
        scope=scope_value,
        associations=tuple(associations.values()),
        leg_ids=tuple(associations),
        lots_per_leg=lots_per_leg,
    )
    return scope_value, associations, projector


def _fact(
    timing: ModuleType,
    scope_value: Any,
    association: Any,
    *,
    fact_id: str,
    fact_type: str,
    origin_lower_ns: int,
    **overrides: object,
) -> Any:
    confirmation = fact_type in {"confirmed", "fill"}
    values: dict[str, object] = {
        "fact_id": fact_id,
        "fact_type": fact_type,
        "intent_id": association.intent_id,
        "provider_id": scope_value.provider_id,
        "source_id": scope_value.source_id,
        "scope_id": scope_value.scope_id,
        "clock_domain_id": scope_value.clock_domain_id,
        "order_id": association.order_id,
        "leg_id": association.leg_id,
        "origin_lower_ns": origin_lower_ns,
        "scope": scope_value,
        "decision_id": association.decision_id,
        "basket_id": association.basket_id,
        "cycle_id": association.cycle_id,
        "exchange_id": "CZCE" if confirmation else "",
        "trade_id": f"trade-{fact_id}" if confirmation else "",
        "direction": "buy",
        "offset": "open",
        "quantity": 1 if confirmation else None,
        "cumulative_quantity": None,
        "origin_upper_ns": origin_lower_ns,
        "received_ns": origin_lower_ns,
        "order_aliases": association.aliases,
        "synthetic": True,
    }
    values.update(overrides)
    return timing.TimingFact(**values)


def _snapshot(
    timing: ModuleType,
    scope_value: Any,
    facts: Iterable[Any],
    now_upper_ns: int,
    *,
    legal_executable_quote: bool = False,
    calendar_seconds_until_close: int | None = 3_601,
    stop_requested: bool = False,
    wall_utc: str = "2026-09-11T01:00:00+00:00",
) -> Any:
    clock = timing.TimingClock(
        scope=scope_value,
        source_id=scope_value.source_id,
        now_lower_ns=now_upper_ns,
        now_upper_ns=now_upper_ns,
        wall_utc=wall_utc,
        anchor_wall_utc="2026-09-11T00:00:00+00:00",
        anchor_monotonic_ns=0,
        error_bound_ns=0,
        valid_until_ns=max(now_upper_ns, 1_000_000_000_000),
        trusted=True,
        synthetic=True,
    )
    return timing.TimingSnapshot(
        scope=scope_value,
        clock=clock,
        facts=tuple(facts),
        legal_executable_quote=legal_executable_quote,
        calendar_seconds_until_close=calendar_seconds_until_close,
        stop_requested=stop_requested,
    )


def _effective_config(runner: ModuleType) -> dict[str, Any]:
    raw, _ = runner.load_config(EXAMPLE / "config.yaml")
    return runner.effective_config(raw, mode="replay", purpose="formula")


def _cohort_gate_result(
    runner: ModuleType,
    backtrader: ModuleType,
    *,
    receive_offsets_ns: tuple[int, int, int],
    now_offset_ns: int,
) -> Any:
    """Run one actual public cohort-validator boundary with fixture identities."""

    config = _effective_config(runner)
    fixture, _, _ = runner.load_fixture(config)
    bundle = runner.validate_bundle(fixture, config)
    feed = config["feed"]
    expected_legs = tuple(
        backtrader.feeds.CtpCohortLeg(
            symbol=str(bundle[role]["symbol"]),
            exchange=str(bundle[role]["exchange_id"]),
            price_tick=float(bundle[role]["tick_size"]),
            asset_type="future" if role == "future" else "option",
        )
        for role in ("future", "call", "put")
    )
    validator = backtrader.feeds.CtpQuoteCohortValidator(
        expected_legs=expected_legs,
        expected_rules_hash=runner.canonical_sha256(bundle),
        policy=backtrader.feeds.CtpCohortPolicy(
            max_receive_age_ms=float(feed["max_quote_age_ms"]),
            max_receive_skew_ms=float(feed["max_cross_leg_skew_ms"]),
            max_source_age_ms=float(feed["max_source_age_upper_ms"]),
            max_source_skew_ms=float(feed["max_source_skew_upper_ms"]),
            max_source_clock_error_ms=float(feed["max_source_clock_error_ms"]),
            max_receive_clock_error_ms=float(feed["max_source_clock_error_ms"]),
        ),
    )
    base_epoch = float(fixture["start_epoch"])
    base_monotonic = 1_000_000_000_000_000
    now = backtrader.feeds.CtpCohortNow(
        now_monotonic_ns=base_monotonic + now_offset_ns,
        now_epoch=base_epoch + now_offset_ns / 1_000_000_000.0,
        clock_domain_id="iter25-fixture-monotonic-v1",
        receive_clock_error_ms=0.0,
    )
    result = None
    for sequence, (role, offset) in enumerate(
        zip(("future", "call", "put"), receive_offsets_ns), start=1
    ):
        receive_epoch = base_epoch + offset / 1_000_000_000.0
        tick = runner._make_tick(
            role=role,
            bundle=bundle,
            quote=fixture["base_quotes"][role],
            source_epoch=base_epoch,
            receive_epoch=receive_epoch,
            receive_monotonic_ns=base_monotonic + offset,
            sequence=sequence,
            rules_hash=runner.canonical_sha256(bundle),
            trading_day=str(fixture["trading_day"]),
            source=str(fixture["source"]),
        )
        result = validator.ingest(tick, now=now)
    assert result is not None
    return result


def _direct_result(actual: Mapping[str, Any], *assertion_ids: str) -> dict[str, Any]:
    """Return observations together with assertions reached after real checks.

    Callers only construct this result after their concrete ``_assert`` calls;
    the receipt evaluator rejects missing IDs rather than inferring success
    from an enclosing group status.
    """

    _assert(bool(assertion_ids), "direct probe must name its reached assertions")
    return {
        "actual": dict(actual),
        "direct_assertions": {
            assertion_id: {"passed": True, "kind": "direct"} for assertion_id in assertion_ids
        },
    }


def _probe_root02(case: Mapping[str, Any], timing: ModuleType) -> dict[str, Any]:
    inputs = case["inputs"]
    expected = case["expected"]
    durable = inputs["intent_lower_ns"]
    send = inputs["proven_same_domain_native_send_lower_ns"]
    scope_value, associations, projector = _context(timing)
    association = associations["FG701"]
    proved = projector.project(
        _snapshot(
            timing,
            scope_value,
            (
                _fact(
                    timing,
                    scope_value,
                    association,
                    fact_id="intent",
                    fact_type="durable_intent",
                    origin_lower_ns=durable,
                ),
                _fact(
                    timing,
                    scope_value,
                    association,
                    fact_id="send",
                    fact_type="send",
                    origin_lower_ns=send,
                ),
            ),
            send,
        ),
        callback="tick",
    )
    _assert(
        proved.origin_lower_ns + inputs["leg_timeout_ns"]
        == expected["deadline_with_proven_send_ns"],
        "ROOT-HFT1-02 proved-send deadline differs from frozen oracle",
    )
    scope_value, associations, projector = _context(timing)
    association = associations["FG701"]
    first = projector.project(
        _snapshot(
            timing,
            scope_value,
            (
                _fact(
                    timing,
                    scope_value,
                    association,
                    fact_id="intent",
                    fact_type="durable_intent",
                    origin_lower_ns=durable,
                ),
            ),
            durable,
        ),
        callback="tick",
    )
    late = projector.project(
        _snapshot(
            timing,
            scope_value,
            (
                _fact(
                    timing,
                    scope_value,
                    association,
                    fact_id="intent",
                    fact_type="durable_intent",
                    origin_lower_ns=durable,
                ),
                _fact(
                    timing,
                    scope_value,
                    association,
                    fact_id="late-send",
                    fact_type="send",
                    origin_lower_ns=send,
                ),
            ),
            send,
        ),
        callback="idle",
    )
    _assert(
        first.origin_lower_ns == late.origin_lower_ns == durable, "late proof extended ROOT-HFT1-02"
    )
    _assert(
        late.origin_lower_ns + inputs["leg_timeout_ns"]
        == expected["deadline_if_send_unavailable_ns"],
        "ROOT-HFT1-02 durable-intent deadline differs from frozen oracle",
    )
    return _direct_result(
        {
            "proved_origin_ns": proved.origin_lower_ns,
            "late_origin_ns": late.origin_lower_ns,
            "proved_deadline_ns": proved.origin_lower_ns + inputs["leg_timeout_ns"],
            "late_deadline_ns": late.origin_lower_ns + inputs["leg_timeout_ns"],
        },
        "DIRECT_ROOT02_PROVED_SEND_DEADLINE",
        "DIRECT_ROOT02_LATE_PROOF_FREEZE",
    )


def _probe_root03(case: Mapping[str, Any], timing: ModuleType) -> dict[str, Any]:
    inputs = case["inputs"]
    expected = case["expected"]
    origin = inputs["earliest_basket_possible_exposure_lower_ns"]
    late_send = inputs["last_leg_send_ns"]
    scope_value, associations, projector = _context(timing)
    association = associations["FG701"]
    facts = (
        _fact(
            timing,
            scope_value,
            association,
            fact_id="intent",
            fact_type="durable_intent",
            origin_lower_ns=origin,
        ),
        _fact(
            timing,
            scope_value,
            association,
            fact_id="send",
            fact_type="send",
            origin_lower_ns=late_send,
        ),
    )
    projector.project(_snapshot(timing, scope_value, facts, late_send), callback="tick")
    due = projector.project(
        _snapshot(timing, scope_value, facts, expected["proposed_unhedged_deadline_ns"]),
        callback="idle",
    )
    _assert(due.aggregate_expired is True, "ROOT-HFT1-03 did not expire at frozen basket deadline")
    _assert(
        due.exposure_origin_lower_ns + inputs["basket_timeout_ns"]
        == expected["proposed_unhedged_deadline_ns"],
        "ROOT-HFT1-03 origin was not earliest possible exposure",
    )
    late_ack = projector.project(
        _snapshot(
            timing,
            scope_value,
            facts
            + (
                _fact(
                    timing,
                    scope_value,
                    association,
                    fact_id="late-ack",
                    fact_type="ack",
                    origin_lower_ns=expected["proposed_unhedged_deadline_ns"] + 1,
                ),
            ),
            expected["proposed_unhedged_deadline_ns"] + 1,
        ),
        callback="idle",
    )
    _assert(
        late_ack.exposure_origin_lower_ns == origin,
        "ROOT-HFT1-03 late ACK extended basket origin",
    )
    return _direct_result(
        {
            "exposure_origin_ns": due.exposure_origin_lower_ns,
            "late_ack_origin_ns": late_ack.exposure_origin_lower_ns,
            "aggregate_expired": due.aggregate_expired,
        },
        "DIRECT_ROOT03_EARLIEST_EXPOSURE",
        "DIRECT_ROOT03_LATE_ACK_FREEZE",
    )


def _probe_root04(case: Mapping[str, Any], timing: ModuleType) -> dict[str, Any]:
    inputs = case["inputs"]
    expected = case["expected"]
    origin = inputs["first_possible_exposure_lower_ns"]
    late_fill = inputs["complete_basket_fill_upper_ns"]
    scope_value, associations, projector = _context(timing)
    association = associations["FG701"]
    facts = (
        _fact(
            timing,
            scope_value,
            association,
            fact_id="intent",
            fact_type="durable_intent",
            origin_lower_ns=origin,
        ),
        _fact(
            timing,
            scope_value,
            association,
            fact_id="late-confirmed",
            fact_type="confirmed",
            origin_lower_ns=late_fill,
        ),
    )
    projector.project(_snapshot(timing, scope_value, facts, late_fill), callback="tick")
    due = projector.project(
        _snapshot(timing, scope_value, facts, expected["proposed_maximum_hold_deadline_ns"]),
        callback="idle",
    )
    _assert(due.hold_expired is True, "ROOT-HFT1-04 did not expire at frozen holding deadline")
    _assert(
        due.exposure_origin_lower_ns + inputs["maximum_hold_ns"]
        == expected["proposed_maximum_hold_deadline_ns"],
        "ROOT-HFT1-04 holding deadline moved to later fill",
    )
    _assert(
        expected["proposed_maximum_hold_deadline_ns"] != late_fill + inputs["maximum_hold_ns"],
        "ROOT-HFT1-04 frozen oracle no longer distinguishes late fill",
    )
    return _direct_result(
        {"exposure_origin_ns": due.exposure_origin_lower_ns, "hold_expired": due.hold_expired},
        "DIRECT_ROOT04_HOLD_DEADLINE",
    )


def _probe_root05(case: Mapping[str, Any], timing: ModuleType) -> dict[str, Any]:
    inputs = case["inputs"]
    expected = case["expected"]
    origin = inputs["original_monotonic_deadline_ns"] - int(timing.UNHEDGED_TTL_NS)
    scope_value, associations, projector = _context(timing)
    association = associations["FG701"]
    facts = (
        _fact(
            timing,
            scope_value,
            association,
            fact_id="intent",
            fact_type="durable_intent",
            origin_lower_ns=origin,
        ),
    )
    first = projector.project(
        _snapshot(timing, scope_value, facts, origin + 1, wall_utc="2026-09-11T01:00:00+00:00"),
        callback="tick",
    )
    back = projector.project(
        _snapshot(timing, scope_value, facts, origin + 2, wall_utc="2026-09-10T01:00:00+00:00"),
        callback="idle",
    )
    forward = projector.project(
        _snapshot(timing, scope_value, facts, origin + 3, wall_utc="2026-09-12T01:00:00+00:00"),
        callback="idle",
    )
    baseline_deadline = first.exposure_origin_lower_ns + timing.UNHEDGED_TTL_NS
    jumped_deadlines = [
        value.exposure_origin_lower_ns + timing.UNHEDGED_TTL_NS for value in (back, forward)
    ]
    _assert(
        baseline_deadline == expected["deadline_ns_each"][0]
        and jumped_deadlines == expected["deadline_ns_each"],
        "ROOT-HFT1-05 wall jump shifted deadline",
    )
    return _direct_result(
        {
            "baseline_deadline_ns": baseline_deadline,
            "deadline_ns_each": jumped_deadlines,
            "wall_jump_seconds": inputs["wall_jump_seconds"],
        },
        "DIRECT_ROOT05_MONOTONIC_DEADLINE",
        "DIRECT_ROOT05_WALL_JUMP_INVARIANT",
    )


def _probe_root06(case: Mapping[str, Any], timing: ModuleType) -> dict[str, Any]:
    origin = 100_000_000_000
    scope_value, associations, projector = _context(timing)
    association = associations["FG701"]
    local = (
        _fact(
            timing,
            scope_value,
            association,
            fact_id="intent",
            fact_type="durable_intent",
            origin_lower_ns=origin,
        ),
    )
    projector.project(_snapshot(timing, scope_value, local, origin + 1), callback="tick")
    foreign_scope = _scope(timing, boot_id="foreign-boot", clock_domain_id="foreign-domain")
    foreign = _fact(
        timing,
        foreign_scope,
        association,
        fact_id="foreign-confirmed",
        fact_type="confirmed",
        origin_lower_ns=origin + 2,
    )
    foreign_result = projector.project(
        _snapshot(timing, foreign_scope, (foreign,), origin + 2),
        callback="idle",
    )
    reentry = projector.project(_snapshot(timing, scope_value, local, origin + 3), callback="tick")
    _assert(
        foreign_result.reason == "CLOCK_SCOPE_MISMATCH", "ROOT-HFT1-06 foreign scope was accepted"
    )
    _assert(foreign_result.unresolved_exposure is True, "ROOT-HFT1-06 lost possible exposure")
    _assert(reentry.ordinary_entry_allowed is False, "ROOT-HFT1-06 allowed re-entry after fault")
    _assert(reentry.status == "BLOCKED_SOURCE", "ROOT-HFT1-06 did not latch closed")
    return _direct_result(
        {
            "foreign_reason": foreign_result.reason,
            "reentry_reason": reentry.reason,
            "unresolved_exposure": reentry.unresolved_exposure,
        },
        "DIRECT_ROOT06_FOREIGN_SCOPE_LATCH",
    )


def _probe_root07(
    case: Mapping[str, Any], timing: ModuleType, guard: _LocalGuard
) -> dict[str, Any]:
    inputs = case["inputs"]
    expected = case["expected"]
    origin = 100_000_000_000
    results: list[bool] = []
    for gap in inputs["idle_gaps_ns"]:
        scope_value, associations, projector = _context(timing)
        facts = (
            _fact(
                timing,
                scope_value,
                associations["FG701"],
                fact_id="intent",
                fact_type="durable_intent",
                origin_lower_ns=origin,
            ),
        )
        projector.project(_snapshot(timing, scope_value, facts, origin), callback="idle")
        result = projector.project(
            _snapshot(timing, scope_value, facts, origin + gap), callback="idle"
        )
        results.append(not result.idle_overdue)
    _assert(results == expected["cadence_limit_satisfied"], "ROOT-HFT1-07 50ms boundary mismatch")

    entered = threading.Event()
    release = threading.Event()
    query_result: dict[str, Any] = {}
    frozen_query_path = FROZEN_INPUTS["timing_oracles"][0]
    # This is a frozen *synthetic local* block scenario.  It deliberately
    # uses the oracle's two-second value, while the receipt labels it as a
    # functional concurrency check rather than a scheduler/venue SLA.
    local_block_target_ns = int(inputs["parallel_read_only_query_duration_ns"])

    def blocked_guarded_local_read() -> None:
        started_ns = time.monotonic_ns()
        digest = _sha256(frozen_query_path)
        guard.record_guarded_local_read(
            event="tracked_fixture_sha256_read_started",
            path=_relative(frozen_query_path),
            sha256=digest,
            started_monotonic_ns=started_ns,
        )
        query_result["sha256"] = digest
        query_result["started_monotonic_ns"] = started_ns
        entered.set()
        if not release.wait(timeout=local_block_target_ns / 1_000_000_000 + 1.0):
            query_result["timeout"] = True
            return
        finished_ns = time.monotonic_ns()
        query_result["finished_monotonic_ns"] = finished_ns
        query_result["duration_ns"] = finished_ns - started_ns
        guard.record_guarded_local_read(
            event="tracked_fixture_sha256_read_released",
            path=_relative(frozen_query_path),
            sha256=digest,
            finished_monotonic_ns=finished_ns,
            duration_ns=query_result["duration_ns"],
        )

    worker = threading.Thread(target=blocked_guarded_local_read, daemon=True)
    worker.start()
    _assert(entered.wait(timeout=0.5), "ROOT-HFT1-07 guarded local read worker did not start")
    scope_value, associations, projector = _context(timing)
    facts = (
        _fact(
            timing,
            scope_value,
            associations["FG701"],
            fact_id="intent",
            fact_type="durable_intent",
            origin_lower_ns=origin,
        ),
    )
    projector.project(_snapshot(timing, scope_value, facts, origin), callback="idle")
    concurrent = projector.project(
        _snapshot(timing, scope_value, facts, origin + max(inputs["idle_gaps_ns"])), callback="idle"
    )
    _assert(
        worker.is_alive() and not release.is_set(), "ROOT-HFT1-07 guarded read was not concurrent"
    )
    _assert(
        concurrent.idle_overdue is True,
        "ROOT-HFT1-07 idle risk cadence did not progress during read",
    )
    _assert(concurrent.protection_required is True, "ROOT-HFT1-07 risk did not advance during read")
    _assert(concurrent.risk_projection_available is True, "ROOT-HFT1-07 idle projection blocked")
    time.sleep(local_block_target_ns / 1_000_000_000)
    release.set()
    worker.join(timeout=0.5)
    _assert(not worker.is_alive(), "ROOT-HFT1-07 guarded local read worker did not release")
    _assert(query_result.get("timeout") is not True, "ROOT-HFT1-07 guarded local read timed out")
    _assert(
        query_result.get("sha256") == FROZEN_INPUTS["timing_oracles"][1],
        "ROOT-HFT1-07 guarded read did not hash the pinned tracked oracle",
    )
    _assert(
        int(query_result.get("duration_ns", 0)) >= local_block_target_ns,
        "ROOT-HFT1-07 guarded read did not remain blocked through risk projection",
    )
    return _direct_result(
        {
            "cadence_limit_satisfied": results,
            "guarded_tracked_read_path": _relative(frozen_query_path),
            "guarded_read_sha256": query_result["sha256"],
            "observed_guarded_read_duration_ns": query_result["duration_ns"],
            "local_block_target_ns": local_block_target_ns,
            "frozen_query_budget_ns": inputs["parallel_read_only_query_duration_ns"],
            "risk_progressed_while_read_blocked": True,
            "risk_projection_available": concurrent.risk_projection_available,
            "idle_overdue": concurrent.idle_overdue,
            "protection_required": concurrent.protection_required,
            "not_a_live_sla": True,
        },
        "DIRECT_ROOT07_CADENCE_BOUNDARIES",
        "DIRECT_ROOT07_GUARDED_CONCURRENT_READ",
    )


def _probe_root08(case: Mapping[str, Any], timing: ModuleType) -> dict[str, Any]:
    inputs = case["inputs"]
    origin = 100_000_000_000
    scope_value, associations, projector = _context(timing)
    association = associations["FG701"]
    ack_only = projector.project(
        _snapshot(
            timing,
            scope_value,
            (
                _fact(
                    timing,
                    scope_value,
                    association,
                    fact_id="intent",
                    fact_type="durable_intent",
                    origin_lower_ns=origin,
                ),
                _fact(
                    timing,
                    scope_value,
                    association,
                    fact_id="ack",
                    fact_type="ack",
                    origin_lower_ns=origin,
                ),
            ),
            origin,
            legal_executable_quote=True,
        ),
        callback="tick",
    )
    _assert(
        dict(ack_only.confirmed_quantities)[association.leg_id]
        == inputs["protection_leg_confirmed_quantities"][0],
        "ROOT-HFT1-08 ACK synthesized volume",
    )
    scope_value, associations, projector = _context(timing)
    association = associations["FG701"]
    confirmed = projector.project(
        _snapshot(
            timing,
            scope_value,
            (
                _fact(
                    timing,
                    scope_value,
                    association,
                    fact_id="intent",
                    fact_type="durable_intent",
                    origin_lower_ns=origin,
                ),
                _fact(
                    timing,
                    scope_value,
                    association,
                    fact_id="confirmed",
                    fact_type="confirmed",
                    origin_lower_ns=origin,
                ),
            ),
            origin + 1,
        ),
        callback="tick",
    )
    _assert(
        dict(confirmed.confirmed_quantities)[association.leg_id]
        == inputs["protection_leg_confirmed_quantities"][1],
        "ROOT-HFT1-08 confirmed volume was not retained",
    )
    return _direct_result(
        {
            "ack_quantity": dict(ack_only.confirmed_quantities)[association.leg_id],
            "confirmed_quantity": dict(confirmed.confirmed_quantities)[association.leg_id],
        },
        "DIRECT_ROOT08_ACK_NOT_VOLUME",
        "DIRECT_ROOT08_CONFIRMED_VOLUME",
    )


def _probe_root09(case: Mapping[str, Any], timing: ModuleType) -> dict[str, Any]:
    origin = 100_000_000_000
    scope_value, associations, projector = _context(timing)
    association = associations["FG701"]
    initial_facts = (
        _fact(
            timing,
            scope_value,
            association,
            fact_id="intent",
            fact_type="durable_intent",
            origin_lower_ns=origin,
        ),
        _fact(
            timing,
            scope_value,
            association,
            fact_id="cancel",
            fact_type="cancel",
            origin_lower_ns=origin,
        ),
        _fact(
            timing,
            scope_value,
            association,
            fact_id="late-trade",
            fact_type="confirmed",
            origin_lower_ns=origin,
        ),
    )
    first = projector.project(
        _snapshot(timing, scope_value, initial_facts, origin), callback="idle"
    )
    duplicate = projector.project(
        _snapshot(timing, scope_value, initial_facts, origin + 1), callback="idle"
    )
    conflict = _fact(
        timing,
        scope_value,
        association,
        fact_id="duplicate-trade",
        fact_type="confirmed",
        origin_lower_ns=origin + 2,
        trade_id="trade-late-trade",
    )
    conflicted = projector.project(
        _snapshot(timing, scope_value, initial_facts + (conflict,), origin + 2),
        callback="idle",
    )
    _assert(
        dict(first.confirmed_quantities)[association.leg_id] == 1, "ROOT-HFT1-09 late trade lost"
    )
    _assert(
        dict(duplicate.confirmed_quantities)[association.leg_id] == 1,
        "ROOT-HFT1-09 duplicate reapplied",
    )
    _assert(
        conflict.fact_id in conflicted.quarantined_fact_ids,
        "ROOT-HFT1-09 conflicting trade accepted",
    )
    _assert(conflicted.unresolved_exposure is True, "ROOT-HFT1-09 conflict claimed flat")
    _assert(conflicted.status != "FLAT_VERIFIED", "ROOT-HFT1-09 synthesized flat")
    return _direct_result(
        {"quarantined": list(conflicted.quarantined_fact_ids), "status": conflicted.status},
        "DIRECT_ROOT09_LATE_TRADE_ONCE",
        "DIRECT_ROOT09_CONFLICT_UNRESOLVED",
    )


def _probe_root10(
    case: Mapping[str, Any], runner: ModuleType, timing: ModuleType, backtrader: ModuleType
) -> dict[str, Any]:
    inputs = case["inputs"]
    raw, _ = runner.load_config(EXAMPLE / "config.yaml")
    age_ns, stale_age_ns = inputs["cohort_age_ns"]
    skew_ns, stale_skew_ns = inputs["cohort_skew_ns"]
    _assert(
        raw["feed"]["max_quote_age_ms"] * 1_000_000 == age_ns, "ROOT-HFT1-10 quote-age config drift"
    )
    _assert(
        raw["feed"]["max_cross_leg_skew_ms"] * 1_000_000 == skew_ns,
        "ROOT-HFT1-10 skew config drift",
    )
    for field, rejected_ns in (
        ("max_quote_age_ms", stale_age_ns),
        ("max_cross_leg_skew_ms", stale_skew_ns),
    ):
        changed = copy.deepcopy(raw)
        changed["feed"][field] = rejected_ns / 1_000_000
        try:
            runner.effective_config(changed, mode="replay", purpose="formula")
        except runner.RunnerConfigurationError:
            pass
        else:
            raise AssertionError(f"ROOT-HFT1-10 accepted widened {field}")
    age_equal = _cohort_gate_result(
        runner,
        backtrader,
        receive_offsets_ns=(0, 0, 0),
        now_offset_ns=age_ns,
    )
    age_plus = _cohort_gate_result(
        runner,
        backtrader,
        receive_offsets_ns=(0, 0, 0),
        now_offset_ns=stale_age_ns,
    )
    skew_equal = _cohort_gate_result(
        runner,
        backtrader,
        receive_offsets_ns=(0, 0, skew_ns),
        now_offset_ns=skew_ns,
    )
    skew_plus = _cohort_gate_result(
        runner,
        backtrader,
        receive_offsets_ns=(0, 0, stale_skew_ns),
        now_offset_ns=stale_skew_ns,
    )
    _assert(age_equal.cohort is not None, "ROOT-HFT1-10 rejected 250ms equality")
    _assert(age_plus.reason == "STALE_COHORT_RECEIVE_TIME", "ROOT-HFT1-10 accepted 250ms + 1ns")
    _assert(skew_equal.cohort is not None, "ROOT-HFT1-10 rejected 100ms equality")
    _assert(skew_plus.reason == "BLOCKED_CROSS_LEG_SKEW", "ROOT-HFT1-10 accepted 100ms + 1ns")
    stale = runner.run_replay(_effective_config(runner), scenario="stale_source")
    _assert(stale["ordinary_intent_count"] == 0, "ROOT-HFT1-10 stale cohort formed an intent")

    origin = 100_000_000_000
    scope_value, associations, projector = _context(timing)
    association = associations["FG701"]
    facts = (
        _fact(
            timing,
            scope_value,
            association,
            fact_id="intent",
            fact_type="durable_intent",
            origin_lower_ns=origin,
        ),
    )
    projector.project(_snapshot(timing, scope_value, facts, origin), callback="tick")
    refreshed = projector.project(
        _snapshot(
            timing,
            scope_value,
            facts
            + (
                _fact(
                    timing,
                    scope_value,
                    association,
                    fact_id="fresh-ack",
                    fact_type="ack",
                    origin_lower_ns=origin + 1,
                ),
            ),
            origin + 1,
        ),
        callback="tick",
    )
    _assert(
        refreshed.exposure_origin_lower_ns == origin, "ROOT-HFT1-10 fresh cohort extended exposure"
    )
    return _direct_result(
        {
            "age_gate_ns": [age_ns, stale_age_ns],
            "skew_gate_ns": [skew_ns, stale_skew_ns],
            "age_results": [age_equal.reason, age_plus.reason],
            "skew_results": [skew_equal.reason, skew_plus.reason],
            "stale_intent_count": stale["ordinary_intent_count"],
            "exposure_origin_ns": refreshed.exposure_origin_lower_ns,
        },
        "DIRECT_ROOT10_AGE_BOUNDARIES",
        "DIRECT_ROOT10_SKEW_BOUNDARIES",
        "DIRECT_ROOT10_FRESH_ACK_FREEZE",
    )


def _probe_root11(case: Mapping[str, Any], timing: ModuleType) -> dict[str, Any]:
    inputs = case["inputs"]
    expected = case["expected"]
    origin = 100_000_000_000
    outcomes: list[str] = []
    risk_due: list[bool] = []
    for seconds in inputs["seconds_until_segment_close"]:
        scope_value, associations, projector = _context(timing)
        facts = (
            _fact(
                timing,
                scope_value,
                associations["FG701"],
                fact_id="intent",
                fact_type="durable_intent",
                origin_lower_ns=origin,
            ),
        )
        missing = projector.project(
            _snapshot(timing, scope_value, facts, origin, calendar_seconds_until_close=None),
            callback="tick",
        )
        result = projector.project(
            _snapshot(
                timing,
                scope_value,
                facts,
                origin + 1,
                legal_executable_quote=False,
                calendar_seconds_until_close=seconds,
            ),
            callback="idle",
        )
        _assert(
            missing.calendar_status == "CALENDAR_REQUIRED",
            "ROOT-HFT1-11 missing calendar admitted entry",
        )
        _assert(
            result.normal_exit_allowed is False and result.unresolved_exposure is True,
            "ROOT-HFT1-11 priced an unresolved exit",
        )
        outcomes.append(result.calendar_status)
        risk_due.append(
            "SESSION_RISK_EXIT_DUE" in result.expired_reasons
            or "SESSION_HANDOVER_DUE" in result.expired_reasons
        )
    _assert(
        outcomes == expected["independent_obligations"], "ROOT-HFT1-11 calendar obligations drifted"
    )
    _assert(risk_due == [False, True, True], "ROOT-HFT1-11 risk-close boundary drifted")
    return _direct_result(
        {"calendar_statuses": outcomes, "risk_due": risk_due},
        "DIRECT_ROOT11_CALENDAR_BOUNDARIES",
        "DIRECT_ROOT11_CALENDAR_REQUIRED",
        "DIRECT_ROOT11_UNPRICED_UNRESOLVED",
    )


def _probe_root12(case: Mapping[str, Any], timing: ModuleType) -> dict[str, Any]:
    origin = 100_000_000_000
    scope_value, associations, projector = _context(timing)
    pending = _fact(
        timing,
        scope_value,
        associations["FG701"],
        fact_id="pending-intent",
        fact_type="durable_intent",
        origin_lower_ns=origin,
    )
    projector.project(_snapshot(timing, scope_value, (pending,), origin), callback="tick")
    stopped = projector.project(
        _snapshot(timing, scope_value, (), origin + 1, stop_requested=True),
        callback="idle",
    )
    later = projector.project(
        _snapshot(timing, scope_value, (), origin + 2, stop_requested=True),
        callback="idle",
    )
    _assert(stopped.status == "STOP_INCOMPLETE", "ROOT-HFT1-12 stop status drifted")
    _assert(
        stopped.reason == "UNRESOLVED_EXPOSURE" and stopped.unresolved_exposure is True,
        "ROOT-HFT1-12 cleared pending exposure",
    )
    _assert(pending.fact_id in stopped.audit_fact_ids, "ROOT-HFT1-12 dropped original audit fact")
    _assert(later.status != "FLAT_VERIFIED", "ROOT-HFT1-12 claimed flat later")
    return _direct_result(
        {"status": stopped.status, "audit_fact_ids": list(stopped.audit_fact_ids)},
        "DIRECT_ROOT12_STOP_UNRESOLVED",
        "DIRECT_ROOT12_NO_FLAT_CLAIM",
        "DIRECT_ROOT12_AUDIT_RETENTION",
    )


def _run_root_probes(
    oracles: Iterable[Mapping[str, Any]],
    runner: ModuleType,
    timing: ModuleType,
    backtrader: ModuleType,
    guard: _LocalGuard,
) -> dict[str, Any]:
    probes: dict[str, Callable[[Mapping[str, Any]], dict[str, Any]]] = {
        "ROOT-HFT1-02": lambda case: _probe_root02(case, timing),
        "ROOT-HFT1-03": lambda case: _probe_root03(case, timing),
        "ROOT-HFT1-04": lambda case: _probe_root04(case, timing),
        "ROOT-HFT1-05": lambda case: _probe_root05(case, timing),
        "ROOT-HFT1-06": lambda case: _probe_root06(case, timing),
        "ROOT-HFT1-07": lambda case: _probe_root07(case, timing, guard),
        "ROOT-HFT1-08": lambda case: _probe_root08(case, timing),
        "ROOT-HFT1-09": lambda case: _probe_root09(case, timing),
        "ROOT-HFT1-10": lambda case: _probe_root10(case, runner, timing, backtrader),
        "ROOT-HFT1-11": lambda case: _probe_root11(case, timing),
        "ROOT-HFT1-12": lambda case: _probe_root12(case, timing),
    }
    results: dict[str, Any] = {}
    for case in oracles:
        case_id = str(case["id"])
        if case_id == "ROOT-HFT1-01":
            # The formerly used replay callback occurred only *after*
            # Cerebro completed.  It cannot establish active-engine no-tick /
            # no-bar behavior, so this group intentionally has no direct
            # synthetic pass and is discharged only by its exact JUnit nodes.
            results[case_id] = {
                "passed": True,
                "validation_mode": "JUNIT_ONLY_ACTIVE_ENGINE",
                "direct_status": "NOT_RUN_POST_ENGINE_PROBE_NOT_COUNTED",
                "frozen_input": case["inputs"],
                "frozen_expected": case["expected"],
                "actual": {
                    "direct_probe": "NOT_RUN",
                    "reason": "post-engine replay callback cannot prove active-engine no-tick/no-bar behavior",
                },
                "direct_assertions": {},
                "pytest_nodes": list(ROOT_TEST_COVERAGE[case_id]),
            }
            continue
        try:
            direct = probes[case_id](case)
            results[case_id] = {
                "passed": True,
                "validation_mode": "DIRECT_AND_JUNIT",
                "direct_status": "PASS",
                "frozen_input": case["inputs"],
                "frozen_expected": case["expected"],
                **direct,
                "pytest_nodes": list(ROOT_TEST_COVERAGE[case_id]),
            }
        except BaseException as exc:
            results[case_id] = {
                "passed": False,
                "validation_mode": "DIRECT_AND_JUNIT",
                "direct_status": "FAIL",
                "frozen_input": case.get("inputs"),
                "frozen_expected": case.get("expected"),
                "direct_assertions": {},
                "error": repr(exc),
                "traceback": traceback.format_exc(),
                "pytest_nodes": list(ROOT_TEST_COVERAGE.get(case_id, ())),
            }
    return results


def _source_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _historical_source_provenance(observation: Mapping[str, Any]) -> dict[str, Any]:
    """Bind a frozen source finding without pretending its old line is current."""

    path = EXAMPLE / str(observation["file"])
    _assert(path.is_file(), f"source observation file is absent: {path}")
    lines = _source_text(path).splitlines()
    line_number = int(observation["line"])
    _assert(
        1 <= line_number <= len(lines), f"source observation line is outside current file: {path}"
    )
    _assert(bool(str(observation["fact"]).strip()), "source observation fact is empty")
    _assert(
        bool(str(observation["implication"]).strip()), "source observation implication is empty"
    )
    return {
        "observed_file": _relative(path),
        "current_source_sha256": _sha256(path),
        "historical_line": line_number,
        "current_line_text": lines[line_number - 1],
        "historical_line_is_not_current_behavior_claim": True,
    }


def _run_source_probes(
    observations: Iterable[Mapping[str, Any]],
    runner: ModuleType,
    strategy: ModuleType,
) -> dict[str, Any]:
    strategy_path = EXAMPLE / "ctp_options_highfreq_strategy.py"
    runner_path = EXAMPLE / "run.py"
    config_path = EXAMPLE / "config.yaml"
    timing_path = EXAMPLE / "execution_timing.py"
    source = {
        "strategy": _source_text(strategy_path),
        "runner": _source_text(runner_path),
        "config": _source_text(config_path),
        "timing": _source_text(timing_path),
    }
    report = runner.run_replay(
        _effective_config(runner),
        scenario="valid_cohort",
        invoke_idle_probe=True,
    )
    intent = report["ordinary_intents"][0]
    deadline = intent["deadline_projection"]
    last_quotes = report["last_cohort"]["quotes"]
    source_checks: dict[str, Callable[[], dict[str, Any]]] = {
        "HF-SOURCE-01": lambda: _source01(report, source),
        "HF-SOURCE-02": lambda: _source02(intent, deadline, last_quotes, source),
        "HF-SOURCE-03": lambda: _source03(strategy, report, source),
        "HF-SOURCE-04": lambda: _source04(runner, source),
        "HF-SOURCE-05": lambda: _source05(runner, source),
        "HF-SOURCE-06": lambda: _source06(strategy, report, source),
    }
    results: dict[str, Any] = {}
    for observation in observations:
        observation_id = str(observation["id"])
        try:
            provenance = _historical_source_provenance(observation)
            behavior = source_checks[observation_id]()
            source_number = observation_id.rsplit("-", 1)[1]
            results[observation_id] = {
                "passed": True,
                "validation_mode": "DIRECT_AND_JUNIT",
                "frozen_observation": {
                    key: observation[key] for key in ("file", "line", "fact", "implication")
                },
                "actual": {
                    "historical_source_provenance": provenance,
                    "current_behavior": behavior,
                },
                "direct_assertions": {
                    f"DIRECT_SOURCE{source_number}_HISTORICAL_PROVENANCE": {
                        "passed": True,
                        "kind": "historical_frozen_provenance",
                    },
                    f"DIRECT_SOURCE{source_number}_CURRENT_BEHAVIOR": {
                        "passed": True,
                        "kind": "direct",
                    },
                },
                "pytest_nodes": [SOURCE_TEST_NODE],
            }
        except BaseException as exc:
            results[observation_id] = {
                "passed": False,
                "validation_mode": "DIRECT_AND_JUNIT",
                "frozen_observation": observation,
                "direct_assertions": {},
                "error": repr(exc),
                "traceback": traceback.format_exc(),
                "pytest_nodes": [SOURCE_TEST_NODE],
            }
    return results


def _source01(report: Mapping[str, Any], source: Mapping[str, str]) -> dict[str, Any]:
    for token in (
        '"status": "OFFLINE_SIGNAL_ONLY"',
        '"risk_projection_available": False',
        '"basis": "no_sdk_read_only_risk_projection"',
        '"risk_actions": []',
    ):
        _assert(token in source["strategy"], f"HF-SOURCE-01 source token absent: {token}")
    projection = report["offline_deadline_projection"]
    _assert(projection["status"] == "OFFLINE_SIGNAL_ONLY", "HF-SOURCE-01 report status drifted")
    _assert(projection["risk_projection_available"] is False, "HF-SOURCE-01 exposed a risk grant")
    _assert(projection["risk_actions"] == [], "HF-SOURCE-01 emitted risk actions")
    return {"offline_projection": projection}


def _source02(
    intent: Mapping[str, Any],
    deadline: Mapping[str, Any],
    last_quotes: Mapping[str, Mapping[str, Any]],
    source: Mapping[str, str],
) -> dict[str, Any]:
    for token in ("anchor_ns = max(", '"execution_status": "NOT_SUBMITTED_REPLAY"'):
        _assert(token in source["strategy"], f"HF-SOURCE-02 source token absent: {token}")
    expected_anchor = max(item["receive_monotonic_ns"] for item in last_quotes.values())
    _assert(
        intent["execution_status"] == "NOT_SUBMITTED_REPLAY", "HF-SOURCE-02 submitted replay intent"
    )
    _assert(
        deadline["anchor_monotonic_ns"] == expected_anchor, "HF-SOURCE-02 deadline anchor drifted"
    )
    _assert(
        deadline["leg_deadline_monotonic_ns"] == expected_anchor + 1_000_000_000,
        "HF-SOURCE-02 leg deadline drifted",
    )
    return {"anchor_monotonic_ns": expected_anchor, "execution_status": intent["execution_status"]}


def _source03(
    strategy: ModuleType, report: Mapping[str, Any], source: Mapping[str, str]
) -> dict[str, Any]:
    signature = inspect.signature(strategy.CtpOptionsHighfreqStrategy.notify_idle)
    _assert(
        "now" in signature.parameters and signature.parameters["now"].default is None,
        "HF-SOURCE-03 idle signature drifted",
    )
    for token in ('"TRUSTED_NOW_REQUIRED"', "last tick's", "def notify_idle"):
        _assert(token in source["strategy"], f"HF-SOURCE-03 source token absent: {token}")
    _assert(report["ordinary_intent_count"] == 1, "HF-SOURCE-03 idle created an ordinary intent")
    _assert(
        report["ordinary_position_exit_proposals"] == [], "HF-SOURCE-03 idle created a normal exit"
    )
    return {
        "notify_idle_signature": str(signature),
        "timing_provider_status": report["timing_provider_status"],
    }


def _source04(runner: ModuleType, source: Mapping[str, str]) -> dict[str, Any]:
    body = inspect.getsource(runner.run_replay)
    run_at = body.index("cerebro.run(")
    idle_at = body.index("strategy.notify_idle()")
    _assert(run_at < idle_at, "HF-SOURCE-04 idle probe unexpectedly runs inside the engine")
    for token in ("if invoke_idle_probe:", "strategy.notify_idle()", "cerebro.run("):
        _assert(token in source["runner"], f"HF-SOURCE-04 source token absent: {token}")
    return {"post_engine_idle_probe": True, "cerebro_before_idle_probe": True}


def _source05(runner: ModuleType, source: Mapping[str, str]) -> dict[str, Any]:
    raw, _ = runner.load_config(config_path := EXAMPLE / "config.yaml")
    execution = raw["execution"]
    _assert(execution["order_type"] == "limit", "HF-SOURCE-05 order type drifted")
    _assert(
        execution
        == {
            "order_type": "limit",
            "ordinary_requests_per_second": 2,
            "max_daily_write_attempts": 100,
            "max_daily_ordinary_attempts": 80,
            "safety_daily_reserved_attempts": 20,
        },
        "HF-SOURCE-05 execution schema drifted",
    )
    changed = copy.deepcopy(raw)
    changed["timing"]["runtime_provider"] = "network"
    try:
        runner.effective_config(changed, mode="replay", purpose="formula")
    except runner.RunnerConfigurationError:
        pass
    else:
        raise AssertionError("HF-SOURCE-05 allowed an execution timing provider")
    _assert(
        "runtime_provider: unavailable" in source["config"], "HF-SOURCE-05 config source drifted"
    )
    return {
        "execution": execution,
        "runtime_provider": raw["timing"]["runtime_provider"],
        "config_path": str(config_path),
    }


def _source06(
    strategy: ModuleType, report: Mapping[str, Any], source: Mapping[str, str]
) -> dict[str, Any]:
    for method in ("notify_tick", "notify_bar", "notify_idle", "next"):
        _assert(
            hasattr(strategy.CtpOptionsHighfreqStrategy, method), f"HF-SOURCE-06 missing {method}"
        )
    tick_body = inspect.getsource(strategy.CtpOptionsHighfreqStrategy.notify_tick)
    bar_body = inspect.getsource(strategy.CtpOptionsHighfreqStrategy.notify_bar)
    idle_body = inspect.getsource(strategy.CtpOptionsHighfreqStrategy.notify_idle)
    next_body = inspect.getsource(strategy.CtpOptionsHighfreqStrategy.next)
    _assert("_consider_cohort" in tick_body, "HF-SOURCE-06 tick no longer consumes cohort")
    _assert(
        tick_body.index("_advance_synthetic_timing") < tick_body.index("_cohort_validator.ingest"),
        "HF-SOURCE-06 rejected ticks can bypass synthetic risk timing",
    )
    _assert(
        "_consider_cohort" not in bar_body + idle_body + next_body,
        "HF-SOURCE-06 non-tick callback consumes cohort",
    )
    _assert(
        report["ordinary_intent_count"] == 1,
        "HF-SOURCE-06 valid tick did not retain candidate intent",
    )
    return {"normal_intent_producer": "notify_tick", "callback_counts": report["callback_counts"]}


def _static_native_scan() -> dict[str, list[str]]:
    paths = (
        EXAMPLE / "ctp_options_highfreq_strategy.py",
        EXAMPLE / "execution_timing.py",
        EXAMPLE / "run.py",
    )
    findings: dict[str, list[str]] = {}
    for path in paths:
        text = _source_text(path)
        found = [token for token in NATIVE_API_TOKENS if token in text]
        findings[_relative(path)] = found
    _assert(
        not any(findings.values()), "selected product source contains native CTP account/order APIs"
    )
    return findings


def _junit_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"valid": False, "reason": "JUNIT_MISSING"}
    try:
        root = ElementTree.parse(path).getroot()
    except ElementTree.ParseError as exc:
        return {"valid": False, "reason": f"JUNIT_PARSE_ERROR:{exc}"}
    cases = root.findall(".//testcase")
    names = [case.attrib.get("name", "") for case in cases]
    classes = [case.attrib.get("classname", "") for case in cases]
    failures = len(root.findall(".//failure"))
    errors = len(root.findall(".//error"))
    skipped_children = len(root.findall(".//skipped"))
    suite_skipped = sum(
        int(suite.attrib.get("skipped", "0")) for suite in root.findall(".//testsuite")
    )
    expected_set = set(EXPECTED_JUNIT_NAMES)
    actual_set = set(names)
    exact_set = (
        len(cases) == EXPECTED_TESTCASE_COUNT
        and len(actual_set) == EXPECTED_TESTCASE_COUNT
        and actual_set == expected_set
        and all(item == "tests.unit.test_ctp_options_highfreq_example" for item in classes)
    )
    zero_outcomes = failures == 0 and errors == 0 and skipped_children == 0 and suite_skipped == 0
    return {
        "valid": exact_set and zero_outcomes,
        "expected_count": EXPECTED_TESTCASE_COUNT,
        "actual_count": len(cases),
        "expected_names": list(EXPECTED_JUNIT_NAMES),
        "actual_names": names,
        "actual_classes": classes,
        "missing_names": sorted(expected_set - actual_set),
        "unexpected_names": sorted(actual_set - expected_set),
        "duplicate_or_missing_identity": len(actual_set) != len(cases),
        "failures": failures,
        "errors": errors,
        "skipped_children": skipped_children,
        "skipped_suite_count": suite_skipped,
        "order_matches_command": names == list(EXPECTED_JUNIT_NAMES),
    }


def _junit_assertion_results(junit: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    actual_names = set(junit.get("actual_names", ()))
    results: dict[str, dict[str, Any]] = {}
    for assertion_id, nodes in JUNIT_ASSERTION_NODES.items():
        node_names = [node.rsplit("::", 1)[1] for node in nodes]
        passed = bool(
            junit.get("valid") is True and all(name in actual_names for name in node_names)
        )
        results[assertion_id] = {
            "passed": passed,
            "kind": "exact_junit_node",
            "node_ids": list(nodes),
            "node_names": node_names,
        }
    return results


def _evaluate_field_assertion_map(
    assertion_map: Mapping[str, Any],
    root_results: Mapping[str, Any],
    source_results: Mapping[str, Any],
    junit: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve every frozen field to a concrete direct or exact-JUnit result."""

    junit_results = _junit_assertion_results(junit)
    groups: dict[str, Any] = {}
    all_complete = True
    unknown_assertions: list[str] = []

    def resolve_assertion(group_result: Mapping[str, Any], assertion_id: str) -> dict[str, Any]:
        if assertion_id in junit_results:
            return junit_results[assertion_id]
        direct = group_result.get("direct_assertions", {}).get(assertion_id)
        if isinstance(direct, Mapping):
            return dict(direct)
        unknown_assertions.append(assertion_id)
        return {"passed": False, "kind": "missing_direct_assertion"}

    def evaluate_group(
        group_id: str,
        group_map: Mapping[str, Any],
        group_result: Mapping[str, Any],
        sections: tuple[str, ...],
    ) -> dict[str, Any]:
        field_results: dict[str, Any] = {}
        group_complete = True
        for section in sections:
            for field, assertion_ids in group_map[section].items():
                resolved = {
                    assertion_id: resolve_assertion(group_result, assertion_id)
                    for assertion_id in assertion_ids
                }
                passed = bool(resolved) and all(
                    item.get("passed") is True for item in resolved.values()
                )
                field_results[f"{section}.{field}"] = {
                    "assertion_ids": list(assertion_ids),
                    "resolved": resolved,
                    "passed": passed,
                }
                group_complete = group_complete and passed
        return {
            "validation_mode": group_map["validation_mode"],
            "direct_status": group_result.get("direct_status", "NOT_APPLICABLE"),
            "field_results": field_results,
            "passed": group_complete,
        }

    for group_id, group_map in assertion_map["root_groups"].items():
        result = evaluate_group(
            group_id,
            group_map,
            root_results.get(group_id, {}),
            ("inputs", "expected"),
        )
        groups[group_id] = result
        all_complete = all_complete and result["passed"]
    for group_id, group_map in assertion_map["source_groups"].items():
        result = evaluate_group(
            group_id,
            group_map,
            source_results.get(group_id, {}),
            ("fields",),
        )
        groups[group_id] = result
        all_complete = all_complete and result["passed"]
    return {
        "schema_version": "backtrader.iter27.hf-t1-field-assertion-coverage.v1",
        "junit_assertions": junit_results,
        "groups": groups,
        "unknown_or_missing_assertion_ids": sorted(set(unknown_assertions)),
        "all_fields_mapped_and_passed": all_complete and not unknown_assertions,
    }


def _installation_binding(backtrader: ModuleType) -> dict[str, Any]:
    origin = Path(str(backtrader.__file__)).resolve()
    try:
        installed_version = importlib.metadata.version("backtrader")
    except importlib.metadata.PackageNotFoundError:
        installed_version = None
    return {
        "import_origin": _relative(origin),
        "import_origin_sha256": _sha256(origin),
        "local_import": str(origin).startswith(str(ROOT.resolve())),
        "module_version": getattr(backtrader, "__version__", None),
        "installed_distribution_version": installed_version,
        "harness_sha256": _sha256(Path(__file__).resolve()),
    }


def _all_pass(results: Mapping[str, Any]) -> bool:
    return bool(results) and all(item.get("passed") is True for item in results.values())


def _all_direct_root_probes_passed(results: Mapping[str, Any]) -> bool:
    """Return true only when every root group actually ran a direct probe."""

    return bool(results) and all(
        item.get("passed") is True and item.get("direct_status") == "PASS"
        for item in results.values()
    )


def _all_contract_root_groups_discharged(coverage: Mapping[str, Any]) -> bool:
    groups = coverage.get("groups", {})
    root_groups = [
        group for group_id, group in groups.items() if str(group_id).startswith("ROOT-HFT1-")
    ]
    return len(root_groups) == 12 and all(group.get("passed") is True for group in root_groups)


def main() -> int:
    args = _parse_args()
    output = _output_path(args.output_dir)
    stdout_path = output / "stdout.log"
    stderr_path = output / "stderr.log"
    junit_path = output / "junit.xml"
    manifest_path = output / "manifest.json"
    golden_path = output / "golden-observations.json"
    guard_path = output / "guard-events.json"
    modules_path = output / "module-origins.json"
    coverage_path = output / "field-assertion-coverage.json"
    consolidated_path = output / "consolidated.json"

    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["PYTEST_ADDOPTS"] = "-p no:cacheprovider -p no:rerunfailures"
    sys.path.insert(0, str(ROOT))

    guard = _LocalGuard()
    result_code = 99
    error: str | None = None
    frozen_payloads: dict[str, Any] | None = None
    frozen_hashes: dict[str, str] = {}
    source_before: dict[str, str] = {}
    source_after: dict[str, str] = {}
    modules_before: dict[str, str] = {}
    modules_after: dict[str, str] = {}
    dynamic_module_delta: dict[str, list[str]] = {"added": [], "removed": [], "changed": []}
    root_results: dict[str, Any] = {}
    source_results: dict[str, Any] = {}
    native_static_findings: dict[str, list[str]] = {}
    installation: dict[str, Any] = {}
    receipt_frozen_copy_hashes: dict[str, str] = {}
    git_state_before: dict[str, Any] = {}
    git_state_after: dict[str, Any] = {}
    coverage: dict[str, Any] = {
        "schema_version": "backtrader.iter27.hf-t1-field-assertion-coverage.v1",
        "all_fields_mapped_and_passed": False,
        "reason": "NOT_EVALUATED",
    }
    old_cwd = Path.cwd()

    try:
        # This read-only state is deliberately captured before the Python
        # no-child-process guard begins.  A constrained postflight read below
        # gives the receipt a before/after record without opening a general
        # subprocess escape hatch.
        git_state_before = _git_state()
        guard.install()
        os.chdir(ROOT)
        frozen_payloads, frozen_hashes = _load_frozen_inputs()
        receipt_frozen_copy_hashes = _copy_frozen_inputs_to_receipt(output)
        runner, strategy, timing, backtrader = _load_example_modules()
        # Complete dependency imports while the network/native guards are
        # already active, then make process spawning fail closed before any
        # golden observation or selected test node is evaluated.
        import pytest

        # Preload all local modules that selected nodes can import before the
        # dynamic source snapshot.  The after-set is compared in full below;
        # a newly imported local file cannot be silently omitted.
        # Pytest imports its nested conftests during collection.  Bind those
        # actual modules before the snapshot; the repository-root conftest is
        # source-hashed statically but is not a durable pytest module identity.
        importlib.import_module("tests.conftest")
        importlib.import_module("tests.unit.conftest")
        importlib.import_module("tests.unit.test_ctp_options_highfreq_example")

        guard.enforce_no_child_processes()
        installation = _installation_binding(backtrader)
        _assert(
            installation["local_import"] is True, "harness did not import checkout-local backtrader"
        )
        source_before = _hash_paths(
            [ROOT / path for path in STATIC_DEPENDENCIES]
            + [path for path, _ in FROZEN_INPUTS.values()]
        )
        modules_before = _loaded_local_module_hashes()
        native_static_findings = _static_native_scan()
        root_results = _run_root_probes(
            frozen_payloads["timing_oracles"]["cases"], runner, timing, backtrader, guard
        )
        source_results = _run_source_probes(
            frozen_payloads["source_observations"]["observations"], runner, strategy
        )
        pytest_args = ["-q", f"--junitxml={junit_path}", *TEST_NODE_IDS]
        with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open(
            "w", encoding="utf-8"
        ) as stderr, contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result_code = int(pytest.main(pytest_args))
    except BaseException as exc:
        error = repr(exc)
        with stderr_path.open("a", encoding="utf-8") as stderr:
            traceback.print_exc(file=stderr)
    finally:
        os.chdir(old_cwd)
        guard.restore()

    try:
        source_after = _hash_paths(
            [ROOT / path for path in STATIC_DEPENDENCIES]
            + [path for path, _ in FROZEN_INPUTS.values()]
        )
        modules_after = _loaded_local_module_hashes()
        dynamic_module_delta = {
            "added": sorted(set(modules_after) - set(modules_before)),
            "removed": sorted(set(modules_before) - set(modules_after)),
            "changed": sorted(
                path
                for path in set(modules_before) & set(modules_after)
                if modules_before[path] != modules_after[path]
            ),
        }
    except BaseException as exc:
        if error is None:
            error = repr(exc)
        with stderr_path.open("a", encoding="utf-8") as stderr:
            traceback.print_exc(file=stderr)

    try:
        guard.enforce_no_child_processes()
        guard.allow_postflight_git_reads()
        git_state_after = _git_state()
    except BaseException as exc:
        if error is None:
            error = repr(exc)
        with stderr_path.open("a", encoding="utf-8") as stderr:
            traceback.print_exc(file=stderr)

    junit = _junit_summary(junit_path)
    source_stable = source_before == source_after
    module_sources_stable = modules_before == modules_after
    git_state_stable = bool(
        git_state_before and git_state_after and git_state_before == git_state_after
    )
    if frozen_payloads is not None:
        coverage = _evaluate_field_assertion_map(
            frozen_payloads["assertion_map"], root_results, source_results, junit
        )
    _json_dump(
        golden_path,
        {
            "schema_version": "backtrader.iter27.hf-t1-golden-observations.v3",
            "frozen_input_hashes": frozen_hashes,
            "root_oracles": root_results,
            "source_observations": source_results,
            "all_direct_root_probes_passed": _all_direct_root_probes_passed(root_results),
            "all_direct_source_probes_passed": _all_pass(source_results),
            "all_contract_root_groups_discharged": _all_contract_root_groups_discharged(coverage),
            "root01_direct_status": root_results.get("ROOT-HFT1-01", {}).get("direct_status"),
            "field_assertion_coverage_file": coverage_path.name,
        },
    )
    _json_dump(coverage_path, coverage)
    status_label_contract = _status_label_contract()
    accepted = (
        error is None
        and result_code == 0
        and _all_contract_root_groups_discharged(coverage)
        and _all_pass(source_results)
        and junit.get("valid") is True
        and coverage.get("all_fields_mapped_and_passed") is True
        and source_stable
        and module_sources_stable
        and not guard.external_network_attempts
        and not guard.native_api_attempts
        and not guard.process_attempts
        and status_label_contract["passed"] is True
    )
    sealed_build_claim = bool(
        accepted
        and git_state_stable
        and git_state_before.get("worktree_clean") is True
        and git_state_before.get("all_owned_inputs_committed_at_head") is True
        and git_state_after.get("all_owned_inputs_committed_at_head") is True
    )
    status = _receipt_status(accepted=accepted, sealed_build_claim=sealed_build_claim)
    manifest = {
        "schema_version": "backtrader.iter27.hf-t1-independent-attempt.v4",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "repository_root": str(ROOT),
        "python": sys.executable,
        "frozen_inputs": {
            name: {"path": _relative(path), "sha256": digest}
            for name, (path, digest) in FROZEN_INPUTS.items()
        },
        "receipt_frozen_copy_hashes": receipt_frozen_copy_hashes,
        "fixture_provenance_policy": (
            frozen_payloads.get("fixture_provenance", {}) if frozen_payloads else {}
        ),
        "test_file": TEST_FILE,
        "test_node_ids": list(TEST_NODE_IDS),
        "expected_testcase_count": EXPECTED_TESTCASE_COUNT,
        "junit_identity": {
            "expected_classname": "tests.unit.test_ctp_options_highfreq_example",
            "expected_names": list(EXPECTED_JUNIT_NAMES),
            "zero_skips_required": True,
        },
        "static_dependency_hashes_before": source_before,
        "static_dependency_hashes_after": source_after,
        "loaded_local_module_hashes_before": modules_before,
        "loaded_local_module_hashes_after": modules_after,
        "dynamic_local_module_delta": dynamic_module_delta,
        "installation_binding": installation,
        "git_state_before": git_state_before,
        "git_state_after": git_state_after,
        "git_state_stable": git_state_stable,
        "receipt_status": status,
        "status_label_contract": status_label_contract,
        "network_guard": {
            "python_audit_events": [
                "socket.connect",
                "socket.getaddrinfo",
                "socket.sendto",
                "socket.bind",
            ],
            "socket_wrappers": [
                "create_connection",
                "getaddrinfo",
                "gethostbyname",
                "gethostbyname_ex",
            ],
            "loopback_policy": "counted separately; no loopback event occurred is not required for the local result",
            "native_import_blocklist": sorted(BLOCKED_IMPORT_ROOTS),
            "named_ctypes_and_post_bootstrap_process_audit_blocked": True,
            "bootstrap_process_policy": "local scientific-stack import events are recorded before oracle/test execution; child processes are then fail-closed",
            "postflight_git_read_policy": "after test execution, only git status/rev-parse/ls-files/ls-tree reads are allowed to record receipt state",
        },
        "scope": "same-checkout, synthetic local timing projection; HFT remains NOT_ADMITTED",
        "limitations": [
            "This is a self-attested same-checkout run, not an independently trusted sealed build or separate attestation environment.",
            "Python audit hooks and socket wrappers cannot intercept every native extension or kernel-level syscall; no OS firewall, VM, container, or hardware network isolation was asserted.",
            "A local scientific-stack import may perform a recorded local CPU-capability child-process probe before the no-child-process guard is enforced; no oracle or selected pytest node runs before that guard is enabled.",
            "No CTP/SimNow connection, account query, native API initialization, order/cancel submission, fill, reconciliation, queue, latency, or profitability evidence is exercised.",
            "A local PASS means only LOCAL_HIGHFREQ_TIMING_PROJECTION_SUBSET_PASS under the frozen contract; it does not admit HFT or real trading.",
            "A receipt file hash manifest is not a sealed-build claim. This attempt marks sealed_build_claim false unless the whole worktree is clean, stable, and the owned inputs are committed at HEAD before and after execution.",
        ],
    }
    _json_dump(manifest_path, manifest)
    _json_dump(
        guard_path,
        {
            "external_network_attempts": guard.external_network_attempts,
            "loopback_network_events": guard.loopback_network_events,
            "native_api_attempts": guard.native_api_attempts,
            "process_or_native_load_attempts": guard.process_attempts,
            "allowed_runtime_loader_events": guard.runtime_loader_events,
            "bootstrap_process_events_before_oracle_execution": guard.bootstrap_process_events,
            "guarded_local_read_events": guard.guarded_local_read_events,
            "postflight_git_read_events": guard.postflight_git_read_events,
            "static_native_api_findings": native_static_findings,
        },
    )
    _json_dump(
        modules_path,
        {
            "installation_binding": installation,
            "loaded_local_module_hashes_before": modules_before,
            "loaded_local_module_hashes_after": modules_after,
            "dynamic_local_module_delta": dynamic_module_delta,
            "module_sources_stable": module_sources_stable,
        },
    )
    consolidated = {
        "accepted": accepted,
        "status": status,
        "maximum_contract_status": (
            "LOCAL_HIGHFREQ_TIMING_PROJECTION_SUBSET_PASS" if accepted else "FAIL"
        ),
        "sealed_build_claim": sealed_build_claim,
        "status_label_contract": status_label_contract,
        "execution_status": "HFT_NOT_ADMITTED_NO_GO_FOR_REAL_TRADING",
        "exit_code": result_code,
        "error": error,
        "frozen_input_hashes": frozen_hashes,
        "all_direct_root_probes_passed": _all_direct_root_probes_passed(root_results),
        "all_contract_root_groups_discharged": _all_contract_root_groups_discharged(coverage),
        "all_source_observations_passed": _all_pass(source_results),
        "root_observation_count": len(root_results),
        "source_observation_count": len(source_results),
        "junit": junit,
        "field_assertion_coverage": coverage,
        "source_stable": source_stable,
        "module_sources_stable": module_sources_stable,
        "dynamic_local_module_delta": dynamic_module_delta,
        "git_state_before": git_state_before,
        "git_state_after": git_state_after,
        "git_state_stable": git_state_stable,
        "external_network_attempts": guard.external_network_attempts,
        "loopback_network_event_count": len(guard.loopback_network_events),
        "native_api_attempts": guard.native_api_attempts,
        "process_or_native_load_attempts": guard.process_attempts,
        "allowed_runtime_loader_events": guard.runtime_loader_events,
        "bootstrap_process_events_before_oracle_execution": guard.bootstrap_process_events,
        "guarded_local_read_events": guard.guarded_local_read_events,
        "postflight_git_read_events": guard.postflight_git_read_events,
        "limitations": manifest["limitations"],
    }
    _json_dump(consolidated_path, consolidated)
    seal_inputs = (
        manifest_path,
        golden_path,
        guard_path,
        modules_path,
        coverage_path,
        junit_path,
        stdout_path,
        stderr_path,
        consolidated_path,
        *(output / "frozen-inputs" / path.name for path, _ in FROZEN_INPUTS.values()),
    )
    _json_dump(
        output / "seal.json",
        {
            "schema_version": "backtrader.iter27.acceptance-seal.v3",
            "files": {path.name: _sha256(path) for path in seal_inputs if path.exists()},
            "excludes": ["seal.json"],
            "integrity_manifest_only": True,
            "sealed_build_claim": sealed_build_claim,
            "sealed_at_utc": datetime.now(timezone.utc).isoformat(),
        },
    )
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
